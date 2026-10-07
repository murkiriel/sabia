"""Aeródromos da ANAC (HS8; Parte 9 da pesquisa): aeroportos e pistas, públicos e privados.

- **Fonte.** As listas de aeródromos públicos e privados dos dados abertos da ANAC (JSON em UTF-8 com BOM, refeitas
  pela ANAC; a de 2026-10 tem 496 públicos e 3.924 privados), com nome, código OACI e ponto em graus decimais.
  Baixadas e conferidas como os arquivos do IBGE (sources._checked_download): uma lista de aeródromos com as colunas
  lidas e um mínimo com ponto em cada lista (MIN_PUBLIC, MIN_PRIVATE).
- **O que entra.** Cada aeródromo com ponto no Brasil e que não está interditado vira um ponto de interesse
  `aeroway=aerodrome` (o `kind` do OpenStreetMap; "aeroporto" acha) chamado pelo nome, com "Aeródromo" na frente
  quando o nome não diz o que é, e o código OACI no fim: "Aeródromo Fazenda Boa Vista (SWXX)".
- **Sem repetir.** Fica de fora o aeródromo com um aeródromo do OpenStreetMap a até DUPLICATE_M, qualquer que seja o
  nome (o do OpenStreetMap é o centro da área da pista). Medido em Goiás (2026-10-07): dos 19 públicos, 17 têm um a até
  676 m; dos 243 privados, 82 a até 1 km e só mais 2 até 2 km (o próximo, a 5,5 km).
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Dict, List, Optional, Sequence, Tuple

from . import merge
from .merge import Point
from .municipalities import MunicipalityIndex
from .records import Item
from .text import fold, title_pt

# Menos que isto com ponto é resposta quebrada (em 2026-10: 496 públicos e 3.924 privados).
MIN_PUBLIC = 400
MIN_PRIVATE = 3000
DUPLICATE_M = 1500.0
KIND = "aeroway=aerodrome"
COLUMNS = ("CódigoOACI", "Nome", "LatGeoPoint", "LonGeoPoint")
CLOSED = "interditado"
# Palavras que já dizem que o lugar é um aeródromo.
SELF_NAMED = {"aeroporto", "aerodromo", "aeroclube", "heliponto", "pista"}
BRAZIL = (-34.0, -74.5, 5.5, -28.5)


def _rows(path: Path) -> list:
    rows = json.loads(path.read_text(encoding="utf-8-sig"))
    if not isinstance(rows, list):
        raise ValueError("não é uma lista")
    return rows


def _number(text: object) -> Optional[float]:
    try:
        return float(str(text).strip().replace(",", "."))
    except ValueError:
        return None


def _point(row: dict) -> Optional[Tuple[float, float]]:
    lat, lng = _number(row.get("LatGeoPoint")), _number(row.get("LonGeoPoint"))
    if lat is None or lng is None or not (BRAZIL[0] <= lat <= BRAZIL[2] and BRAZIL[1] <= lng <= BRAZIL[3]):
        return None
    return lat, lng


def problem(path: Path, minimum: int) -> Optional[str]:
    """O que há de errado com uma lista da ANAC, ou None se ela tem pelo menos `minimum` aeródromos com ponto."""
    try:
        rows = _rows(path)
    except (OSError, UnicodeDecodeError) as e:
        return f"não deu para ler ({e.__class__.__name__})"
    except json.JSONDecodeError as e:
        return f"não é JSON ({e.__class__.__name__})"
    except ValueError:
        return "não é a lista de aeródromos"
    for row in rows:
        missing = [c for c in COLUMNS if not isinstance(row, dict) or c not in row]
        if missing:
            return f"aeródromo sem as colunas {', '.join(missing)}"
    with_point = sum(1 for r in rows if _point(r) is not None)
    if with_point < minimum:
        return f"só {with_point} aeródromos com ponto (mínimo {minimum})"
    return None


def name_of(row: dict) -> str:
    name = " ".join(str(row.get("Nome") or "").split())
    if name.isupper():
        name = title_pt(name)
    if not SELF_NAMED & set(fold(name).split()):
        name = f"Aeródromo {name}".strip()
    code = str(row.get("CódigoOACI") or "").strip()
    return f"{name} ({code})" if code else name


def load_rows(rows: Sequence[dict]) -> List[Point]:
    """Os aeródromos com ponto no Brasil que não estão interditados, na ordem da lista."""
    out = []
    for row in rows:
        if str(row.get("SITUAÇÃO") or "").strip().lower() == CLOSED:
            continue
        point = _point(row)
        if point is not None:
            out.append(Point(name_of(row), KIND, point[0], point[1]))
    return out


def load(path: Path) -> List[Point]:
    return load_rows(_rows(path))


def is_same(item: Item, point: Point) -> bool:
    """Um aeródromo do OpenStreetMap (ou de outra lista) perto é o mesmo, qualquer que seja o nome."""
    return item.kind == KIND


def add(items: Dict[str, List[Item]], points: Sequence[Point], index: MunicipalityIndex,
        states: Sequence[str]) -> Tuple[int, int]:
    """Junta os aeródromos aos registros dos estados pedidos; devolve (entraram, já estavam)."""
    return merge.add(items, points, index, states, DUPLICATE_M, is_same)
