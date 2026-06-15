"""
Process controller for the mitigator.

Runs mitigate.py as a subprocess, reads its log stream (which includes the
per-action telemetry), and exposes a small thread-safe API for the web layer:
start(), stop(), status(), logs().

This service is expected to run as root (see systemd unit and README), because
the mitigator needs raw sockets, iptables and sysctl. That keeps signal handling
simple: we put the child in its own process group and send SIGINT for a clean
shutdown, which triggers mitigate.py's own iptables/sysctl cleanup.
"""
from __future__ import annotations

import collections
import os
import re
import signal
import subprocess
import threading
import time

import config

# Telemetry emitted by mitigate.py's logging. Examples:
#   S2C_ActionEffect: actionId=1d6f sourceSequence=0007 wait=600ms->421ms rtt=232ms downstream=118ms upstream=121ms ...
_RE_RTT = re.compile(r"rtt=(\d+)ms")
_RE_WAIT = re.compile(r"wait=(\d+)ms->(\d+)ms")
_RE_DOWN = re.compile(r"downstream=(\d+)ms")
_RE_UP = re.compile(r"upstream=(\d+)ms")
_RE_LISTENING = re.compile(r"Listening on")
_RE_ROOT = re.compile(r"RootRequired|Operation not permitted|must be run as root", re.I)


