"""Pontos de fontes novas juntados aos registros de cada estado (HS2 em diante; Parte 9 da pesquisa).

Cada fonte (PRF, CNES, Overture...) lê o próprio arquivo e entrega `Point`s com nome, `kind` e posição. Aqui:

- **Município pelo ponto**, pela malha do IBGE (como os registros do OpenStreetMap); o que cai fora dos municípios
  dos estados pedidos fica de fora.
- **Sem repetir.** Um ponto não entra se já houver, a até `radius_m`, um registro que a regra da fonte (`same`) diga
  ser o mesmo lugar. O raio é medido para cada fonte e fica no módulo dela. Os pontos que entram passam a contar:
  dois pontos iguais da mesma fonte entram uma vez.
- Os registros de cada estado ficam na ordem da geração (records.order_key).
- **Nomes alternativos** (HS9, `attach_aliases`): o nome e os nomes alternativos de um ponto vão para o registro mais
  perto que seja o mesmo lugar; ficam só no índice de busca (database.write_state), o nome mostrado não muda.
"""
from __future__ import annotations

import math
from collections import defaultdict
from dataclasses import dataclass, field
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
    aliases: List[str] = field(default_factory=list, kw_only=True)   # nomes alternativos (HS9)


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
        radius_m: float, same: Callable[[Item, Point], bool], cls: str = "poi", origin: str = "") -> Tuple[int, int]:
    """Junta os pontos dos estados pedidos aos registros (em `items`, por UF). Devolve (quantos entraram, quantos já
    estavam registrados). `origin` marca os registros novos (Item.origin, só para a importância)."""
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
        item = Item(cls, point.kind, point.name, code, point.lat, point.lng, aliases=list(point.aliases),
                    origin=origin)
        items.setdefault(state, []).append(item)
        grid.put(item)
        touched.add(state)
        added += 1
    for state in touched:
        items[state].sort(key=order_key)
    return added, repeated


# Palavras que não distinguem um nome de outro (artigos, preposições, forma da empresa).
_FILLER = {"a", "o", "as", "os", "de", "da", "do", "das", "dos", "e", "em", "na", "no", "the", "ltda", "me", "eireli",
           "sa", "s"}


# Nomes alternativos por registro, no máximo (o índice de busca não incha com listas de grafias).
MAX_ALIASES = 5


def usable_alias(name: str) -> bool:
    """Nome alternativo que serve para buscar: escrita latina, com letra, de 3 caracteres ou mais."""
    return (len(name.strip()) >= 3 and any(c.isalpha() for c in name)
            and all(ord(c) < 0x250 for c in name))


def attach_aliases(items: Dict[str, List[Item]], points: Sequence[Point], index: MunicipalityIndex,
                   states: Sequence[str], radius_m: float, match: Callable[[Item, Point], bool]) -> int:
    """Põe o nome e os nomes alternativos de cada ponto no registro mais perto a até `radius_m` que `match` diga ser o
    mesmo lugar: só os que servem para buscar, sem repetir o nome nem outro alternativo dele, até MAX_ALIASES.
    Devolve quantos registros ganharam nome alternativo."""
    wanted = set(states)
    codes = index.locate([p.lat for p in points], [p.lng for p in points])
    grids: Dict[str, _Grid] = {}
    changed = set()
    for point, code in zip(points, codes):
        state = config.IBGE_STATE_CODES.get(code[:2]) if code else None
        if state is None or state not in wanted:
            continue
        grid = grids.get(state)
        if grid is None:
            grid = grids[state] = _Grid(radius_m)
            for it in items.get(state, []):
                grid.put(it)
        near = [(geo.dist_m(it.lat, it.lng, point.lat, point.lng), n, it)
                for n, it in enumerate(grid.near(point.lat, point.lng))]
        near = [x for x in near if x[0] <= radius_m and match(x[2], point)]
        if not near:
            continue
        target = min(near, key=lambda x: (x[0], x[1]))[2]
        known = {fold(target.name)} | {fold(a) for a in target.aliases}
        for name in [point.name, *point.aliases]:
            if len(target.aliases) >= MAX_ALIASES:
                break
            if usable_alias(name) and fold(name) not in known:
                known.add(fold(name))
                target.aliases.append(name.strip())
                changed.add(id(target))
    return len(changed)


def similar_names(a: str, b: str) -> bool:
    """Dois nomes do mesmo lugar? As palavras (sem acento, sem artigo nem "Ltda") de um contidas nas do outro, ou pelo
    menos metade das do nome mais curto em comum: "Pão de Ouro Padaria" e "Padaria Pão de Ouro Ltda" sim; "Bar" e
    "Barbearia do Zé" não."""
    wa, wb = words(a) - _FILLER, words(b) - _FILLER
    if not wa or not wb:
        return False
    return len(wa & wb) * 2 >= min(len(wa), len(wb))
