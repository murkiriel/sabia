"""Contas de geometria pequenas, em graus (lat, lng) e metros, sem projeção: as distâncias que importam aqui são
de dezenas de metros a poucos quilômetros, em que a aproximação plana local erra menos de 1%."""
from __future__ import annotations

import math
from typing import Sequence, Tuple

M_PER_DEG = 111_320.0
# Zoom do quadrado do mapa (`cell`): no 13, ~4,9 km de lado no equador, ~4,2 km a 30° S. "Mais perto" e "que rua é
# esta?" olham os 9 quadrados em volta do ponto.
CELL_ZOOM = 13


def dist_m(lat1: float, lng1: float, lat2: float, lng2: float) -> float:
    k = math.cos(math.radians((lat1 + lat2) / 2))
    return math.hypot((lat1 - lat2) * M_PER_DEG, (lng1 - lng2) * M_PER_DEG * k)


def cell(lat: float, lng: float, zoom: int = CELL_ZOOM) -> int:
    """O quadrado do mapa (tile do zoom 13, o mesmo dos mapas na web) como um número só: x * 2^zoom + y."""
    n = 1 << zoom
    x = min(n - 1, max(0, int((lng + 180.0) / 360.0 * n)))
    lat_rad = math.radians(max(-85.05112878, min(85.05112878, lat)))
    y = min(n - 1, max(0, int((1.0 - math.asinh(math.tan(lat_rad)) / math.pi) / 2.0 * n)))
    return x * n + y


def midpoint(lats: Sequence[float], lngs: Sequence[float]) -> Tuple[float, float]:
    """O ponto no meio do comprimento de uma linha."""
    if len(lats) == 1:
        return lats[0], lngs[0]
    lengths = [dist_m(lats[i], lngs[i], lats[i + 1], lngs[i + 1]) for i in range(len(lats) - 1)]
    half = sum(lengths) / 2
    for i, seg in enumerate(lengths):
        if half <= seg and seg > 0:
            t = half / seg
            return lats[i] + t * (lats[i + 1] - lats[i]), lngs[i] + t * (lngs[i + 1] - lngs[i])
        half -= seg
    return lats[-1], lngs[-1]


def extent_m(lats: Sequence[float], lngs: Sequence[float]) -> float:
    """A diagonal do retângulo que contém os pontos: a extensão "de ponta a ponta" de uma rua juntada."""
    return dist_m(min(lats), min(lngs), max(lats), max(lngs))
