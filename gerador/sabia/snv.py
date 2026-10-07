"""Quilômetros das rodovias federais (HS6; Parte 9 da pesquisa): "BR-060 km 120", como o piloto fala de um lugar na
estrada.

- **Fonte.** O Sistema Nacional de Viação do DNIT, a camada `vgeo:vw_snv_rod` do serviço WFS do DNITGeo (GeoJSON),
  só a versão em vigor no dia (`dt_ini` e `dt_fim`), só os trechos de eixo principal (`Sigla_Tipo_Trecho` B) já
  construídos (sem os planejados, `Superficie_Federal` PLA). Cada trecho tem a rodovia, a UF, o km inicial e o final
  e a linha. Baixado e conferido como os arquivos do IBGE (sources._checked_download): FeatureCollection com as
  propriedades lidas, todas as UFs e pelo menos MIN_SEGMENTS trechos.
- **O que entra.** Um ponto por km inteiro ao longo de cada trecho, na fração da linha que o km ocupa entre o inicial e
  o final (a linha desenhada não tem o comprimento nominal exato), como `poi` `highway=milestone` (a etiqueta do marco
  quilométrico no OpenStreetMap) chamado "BR-060 km 120". O km recomeça em cada UF, como na rodovia: a chave é
  rodovia, UF e km; o km que fica na emenda de dois trechos entra uma vez.
- **Precisão** (medida em 2026-10-07 contra 572 pontos de km conhecidos, as unidades da PRF e as edificações das
  concessionárias da ANTT): mediana de 286 m, 71% a até 1 km. Onde o ponto conhecido usa a numeração do SNV recente,
  a mediana fica perto de 70 m; nos trechos concedidos com numeração antiga (PNV de 2007, 2016, 2023), a placa da
  estrada fica a vários km do km do SNV.
- **Sem repetir.** Um marco de mesmo nome a até DUPLICATE_M não entra de novo.
"""
from __future__ import annotations

import json
import math
import urllib.parse
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, List, Optional, Sequence, Tuple

from . import config, geo, merge
from .merge import Point
from .municipalities import MunicipalityIndex
from .records import Item
from .text import fold

# Menos que isto é resposta quebrada (a versão 202607A tem 5.059 trechos de eixo principal construídos).
MIN_SEGMENTS = 4000
DUPLICATE_M = 1000.0
KIND = "highway=milestone"
PROPERTIES = ("Codigo_BR", "Unidade_Federacao", "Sigla_Tipo_Trecho", "Superficie_Federal", "Quilometragem_Inicio",
              "Quilometragem_Fim", "Versao_SNV", "dt_ini")
MAIN_AXIS = "B"
PLANNED = "PLA"


@dataclass
class Segment:
    road: str     # o número da BR, 3 dígitos ("060")
    uf: str
    start: float  # km inicial e final
    end: float
    parts: List[List[Tuple[float, float]]]   # as partes da linha, (lat, lng)


def url(day: str) -> str:
    """A consulta WFS da versão do SNV em vigor em `day` (AAAA-MM-DD): trechos de eixo principal construídos, em
    GeoJSON, só as propriedades lidas."""
    cql = (f"dt_ini<='{day}' AND dt_fim>='{day}' AND Sigla_Tipo_Trecho='{MAIN_AXIS}' "
           f"AND Superficie_Federal<>'{PLANNED}'")
    params = {"service": "WFS", "version": "2.0.0", "request": "GetFeature", "typeNames": config.SNV_LAYER,
              "outputFormat": "application/json", "propertyName": ",".join(("geom",) + PROPERTIES),
              "CQL_FILTER": cql}
    return config.SNV_WFS_URL + "?" + urllib.parse.urlencode(params)


def _features(path: Path) -> list:
    data = json.loads(path.read_text(encoding="utf-8"))
    features = data.get("features") if isinstance(data, dict) else None
    if not isinstance(features, list):
        raise ValueError("sem a lista features")
    return features


