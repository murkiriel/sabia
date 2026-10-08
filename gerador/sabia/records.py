"""Os registros de cada estado, a partir do que o osm_reader leu e dos municípios do IBGE.

| cls      | O que é |
|----------|---------|
| `place`  | Município (`kind` "municipality": nome do IBGE, ponto da sede) e lugares com nome do OpenStreetMap |
| `street` | Uma rua: os trechos de mesmo nome no mesmo município que se tocam ou têm as pontas a menos de 60 m (D5) |
| `road`   | Uma rodovia (`ref`) em um município: "BR-153" em Anápolis |
| `poi`    | Ponto de interesse (D7) |

Cada registro é do município cujo polígono contém o ponto dele (o meio da via, para ruas e rodovias); o estado é o
do município. O que cai fora dos municípios dos estados pedidos fica de fora.
"""
from __future__ import annotations

import math
import re
from collections import defaultdict
from dataclasses import dataclass, field
from typing import Dict, Iterable, List, Optional, Sequence, Tuple

from . import config, geo, kinds
from .municipalities import MunicipalityIndex
from .osm_reader import OsmData, Way
from .sources import Municipality
from .text import fold

# D5: pontas de trechos de mesmo nome a menos disto se juntam.
MERGE_GAP_M = 60.0
# Rua só de vias locais com mais que isto de ponta a ponta: suspeita de junção errada (vai para o relatório).
LONG_LOCAL_STREET_M = 3000.0
# Um lugar desenhado como área só entra se não houver um ponto de lugar de mesmo nome no município a até esta distância.
AREA_PLACE_DUPLICATE_M = 2000.0

CLS_ORDER = {"place": 0, "street": 1, "road": 2, "poi": 3}


@dataclass
class Item:
    cls: str
    kind: str
    name: str
    municipality: str
    lat: float
    lng: float
    district: Optional[str] = None                     # nome do bairro (G4)
    district_id: Optional[int] = None
    ways: List[int] = field(default_factory=list)      # índices em OsmData.ways: o traçado (G5)
    extent_m: float = 0.0
    suspect_long: bool = False
    aliases: List[str] = field(default_factory=list)   # nomes alternativos: só no índice de busca (HS9)
    source: str = ""                                   # origem sem conferência no mapa: "anp" (HP5b1); "" = o mapa

    @property
    def uf(self) -> str:
        return config.IBGE_STATE_CODES[self.municipality[:2]]


def order_key(it: "Item") -> Tuple[int, str, str, float, float, str]:
    """A ordem dos registros de um estado em toda geração: classe, nome sem acento, nome, ponto, kind."""
    return (CLS_ORDER[it.cls], fold(it.name), it.name, it.lat, it.lng, it.kind)


class _Dsu:
    def __init__(self, n: int) -> None:
        self.parent = list(range(n))

    def find(self, x: int) -> int:
        while self.parent[x] != x:
            self.parent[x] = self.parent[self.parent[x]]
            x = self.parent[x]
        return x

    def union(self, a: int, b: int) -> None:
        ra, rb = self.find(a), self.find(b)
        if ra != rb:
            self.parent[max(ra, rb)] = min(ra, rb)


