"""Pontos de fontes novas juntados aos registros de cada estado (HS2 em diante; Parte 9 da pesquisa).

Cada fonte (PRF, CNES, Overture...) lê o próprio arquivo e entrega `Point`s com nome, `kind` e posição. Aqui:

- **Município pelo ponto**, pela malha do IBGE (como os registros do OpenStreetMap); o que cai fora dos municípios
  dos estados pedidos fica de fora.
- **Sem repetir.** Um ponto não entra se já houver, a até `radius_m`, um registro que a regra da fonte (`same`) diga
  ser o mesmo lugar. O raio é medido para cada fonte e fica no módulo dela. Os pontos que entram passam a contar:
  dois pontos iguais da mesma fonte entram uma vez.
- Os registros de cada estado ficam na ordem da geração (records.order_key).
"""
from __future__ import annotations

import math
from collections import defaultdict
from dataclasses import dataclass
from typing import Callable, Dict, List, Sequence, Set, Tuple

from . import config, geo
from .municipalities import MunicipalityIndex
from .records import Item, order_key
from .text import fold

# A grade dos registros usa quadrados de `radius_m` na latitude mais ao sul do Brasil (~34° S): em qualquer ponto do
# país, um quadrado tem pelo menos o raio de lado, e os 9 em volta cobrem o círculo.
_COS_SOUTH = math.cos(math.radians(35.0))


@dataclass
class Point:
    name: str
    kind: str
    lat: float
    lng: float


def words(name: str) -> Set[str]:
    """As palavras do nome dobrado (sem acento, minúsculo, pontuação fora): para as regras de nome parecido."""
    return set(fold(name).split())


class _Grid:
    def __init__(self, radius_m: float) -> None:
        self.step = max(radius_m, 1.0) / (geo.M_PER_DEG * _COS_SOUTH)
        self.cells: Dict[Tuple[int, int], List[Item]] = defaultdict(list)

    def key(self, lat: float, lng: float) -> Tuple[int, int]:
        return int(math.floor(lat / self.step)), int(math.floor(lng / self.step))

    def put(self, item: Item) -> None:
        self.cells[self.key(item.lat, item.lng)].append(item)

    def near(self, lat: float, lng: float) -> List[Item]:
        y, x = self.key(lat, lng)
        return [it for dy in (-1, 0, 1) for dx in (-1, 0, 1) for it in self.cells.get((y + dy, x + dx), ())]


def add(items: Dict[str, List[Item]], points: Sequence[Point], index: MunicipalityIndex, states: Sequence[str],
        radius_m: float, same: Callable[[Item, Point], bool], cls: str = "poi") -> Tuple[int, int]:
    """Junta os pontos dos estados pedidos aos registros (em `items`, por UF). Devolve (quantos entraram, quantos já
    estavam registrados)."""
    wanted = set(states)
    codes = index.locate([p.lat for p in points], [p.lng for p in points])
    grids: Dict[str, _Grid] = {}
    added = repeated = 0
    touched = set()
    for point, code in zip(points, codes):
        state = config.IBGE_STATE_CODES.get(code[:2]) if code else None
        if code is None or state is None or state not in wanted:
            continue
        grid = grids.get(state)
        if grid is None:
            grid = grids[state] = _Grid(radius_m)
            for it in items.get(state, []):
                grid.put(it)
        if any(geo.dist_m(it.lat, it.lng, point.lat, point.lng) <= radius_m and same(it, point)
               for it in grid.near(point.lat, point.lng)):
            repeated += 1
            continue
        item = Item(cls, point.kind, point.name, code, point.lat, point.lng)
        items.setdefault(state, []).append(item)
        grid.put(item)
        touched.add(state)
        added += 1
    for state in touched:
        items[state].sort(key=order_key)
    return added, repeated