def problem(path: Path) -> Optional[str]:
    """O que há de errado com o SNV baixado, ou None se ele tem os trechos do país inteiro."""
    try:
        features = _features(path)
    except (OSError, UnicodeDecodeError) as e:
        return f"não deu para ler ({e.__class__.__name__})"
    except json.JSONDecodeError as e:
        return f"não é JSON ({e.__class__.__name__})"
    except ValueError:
        return "não é uma FeatureCollection (sem a lista features)"
    present = set()
    for f in features:
        props = (f.get("properties") if isinstance(f, dict) else None) or {}
        missing = [p for p in PROPERTIES if p not in props]
        if missing:
            return f"trecho sem as propriedades {', '.join(missing)}"
        present.add(props["Unidade_Federacao"])
    absent = sorted(uf for uf in config.STATES if uf not in present)
    if absent:
        return f"faltam as UFs {', '.join(absent)}"
    if len(features) < MIN_SEGMENTS:
        return f"só {len(features)} trechos (mínimo {MIN_SEGMENTS})"
    return None


def version(path: Path) -> Tuple[str, str]:
    """(versão do SNV, data de início dela): ('202607A', '2026-07-28')."""
    props = [f["properties"] for f in _features(path)]
    return max(p["Versao_SNV"] for p in props), max(p["dt_ini"] for p in props)[:10]


def load(path: Path) -> List[Segment]:
    """Os trechos de eixo principal construídos, na ordem do arquivo."""
    out = []
    for f in _features(path):
        props, geometry = f["properties"], f.get("geometry")
        if props["Sigla_Tipo_Trecho"] != MAIN_AXIS or props["Superficie_Federal"] == PLANNED or not geometry:
            continue
        lines = geometry["coordinates"] if geometry["type"] == "MultiLineString" else [geometry["coordinates"]]
        parts = [[(float(lat), float(lng)) for lng, lat, *_ in line] for line in lines if len(line) >= 1]
        start, end = props["Quilometragem_Inicio"], props["Quilometragem_Fim"]
        if not parts or start is None or end is None:
            continue
        out.append(Segment(str(props["Codigo_BR"]).zfill(3), props["Unidade_Federacao"], float(start), float(end),
                           parts))
    return out


def _at(parts: Sequence[Sequence[Tuple[float, float]]], fraction: float) -> Tuple[float, float]:
    """O ponto a `fraction` (0 a 1) do comprimento da linha; o vão entre duas partes não conta."""
    pieces = [(a, b, geo.dist_m(a[0], a[1], b[0], b[1])) for part in parts for a, b in zip(part, part[1:])]
    total = sum(d for _, _, d in pieces)
    if total <= 0:
        return parts[0][0]
    want = min(max(fraction, 0.0), 1.0) * total
    for a, b, d in pieces:
        if want <= d and d > 0:
            t = want / d
            return a[0] + t * (b[0] - a[0]), a[1] + t * (b[1] - a[1])
        want -= d
    return parts[-1][-1]


def markers(segments: Sequence[Segment]) -> List[Point]:
    """Um ponto por km inteiro de cada trecho; o km da emenda de dois trechos, uma vez."""
    seen = set()
    out = []
    for s in segments:
        for km in range(math.ceil(s.start), math.floor(s.end) + 1):
            key = (s.road, s.uf, km)
            if key in seen:
                continue
            seen.add(key)
            fraction = (km - s.start) / (s.end - s.start) if s.end > s.start else 0.0
            lat, lng = _at(s.parts, fraction)
            out.append(Point(f"BR-{s.road} km {km}", KIND, lat, lng))
    return out


def is_same(item: Item, point: Point) -> bool:
    return item.kind == KIND and fold(item.name) == fold(point.name)


def add(items: Dict[str, List[Item]], points: Sequence[Point], index: MunicipalityIndex,
        states: Sequence[str]) -> Tuple[int, int]:
    """Junta os marcos aos registros dos estados pedidos; devolve (entraram, já estavam)."""
    return merge.add(items, points, index, states, DUPLICATE_M, is_same)
