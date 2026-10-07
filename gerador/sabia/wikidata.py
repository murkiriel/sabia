"""Wikidata (HS9; Parte 9 da pesquisa): pontos turísticos e os nomes alternativos deles.

- **Fonte.** Uma consulta SPARQL ao serviço público do Wikidata (CC0): os itens no Brasil (P17 = Q155) com coordenada
  que são cachoeira, caverna, praia, montanha, atração turística, mirante, parque nacional, fonte termal ou torre de
  observação (KINDS), com o rótulo e os apelidos em português. Resposta em JSON, baixada e conferida como os arquivos
  do IBGE (sources._checked_download): as variáveis da consulta e um mínimo de itens. Em 2026-10: 1.364 itens.
- **O que entra.** Como no GeoNames (sabia/geonames.py): os apelidos vão para o índice de busca do registro que já
  existe com nome parecido a até ALIAS_M, e o item que não está no pacote vira ponto de interesse com o `kind` do
  OpenStreetMap; um registro de nome parecido a até DUPLICATE_M é o mesmo.
"""
from __future__ import annotations

import json
import urllib.parse
from pathlib import Path
from typing import Dict, List, Optional, Sequence, Tuple

from . import config, geonames
from .merge import Point
from .municipalities import MunicipalityIndex
from .records import Item
from .text import fold

MIN_ITEMS = 1000
ALIAS_M = geonames.ALIAS_M
DUPLICATE_M = geonames.DUPLICATE_M
VARIABLES = ("item", "label", "lat", "lon", "type", "alts")
# Tipo do Wikidata -> `kind` do OpenStreetMap.
KINDS = {"Q34038": "natural=waterfall", "Q35509": "natural=cave_entrance", "Q40080": "natural=beach",
         "Q8502": "natural=peak", "Q570116": "tourism=attraction", "Q6017969": "tourism=viewpoint",
         "Q46169": "boundary=national_park", "Q177380": "natural=hot_spring", "Q1440300": "tourism=viewpoint"}

QUERY = """SELECT ?item ?label ?lat ?lon ?type (GROUP_CONCAT(DISTINCT ?alt; separator="|") AS ?alts) WHERE {
  VALUES ?type { %s }
  ?item wdt:P31 ?type; wdt:P17 wd:Q155; p:P625/psv:P625 [wikibase:geoLatitude ?lat; wikibase:geoLongitude ?lon].
  ?item rdfs:label ?label FILTER(LANG(?label) = "pt")
  OPTIONAL { ?item skos:altLabel ?alt FILTER(LANG(?alt) = "pt") }
} GROUP BY ?item ?label ?lat ?lon ?type"""


def url() -> str:
    """A consulta SPARQL, em GET, com a resposta em JSON."""
    query = QUERY % " ".join(f"wd:{q}" for q in KINDS)
    return config.WIKIDATA_SPARQL_URL + "?" + urllib.parse.urlencode({"query": query, "format": "json"})


def _bindings(path: Path) -> list:
    data = json.loads(path.read_text(encoding="utf-8"))
    head = (data.get("head") or {}).get("vars") if isinstance(data, dict) else None
    missing = [v for v in VARIABLES if not isinstance(head, list) or v not in head]
    if missing:
        raise KeyError(", ".join(missing))
    return data["results"]["bindings"]


def problem(path: Path) -> Optional[str]:
    """O que há de errado com a resposta, ou None se ela tem os itens do Brasil."""
    try:
        rows = _bindings(path)
    except (OSError, UnicodeDecodeError) as e:
        return f"não deu para ler ({e.__class__.__name__})"
    except json.JSONDecodeError as e:
        return f"não é JSON ({e.__class__.__name__})"
    except KeyError as e:
        return f"a resposta não tem as variáveis {e.args[0]}"
    if len(rows) < MIN_ITEMS:
        return f"só {len(rows)} itens (mínimo {MIN_ITEMS})"
    return None


def _value(row: dict, key: str) -> str:
    return str((row.get(key) or {}).get("value") or "").strip()


def load(path: Path) -> List[Point]:
    """Os itens com rótulo, ponto e tipo conhecido, com os apelidos (sem repetir o rótulo), na ordem da resposta."""
    out = []
    for row in _bindings(path):
        name = _value(row, "label")
        kind = KINDS.get(_value(row, "type").rsplit("/", 1)[-1])
        try:
            lat, lng = float(_value(row, "lat")), float(_value(row, "lon"))
        except ValueError:
            continue
        if not name or not kind:
            continue
        seen = {fold(name)}
        aliases = []
        for alt in _value(row, "alts").split("|"):
            alt = alt.strip()
            if alt and fold(alt) not in seen:
                seen.add(fold(alt))
                aliases.append(alt)
        out.append(Point(name, kind, lat, lng, aliases=aliases))
    return out


def add(items: Dict[str, List[Item]], points: Sequence[Point], index: MunicipalityIndex,
        states: Sequence[str]) -> Tuple[int, int, int]:
    """Como geonames.add: (entraram, já estavam, registros que ganharam nome alternativo)."""
    return geonames.add(items, points, index, states)