def merge_segments(ways: Sequence[Way], gap_m: float = MERGE_GAP_M) -> List[List[int]]:
    """D5: grupos de trechos (índices em `ways`) que se tocam (nó em comum) ou têm pontas a menos de `gap_m`.
    Em cadeia: A perto de B e B perto de C juntam os três."""
    dsu = _Dsu(len(ways))
    owner: Dict[int, int] = {}
    for i, w in enumerate(ways):
        for node in w.nodes:
            if node in owner:
                dsu.union(i, owner[node])
            else:
                owner[node] = i
    # pontas numa grade de `gap_m`: só as das células vizinhas podem estar perto
    lat0 = ways[0].lats[0] if ways else 0.0
    k = geo.M_PER_DEG * max(0.1, abs(math.cos(math.radians(lat0))))
    grid: Dict[Tuple[int, int], List[Tuple[int, float, float]]] = defaultdict(list)
    for i, w in enumerate(ways):
        for lat, lng in ((w.lats[0], w.lngs[0]), (w.lats[-1], w.lngs[-1])):
            gx, gy = int(lng * k // gap_m), int(lat * geo.M_PER_DEG // gap_m)
            for dx in (-1, 0, 1):
                for dy in (-1, 0, 1):
                    for j, lat2, lng2 in grid.get((gx + dx, gy + dy), ()):
                        if j != i and geo.dist_m(lat, lng, lat2, lng2) < gap_m:
                            dsu.union(i, j)
            grid[(gx, gy)].append((i, lat, lng))
    groups: Dict[int, List[int]] = defaultdict(list)
    for i in range(len(ways)):
        groups[dsu.find(i)].append(i)
    return [sorted(g) for g in groups.values()]


def _central_point(ways: Sequence[Way]) -> Tuple[float, float]:
    """O meio do trecho cujo meio fica mais perto da média dos meios de todos: "o trecho mais central"."""
    mids = [geo.midpoint(w.lats, w.lngs) for w in ways]
    mean_lat = sum(m[0] for m in mids) / len(mids)
    mean_lng = sum(m[1] for m in mids) / len(mids)
    return min(mids, key=lambda m: geo.dist_m(m[0], m[1], mean_lat, mean_lng))


REF_PATTERN = re.compile(r"^([A-Z]{2,4})[\s-]*(\d+[A-Z]?)$")


def split_refs(ref: str) -> List[str]:
    """'BR-153;GO-060' -> ['BR-153', 'GO-060']; 'BR 153' -> ['BR-153']; '74423020' (um CEP) -> []."""
    out = []
    for part in re.split(r"[;/]", ref.upper()):
        part = " ".join(part.split())
        if not part:
            continue
        m = REF_PATTERN.match(part)
        if m:  # o resto não é código de rodovia (há CEP em `ref`)
            out.append(f"{m.group(1)}-{m.group(2)}")
    return list(dict.fromkeys(out))


def _seat(municipality: Municipality, places: Iterable[Tuple[int, object]]) -> Optional[int]:
    """Índice do lugar do OpenStreetMap que é a sede: mesmo nome dobrado, o de maior posto (cidade antes de vila)."""
    target = fold(municipality.name)
    best = None
    for idx, place in places:
        rank = kinds.SEAT_RANK.get(place.kind)  # type: ignore[attr-defined]
        if rank is None or fold(place.name) != target:  # type: ignore[attr-defined]
            continue
        if best is None or rank < best[0]:
            best = (rank, idx)
    return best[1] if best else None


def build(data: OsmData, municipalities: Sequence[Municipality], states: Sequence[str]) -> Dict[str, List[Item]]:
    """{UF: registros} para os estados pedidos, cada lista em ordem fixa (classe, nome, posição)."""
    wanted = set(states)
    chosen = [m for m in municipalities if m.uf in wanted]
    index = MunicipalityIndex(chosen)
    items: List[Item] = []

    # lugares
    place_mun = index.locate([p.lat for p in data.places], [p.lng for p in data.places])
    by_mun: Dict[str, List[int]] = defaultdict(list)
    for i, code in enumerate(place_mun):
        if code is not None:
            by_mun[code].append(i)
    used = set()
    for m in chosen:
        if m.geometry is not None:
            seat = _seat(m, ((i, data.places[i]) for i in by_mun.get(m.code, ())))
        else:  # município sem polígono: a sede é procurada no estado inteiro
            seat = _seat(m, ((i, data.places[i]) for i, code in enumerate(place_mun)
                             if code is not None and code[:2] == m.code[:2]))
        if seat is not None:
            used.add(seat)
            lat, lng = data.places[seat].lat, data.places[seat].lng
        elif m.geometry is not None:
            point = m.geometry.representative_point()
            lat, lng = point.y, point.x
        else:
            continue  # sem polígono e sem ponto: a trava de cobertura aponta
        items.append(Item("place", "municipality", m.name, m.code, lat, lng))
    node_names: Dict[Tuple[str, str], List[Tuple[float, float]]] = defaultdict(list)
    for i, place in enumerate(data.places):
        code = place_mun[i]
        if code is not None and not place.from_area:
            node_names[(code, fold(place.name))].append((place.lat, place.lng))
    for i, place in enumerate(data.places):
        code = place_mun[i]
        if code is None or i in used:
            continue
        if place.from_area and any(geo.dist_m(place.lat, place.lng, lat, lng) <= AREA_PLACE_DUPLICATE_M
                                   for lat, lng in node_names.get((code, fold(place.name)), ())):
            continue
        items.append(Item("place", f"place={place.kind}", place.name, code, place.lat, place.lng))

    # ruas e rodovias: o município é o do meio da via
    mids = [geo.midpoint(w.lats, w.lngs) for w in data.ways]
    way_mun = index.locate([m[0] for m in mids], [m[1] for m in mids])
    streets: Dict[Tuple[str, str], List[int]] = defaultdict(list)
    roads: Dict[Tuple[str, str], List[int]] = defaultdict(list)
    for i, w in enumerate(data.ways):
        code = way_mun[i]
        if code is None:
            continue
        if w.name and w.highway in kinds.STREET_HIGHWAYS:
            streets[(code, w.name)].append(i)
        if w.ref and w.highway in kinds.ROAD_HIGHWAYS:
            for ref in split_refs(w.ref):
                roads[(code, ref)].append(i)
    for (code, name), idxs in streets.items():
        group_ways = [data.ways[i] for i in idxs]
        for group in merge_segments(group_ways):
            ways = [group_ways[g] for g in group]
            lat, lng = _central_point(ways)
            highway = min((w.highway for w in ways), key=lambda h: kinds.HIGHWAY_RANK.get(h, 99))
            lats = [v for w in ways for v in w.lats]
            lngs = [v for w in ways for v in w.lngs]
            extent = geo.extent_m(lats, lngs)
            local = all(w.highway in kinds.LOCAL_HIGHWAYS for w in ways)
            items.append(Item("street", f"highway={highway}", name, code, lat, lng,
                              ways=[idxs[g] for g in group], extent_m=round(extent, 1),
                              suspect_long=local and extent > LONG_LOCAL_STREET_M))
    for (code, ref), idxs in roads.items():
        lat, lng = _central_point([data.ways[i] for i in idxs])
        items.append(Item("road", "road", ref, code, lat, lng, ways=list(idxs)))

    # pontos de interesse
    poi_mun = index.locate([p.lat for p in data.pois], [p.lng for p in data.pois])
    for poi, code in zip(data.pois, poi_mun):
        if code is not None:
            items.append(Item("poi", poi.kind, poi.name, code, poi.lat, poi.lng))

    out: Dict[str, List[Item]] = {uf: [] for uf in sorted(wanted)}
    for item in sorted(items, key=order_key):
        out[item.uf].append(item)
    return out
