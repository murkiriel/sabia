"""Traçado das ruas (G5, decisão D6): o que responde "que rua é esta?" a partir de uma coordenada.

Cada trecho de rua com nome (e cada trecho sem nome de uma rodovia) é simplificado a 10 m (Douglas-Peucker) e
cortado em pedaços de até 2 km; cada pedaço guarda o quadrado do zoom 13 do meio dele (`cell`). Assim, quem procura a
rua de um ponto lê só os pedaços dos 9 quadrados em volta e mede a distância até os segmentos: um pedaço nunca passa
de 1 km do próprio meio, bem menos que o lado de um quadrado (~4 km).

Medido em Goiás (4.000 pontos tirados do meio de trechos de rua, até 12 m para o lado): o traçado simplificado a 10 m
acerta a rua de 99% dos pontos, com ~8 MB; um ponto a cada 50 m acertava 95% com 47 MB.

`coords`: int32 little-endian, lat e lng de cada vértice multiplicados por 100.000 (5 casas, ~1 m), na ordem
lat, lng, lat, lng...
"""
from __future__ import annotations

import math
import struct
from dataclasses import dataclass
from typing import List, Optional, Sequence, Tuple

from shapely.geometry import LineString

from . import geo
from .osm_reader import OsmData
from .records import Item

SIMPLIFY_M = 10.0
MAX_PIECE_M = 2000.0
SCALE = 100_000

Coords = List[Tuple[float, float]]


@dataclass
class StreetLine:
    item: int        # índice do registro na lista do estado (no banco, o id do registro é índice + 1)
    cell: int
    coords: bytes


def encode(coords: Sequence[Tuple[float, float]]) -> bytes:
    flat = [round(v * SCALE) for point in coords for v in point]
    return struct.pack(f"<{len(flat)}i", *flat)


def decode(blob: bytes) -> Coords:
    flat = struct.unpack(f"<{len(blob) // 4}i", blob)
    return [(flat[i] / SCALE, flat[i + 1] / SCALE) for i in range(0, len(flat), 2)]


def simplify(lats: Sequence[float], lngs: Sequence[float], tolerance_m: float = SIMPLIFY_M) -> Coords:
    """Douglas-Peucker em metros (plano local na latitude do trecho)."""
    lat0 = lats[0]
    k = geo.M_PER_DEG * math.cos(math.radians(lat0))
    line = LineString([(lng * k, lat * geo.M_PER_DEG) for lat, lng in zip(lats, lngs)])
    simple = line.simplify(tolerance_m, preserve_topology=False)
    return [(y / geo.M_PER_DEG, x / k) for x, y in simple.coords]


def cut(coords: Coords, max_m: float = MAX_PIECE_M) -> List[Coords]:
    """Pedaços de até `max_m` de comprimento; um segmento longo ganha vértices no meio. Pedaços vizinhos dividem o
    vértice da emenda."""
    pieces: List[Coords] = []
    current: Coords = [coords[0]]
    length = 0.0
    for b in coords[1:]:
        a = current[-1]
        seg = geo.dist_m(*a, *b)
        while length + seg > max_m and seg > 0:
            t = (max_m - length) / seg
            point = (a[0] + t * (b[0] - a[0]), a[1] + t * (b[1] - a[1]))
            current.append(point)
            pieces.append(current)
            current, length = [point], 0.0
            a, seg = point, geo.dist_m(*point, *b)
        current.append(b)
        length += seg
    if len(current) >= 2:
        pieces.append(current)
    return pieces


def build(items: Sequence[Item], data: OsmData) -> List[StreetLine]:
    """Os pedaços de traçado de um estado. Trecho com nome vai para a rua; trecho só com `ref`, para a rodovia."""
    out: List[StreetLine] = []
    for index, item in enumerate(items):
        if item.cls not in ("street", "road"):
            continue
        for w in item.ways:
            way = data.ways[w]
            if item.cls == "road" and way.name:
                continue  # o traçado de um trecho com nome já está na rua
            for piece in cut(simplify(way.lats, way.lngs)):
                lat, lng = geo.midpoint([p[0] for p in piece], [p[1] for p in piece])
                out.append(StreetLine(index, geo.cell(lat, lng), encode(piece)))
    return out


def distance_to_line(lat: float, lng: float, coords: Coords) -> float:
    """Metros do ponto até o segmento mais próximo da linha (plano local no ponto)."""
    k = geo.M_PER_DEG * math.cos(math.radians(lat))
    px, py = lng * k, lat * geo.M_PER_DEG
    best = math.inf
    for (alat, alng), (blat, blng) in zip(coords, coords[1:]):
        ax, ay, bx, by = alng * k, alat * geo.M_PER_DEG, blng * k, blat * geo.M_PER_DEG
        dx, dy = bx - ax, by - ay
        seg2 = dx * dx + dy * dy
        t = 0.0 if seg2 == 0 else max(0.0, min(1.0, ((px - ax) * dx + (py - ay) * dy) / seg2))
        best = min(best, math.hypot(px - (ax + t * dx), py - (ay + t * dy)))
    return best


def nearest(lines: Sequence[StreetLine], lat: float, lng: float) -> Optional[StreetLine]:
    """O pedaço mais perto do ponto entre `lines` (quem consome passa só os dos 9 quadrados em volta)."""
    best, best_d = None, math.inf
    for line in lines:
        d = distance_to_line(lat, lng, decode(line.coords))
        if d < best_d:
            best, best_d = line, d
    return best
