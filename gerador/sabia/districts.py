"""Bairros (G4): a lista de bairros de cada estado e o bairro de cada registro.

- **Lista.** As áreas de bairro do OpenStreetMap (relações e vias fechadas com `place` suburb, quarter ou
  neighbourhood, ou limite administrativo de nível 10 ou 9), cada uma no município do ponto central dela; mais os
  pontos de bairro (nós `place=`) que não têm área de mesmo nome no mesmo município.
- **Bairro de um registro.** O do polígono que contém o ponto dele: bairro antes de vizinhança, vizinhança antes de
  distrito (kinds.DISTRICT_RANK) e, no mesmo nível, o menor polígono. Fora de todos os polígonos, o ponto de bairro mais
  próximo, até 3 km e no mesmo município (a reserva da medição: com o ponto só, o bairro acerta a menos de 3 km em
  73% das ruas; com o polígono, a rua está dentro do bairro).

Os municípios e os próprios bairros (lugares suburb, quarter, neighbourhood) ficam sem bairro.
"""
from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
from typing import Dict, List, Optional, Sequence, Tuple

import numpy as np
import shapely
from shapely.geometry.base import BaseGeometry
from shapely.strtree import STRtree

from . import config, geo, kinds
from .municipalities import MunicipalityIndex
from .osm_reader import OsmData
from .records import Item
from .sources import Municipality
from .text import fold

# A reserva: ponto de bairro mais próximo, até esta distância.
FALLBACK_MAX_M = 3000.0
_GRID_DEG = 0.05  # grade dos pontos de bairro para a reserva (> 3 km em qualquer latitude do Brasil)


@dataclass
class District:
    name: str
    municipality: str
    kind: str                          # kinds.district_kind
    lat: float
    lng: float
    polygon: Optional[BaseGeometry]    # None: bairro conhecido só pelo ponto
    id: int = 0                        # 1, 2, ... dentro do estado


def build(data: OsmData, municipalities: Sequence[Municipality], states: Sequence[str]) -> Dict[str, List[District]]:
    """{UF: bairros}, em ordem fixa (município, nome, posição), com `id` a partir de 1 em cada estado."""
    wanted = set(states)
    index = MunicipalityIndex([m for m in municipalities if m.uf in wanted])
    found: List[District] = []
    centers = [a.geometry.representative_point() for a in data.district_areas]
    area_mun = index.locate([c.y for c in centers], [c.x for c in centers])
    with_polygon = set()
    for area, center, code in zip(data.district_areas, centers, area_mun):
        if code is None:
            continue
        found.append(District(area.name, code, area.kind, center.y, center.x, area.geometry))
        with_polygon.add((code, fold(area.name)))
    points = [p for p in data.places if p.kind in kinds.DISTRICT_PLACES and not p.from_area]
    point_mun = index.locate([p.lat for p in points], [p.lng for p in points])
    for place, code in zip(points, point_mun):
        if code is None or (code, fold(place.name)) in with_polygon:
            continue
        found.append(District(place.name, code, place.kind, place.lat, place.lng, None))
    out: Dict[str, List[District]] = {uf: [] for uf in sorted(wanted)}
    for d in sorted(found, key=lambda d: (d.municipality, fold(d.name), d.name, d.lat, d.lng, d.kind)):
        out[config.IBGE_STATE_CODES[d.municipality[:2]]].append(d)
    for ds in out.values():
        for i, d in enumerate(ds, 1):
            d.id = i
    return out


def _needs_district(item: Item) -> bool:
    if item.kind == "municipality":
        return False
    return not (item.cls == "place" and item.kind.removeprefix("place=") in kinds.DISTRICT_PLACES)


def _by_polygon(items: Sequence[Item], districts: Sequence[District]) -> List[Optional[District]]:
    polys = [d for d in districts if d.polygon is not None]
    out: List[Optional[District]] = [None] * len(items)
    if not polys or not items:
        return out
    tree = STRtree([d.polygon for d in polys])
    points = shapely.points(np.array([i.lng for i in items]), np.array([i.lat for i in items]))
    item_idx, poly_idx = tree.query(points, predicate="within")
    best: Dict[int, Tuple[int, float, int]] = {}
    for it, pi in zip(item_idx.tolist(), poly_idx.tolist()):
        d = polys[pi]
        key = (kinds.DISTRICT_RANK.get(d.kind, 9), d.polygon.area, d.id)  # type: ignore[union-attr]
        if it not in best or key < best[it]:
            best[it] = key
    by_id = {d.id: d for d in polys}
    for it, key in best.items():
        out[it] = by_id[key[2]]
    return out


def _by_nearest_point(item: Item, grid: Dict[Tuple[int, int], List[District]]) -> Optional[District]:
    gx, gy = int(item.lng // _GRID_DEG), int(item.lat // _GRID_DEG)
    best, best_d = None, FALLBACK_MAX_M
    for dx in (-1, 0, 1):
        for dy in (-1, 0, 1):
            for d in grid.get((gx + dx, gy + dy), ()):
                if d.municipality != item.municipality:
                    continue
                dist = geo.dist_m(item.lat, item.lng, d.lat, d.lng)
                if dist <= best_d:
                    best, best_d = d, dist
    return best


def assign(items_by_state: Dict[str, List[Item]], districts_by_state: Dict[str, List[District]]) -> None:
    """Preenche `district` e `district_id` dos registros, estado por estado."""
    for uf, items in items_by_state.items():
        districts = districts_by_state.get(uf, [])
        targets = [i for i in items if _needs_district(i)]
        grid: Dict[Tuple[int, int], List[District]] = defaultdict(list)
        for d in districts:
            if d.polygon is None:
                grid[(int(d.lng // _GRID_DEG), int(d.lat // _GRID_DEG))].append(d)
        for item, inside in zip(targets, _by_polygon(targets, districts)):
            chosen = inside if inside is not None else _by_nearest_point(item, grid)
            if chosen is not None:
                item.district, item.district_id = chosen.name, chosen.id