class MitigatorController:
    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._proc: subprocess.Popen | None = None
        self._reader: threading.Thread | None = None
        self._started_at = 0.0
        self._listening = False
        self._last_error: str | None = None
        self._logs: collections.deque[str] = collections.deque(maxlen=config.LOG_BUFFER)
        self._tele = self._blank_tele()

    # ------------------------------------------------------------------ API ---
    def start(self) -> dict:
        with self._lock:
            if self._running_locked():
                return self._status_locked()

            problem = self._preflight()
            if problem:
                self._last_error = problem
                self._append_log(f"[cannot start] {problem}")
                return self._status_locked()

            self._logs.clear()
            self._tele = self._blank_tele()
            self._listening = False
            self._last_error = None

            cmd = self._build_cmd()
            self._append_log("$ " + " ".join(cmd))
            try:
                self._proc = subprocess.Popen(
                    cmd,
                    cwd=os.path.dirname(config.MITIGATE_PATH) or config.BASE_DIR,
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.PIPE,
                    text=True,
                    bufsize=1,
                    start_new_session=True,  # own process group, so we can signal children
                )
            except OSError as exc:
                self._last_error = f"Failed to launch mitigator: {exc}"
                self._append_log(f"[error] {self._last_error}")
                self._proc = None
                return self._status_locked()

            self._started_at = time.time()
            self._reader = threading.Thread(
                target=self._read_loop, args=(self._proc,), daemon=True
            )
            self._reader.start()
            return self._status_locked()

    def stop(self) -> dict:
        with self._lock:
            proc = self._proc
            if proc is None or proc.poll() is not None:
                self._proc = None
                self._run_cleanup_script()
                return self._status_locked()
            pgid = os.getpgid(proc.pid)

        # Graceful: SIGINT == Ctrl+C, which makes mitigate.py run its finally block
        # and undo its own iptables REDIRECT + sysctl changes.
        self._signal_group(pgid, signal.SIGINT)
        if not self._wait_exit(proc, timeout=8):
            self._signal_group(pgid, signal.SIGKILL)
            self._wait_exit(proc, timeout=3)

        with self._lock:
            self._proc = None
            self._run_cleanup_script()  # safety net for any leftover rules
            return self._status_locked()

    def status(self) -> dict:
        with self._lock:
            return self._status_locked()

    def logs(self, n: int = 200) -> list[str]:
        with self._lock:
            data = list(self._logs)
        return data if n >= len(data) else data[-n:]

    # ------------------------------------------------------------- internals ---
    def _build_cmd(self) -> list[str]:
        cmd = [
            config.PYTHON_BIN,
            config.MITIGATE_PATH,
            "-m",                       # measure ping: adaptive delay + telemetry
            "-e", str(config.EXTRA_DELAY),
        ]
        if os.path.exists(config.OPCODES_JSON):
            cmd += ["-j", config.OPCODES_JSON]   # vendored opcodes, no runtime GitHub
        return cmd

    def _preflight(self) -> str | None:
        if not os.path.exists(config.MITIGATE_PATH):
            return (
                f"mitigate.py not found at {config.MITIGATE_PATH}. "
                "Fetch it into vendor/ (see README)."
            )
        if os.geteuid() != 0:
            return "Control panel is not running as root; the mitigator needs root."
        return None

    def _read_loop(self, proc: subprocess.Popen) -> None:
        assert proc.stderr is not None
        for raw in proc.stderr:
            self._ingest(raw.rstrip("\n"))
        rc = proc.poll()
        with self._lock:
            self._append_log(f"[mitigator exited, code={rc}]")
            if rc not in (0, None) and not self._last_error:
                self._last_error = f"Mitigator stopped unexpectedly (code {rc})."

    def _ingest(self, line: str) -> None:
        with self._lock:
            self._append_log(line)
            if _RE_LISTENING.search(line):
                self._listening = True
            if _RE_ROOT.search(line):
                self._last_error = "Permission denied: the mitigator needs root."

            changed = False
            if (m := _RE_RTT.search(line)):
                self._tele["rtt_ms"] = int(m.group(1)); changed = True
            if (m := _RE_WAIT.search(line)):
                base, reduced = int(m.group(1)), int(m.group(2))
                self._tele["base_lock_ms"] = base
                self._tele["reduced_lock_ms"] = reduced
                self._tele["saved_ms"] = max(0, base - reduced)
                changed = True
            if (m := _RE_DOWN.search(line)):
                self._tele["down_ms"] = int(m.group(1)); changed = True
            if (m := _RE_UP.search(line)):
                self._tele["up_ms"] = int(m.group(1)); changed = True
            if changed:
                self._tele["updated_at"] = time.time()

    def _status_locked(self) -> dict:
        running = self._running_locked()
        tele = dict(self._tele)
        age = (time.time() - tele["updated_at"]) if tele["updated_at"] else None
        return {
            "running": running,
            "listening": bool(self._listening and running),
            "pid": self._proc.pid if running else None,
            "uptime_s": int(time.time() - self._started_at) if running else 0,
            "telemetry": tele,
            "telemetry_age_s": int(age) if age is not None else None,
            "opcodes_updated_at": self._opcodes_mtime(),
            "error": self._last_error,
        }

    def _running_locked(self) -> bool:
        return self._proc is not None and self._proc.poll() is None

    def _append_log(self, line: str) -> None:
        self._logs.append(f"{time.strftime('%H:%M:%S')}  {line}")

    @staticmethod
    def _blank_tele() -> dict:
        return {
            "rtt_ms": None,
            "base_lock_ms": None,
            "reduced_lock_ms": None,
            "saved_ms": None,
            "down_ms": None,
            "up_ms": None,
            "updated_at": 0.0,
        }

    @staticmethod
    def _signal_group(pgid: int, sig: int) -> None:
        try:
            os.killpg(pgid, sig)
        except ProcessLookupError:
            pass

    @staticmethod
    def _wait_exit(proc: subprocess.Popen, timeout: float) -> bool:
        deadline = time.time() + timeout
        while time.time() < deadline:
            if proc.poll() is not None:
                return True
            time.sleep(0.2)
        return proc.poll() is not None

    @staticmethod
    def _opcodes_mtime() -> int | None:
        try:
            return int(os.path.getmtime(config.OPCODES_JSON))
        except OSError:
            return None

    def _run_cleanup_script(self) -> None:
        # mitigate.py writes a .cleanup.sh next to itself that removes any iptables
        # rules it added. We run it on stop as a belt-and-suspenders measure.
        path = os.path.join(os.path.dirname(config.MITIGATE_PATH), ".cleanup.sh")
        if os.path.exists(path):
            try:
                subprocess.run(
                    ["sh", path], timeout=10,
                    stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                )
            except Exception:
                pass


controller = MitigatorController()
