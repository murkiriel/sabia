"""Postos de combustível da ANP (HS10; etapa C da pesquisa, medição M8 e Parte 9): os postos em operação que o
OpenStreetMap não tem, e o nome dos postos sem nome que ele tem.

- **Fonte.** A API de revendedores da ANP (`/v1/combustivel`, sem conta), que dá o cadastro dos postos em operação com
  a posição geográfica que a fiscalização da ANP ou o próprio posto declarou. A etapa C da pesquisa previa achar o
  lugar de cada posto pelo endereço no CNEFE (26% acharam lugar, M8); a API já traz o ponto de 98% deles (Goiás: 2.019
  de 2.069). Baixada UF por UF, página por página (até 5.000 postos por página), num arquivo só, conferido: uma lista
  com os campos lidos, todas as UFs e pelo menos MIN_STATIONS postos.
- **O que entra.** Cada posto com ponto no Brasil e sem interdição (`statusSIGAF`) vira `amenity=fuel` chamado pela
  bandeira ("Posto Ipiranga", "Posto Petrobras" para a Vibra, "Posto Shell" para a Raízen) ou, bandeira branca, pela
  razão social sem "Ltda" em caixa de título.
- **Sem repetir.** Um posto do pacote (OpenStreetMap ou Overture) a até DUPLICATE_M é o mesmo; se ele não tem nome,
  ganha o da ANP ("posto ipiranga" passa a achar). Medido em Goiás (2026-10-07): 1.122 dos 2.019 postos da ANP têm um
  posto do pacote a até 100 m; com os pontos da ANP deslocados 333 m (o acaso), 59. Entre 150 e 200 m o acaso já
  passa do que casa de verdade.
"""
from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Dict, List, Optional, Sequence, Tuple

from . import config, geo
from .merge import Point, _Grid
from .municipalities import MunicipalityIndex
from .records import Item, order_key
from .text import fold, title_pt

# Menos que isto no país é resposta quebrada.
MIN_STATIONS = 30_000
DUPLICATE_M = 100.0
# Segundos entre um pedido e outro à API: ela fica atrás de um Cloudflare que responde 429 ("Just a moment...") a
# pedidos seguidos (2026-10-07, na 12ª UF sem pausa). Os testes zeram.
PAUSE_DEFAULT = 5
PAUSE = PAUSE_DEFAULT
KIND = "amenity=fuel"
FIELDS = ("razaoSocial", "uf", "distribuidora", "latitude", "longitude")
UNBRANDED = "BANDEIRA BRANCA"
# Bandeira na ANP -> como o posto é conhecido.
BRANDS = {"VIBRA": "Petrobras", "RAIZEN": "Shell", "IPIRANGA": "Ipiranga", "ALE": "Ale"}
BRAZIL = (-34.0, -74.5, 5.5, -28.5)
_COMPANY = re.compile(r"\s+(LTDA|EIRELI|ME|EPP|S/?A|S\.A\.?)\.?$", re.IGNORECASE)


def _rows(path: Path) -> list:
    rows = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(rows, list):
        raise ValueError("não é uma lista")
    return rows


def problem(path: Path) -> Optional[str]:
    """O que há de errado com o arquivo dos postos, ou None se ele tem o país inteiro."""
    try:
        rows = _rows(path)
    except (OSError, UnicodeDecodeError) as e:
        return f"não deu para ler ({e.__class__.__name__})"
    except json.JSONDecodeError as e:
        return f"não é JSON ({e.__class__.__name__})"
    except ValueError:
        return "não é a lista de postos"
    for row in rows:
        missing = [f for f in FIELDS if not isinstance(row, dict) or f not in row]
        if missing:
            return f"posto sem os campos {', '.join(missing)}"
    absent = sorted(uf for uf in config.STATES if uf not in {r["uf"] for r in rows})
    if absent:
        return f"faltam as UFs {', '.join(absent)}"
    if len(rows) < MIN_STATIONS:
        return f"só {len(rows)} postos (mínimo {MIN_STATIONS})"
    return None


def _number(text: object) -> Optional[float]:
    try:
        return float(str(text).strip().replace(",", "."))
    except ValueError:
        return None


def name_of(row: dict) -> str:
    brand = str(row.get("distribuidora") or "").strip().upper()
    if brand and brand != UNBRANDED:
        return f"Posto {BRANDS.get(brand, title_pt(brand))}"
    company = " ".join(str(row.get("razaoSocial") or "").split())
    while True:
        shorter = _COMPANY.sub("", company)
        if shorter == company:
            break
        company = shorter
    name = title_pt(company)
    return name if "posto" in fold(name).split()[:2] else f"Posto {name}".strip()


def load(path: Path) -> List[Point]:
    """Os postos com ponto no Brasil e sem interdição, na ordem do arquivo."""
    out = []
    for row in _rows(path):
        if "INTERDIT" in str(row.get("statusSIGAF") or "").upper():
            continue
        lat, lng = _number(row.get("latitude")), _number(row.get("longitude"))
        if lat is None or lng is None or not (BRAZIL[0] <= lat <= BRAZIL[2] and BRAZIL[1] <= lng <= BRAZIL[3]):
            continue
        out.append(Point(name_of(row), KIND, lat, lng))
    return out


def add(items: Dict[str, List[Item]], points: Sequence[Point], index: MunicipalityIndex,
        states: Sequence[str]) -> Tuple[int, int, int]:
    """Junta os postos aos registros dos estados pedidos; o posto do pacote a até DUPLICATE_M é o mesmo e, sem nome,
    ganha o da ANP. Devolve (entraram, já estavam, postos do pacote que ganharam nome)."""
    wanted = set(states)
    codes = index.locate([p.lat for p in points], [p.lng for p in points])
    grids: Dict[str, _Grid] = {}
    added = repeated = named = 0
    touched = set()
    for point, code in zip(points, codes):
        state = config.IBGE_STATE_CODES.get(code[:2]) if code else None
        if code is None or state is None or state not in wanted:
            continue
        grid = grids.get(state)
        if grid is None:
            grid = grids[state] = _Grid(DUPLICATE_M)
            for it in items.get(state, []):
                grid.put(it)
        near = [(geo.dist_m(it.lat, it.lng, point.lat, point.lng), n, it)
                for n, it in enumerate(grid.near(point.lat, point.lng)) if it.kind == KIND]
        near = [x for x in near if x[0] <= DUPLICATE_M]
        if near:
            repeated += 1
            same = min(near, key=lambda x: (x[0], x[1]))[2]
            if not same.name.strip():
                same.name = point.name
                named += 1
                touched.add(state)
            continue
        item = Item("poi", KIND, point.name, code, point.lat, point.lng)
        items.setdefault(state, []).append(item)
        grid.put(item)
        touched.add(state)
        added += 1
    for state in touched:
        items[state].sort(key=order_key)
    return added, repeated, named
