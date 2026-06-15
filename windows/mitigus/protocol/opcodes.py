"""
Definições de opcode do FFXIV (Fase 2).

Os opcodes IPC (o campo `type` de 16 bits de cada mensagem) são embaralhados pela
Square Enix a CADA patch, como anti-tooling. Portanto os valores não podem ser
hardcoded: carregamos de um JSON externo, auto-atualizável, no MESMO formato que
o XivAlexander/XivMitmLatencyMitigator usam (pasta StaticData/OpcodeDefinition),
para reaproveitar os dumps que a comunidade mantém a cada patch.

`OpcodeDefinition` espelha fielmente o do `mitigate.py` (mesmos nomes de campo),
para o port da lógica de mitigação (Fase 4) encaixar sem tradução.
"""
from __future__ import annotations

import dataclasses
import ipaddress
import json
import os
import time
import urllib.request
from typing import List, Optional, Tuple, Union

OPCODE_DEFINITION_LIST_URL = (
    "https://api.github.com/repos/Soreepeong/XivAlexander/contents/StaticData/OpcodeDefinition"
)

# Campos de opcode (inteiros) que nos interessam, na ordem do mitigate.py.
INT_FIELDS = (
    "C2S_ActionRequest",
    "C2S_ActionRequestGroundTargeted",
    "S2C_ActionEffect01",
    "S2C_ActionEffect08",
    "S2C_ActionEffect16",
    "S2C_ActionEffect24",
    "S2C_ActionEffect32",
    "S2C_ActorCast",
    "S2C_ActorControl",
    "S2C_ActorControlSelf",
)

_IpRange = Union[ipaddress.IPv4Network, Tuple[ipaddress.IPv4Address, ipaddress.IPv4Address]]


def _as_int(v) -> int:
    return int(v, 0) if isinstance(v, str) else int(v)


def _parse_ip_ranges(spec: str) -> List[_IpRange]:
    out: List[_IpRange] = []
    for partstr in (spec or "").split(","):
        partstr = partstr.strip()
        if not partstr:
            continue
        part = [x.strip() for x in partstr.split("-")]
        try:
            if len(part) == 1:
                out.append(ipaddress.IPv4Network(part[0]))
            elif len(part) == 2:
                out.append(tuple(sorted(ipaddress.IPv4Address(x) for x in part)))
            else:
                raise ValueError
        except ValueError:
            pass  # ignora entrada inválida, como o original
    return out


def _parse_port_ranges(spec: str) -> List[Tuple[int, int]]:
    out: List[Tuple[int, int]] = []
    for partstr in (spec or "").split(","):
        partstr = partstr.strip()
        if not partstr:
            continue
        part = [x.strip() for x in partstr.split("-")]
        try:
            if len(part) == 1:
                out.append((int(part[0], 0), int(part[0], 0)))
            elif len(part) == 2:
                out.append((int(part[0], 0), int(part[1], 0)))
            else:
                raise ValueError
        except ValueError:
            pass
    return out


