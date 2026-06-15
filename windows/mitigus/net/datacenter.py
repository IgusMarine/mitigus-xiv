"""
Identifica a REGIÃO do servidor de FFXIV pelo IP (faixas públicas da Square Enix).

Mostramos a região (NA/EU/JP/OCE) + o IP no painel — coisa que o console não tem
overlay pra ver. Não tentamos adivinhar o data center exato (Aether/Crystal/...),
porque os DCs de uma mesma região compartilham as mesmas faixas de IP de zona e não
dá pra separar com confiança só pelo IP. Honesto > bonito-e-errado.

Tabela editável: é só prefixo de IP -> (sigla, rótulo). As faixas vêm do
Server_IpRange das definições do XivAlexander (mesma fonte dos opcodes).
"""
from __future__ import annotations

from typing import Optional

# (prefixo do IP, sigla, rótulo amigável)
SE_BLOCKS = (
    ("204.2.29.", "NA", "América do Norte"),
    ("204.2.229.", "NA", "América do Norte"),
    ("80.239.145.", "EU", "Europa"),
    ("124.150.157.", "JP", "Japão"),
    ("153.254.80.", "JP", "Japão"),
    ("119.252.", "JP", "Japão"),
    ("125.6.", "JP", "Japão"),
    ("103.6.20.", "OCE", "Oceania"),
)


def lookup(ip: Optional[str]) -> dict:
    """Devolve {region, label} para o IP, ou {None, None} se não reconhecido."""
    if ip:
        for prefix, region, label in SE_BLOCKS:
            if ip.startswith(prefix):
                return {"region": region, "label": label}
    return {"region": None, "label": None}
