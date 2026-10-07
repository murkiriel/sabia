"""Postos e unidades da Polícia Rodoviária Federal (HS2; Parte 9 da pesquisa): poucos registros e úteis na estrada.

- **Fonte.** O conjunto "PRF" dos dados abertos da ANTT (JSON, atualizado todo mês): as unidades da PRF nas rodovias
  concedidas, com rodovia, km, situação e ponto. Baixado e conferido como os arquivos do IBGE
  (sources._checked_download): JSON com a lista `PRF`, as colunas lidas e pelo menos MIN_UNITS unidades com ponto.
- **O que entra.** Cada unidade ativa, com ponto no Brasil, vira um ponto de interesse `amenity=police` (o mesmo `kind`
  dos postos de polícia do OpenStreetMap, para "polícia" e "delegacia" acharem) chamado
  "PRF - Polícia Rodoviária Federal, BR-060 km 182". O nome do arquivo não serve para buscar ("PRF02-BR060_KM182+250",
  "EDF 116 PR 094+910 S 1"); a rodovia e o km servem.
- **Sem repetir.** Fica de fora a unidade com um posto de polícia a até DUPLICATE_M que seja da PRF pelo nome ("PRF",
  "Polícia Rodoviária Federal") ou sem nome. Medido em Goiás e no DF (2026-10-07): 14 das 16 unidades têm um posto
  assim no OpenStreetMap, a 4 a 202 m.
"""
from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Dict, List, Optional, Sequence, Tuple

from . import merge
from .merge import Point
from .municipalities import MunicipalityIndex
from .records import Item

# Menos que isto com ponto é resposta quebrada (em 2026-08 eram 172, todas ativas).
MIN_UNITS = 100
# Um posto de polícia da PRF no OpenStreetMap a até esta distância é a mesma unidade (o mais longe medido: 202 m).
DUPLICATE_M = 250.0

KIND = "amenity=police"
NAME = "PRF - Polícia Rodoviária Federal"
COLUMNS = ("rodovia", "km_m", "situacao", "latitude", "longitude")
ACTIVE = "ativo"
# O retângulo do Brasil, com folga: ponto fora dele é coordenada errada (zero, trocada, sem sinal).
BRAZIL = (-34.0, -74.5, 5.5, -28.5)

_ROAD = re.compile(r"^\s*([A-Za-z]{2})\s*-?\s*(\d{1,3})\s*$")


def _rows(path: Path) -> List[dict]:
    data = json.loads(path.read_text(encoding="utf-8"))
    rows = data.get("PRF") if isinstance(data, dict) else None
    if not isinstance(rows, list):
        raise ValueError("sem a lista PRF")
    return rows


def _number(text: object) -> Optional[float]:
    try:
        return float(str(text).strip().replace(",", "."))
    except ValueError:
        return None


def _point(row: dict) -> Optional[Tuple[float, float]]:
    lat, lng = _number(row.get("latitude")), _number(row.get("longitude"))
    if lat is None or lng is None:
        return None
    if not (BRAZIL[0] <= lat <= BRAZIL[2] and BRAZIL[1] <= lng <= BRAZIL[3]):
        return None
    return lat, lng


def problem(path: Path) -> Optional[str]:
    """O que há de errado com o arquivo da ANTT, ou None se ele tem as unidades da PRF."""
    try:
        rows = _rows(path)
    except (OSError, UnicodeDecodeError) as e:
        return f"não deu para ler ({e.__class__.__name__})"
    except ValueError as e:
        if isinstance(e, json.JSONDecodeError):
            return f"não é JSON ({e.__class__.__name__})"
        return "não é a lista de postos da PRF (chave PRF)"
    for row in rows:
        missing = [c for c in COLUMNS if not isinstance(row, dict) or c not in row]
        if missing:
            return f"linha sem as colunas {', '.join(missing)}"
    with_point = sum(1 for r in rows if _point(r) is not None)
    if with_point < MIN_UNITS:
        return f"só {with_point} postos com ponto (mínimo {MIN_UNITS})"
    return None


def _road(text: str) -> str:
    """'BR-60' -> 'BR-060' (a sigla como o OpenStreetMap escreve); texto que não é sigla de rodovia -> ''."""
    m = _ROAD.match(text or "")
    return f"{m.group(1).upper()}-{int(m.group(2)):03d}" if m else ""


def name_of(row: dict) -> str:
    road = _road(str(row.get("rodovia") or ""))
    km = _number(row.get("km_m")) if str(row.get("km_m") or "").strip() else None
    if road and km is not None:
        return f"{NAME}, {road} km {int(km)}"
    if road:
        return f"{NAME}, {road}"
    return NAME


def load_rows(rows: Sequence[dict]) -> List[Point]:
    """As unidades ativas com ponto no Brasil, na ordem do arquivo."""
    out = []
    for row in rows:
        if str(row.get("situacao") or "").strip().lower() != ACTIVE:
            continue
        point = _point(row)
        if point is None:
            continue
        out.append(Point(name_of(row), KIND, point[0], point[1]))
    return out


def load(path: Path) -> List[Point]:
    return load_rows(_rows(path))


def is_prf(item: Item, point: Point) -> bool:
    """O registro é um posto da PRF? Polícia sem nome, ou com "PRF" ou "rodoviária federal" no nome."""
    if item.kind != KIND:
        return False
    found = merge.words(item.name)
    return not found or "prf" in found or {"rodoviaria", "federal"} <= found


def add(items: Dict[str, List[Item]], points: Sequence[Point], index: MunicipalityIndex,
        states: Sequence[str]) -> Tuple[int, int]:
    """Junta as unidades aos registros dos estados pedidos; devolve (entraram, já estavam)."""
    return merge.add(items, points, index, states, DUPLICATE_M, is_prf)
