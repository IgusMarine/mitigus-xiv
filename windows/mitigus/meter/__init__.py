"""
Medidor de DPS (variante DPS / branch dps-meter).

Parser de combate + agregador de DPS, alimentado pelos ActionEffect JÁ
desofuscados (ver research/deob). Independente do deob: opera sobre o buffer
IPC em claro (a partir do header IPC). Reusável tanto offline (analisar uma
captura) quanto ao vivo (no relay).
"""
