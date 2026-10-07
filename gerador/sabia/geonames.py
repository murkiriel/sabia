"""GeoNames (HS9; Parte 9 da pesquisa): nomes alternativos e pontos turísticos.

- **Fonte.** O arquivo do Brasil do GeoNames (`BR.zip`, ~235 mil lugares, CC BY 4.0) e o dos nomes alternativos do
  Brasil (`alternatenames/BR.zip`, ~310 mil nomes com a língua). Baixados e conferidos como os arquivos do IBGE
  (sources._checked_download): zip com o `BR.txt`, as colunas do formato, todas as UFs e um mínimo de linhas; nos nomes,
  os em português.
- **Nomes alternativos.** Os nomes em português (`pt`) e os sem língua (nomes antigos e grafias locais) de cada
  lugar habitado (classe P) e de cada ponto turístico vão para o índice de busca do registro que já existe com o
  mesmo nome (ou parecido) a até ALIAS_M: "Bonfim" acha Silvânia, "Rio Preto" acha São José do Rio Preto. O nome
  mostrado não muda.
- **Pontos turísticos.** Cachoeiras, cavernas, praias, picos e morros, fontes e parques (TOURISM) que não estão no
  pacote viram pontos de interesse com o `kind` do OpenStreetMap; um registro de nome parecido a até DUPLICATE_M é o
  mesmo. Os lugares habitados não entram como registro novo: as localidades do IBGE e o OpenStreetMap cobrem.

Medido em Goiás (2026-10-07): 41 pontos turísticos (37 novos) e 606 lugares que casam com o pacote, 155 deles com
nome alternativo.
"""
from __future__ import annotations

import io
import zipfile
from collections import defaultdict
from pathlib import Path
from typing import Dict, Iterator, List, Optional, Sequence, Tuple

from . import merge
from .merge import Point
from .municipalities import MunicipalityIndex
from .records import Item
from .text import fold

# Menos que isto é arquivo quebrado (em 2026-10: 235.529 lugares e 308.715 nomes alternativos).
MIN_PLACES = 200_000
MIN_NAMES = 250_000
# Um lugar do GeoNames casa com um registro de nome parecido até esta distância (ponto de cidade contra ponto de
# cidade); um ponto turístico novo de nome parecido a até DUPLICATE_M de um registro é o mesmo.
ALIAS_M = 3000.0
DUPLICATE_M = 2000.0
PLACES_COLUMNS = 19
NAMES_COLUMNS = 10
INNER = "BR.txt"
POPULATED = "P"
PORTUGUESE = "pt"
# Código do GeoNames -> `kind` do OpenStreetMap.
TOURISM = {"FLLS": "natural=waterfall", "FLLSX": "natural=waterfall", "CAVE": "natural=cave_entrance",
           "BCH": "natural=beach", "PK": "natural=peak", "MT": "natural=peak", "SPNG": "natural=spring",
           "SPNT": "natural=hot_spring", "PRK": "leisure=park"}


def _lines(path: Path) -> Iterator[List[str]]:
    with zipfile.ZipFile(path) as z:
        if INNER not in z.namelist():
            raise ValueError(f"o zip não tem o {INNER}")
        with z.open(INNER) as raw:
            for line in io.TextIOWrapper(raw, encoding="utf-8"):
                line = line.rstrip("\n")
                if line:
                    yield line.split("\t")


def _read_problem(path: Path) -> Optional[str]:
    if not zipfile.is_zipfile(path):
        return "não é um zip"
    return None


def places_problem(path: Path) -> Optional[str]:
    """O que há de errado com o BR.zip dos lugares, ou None se ele tem o país inteiro."""
    found = _read_problem(path)
    if found:
        return found
    rows = 0
    states = set()
    try:
        for row in _lines(path):
            if len(row) != PLACES_COLUMNS:
                return f"linha com {len(row)} colunas (o formato tem {PLACES_COLUMNS})"
            rows += 1
            if row[10]:
                states.add(row[10])
    except (OSError, ValueError, UnicodeDecodeError, zipfile.BadZipFile) as e:
        return f"não deu para ler ({e.__class__.__name__}: {e})"
    if len(states) < 27:
        return f"só {len(states)} UFs (o Brasil tem 27)"
    if rows < MIN_PLACES:
        return f"só {rows} lugares (mínimo {MIN_PLACES})"
    return None


def names_problem(path: Path) -> Optional[str]:
    """O que há de errado com o BR.zip dos nomes alternativos, ou None."""
    found = _read_problem(path)
    if found:
        return found
    rows = portuguese = 0
    try:
        for row in _lines(path):
            if len(row) != NAMES_COLUMNS:
                return f"linha com {len(row)} colunas (o formato tem {NAMES_COLUMNS})"
            rows += 1
            portuguese += row[2] == PORTUGUESE
    except (OSError, ValueError, UnicodeDecodeError, zipfile.BadZipFile) as e:
        return f"não deu para ler ({e.__class__.__name__}: {e})"
    if not portuguese:
        return "nenhum nome em português (pt)"
    if rows < MIN_NAMES:
        return f"só {rows} nomes (mínimo {MIN_NAMES})"
    return None


def _number(text: str) -> Optional[float]:
    try:
        return float(text)
    except ValueError:
        return None


def load(places: Path, names: Path) -> List[Point]:
    """Os lugares habitados (`kind` vazio: só dão nomes) e os pontos turísticos, com os nomes em português e os sem
    língua (no GeoNames, os nomes antigos e as grafias locais: "Bonfim" para Silvânia), na ordem do arquivo."""
    wanted: Dict[str, Point] = {}
    order: List[str] = []
    for row in _lines(places):
        kind = TOURISM.get(row[7], "")
        if row[6] != POPULATED and not kind:
            continue
        lat, lng = _number(row[4]), _number(row[5])
        if lat is None or lng is None or not row[1].strip():
            continue
        wanted[row[0]] = Point(row[1].strip(), kind, lat, lng)
        order.append(row[0])
    extra: Dict[str, List[str]] = defaultdict(list)
    for row in _lines(names):
        if row[1] in wanted and row[2] in (PORTUGUESE, ""):
            extra[row[1]].append(row[3].strip())
    out = []
    for gid in order:
        point = wanted[gid]
        seen = {fold(point.name)}
        for name in extra.get(gid, []):
            if name and fold(name) not in seen:
                seen.add(fold(name))
                point.aliases.append(name)
        out.append(point)
    return out


def _match(item: Item, point: Point) -> bool:
    """O registro é o mesmo lugar? Lugar habitado só casa com lugar; ponto turístico, com lugar ou com ponto de
    interesse."""
    if item.cls != "place" and (not point.kind or item.cls != "poi"):
        return False
    return fold(item.name) == fold(point.name) or merge.similar_names(item.name, point.name)


def add(items: Dict[str, List[Item]], points: Sequence[Point], index: MunicipalityIndex,
        states: Sequence[str]) -> Tuple[int, int, int]:
    """Os nomes alternativos nos registros que já existem e os pontos turísticos novos. Devolve (entraram, já estavam,
    registros que ganharam nome alternativo)."""
    aliased = merge.attach_aliases(items, points, index, states, ALIAS_M, _match)
    added, repeated = merge.add(items, [p for p in points if p.kind], index, states, DUPLICATE_M, _match)
    return added, repeated, aliased
