"""
Central configuration for the Weave Box control panel.

Every value can be overridden with an environment variable, so you never have to
edit this file to move things around. Defaults assume the layout produced by
scripts/install.sh.
"""
import os

BASE_DIR = os.path.dirname(os.path.abspath(__file__))

# --- Mitigator (the upstream XivMitmLatencyMitigator script) -----------------
# Fetch mitigate.py from the repo into vendor/ (see README). The control panel
# launches it as a subprocess; it is never modified by us.
MITIGATE_PATH = os.environ.get(
    "WEAVE_MITIGATE_PATH", os.path.join(BASE_DIR, "vendor", "mitigate.py")
)

# Local opcode definitions, produced by scripts/update-opcodes.sh. When this file
# exists we pass it with -j, so the mitigator NEVER calls GitHub at runtime.
OPCODES_JSON = os.environ.get(
    "WEAVE_OPCODES_JSON", os.path.join(BASE_DIR, "vendor", "opcodes.json")
)

# Python interpreter used to run mitigate.py.
PYTHON_BIN = os.environ.get("WEAVE_PYTHON_BIN", "python3")

# Safety margin handed to the mitigator (seconds). 0.075 is the documented floor
# that keeps you above the server's sanity check. Do NOT lower this.
EXTRA_DELAY = os.environ.get("WEAVE_EXTRA_DELAY", "0.075")

# --- Web panel ----------------------------------------------------------------
HOST = os.environ.get("WEAVE_HOST", "0.0.0.0")          # reachable from the LAN
PORT = int(os.environ.get("WEAVE_PORT", "8080"))
LOG_BUFFER = int(os.environ.get("WEAVE_LOG_BUFFER", "600"))  # lines kept in memory
