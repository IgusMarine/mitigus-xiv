#!/usr/bin/env python3
"""
Gera o ícone do app (mitigus.ico) — desenho 100% original (cristal/diamante teal
sobre fundo escuro arredondado), o mesmo motivo do painel. Não usa nenhuma arte
da Square Enix/FFXIV.

    pip install pillow
    python tools/make_icon.py

Saída: windows/mitigus.ico (multi-resolução) e windows/tools/icon_preview.png.
"""
from __future__ import annotations

import os

from PIL import Image, ImageDraw, ImageFilter

S = 1024
CX = CY = S // 2
HERE = os.path.dirname(os.path.abspath(__file__))
OUT_ICO = os.path.join(os.path.dirname(HERE), "mitigus.ico")
OUT_PNG = os.path.join(HERE, "icon_preview.png")

NAVY = (12, 20, 33, 255)
TEAL_LIGHT = (132, 236, 212, 255)
TEAL_MID = (45, 212, 191, 255)
TEAL_DARK = (24, 150, 130, 255)
TEAL_DARKER = (14, 104, 92, 255)


def _layer():
    return Image.new("RGBA", (S, S), (0, 0, 0, 0))


def build() -> Image.Image:
    canvas = _layer()
    d = ImageDraw.Draw(canvas)
    d.rectangle([0, 0, S, S], fill=NAVY)

    # brilho suave no topo (profundidade)
    sheen = _layer()
    ImageDraw.Draw(sheen).ellipse([CX - 460, -260, CX + 460, 360], fill=(46, 74, 110, 150))
    canvas.alpha_composite(sheen.filter(ImageFilter.GaussianBlur(120)))

    # glow atrás do cristal
    glow = _layer()
    ImageDraw.Draw(glow).ellipse([CX - 300, CY - 300, CX + 300, CY + 300], fill=(45, 212, 191, 110))
    canvas.alpha_composite(glow.filter(ImageFilter.GaussianBlur(90)))

    # cristal facetado (iluminado pela direita)
    T = (CX, 150)
    UL, UR = (250, 470), (774, 470)
    C = (CX, 470)
    B = (CX, 884)
    d.polygon([T, UL, C], fill=TEAL_MID)        # coroa esquerda
    d.polygon([T, C, UR], fill=TEAL_LIGHT)       # coroa direita (mais clara)
    d.polygon([UL, C, B], fill=TEAL_DARKER)      # pavilhão esquerdo (sombra)
    d.polygon([C, UR, B], fill=TEAL_DARK)        # pavilhão direito
    # aresta-glint central
    d.line([T, B], fill=(220, 255, 248, 120), width=6)

    # recorta em quadrado arredondado
    mask = Image.new("L", (S, S), 0)
    ImageDraw.Draw(mask).rounded_rectangle([40, 40, S - 40, S - 40], radius=210, fill=255)
    canvas.putalpha(mask)
    return canvas


def main() -> None:
    img = build()
    base = img.resize((256, 256), Image.LANCZOS)
    sizes = [(16, 16), (24, 24), (32, 32), (48, 48), (64, 64), (128, 128), (256, 256)]
    base.save(OUT_ICO, sizes=sizes)
    img.resize((512, 512), Image.LANCZOS).save(OUT_PNG)
    print(f"ok: {OUT_ICO}")
    print(f"ok: {OUT_PNG}")


if __name__ == "__main__":
    main()