@dataclasses.dataclass
class OpcodeDefinition:
    Name: str
    C2S_ActionRequest: int
    C2S_ActionRequestGroundTargeted: int
    S2C_ActionEffect01: int
    S2C_ActionEffect08: int
    S2C_ActionEffect16: int
    S2C_ActionEffect24: int
    S2C_ActionEffect32: int
    S2C_ActorCast: int
    S2C_ActorControl: int
    S2C_ActorControlSelf: int
    Common_UseOodleTcp: bool
    Server_IpRange: List[_IpRange]
    Server_PortRange: List[Tuple[int, int]]

    @classmethod
    def from_dict(cls, data: dict) -> "OpcodeDefinition":
        kwargs = {"Name": str(data.get("Name", "?"))}
        for field in INT_FIELDS:
            kwargs[field] = _as_int(data[field])
        kwargs["Common_UseOodleTcp"] = bool(data.get("Common_UseOodleTcp", True))
        kwargs["Server_IpRange"] = _parse_ip_ranges(data.get("Server_IpRange", ""))
        kwargs["Server_PortRange"] = _parse_port_ranges(data.get("Server_PortRange", ""))
        return cls(**kwargs)

    def is_action_effect(self, opcode: int) -> bool:
        return opcode in (
            self.S2C_ActionEffect01,
            self.S2C_ActionEffect08,
            self.S2C_ActionEffect16,
            self.S2C_ActionEffect24,
            self.S2C_ActionEffect32,
        )

    def opcode_name(self, opcode: int) -> Optional[str]:
        """Nome semântico de um opcode (reverse lookup) — útil para log/telemetria."""
        for field in INT_FIELDS:
            if getattr(self, field) == opcode:
                return field
        return None

    def matches_server(self, ip: str, port: int) -> bool:
        in_ip = not self.Server_IpRange
        addr = ipaddress.IPv4Address(ip)
        for r in self.Server_IpRange:
            if isinstance(r, ipaddress.IPv4Network):
                if addr in r:
                    in_ip = True
                    break
            else:
                if r[0] <= addr <= r[1]:
                    in_ip = True
                    break
        in_port = not self.Server_PortRange or any(lo <= port <= hi for lo, hi in self.Server_PortRange)
        return in_ip and in_port


def download_definitions() -> List[dict]:
    """Baixa todos os JSONs da pasta OpcodeDefinition do XivAlexander."""
    def _get(url):
        req = urllib.request.Request(url, headers={"User-Agent": "mitigus-xiv"})
        with urllib.request.urlopen(req, timeout=30) as resp:
            return json.load(resp)

    filelist = _get(OPCODE_DEFINITION_LIST_URL)
    out: List[dict] = []
    for f in filelist:
        if not str(f.get("name", "")).lower().endswith(".json"):
            continue
        data = _get(f["download_url"])
        data["Name"] = f["name"]
        out.append(data)
    return out


def _parse_all(raw: List[dict]) -> List[OpcodeDefinition]:
    defs: List[OpcodeDefinition] = []
    for entry in raw:
        try:
            defs.append(OpcodeDefinition.from_dict(entry))
        except (KeyError, ValueError, TypeError):
            pass  # pula definições incompletas/quebradas
    return defs


def default_cache_path() -> str:
    from ..paths import app_dir, is_frozen

    # Empacotado: o pacote fica em _MEIPASS (temporário/read-only); grava o cache
    # ao lado do .exe. No modo fonte, mantém junto do módulo.
    if is_frozen():
        return os.path.join(app_dir(), "definitions.json")
    return os.path.join(os.path.dirname(os.path.abspath(__file__)), "definitions.json")


def load_definitions(
    json_path: Optional[str] = None,
    cache_path: Optional[str] = None,
    force_update: bool = False,
    ttl: float = 3600.0,
) -> List[OpcodeDefinition]:
    """
    Carrega as definições. Prioridade:
      1. json_path explícito (um único arquivo de definição)
      2. cache local fresco (< ttl) em cache_path
      3. download da fonte XivAlexander (e grava o cache)
    """
    if json_path:
        with open(json_path, encoding="utf-8") as fp:
            return _parse_all([{"Name": os.path.basename(json_path), **json.load(fp)}])

    cache_path = cache_path or default_cache_path()
    if os.path.exists(cache_path) and not force_update:
        age = time.time() - os.path.getmtime(cache_path)
        if age < ttl:
            with open(cache_path, encoding="utf-8") as fp:
                return _parse_all(json.load(fp))

    raw = download_definitions()
    with open(cache_path, "w", encoding="utf-8") as fp:
        json.dump(raw, fp)
    return _parse_all(raw)


def match_for_server(
    defs: List[OpcodeDefinition], ip: str, port: int
) -> Optional[OpcodeDefinition]:
    """Escolhe a definição cujo range de servidor casa com a conexão observada."""
    for d in defs:
        if d.matches_server(ip, port):
            return d
    return None
