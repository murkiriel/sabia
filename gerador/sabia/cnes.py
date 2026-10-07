"""Hospitais, UPAs e prontos-socorros do CNES (HS3; Parte 9 da pesquisa): o que mais importa numa emergência.

- **Fonte.** O Cadastro Nacional de Estabelecimentos de Saúde (Ministério da Saúde, dados abertos), um CSV nacional
  dentro de um zip, refeito todo dia: tipo de unidade, turno, nome, município (código do IBGE de 6 dígitos) e ponto.
  Baixado e conferido como os arquivos do IBGE (sources._checked_download): zip com o CSV, as colunas lidas, todas as
  UFs, pelo menos MIN_ROWS estabelecimentos e MIN_UNITS de urgência e emergência.
- **O que entra.** Só urgência e emergência, não consultórios: hospital geral, hospital especializado, unidade mista,
  pronto-socorro geral e especializado e pronto atendimento (UPA), com atendimento contínuo de 24 horas, sem motivo
  de desativação e com ponto no Brasil. Cada um vira um ponto de interesse `amenity=hospital` (o `kind` do
  OpenStreetMap, para "hospital" e "upa" acharem), com o nome fantasia (senão a razão social) em caixa de título.
  Hospital-dia e os que só abrem de dia ficam de fora (em Goiás, 416 dos 506 ativos ficam).
- **Coordenada conferida.** O ponto tem de cair no município que o cadastro declara; senão a coordenada está errada
  e a unidade fica de fora (em Goiás, 17 de 506).
- **Sem repetir.** Fica de fora a unidade com um registro de saúde (hospital, clínica, consultório, `healthcare=*`) a
  até DUPLICATE_M que tenha uma palavra do nome em comum (fora as genéricas: hospital, municipal, UPA...) ou não tenha
  nome. Medido em Goiás (2026-10-07): o ponto do CNES fica a dezenas ou centenas de metros do do OpenStreetMap
  (geocodificado pelo endereço); com nome parecido, 148 de 489 a até 500 m, e 25 entre 300 e 500 m.
"""
from __future__ import annotations

import csv
import io
import zipfile
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, Iterator, List, Optional, Sequence, Tuple

from . import config, merge
from .merge import Point
from .municipalities import MunicipalityIndex
from .records import Item
from .text import title_pt

# Menos que isto é resposta quebrada (em 2026-10: 638.236 estabelecimentos, 7.854 de urgência 24 horas).
MIN_ROWS = 500_000
MIN_UNITS = 6000
# Um registro de saúde de nome parecido a até esta distância é a mesma unidade (medido em Goiás).
DUPLICATE_M = 500.0

KIND = "amenity=hospital"
# Tipos de unidade do CNES de urgência e emergência: hospital geral, hospital especializado, unidade mista,
# pronto-socorro geral, pronto-socorro especializado, pronto atendimento (UPA).
TYPES = {"5", "7", "15", "20", "21", "73"}
ALL_DAY = "06"  # turno: atendimento contínuo de 24 horas
COLUMNS = ("CO_UF", "CO_IBGE", "NO_RAZAO_SOCIAL", "NO_FANTASIA", "TP_UNIDADE", "NU_LATITUDE", "NU_LONGITUDE",
           "CO_TURNO_ATENDIMENTO", "CO_MOTIVO_DESAB")
BRAZIL = (-34.0, -74.5, 5.5, -28.5)
# Palavras que não dizem qual é a unidade: não contam para "nome parecido".
GENERIC = {"hospital", "hosp", "municipal", "estadual", "regional", "geral", "de", "da", "do", "das", "dos", "e", "a",
           "o", "upa", "unidade", "pronto", "socorro", "atendimento", "24h", "24", "horas", "saude", "centro",
           "clinica", "ltda", "me", "ps", "pa", "mista", "sao", "santa", "santo", "nossa", "senhora", "maternidade",
           "medico", "medica", "instituto", "casa", "n", "sra"}
HEALTH_KINDS = {"amenity=hospital", "amenity=clinic", "amenity=doctors"}


@dataclass
class Unit(Point):
    municipality: str = ""   # código do IBGE de 6 dígitos que o cadastro declara


