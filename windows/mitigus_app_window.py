#!/usr/bin/env python3
"""
Entry da versão "janela" do app: igual ao mitigus_app, mas abre o painel numa
janela do app (Edge --app, sem abas/barra de endereço) em vez de uma aba do
navegador. Gera o "Mitigus XIV (janela).exe".
"""
from __future__ import annotations

import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
if HERE not in sys.path:
    sys.path.insert(0, HERE)

import mitigus_app

if __name__ == "__main__":
    raise SystemExit(mitigus_app.run_entry("window") or 0)