def _csv_name(z: zipfile.ZipFile) -> str:
    names = [n for n in z.namelist() if n.lower().endswith(".csv")]
    if not names:
        raise ValueError("o zip não tem um .csv")
    return names[0]


def _rows(path: Path) -> Iterator[Dict[str, str]]:
    with zipfile.ZipFile(path) as z:
        with z.open(_csv_name(z)) as raw:
            yield from csv.DictReader(io.TextIOWrapper(raw, encoding="latin-1", newline=""), delimiter=";")


def _number(text: str) -> Optional[float]:
    try:
        return float(text.strip().replace(",", "."))
    except ValueError:
        return None


def _is_emergency(row: Dict[str, str]) -> bool:
    return (row.get("TP_UNIDADE", "").strip() in TYPES and row.get("CO_TURNO_ATENDIMENTO", "").strip() == ALL_DAY
            and not row.get("CO_MOTIVO_DESAB", "").strip())


def problem(path: Path) -> Optional[str]:
    """O que há de errado com o zip do CNES, ou None se ele tem o país inteiro."""
    if not zipfile.is_zipfile(path):
        return "não é um zip"
    rows = units = 0
    present = set()
    try:
        with zipfile.ZipFile(path) as z, z.open(_csv_name(z)) as raw:
            reader = csv.DictReader(io.TextIOWrapper(raw, encoding="latin-1", newline=""), delimiter=";")
            missing = [c for c in COLUMNS if c not in (reader.fieldnames or [])]
            if missing:
                return f"o csv não tem as colunas {', '.join(missing)}"
            for row in reader:
                rows += 1
                present.add(row["CO_UF"].strip())
                units += _is_emergency(row)
    except (OSError, ValueError, zipfile.BadZipFile, csv.Error) as e:
        return f"não deu para ler ({e.__class__.__name__}: {e})"
    missing_states = sorted(uf for code, uf in config.IBGE_STATE_CODES.items() if code not in present)
    if missing_states:
        return f"faltam as UFs {', '.join(missing_states)}"
    if rows < MIN_ROWS:
        return f"só {rows} estabelecimentos (mínimo {MIN_ROWS})"
    if units < MIN_UNITS:
        return f"só {units} de urgência e emergência (mínimo {MIN_UNITS})"
    return None


def load(path: Path) -> List[Unit]:
    """As unidades de urgência e emergência abertas 24 horas, com ponto no Brasil, na ordem do arquivo."""
    out = []
    for row in _rows(path):
        if not _is_emergency(row):
            continue
        lat, lng = _number(row["NU_LATITUDE"]), _number(row["NU_LONGITUDE"])
        if lat is None or lng is None or not (BRAZIL[0] <= lat <= BRAZIL[2] and BRAZIL[1] <= lng <= BRAZIL[3]):
            continue
        name = title_pt(row["NO_FANTASIA"].strip() or row["NO_RAZAO_SOCIAL"].strip())
        if name:
            out.append(Unit(name, KIND, lat, lng, row["CO_IBGE"].strip()))
    return out


def _distinct(name: str) -> set:
    return {w for w in merge.words(name) if w not in GENERIC and not w.isdigit()}


def is_same(item: Item, point: Point) -> bool:
    """O registro é a mesma unidade? De saúde, e sem nome ou com uma palavra do nome (não genérica) em comum."""
    if item.kind not in HEALTH_KINDS and not item.kind.startswith("healthcare="):
        return False
    return not item.name.strip() or bool(_distinct(item.name) & _distinct(point.name))


def add(items: Dict[str, List[Item]], units: Sequence[Unit], index: MunicipalityIndex,
        states: Sequence[str]) -> Tuple[int, int, int]:
    """Junta as unidades aos registros dos estados pedidos; devolve (entraram, já estavam, coordenada fora do
    município declarado)."""
    wanted = set(states)
    codes = index.locate([u.lat for u in units], [u.lng for u in units])
    good: List[Point] = []
    misplaced = 0
    for u, code in zip(units, codes):
        state = config.IBGE_STATE_CODES.get(u.municipality[:2])
        if state not in wanted:
            continue
        if code is None or code[:6] != u.municipality[:6]:
            misplaced += 1
            continue
        good.append(u)
    added, repeated = merge.add(items, good, index, states, DUPLICATE_M, is_same)
    return added, repeated, misplaced
