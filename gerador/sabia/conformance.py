"""O conjunto de conformidade da busca (docs/CONFORMIDADE.md): casos com a entrada e a saída da busca de referência
(search.py, com search_rules.py, text.py e ranks.py), para quem porta a busca para outra linguagem (Kotlin num app,
JavaScript na web) conferir, automaticamente, que o porte dá os mesmos resultados.

O conjunto é amarrado a uma geração (`build_id`, `format_version` e o sha256 de cada pacote): as notas e a ordem
dependem dos registros do banco. Seções:

- `unit`: as funções puras (dobrar o texto, distância de edição, número da casa, alternativas das palavras, notas...),
  comparáveis sem banco: as tabelas de regras e um vocabulário pequeno vão no próprio arquivo (`rules`,
  `unit_fixtures`);
- `search`: a busca num banco (`db`: a UF ou `base`), com o texto, a posição quando há, e os primeiros resultados
  da referência, com os critérios da ordem de cada um e a tolerância da comparação;
- `which_street`: "que rua é esta?" de um ponto.

Os casos de busca vêm de duas fontes: todos os de `buscas.json` (as travas da geração) e uma receita fixa por UF
(`recipe_cases`), escolhida das tabelas do próprio banco em ordem de importância (`rank`, depois `id`), para cobrir
as 27 UFs por igual. A mesma receita propõe os casos levados ao `buscas.json` (`validation_candidates`).

A comparação (`compare_search`, `compare_which_street`, `compare_unit`) é a que um porte deve reproduzir; o
verificador de referência (scripts/check_conformance.py) a usa com a própria busca de referência.
"""
from __future__ import annotations

import hashlib
import io
import json
import math
import sqlite3
import struct
import unicodedata
from contextlib import closing
from pathlib import Path
from typing import Any, Callable, Dict, Iterable, List, Mapping, Optional, Sequence, Tuple

from . import database, geo, ranks, search, search_rules, street_lines, validation
from .text import fold

CONFORMANCE_VERSION = 1
FILE = "sabia-conformidade.json.zst"
SHA_FILE = FILE + ".sha256"

LIMIT = 10                 # resultados pedidos em cada busca
ORDER_EXACT = 3            # a ordem exata vale nos primeiros N; depois, o mesmo conjunto
SCORE_TOL = 1e-6           # diferença máxima da nota (`score`)
COORD_TOL_M = 1.5          # distância máxima entre o ponto esperado e o do porte
DISTANCE_TOL_M = 0.5       # diferença máxima de `distance_m`
FLOAT_TOL = 1e-9           # diferença máxima dos números com vírgula das funções puras (relativa acima de 1)
FRAGILE_EPS = 1e-6         # duas notas mais perto que isto (e diferentes) podem trocar de lugar num porte
EXTRA = 5                  # resultados a mais pedidos à referência para achar as trocas na fronteira

# As capitais (código do IBGE): a receita parte delas.
CAPITALS = {
    "AC": 1200401, "AL": 2704302, "AM": 1302603, "AP": 1600303, "BA": 2927408, "CE": 2304400, "DF": 5300108,
    "ES": 3205309, "GO": 5208707, "MA": 2111300, "MG": 3106200, "MS": 5002704, "MT": 5103403, "PA": 1501402,
    "PB": 2507507, "PE": 2611606, "PI": 2211001, "PR": 4106902, "RJ": 3304557, "RN": 2408102, "RO": 1100205,
    "RR": 1400100, "RS": 4314902, "SC": 4205407, "SE": 2800308, "SP": 3550308, "TO": 1721000,
}

# Rodízio pela posição da UF em ordem alfabética (AC 0, AL 1...), para variar a forma sem sorteio.
NORMALIZATION_STYLES = ("maiusculas", "matematico", "largura_total", "pontuacao")
BRAND_ROTATION = ("ipiranga", "shell", "petrobras", "posto shell")
PHRASE_ROTATION = ("posto de saude", "pronto socorro", "caixa eletronico", "lava jato", "posto de gasolina",
                   "area de descanso")
# Buscas que hoje não acham nada porque a busca não faz isso (coordenada digitada; o CEP não é exportado): ficam no
# conjunto como lacunas conhecidas (um porte que as resolva não falha, só avisa).
KNOWN_GAPS = {"GO": ("-16.68, -49.25", "74115-030", "cep 74115030")}
# A busca na base: além do município de cada UF, as rodovias federais.
BASE_ROADS = ("br 101", "BR-116", "br 153 goias")
HOUSE_CANDIDATES = 30      # ruas da capital com escada tentadas, da mais importante à menos
EMPTY_OFFSETS_DEG = (0.02, 0.05, 0.1, 0.2)
STREET_OFFSET_M = 8.0      # o ponto do "que rua é esta?" sai do traçado para o lado


# --- Comparação (o que um porte reproduz) ---------------------------------------------------------------------------

def _close(a: float, b: float, tol: float) -> bool:
    return abs(a - b) <= tol * max(1.0, abs(a), abs(b))


def same_value(expected: Any, got: Any, tol: float = FLOAT_TOL) -> bool:
    """Igualdade de valores JSON, com os números com vírgula a até `tol` (relativa acima de 1, absoluta abaixo)."""
    if isinstance(expected, bool) or isinstance(got, bool):
        return expected is got if isinstance(expected, bool) and isinstance(got, bool) else False
    if isinstance(expected, (int, float)) and isinstance(got, (int, float)):
        if isinstance(expected, int) and isinstance(got, int):
            return expected == got
        return _close(float(expected), float(got), tol)
    if isinstance(expected, (list, tuple)) and isinstance(got, (list, tuple)):
        return len(expected) == len(got) and all(same_value(e, g, tol) for e, g in zip(expected, got))
    if isinstance(expected, dict) and isinstance(got, dict):
        return expected.keys() == got.keys() and all(same_value(expected[k], got[k], tol) for k in expected)
    return expected == got


def compare_unit(case: Mapping[str, Any], got: Any) -> List[str]:
    if same_value(case["expected"], _plain(got), case.get("tol", FLOAT_TOL)):
        return []
    return [f"{case['fn']}({_short(case['args'])}): esperado {_short(case['expected'])}, veio {_short(_plain(got))}"]


def _same_item(expected: Mapping[str, Any], got: Mapping[str, Any], coord_tol_m: float) -> bool:
    """O mesmo registro: nome, classe, tipo e município iguais e o ponto a até `coord_tol_m` (o `id` muda a cada
    geração e não entra)."""
    return (all(expected.get(k) == got.get(k) for k in ("name", "cls", "kind", "municipality"))
            and geo.dist_m(expected["lat"], expected["lng"], got["lat"], got["lng"]) <= coord_tol_m)


def _attribute_problems(where: str, expected: Mapping[str, Any], got: Mapping[str, Any],
                        compare: Mapping[str, Any]) -> List[str]:
    out = []
    for k in ("district", "house_number", "hits", "house", "elsewhere", "kind_match"):
        if k in expected and k in got and expected[k] != got[k]:
            out.append(f"{where}: {k} esperado {expected[k]!r}, veio {got[k]!r}")
    if "score" in expected and "score" in got and abs(expected["score"] - got["score"]) > compare["score_tol"]:
        out.append(f"{where}: nota esperada {expected['score']:.9f}, veio {got['score']:.9f}")
    if expected.get("distance_m") is not None and got.get("distance_m") is not None \
            and abs(expected["distance_m"] - got["distance_m"]) > compare["distance_tol_m"]:
        out.append(f"{where}: distância esperada {expected['distance_m']} m, veio {got['distance_m']} m")
    return out


def _label(item: Optional[Mapping[str, Any]]) -> str:
    if not item:
        return "nada"
    return f"{item.get('name') or item.get('kind')} ({item.get('kind')}, {item.get('municipality')})"


def compare_search(case: Mapping[str, Any], got: Sequence[Mapping[str, Any]]) -> List[str]:
    """Os problemas do resultado de um porte para um caso de busca (vazio = conforme):

    1. o mesmo número de resultados (com o mesmo `limit`);
    2. nas `order_exact` primeiras posições, o mesmo registro, na mesma ordem;
    3. nas `same_set` primeiras, os mesmos registros, em qualquer ordem;
    4. em cada registro casado, os mesmos critérios da ordem (`hits`, `house`, `elsewhere`, `kind_match`), a nota a
       até `score_tol`, o bairro e o número da casa iguais e a distância a até `distance_tol_m`.
    """
    expected = case["expected"]
    compare = case["compare"]
    problems: List[str] = []
    if len(got) != len(expected):
        problems.append(f"{len(got)} resultados, esperados {len(expected)}")
    for i in range(min(compare["order_exact"], len(expected))):
        g = got[i] if i < len(got) else None
        if g is None or not _same_item(expected[i], g, compare["coord_tol_m"]):
            problems.append(f"posição {i + 1}: esperado {_label(expected[i])}, veio {_label(g)}")
    pool = list(got[:compare["same_set"]])
    for n, e in enumerate(expected[:compare["same_set"]], 1):
        match = next((g for g in pool if _same_item(e, g, compare["coord_tol_m"])), None)
        if match is None:
            problems.append(f"{_label(e)} (posição {n}) não está entre os {compare['same_set']} primeiros")
            continue
        pool.remove(match)
        problems += _attribute_problems(f"{_label(e)}", e, match, compare)
    return problems


def compare_which_street(case: Mapping[str, Any], got: Optional[Mapping[str, Any]]) -> List[str]:
    expected = case["expected"]
    if expected is None or got is None:
        return [] if expected is None and got is None else [f"esperado {_label(expected)}, veio {_label(got)}"]
    problems = [] if _same_item(expected, got, case["compare"]["coord_tol_m"]) else [
        f"esperado {_label(expected)}, veio {_label(got)}"]
    if abs(expected["distance_m"] - got["distance_m"]) > case["compare"]["distance_tol_m"]:
        problems.append(f"distância esperada {expected['distance_m']} m, veio {got['distance_m']} m")
    return problems


def compare_trace(expected: Mapping[str, Any], got: Mapping[str, Any]) -> List[str]:
    """As etapas da análise que diferem (só diagnóstico: ajuda a achar onde o porte se separa da referência)."""
    return [f"{k}: esperado {expected[k]!r}, veio {got.get(k)!r}" for k in expected
            if k in got and not same_value(expected[k], got[k])]


# --- A referência ---------------------------------------------------------------------------------------------------

def result_dict(r: search.Result) -> Dict[str, Any]:
    """Um resultado como o conjunto guarda: o que identifica o registro de forma estável (sem o `id`), o rótulo e os
    critérios da ordem."""
    out: Dict[str, Any] = {"name": r.name, "cls": r.cls, "kind": r.kind, "municipality": r.municipality,
                           "district": r.district, "lat": round(r.lat, 6), "lng": round(r.lng, 6),
                           "house_number": r.house_number, "label": r.label}
    if r.distance_m is not None:
        out["distance_m"] = round(r.distance_m, 2)
    if r.criteria is not None:
        out.update({k: (round(v, 9) if k == "score" else v) for k, v in r.criteria.items()})
    return out


def trace(db, query: str, near: Optional[Tuple[float, float]], limit: int) -> Dict[str, Any]:
    """As etapas da análise da busca de referência (search.search), na mesma ordem: o texto dobrado, corrigido
    (erros de digitação), a troca forçada quando a busca não achou nada, e o que _parse tirou dele."""
    rules = search._Rules(db)
    words = fold(query).split()
    corrected = " ".join(rules.correct_words(words))
    used, forced = corrected, None
    if rules.has_vocab and not search._search(db, rules, corrected, near, limit):
        candidate = " ".join(rules.correct_words(words, force=True))
        if candidate != corrected:
            used = forced = candidate
    parsed = search._parse(rules, used)
    house = search.house_number_in(parsed.text)
    return {"folded": " ".join(words), "corrected": corrected, "forced": forced, "words": parsed.words,
            "text": parsed.text, "kinds": parsed.kinds, "category_words": parsed.category_words,
            "municipality": rules.names.get(parsed.target) if parsed.target else None,
            "house_number": house[0] if house else None}


def _fragile(a: search.Result, b: search.Result) -> bool:
    ca, cb = a.criteria or {}, b.criteria or {}
    same_flags = all(ca.get(k) == cb.get(k) for k in ("hits", "house", "elsewhere", "kind_match"))
    gap = abs(float(ca.get("score", 0.0)) - float(cb.get("score", 0.0)))  # type: ignore[arg-type]
    return same_flags and 0 < gap < FRAGILE_EPS


def tolerance(found: Sequence[search.Result], limit: int) -> Dict[str, Any]:
    """A tolerância de um caso: a ordem exata nos ORDER_EXACT primeiros e o mesmo conjunto nos `limit`, menos onde
    duas notas quase iguais (e diferentes) podem trocar de lugar num porte por arredondamento."""
    shown = min(limit, len(found))
    fragile = {i for i in range(min(len(found) - 1, limit)) if _fragile(found[i], found[i + 1])}
    order_exact = min(ORDER_EXACT, shown)
    for i in sorted(fragile):
        if i < order_exact:
            order_exact = i
            break
    same_set = shown
    while same_set > 0 and (same_set - 1) in fragile:
        same_set -= 1
    return {"order_exact": order_exact, "same_set": same_set, "score_tol": SCORE_TOL, "coord_tol_m": COORD_TOL_M,
            "distance_tol_m": DISTANCE_TOL_M}


def search_case(db, case: Dict[str, Any], limit: int = LIMIT) -> Dict[str, Any]:
    """O caso com a saída da referência: os `limit` primeiros resultados, a tolerância e as etapas."""
    near = tuple(case["near"]) if case.get("near") else None
    found = search.search(db, case["query"], near=near, limit=limit + EXTRA)  # type: ignore[arg-type]
    out = dict(case)
    out["limit"] = limit
    out["expected"] = [result_dict(r) for r in found[:limit]]
    out["compare"] = tolerance(found, limit)
    out["trace"] = trace(db, case["query"], near, limit)  # type: ignore[arg-type]
    return out


def which_street_dict(r: Optional[search.Result]) -> Optional[Dict[str, Any]]:
    if r is None:
        return None
    return {"name": r.name, "cls": r.cls, "kind": r.kind, "municipality": r.municipality, "district": r.district,
            "lat": round(r.lat, 6), "lng": round(r.lng, 6), "distance_m": round(r.distance_m or 0.0, 2)}


def which_street_case(db, case: Dict[str, Any]) -> Dict[str, Any]:
    out = dict(case)
    out["expected"] = which_street_dict(search.which_street(db, case["lat"], case["lng"]))
    out["compare"] = {"coord_tol_m": COORD_TOL_M, "distance_tol_m": DISTANCE_TOL_M}
    return out


# --- As funções puras -----------------------------------------------------------------------------------------------

def rules_section() -> Dict[str, Any]:
    """As tabelas de regras dos pacotes deste formato (iguais em todos, conferidas em check_rules)."""
    return {"word_form": [list(r) for r in search_rules.word_forms()],
            "category": search_rules.categories(), "brand": search_rules.brands()}


def constants_section() -> Dict[str, Any]:
    """As constantes da busca que um porte escreve no código (não estão no banco)."""
    return {
        "stopwords": sorted(search.STOPWORDS), "name_number_words": sorted(search.NAME_NUMBER_WORDS),
        "house_number_connectors": sorted(search.HOUSE_NUMBER_CONNECTORS),
        "max_house_number": search.MAX_HOUSE_NUMBER, "sound_groups": list(search.SOUND_GROUPS),
        "max_combinations": search.MAX_COMBINATIONS, "max_rows": search.MAX_ROWS,
        "max_street_distance_m": search.MAX_STREET_DISTANCE_M, "category_rings": list(search.CATEGORY_RINGS),
        "weights": {"W_FULL": search.W_FULL, "W_NAME": search.W_NAME, "W_MUNICIPALITY": search.W_MUNICIPALITY,
                    "W_COVER": search.W_COVER, "W_RANK": search.W_RANK, "W_PLACE": search.W_PLACE,
                    "W_DISTANCE": search.W_DISTANCE},
        "max_distance_km": search.MAX_DISTANCE_KM, "max_rank": ranks.MAX_RANK, "score_decimals": 9,
        "cell_zoom": geo.CELL_ZOOM, "coord_scale": database.SCALE, "m_per_deg": geo.M_PER_DEG,
    }


# Um vocabulário e uma lista de municípios pequenos, para as funções que precisam deles (correct, parse) sem banco.
UNIT_VOCAB = [
    ("goiania", 900), ("goiana", 4), ("goias", 700), ("anapolis", 300), ("anhanguera", 120), ("bueno", 60),
    ("setor", 5000), ("oeste", 400), ("hotel", 80), ("soccorro", 1), ("socorro", 30), ("pirenopolis", 20),
    ("ipiranga", 50), ("paulista", 70), ("paulo", 300), ("aparecida", 400), ("marista", 40), ("brasilia", 500),
    ("capitao", 15), ("caldas", 90), ("independencia", 60), ("jardim", 3000), ("america", 200), ("cerrado", 50),
]
UNIT_MUNICIPALITIES = [(5208707, "Goiânia"), (5201405, "Aparecida de Goiânia"), (5201108, "Anápolis"),
                       (5200050, "Anhanguera"), (5208905, "Goiás"), (2910800, "Feira de Santana"),
                       (5300108, "Brasília")]

_FOLD_INPUTS = [
    ("R. Cap. Caldas, 280", None), ("São-José", None), ("AVENIDA T-63", None), ("Goia\u0302nia", "NFD"),
    ("GOIÂNIA", None), ("Ç ü ã õ ê", None), ("𝐆𝐨𝐢𝐚\u0302𝐧𝐢𝐚", "matemático negrito"), ("𝑹𝒖𝒂 𝟏𝟎", "matemático"),
    ("ＧＯＩÂＮＩＡ １０", "largura total"), ("ﬁlomena", "ligadura"), ("Rua Nº 5", "º vira o"),
    ("1º de Maio", None), ("Rua\u00a0Dez", "espaço sem quebra"), ("Rua\tDez\n", None), ("Goi\u00adânia", "hífen suave"),
    ("Rua\u200dDez", "junção de largura zero"), ("Rua 🚀 10", "emoji"), ("x²", "sobrescrito"), ("½", "fração"),
    ("Ⅻ", "número romano"), ("", None), ("   ", None), ("--", None), ("a\u0301b", None), ("İstanbul", None),
    ("Đà Nẵng", None), ("Øresund", None), ("Straße", None), ("Œuvre", None), ("ŀ", None),
    ("ΟΔΟΣ", "sigma final"), ("٣", "dígito árabe"), ("किताब", "marca combinante de classe 0"),
    ("한국", "hangul"), ("Avenida  Goiás ,  Setor-Oeste", None),
]
_INFORMATIVE_FOLD = {"ΟΔΟΣ", "٣", "किताब", "한국", "ŀ", "Ⅻ"}

_INDEX_TEXT_INPUTS = ["Rua 14", "Rua Quatorze", "Avenida 1", "Rua Um", "Rua 014", "Avenida T-63", "Rua 1000",
                      "Rua 21", "Praça Dez de Novembro", "BR-153 km 120"]
_EDIT_DISTANCE_INPUTS = [("goiana", "goiania"), ("otel", "hotel"), ("ab", "ba"), ("ca", "abc"), ("", "abc"),
                         ("abc", ""), ("kitten", "sitting"), ("anhanguera", "anhaguera"), ("bueno", "beuno"),
                         ("abcdef", "badcfe"), ("pirenopolis", "pirinopolis"), ("rua", "rua"), ("aa", "aaaa")]
_HOUSE_NUMBER_INPUTS = [
    "rua 10 152 setor oeste", "rua 10", "rua 10 n 152", "avenida t 63", "avenida goias 152", "152",
    "br 153 km 120", "rua x 100000", "rua x 0", "quadra 3", "avenida anhanguera 1000 goiania", "rua bahia no 12",
    "n 12", "rua a 12", "rua 2 12", "go 060 10", "rua 10 numero 152", "rua 10 152 200",
]
_OPTIONS_INPUTS = [("av", False), ("av", True), ("10", False), ("10", True), ("doutor", False), ("setor", False),
                   ("st", False), ("rodoviaria", False), ("s", False), ("s", True), ("sao", True), ("um", False),
                   ("quatorze", False), ("14", False), ("bombeiros", False), ("goiania", True), ("dra", False)]
_NAME_INPUTS = [
    (["rua", "10"], "Rua 10", True), (["rua", "10"], "Rua 10 Setor Oeste", True),
    (["setor", "oeste"], "Rua 10 Setor Oeste", True), (["av", "goias"], "Avenida Goiás", True),
    (["anhang"], "Avenida Anhanguera", True), (["anhang"], "Avenida Anhanguera", False),
    (["dr", "olinto"], "Rua Doutor Olinto Manso", True), (["quatorze"], "Rua 14", True),
    (["14"], "Rua Quatorze", True), (["10"], "Rua 100", False), (["10"], "Rua 100", True),
    (["rodoviaria", "goiania"], "Terminal Rodoviário de Goiânia", True),
    (["jardim", "america"], "Pet shop - banho e tosa - Jardim América", True), (["st"], "Styles", True),
    (["setor"], "St. Central", True), ([], "Rua 10", True),
]
_PARSE_INPUTS = ["cidade de goias", "posto de saude vila nova", "posto ipiranga", "ipiranga", "feira de santana",
                 "rua 10 aparecida de goiania", "avenida anhanguera goiania", "rua 90 goiania", "goiania",
                 "caixa eletronico", "drogasil centro", "de", "hospital de base brasilia", "municipio de anapolis"]
_CORRECT_INPUTS = [("goiana", False, False), ("goiana", False, True), ("otel", False, False),
                   ("anhagu", True, False), ("beuno", False, False), ("xyz", False, False), ("postp", True, False),
                   ("socorro", False, False), ("pirenopols", False, False), ("brasilai", False, False),
                   ("setr", True, False), ("goi", True, False), ("paulista", False, True), ("152", False, False)]
_LADDER = [0, 0, 2, -1667000, -4925800, 0, 0, 102, -1667000, -4925612, 0, 0, 202, -1667000, -4925424,
           1, 0, 1, -1667000, -4925800, 1, 0, 101, -1667000, -4925612,
           0, 1, 1002, -1667000, -4925330, 0, 1, 1042, -1667000, -4925311]


def unit_inputs() -> List[Dict[str, Any]]:
    """As entradas dos casos das funções puras (as saídas vêm da referência, em unit_case)."""
    cases: List[Dict[str, Any]] = []

    def add(fn: str, args: Dict[str, Any], note: Optional[str] = None, informative: bool = False) -> None:
        case: Dict[str, Any] = {"fn": fn, "args": args}
        if note:
            case["note"] = note
        if informative:
            case["informative"] = True
        cases.append(case)

    for text, note in _FOLD_INPUTS:
        add("fold", {"text": text}, note, text in _INFORMATIVE_FOLD)
    for name in _INDEX_TEXT_INPUTS:
        add("index_text", {"name": name})
    for a, b in _EDIT_DISTANCE_INPUTS:
        add("edit_distance", {"a": a, "b": b})
    for n in range(0, 11):
        add("max_errors", {"length": n})
    for a, b in [("c", "s"), ("c", "k"), ("q", "z"), ("x", "s"), ("g", "j"), ("i", "y"), ("u", "w"), ("v", "w"),
                 ("c", "g"), ("h", "o"), ("a", "a"), ("e", "i")]:
        add("same_sound", {"a": a, "b": b})
    for q in _HOUSE_NUMBER_INPUTS:
        add("house_number_in", {"words": q.split()})
    for word, last in _OPTIONS_INPUTS:
        add("options", {"word": word, "last": last})
    for words, name, prefix_last in _NAME_INPUTS:
        add("name_score", {"words": words, "name": name, "prefix_last": prefix_last})
        add("name_cover", {"words": words, "name": name, "prefix_last": prefix_last})
        add("name_hits", {"words": words, "name": name, "last_word": words[-1] if words and prefix_last else ""})
    for q in _PARSE_INPUTS:
        add("parse", {"folded": q})
    for word, prefix, force in _CORRECT_INPUTS:
        add("correct", {"word": word, "prefix": prefix, "force": force})
    for n in (2, 1, 3, 50, 102, 101, 103, 201, 202, 203, 1002, 1010, 1042, 1044, 0):
        add("ladder_position", {"rungs": _LADDER, "number": n})
    for lat, lng in [(-16.68634, -49.25), (-15.7939, -47.8828), (-23.5505, -46.6333), (-33.75, -73.99),
                     (5.27, -60.2), (0.0, 0.0), (-3.7319, -38.5267)]:
        add("cell", {"lat": lat, "lng": lng})
    add("cells_around", {"lat": -16.68634, "lng": -49.25, "ring": 1})
    add("cells_around", {"lat": -16.68634, "lng": -49.25, "ring": 2})
    for p in [(-16.68, -49.25, -16.69, -49.26), (-15.0, -47.0, -15.0, -47.001), (-30.0, -51.0, -29.0, -50.0),
              (0.0, 0.0, 0.0, 0.0)]:
        add("dist_m", {"lat1": p[0], "lng1": p[1], "lat2": p[2], "lng2": p[3]})
    for m in (0.0, 1.0, 500.0, 1000.0, 9999.0, 150000.0, 1999999.0, 2000000.0, 5000000.0):
        add("closeness", {"meters": m})
    line = [[-16.68, -49.26], [-16.68, -49.25], [-16.67, -49.25]]
    for lat, lng in [(-16.6801, -49.255), (-16.675, -49.2499), (-16.69, -49.27), (-16.68, -49.26)]:
        add("distance_to_line", {"lat": lat, "lng": lng, "coords": line})
    scores: List[Dict[str, Any]] = [
        {"full": 3, "partial": 3, "rank": 149, "place_rank": 149, "mun_hits": 0, "mun_words": 0, "cover": 1.0,
         "distance_m": None},
        {"full": 2, "partial": 1, "rank": 20, "place_rank": 140, "mun_hits": 1, "mun_words": 1, "cover": 0.5,
         "distance_m": 1234.5},
        {"full": 0, "partial": 0, "rank": 30, "place_rank": 0, "mun_hits": 0, "mun_words": 0, "cover": None,
         "distance_m": 350.0},
        {"full": 1, "partial": 0, "rank": 255, "place_rank": 255, "mun_hits": 2, "mun_words": 3, "cover": 0.25,
         "distance_m": 2500000.0},
    ]
    for args in scores:
        add("score", args)
    labels: List[Dict[str, Any]] = [
        {"name": "Rua 10", "kind": "highway=residential", "house_number": 152, "district": "Setor Oeste",
         "municipality": "Goiânia"},
        {"name": "", "kind": "amenity=fuel", "house_number": None, "district": None, "municipality": "Goiânia"},
        {"name": "Goiânia", "kind": "municipality", "house_number": None, "district": None, "municipality": "Goiânia"},
        {"name": "Setor Oeste", "kind": "place=suburb", "house_number": None, "district": "Setor Oeste",
         "municipality": "Goiânia"},
    ]
    for r in labels:
        add("label", r)
    return cases


def fixture_db(rules: Mapping[str, Any], fixtures: Mapping[str, Any]) -> sqlite3.Connection:
    """Um banco na memória só com as tabelas de regras e o vocabulário e os municípios de `unit_fixtures`: o que as
    funções com regras (options, name_score, correct, parse...) leem, sem um pacote."""
    db = sqlite3.connect(":memory:")
    db.executescript("CREATE TABLE word_form (word TEXT, form TEXT, rule TEXT); CREATE TABLE category (word TEXT, "
                     "kinds TEXT); CREATE TABLE brand (word TEXT, kinds TEXT); CREATE TABLE vocab (word TEXT PRIMARY "
                     "KEY, n INTEGER); CREATE TABLE municipality (id INTEGER, name TEXT); CREATE TABLE item (id "
                     "INTEGER, cls TEXT, kind TEXT, name TEXT, municipality INTEGER, district INTEGER, lat INTEGER, "
                     "lng INTEGER, cell INTEGER, rank INTEGER);")
    db.executemany("INSERT INTO word_form VALUES (?, ?, ?)", rules["word_form"])
    db.executemany("INSERT INTO category VALUES (?, ?)", sorted(rules["category"].items()))
    db.executemany("INSERT INTO brand VALUES (?, ?)", sorted(rules["brand"].items()))
    db.executemany("INSERT INTO vocab VALUES (?, ?)", fixtures["vocab"])
    db.executemany("INSERT INTO municipality VALUES (?, ?)", fixtures["municipalities"])
    return db


def reference_unit(fn: str, args: Mapping[str, Any], rules_db: sqlite3.Connection) -> Any:
    """A saída da referência para um caso das funções puras."""
    a = args
    if fn == "fold":
        return fold(a["text"])
    if fn == "index_text":
        return database.index_text(a["name"])
    if fn == "edit_distance":
        return search.edit_distance(a["a"], a["b"])
    if fn == "max_errors":
        return search.max_errors(a["length"])
    if fn == "same_sound":
        return search._same_sound(a["a"], a["b"])
    if fn == "house_number_in":
        found = search.house_number_in(a["words"])
        return None if found is None else {"number": found[0], "words": found[1]}
    if fn == "ladder_position":
        return search.ladder_position(a["rungs"], a["number"])
    if fn == "cell":
        return geo.cell(a["lat"], a["lng"])
    if fn == "cells_around":
        return search._cells_around(a["lat"], a["lng"], a["ring"])
    if fn == "dist_m":
        return geo.dist_m(a["lat1"], a["lng1"], a["lat2"], a["lng2"])
    if fn == "closeness":
        return search._closeness(a["meters"])
    if fn == "distance_to_line":
        return street_lines.distance_to_line(a["lat"], a["lng"], [tuple(p) for p in a["coords"]])
    if fn == "score":
        return search.score(a["full"], a["partial"], a["rank"], a["place_rank"], a["mun_hits"], a["mun_words"],
                            a["cover"], a["distance_m"])
    if fn == "label":
        return search.Result(0, "", a["kind"], a["name"], a["municipality"], a["district"], 0.0, 0.0,
                             house_number=a["house_number"]).label
    rules = search._Rules(rules_db)
    if fn == "options":
        return rules.options(a["word"], a["last"])
    if fn == "name_score":
        return search.name_score(rules, a["words"], a["name"], a["prefix_last"])
    if fn == "name_cover":
        return search.name_cover(rules, a["words"], a["name"], a["prefix_last"])
    if fn == "name_hits":
        return search._name_hits(rules, a["words"], a["name"], a["last_word"])
    if fn == "correct":
        return rules.correct(a["word"], a["prefix"], a["force"])
    if fn == "parse":
        p = search._parse(rules, a["folded"])
        return {"words": p.words, "text": p.text, "kinds": p.kinds, "category_words": p.category_words,
                "municipality": rules.names.get(p.target) if p.target else None,
                "municipality_words": sorted(p.mun_words)}
    raise ValueError(f"função desconhecida: {fn}")


UNIT_TOLERANCE = {"dist_m": 1e-6, "distance_to_line": 1e-6, "closeness": FLOAT_TOL, "score": FLOAT_TOL,
                  "name_cover": FLOAT_TOL, "ladder_position": 1e-9}


def unit_cases(rules: Mapping[str, Any], fixtures: Mapping[str, Any]) -> List[Dict[str, Any]]:
    with closing(fixture_db(rules, fixtures)) as db:
        out = []
        counters: Dict[str, int] = {}
        for case in unit_inputs():
            counters[case["fn"]] = counters.get(case["fn"], 0) + 1
            full = {"id": f"{case['fn']}-{counters[case['fn']]:02d}", **case,
                    "expected": _plain(reference_unit(case["fn"], case["args"], db))}
            if case["fn"] in UNIT_TOLERANCE:
                full["tol"] = UNIT_TOLERANCE[case["fn"]]
            out.append(full)
        return out


def unit_fixtures() -> Dict[str, Any]:
    return {"vocab": [list(v) for v in UNIT_VOCAB], "municipalities": [list(m) for m in UNIT_MUNICIPALITIES]}


# --- A receita por UF -----------------------------------------------------------------------------------------------

def _one(db, sql: str, params: Iterable = ()) -> Optional[tuple]:
    return next(iter(db.execute(sql, tuple(params))), None)


def typo(text: str) -> str:
    """O erro de digitação da receita: na palavra mais longa só de letras (de 4 letras ou mais, as que aceitam um
    erro; a primeira, no empate), as duas letras do meio trocadas de lugar (ou, iguais, a do meio apagada). Sem
    palavra assim, o texto como está."""
    words = text.split()
    best = max(range(len(words)), key=lambda i: (len(words[i]) if words[i].isalpha() else 0, -i), default=None)
    if best is None or len(words[best]) < 4 or not words[best].isalpha():
        return text
    w = words[best]
    i = len(w) // 2
    words[best] = w[:i - 1] + w[i] + w[i - 1] + w[i + 1:] if w[i - 1] != w[i] else w[:i] + w[i + 1:]
    return " ".join(words)


def styled(name: str, style: str) -> str:
    """O nome escrito de outro jeito, para a normalização: maiúsculas, letras matemáticas em negrito, largura total
    ou com pontuação e o "cidade de" no começo."""
    if style == "maiusculas":
        return name.upper()
    if style == "pontuacao":
        return f"Cidade de {name.replace(' ', '-')}."
    out = []
    for c in unicodedata.normalize("NFD", name):
        if style == "matematico" and "A" <= c <= "Z":
            out.append(chr(0x1D400 + ord(c) - ord("A")))
        elif style == "matematico" and "a" <= c <= "z":
            out.append(chr(0x1D41A + ord(c) - ord("a")))
        elif style == "largura_total" and "!" <= c <= "~":
            out.append(chr(0xFF01 + ord(c) - ord("!")))
        elif style == "largura_total" and c == " ":
            out.append("\u3000")
        else:
            out.append(c)
    return "".join(out)


def _abbreviated(folded: str) -> str:
    return "av " + folded[len("avenida "):] if folded.startswith("avenida ") else folded


def _prefix(folded: str) -> str:
    """A busca pela metade: a última palavra com metade das letras (pelo menos 3)."""
    words = folded.split()
    last = words[-1]
    words[-1] = last[:max(3, (len(last) + 1) // 2)]
    return " ".join(words)


def _seat(db, code: int) -> Optional[Tuple[str, float, float]]:
    row = _one(db, "SELECT name, lat, lng FROM municipality WHERE id = ?", [code])
    return (row[0], row[1] / database.SCALE, row[2] / database.SCALE) if row else None


def _house_case(db, capital_code: int, capital: str) -> List[Dict[str, Any]]:
    """O número da casa: a rua da capital com escada mais importante em que a referência acha o número (um par entre
    dois degraus, interpolado, e um ímpar num degrau, com "n" antes)."""
    rows = db.execute("SELECT i.id, i.name, h.rungs FROM item i JOIN house_number h ON h.street = i.id "
                      "WHERE i.municipality = ? AND i.cls = 'street' ORDER BY i.rank DESC, i.id LIMIT ?",
                      (capital_code, HOUSE_CANDIDATES)).fetchall()
    for _, name, blob in rows:
        flat = struct.unpack(f"<{len(blob) // 4}i", blob)
        sides: Dict[int, List[int]] = {0: [], 1: []}
        first_piece: Dict[int, int] = {}
        for k in range(0, len(flat), 5):
            side, piece, number = flat[k], flat[k + 1], flat[k + 2]
            first_piece.setdefault(side, piece)
            if piece == first_piece[side]:
                sides[side].append(number)
        if len(sides[0]) < 2 or not sides[1]:
            continue
        evens = sorted(sides[0])
        n1, n2 = evens[len(evens) // 2 - 1], evens[len(evens) // 2]
        even = n1 + 2 if n1 + 2 < n2 else n1
        odd = sorted(sides[1])[len(sides[1]) // 2]
        cases = [{"type": "numero_casa", "query": f"{fold(name)} {even} {fold(capital)}"},
                 {"type": "numero_casa", "query": f"{fold(name)} n {odd}"}]
        if all(any(r.house_number is not None for r in search.search(db, c["query"], limit=3)) for c in cases):
            return cases
    return []


def _main_street(db, capital_code: int) -> Optional[Tuple[int, str]]:
    row = _one(db, "SELECT id, name FROM item WHERE municipality = ? AND cls = 'street' AND name LIKE 'Avenida %' "
                   "ORDER BY rank DESC, id LIMIT 1", [capital_code])
    return row or _one(db, "SELECT id, name FROM item WHERE municipality = ? AND cls = 'street' "
                           "ORDER BY rank DESC, id LIMIT 1", [capital_code])


def recipe_cases(db, uf: str) -> List[Dict[str, Any]]:
    """Os casos de busca da receita para uma UF, só a entrada (ver docs/CONFORMIDADE.md, "A receita")."""
    index = sorted(CAPITALS).index(uf)
    code = CAPITALS[uf]
    seat = _seat(db, code)
    if seat is None:
        return []
    capital, lat, lng = seat
    near = [round(lat, 5), round(lng, 5)]
    cap = fold(capital)
    out: List[Dict[str, Any]] = [{"type": "municipio", "query": capital}]
    second = _one(db, "SELECT name FROM item WHERE kind = 'municipality' AND municipality != ? "
                      "ORDER BY rank DESC, id LIMIT 1", [code]) \
        or _one(db, "SELECT name FROM item WHERE cls = 'place' AND kind != 'municipality' ORDER BY rank DESC, id "
                    "LIMIT 1")
    if second:
        out.append({"type": "municipio", "query": fold(second[0])})
    out.append({"type": "normalizacao", "query": styled(capital, NORMALIZATION_STYLES[index % 4])})
    out.append({"type": "erro_digitacao", "query": typo(cap)})
    suburb = _one(db, "SELECT name FROM item WHERE municipality = ? AND kind IN ('place=suburb', "
                      "'place=neighbourhood', 'place=quarter') ORDER BY rank DESC, id LIMIT 1", [code])
    if suburb:
        out.append({"type": "bairro", "query": f"{fold(suburb[0])} {cap}"})
        out.append({"type": "erro_digitacao", "query": f"{typo(fold(suburb[0]))} {cap}"})
    street = _main_street(db, code)
    if street:
        out.append({"type": "rua", "query": f"{_abbreviated(fold(street[1]))} {cap}"})
        out.append({"type": "prefixo", "query": _prefix(_abbreviated(fold(street[1])))})
    for name, _ in db.execute("SELECT name, COUNT(*) c FROM item WHERE cls = 'street' GROUP BY name "
                              "ORDER BY c DESC, name LIMIT 20").fetchall():
        if _one(db, "SELECT 1 FROM item WHERE cls = 'street' AND name = ? AND municipality = ?", [name, code]):
            out.append({"type": "rua_comum", "query": f"{fold(name)} {cap}"})
            break
    out.append({"type": "categoria", "query": f"hospital {cap}"})
    out.append({"type": "categoria_perto", "query": "posto", "near": near})
    out.append({"type": "marca", "query": BRAND_ROTATION[index % len(BRAND_ROTATION)], "near": near})
    out.append({"type": "frase_categoria", "query": PHRASE_ROTATION[index % len(PHRASE_ROTATION)], "near": near})
    out += _house_case(db, code, capital)
    road = _one(db, "SELECT i.name, m.name FROM item i JOIN item m ON m.municipality = i.municipality AND m.kind = "
                    "'municipality' WHERE i.cls = 'road' AND i.name LIKE 'BR-%' ORDER BY m.rank DESC, i.id LIMIT 1")
    if road:
        out.append({"type": "rodovia", "query": f"{road[0].lower()} {fold(road[1])}"})
    for query in KNOWN_GAPS.get(uf, ()):
        out.append({"type": "lacuna", "query": query, "known_gap": True})
    return out


def which_street_points(db, uf: str) -> List[Dict[str, Any]]:
    """Os pontos do "que rua é esta?" da receita: ao lado (STREET_OFFSET_M) do meio do primeiro segmento do traçado
    da avenida da capital, e o primeiro ponto em volta da sede, cada vez mais longe, sem rua a até 75 m."""
    out: List[Dict[str, Any]] = []
    code = CAPITALS[uf]
    seat = _seat(db, code)
    street = _main_street(db, code)
    if street:
        row = _one(db, "SELECT coords FROM street_line WHERE item = ? ORDER BY rowid LIMIT 1", [street[0]])
        if row:
            (alat, alng), (blat, blng) = street_lines.decode(bytes(row[0]))[:2]
            k = math.cos(math.radians(alat))
            dx, dy = (blng - alng) * k, blat - alat
            norm = math.hypot(dx, dy) or 1.0
            off = STREET_OFFSET_M / geo.M_PER_DEG
            lat = (alat + blat) / 2 + dx / norm * off
            lng = (alng + blng) / 2 - dy / norm * off / k
            out.append({"type": "rua", "lat": round(lat, 6), "lng": round(lng, 6)})
    if seat:
        _, lat0, lng0 = seat
        directions = [(1, 0), (0, 1), (-1, 0), (0, -1), (1, 1), (1, -1), (-1, 1), (-1, -1)]
        for d in EMPTY_OFFSETS_DEG:
            spot = next(((round(lat0 + d * a, 6), round(lng0 + d * b, 6)) for a, b in directions
                         if search.which_street(db, lat0 + d * a, lng0 + d * b) is None), None)
            if spot:
                out.append({"type": "sem_rua", "lat": spot[0], "lng": spot[1]})
                break
    return out


def base_inputs(db, states: Sequence[str]) -> List[Dict[str, Any]]:
    """Os casos da base: em cada UF, o município mais importante depois do primeiro (no DF, o único) com a sigla, e
    algumas rodovias federais."""
    out = []
    for uf in states:
        rows = db.execute("SELECT i.name FROM item i JOIN municipality m ON m.id = i.municipality WHERE m.uf = ? AND "
                          "i.kind = 'municipality' ORDER BY i.rank DESC, i.id LIMIT 2", [uf]).fetchall()
        if rows:
            out.append({"type": "base", "uf": uf, "query": f"{fold(rows[-1][0])} {uf.lower()}"})
    out += [{"type": "base", "uf": "BR", "query": q} for q in BASE_ROADS]
    return out


def validation_candidates(db, uf: str) -> List[Dict[str, Any]]:
    """Os casos que a receita leva ao buscas.json (as travas da geração), no formato dele: o nome da capital com
    erro de digitação, "posto" da sede, "hospital <capital>" e o número da casa (ver docs/CONFORMIDADE.md)."""
    code = CAPITALS[uf]
    seat = _seat(db, code)
    if seat is None:
        return []
    capital, lat, lng = seat
    out: List[Dict[str, Any]] = [
        {"top": 1, "uf": uf, "query": typo(fold(capital)), "name": capital, "kind": "municipality"}]
    if out[0]["query"] == fold(capital):
        out = []  # sem palavra que aceite erro
    out += [
        {"top": 1, "uf": uf, "query": "posto", "near": [round(lat, 4), round(lng, 4)], "kind": "amenity=fuel",
         "within_m": 3000},
        {"top": 3, "uf": uf, "query": f"hospital {fold(capital)}", "kind": "amenity=hospital",
         "municipality": capital},
    ]
    house = _house_case(db, code, capital)
    if house:
        query = house[0]["query"]
        found = search.search(db, query, limit=3)
        hit = next(r for r in found if r.house_number is not None)
        out.append({"top": 3, "uf": uf, "query": query, "name": hit.name, "house_number": hit.house_number,
                    "municipality": capital})
    # só os que a trava aceita hoje ("sao lius" não é corrigido: "lius" está no pacote, na Vila São Lius)
    problems, rows = validation.search_gate(db, out)
    return [c for c, row in zip(out, rows) if row["rank"] is not None and row["rank"] <= c["top"]]


# --- O conjunto -----------------------------------------------------------------------------------------------------

def _plain(value: Any) -> Any:
    """Tuplas viram listas (o que o JSON guarda)."""
    return json.loads(json.dumps(value))


def _short(value: Any, limit: int = 160) -> str:
    text = json.dumps(value, ensure_ascii=False)
    return text if len(text) <= limit else text[:limit] + "..."


def file_sha256(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def _meta(db) -> Dict[str, str]:
    return dict(db.execute("SELECT key, value FROM meta"))


def check_rules(db, name: str) -> List[str]:
    """O pacote tem as mesmas tabelas de regras que o conjunto leva em `rules`."""
    expected = rules_section()
    problems = []
    if sorted(map(list, db.execute("SELECT word, form, rule FROM word_form"))) != sorted(expected["word_form"]):
        problems.append(f"{name}: word_form difere de search_rules")
    if dict(db.execute("SELECT word, kinds FROM category")) != expected["category"]:
        problems.append(f"{name}: category difere de search_rules")
    if dict(db.execute("SELECT word, kinds FROM brand")) != expected["brand"]:
        problems.append(f"{name}: brand difere de search_rules")
    return problems


def load_validation_cases(path: Path) -> List[Dict[str, Any]]:
    return json.loads(path.read_text(encoding="utf-8"))


def build(dbs: Mapping[str, Path], validation_cases: Sequence[Mapping[str, Any]], zst_dir: Optional[Path] = None,
          generator_commit: str = "desconhecido", log: Callable[[str], None] = lambda _: None) -> Dict[str, Any]:
    """O conjunto de conformidade sobre os bancos `dbs` ({'base': caminho, 'GO': caminho, ...}, descompactados).
    `validation_cases`: os de buscas.json (entram todos os das UFs presentes). Com `zst_dir`, o sha256 de cada
    pacote compactado vai junto. Levanta ValueError se os bancos forem de gerações ou formatos diferentes, ou se as
    tabelas de regras não forem as de search_rules."""
    states = sorted(k for k in dbs if k != "base")
    metas: Dict[str, Dict[str, str]] = {}
    problems: List[str] = []
    for name, path in dbs.items():
        with closing(sqlite3.connect(f"file:{path}?mode=ro", uri=True)) as db:
            metas[name] = _meta(db)
            problems += check_rules(db, name)
    builds = {(m.get("build_id"), m.get("format_version")) for m in metas.values()}
    if len(builds) != 1:
        problems.append(f"bancos de gerações ou formatos diferentes: {sorted(map(str, builds))}")
    if problems:
        raise ValueError("; ".join(problems))
    build_id, format_version = builds.pop()
    packages: Dict[str, Dict[str, Any]] = {}
    for name in ["base", *states]:
        if name not in dbs:
            continue
        file = f"sabia-{name}.sqlite.zst"
        entry: Dict[str, Any] = {"file": file}
        if zst_dir is not None and (zst_dir / file).exists():
            entry["sha256"] = file_sha256(zst_dir / file)
        packages[name] = entry

    rules, fixtures = rules_section(), unit_fixtures()
    doc: Dict[str, Any] = {
        "conformance_version": CONFORMANCE_VERSION,
        "build_id": build_id,
        "format_version": int(str(format_version)) if str(format_version).isdigit() else format_version,
        "generator_commit": generator_commit,
        "reference": "gerador/sabia/search.py",
        "unicode_version": unicodedata.unidata_version,
        "limit": LIMIT,
        "states": states,
        "packages": packages,
        "constants": constants_section(),
        "rules": rules,
        "unit_fixtures": fixtures,
        "unit": unit_cases(rules, fixtures),
        "search": [],
        "which_street": [],
    }
    seen = set()
    for name in ["base", *states]:
        if name not in dbs:
            continue
        with closing(sqlite3.connect(f"file:{dbs[name]}?mode=ro", uri=True)) as db:
            if name == "base":
                inputs = base_inputs(db, states)
                for n, c in enumerate(inputs, 1):
                    c["id"] = f"base-{n:02d}"
                    c["origin"] = "receita"
            else:
                mine = [c for c in validation_cases if c["uf"] == name]
                inputs = [{"id": f"trava-{name}-{n:03d}", "type": "trava", "uf": name, "query": c["query"],
                           **({"near": list(c["near"])} if "near" in c else {}), "origin": "buscas.json"}
                          for n, c in enumerate(mine, 1)]
                counters: Dict[str, int] = {}
                for c in recipe_cases(db, name):
                    counters[c["type"]] = counters.get(c["type"], 0) + 1
                    suffix = "" if counters[c["type"]] == 1 else f"-{counters[c['type']]}"
                    inputs.append({"id": f"{name}-{c['type']}{suffix}", "uf": name, **c, "origin": "receita"})
                for p in which_street_points(db, name):
                    doc["which_street"].append(which_street_case(db, {"id": f"{name}-que_rua-{p['type']}", "uf": name,
                                                                      "db": name, **p}))
            for c in inputs:
                key = (name, c["query"], tuple(c.get("near") or ()))
                if key in seen:
                    continue
                seen.add(key)
                c["db"] = name
                doc["search"].append(search_case(db, c))
        log(f"[conformidade] {name}: {sum(1 for c in doc['search'] if c['db'] == name)} buscas")
    return doc


# --- Arquivo --------------------------------------------------------------------------------------------------------

def dumps(doc: Mapping[str, Any], pretty: bool = False) -> bytes:
    if pretty:
        return (json.dumps(doc, ensure_ascii=False, indent=1) + "\n").encode("utf-8")
    return (json.dumps(doc, ensure_ascii=False, separators=(",", ":")) + "\n").encode("utf-8")


def save(doc: Mapping[str, Any], dest: Path) -> Optional[str]:
    """Grava o conjunto: .json.zst compactado (zstd 19, com o sha256 ao lado em <arquivo>.sha256, no formato do
    sha256sum) ou .json legível. Devolve o sha256 do .zst."""
    data = dumps(doc, pretty=not dest.name.endswith(".zst"))
    dest.parent.mkdir(parents=True, exist_ok=True)
    if not dest.name.endswith(".zst"):
        dest.write_bytes(data)
        return None
    import zstandard
    dest.write_bytes(zstandard.ZstdCompressor(level=19, write_checksum=True, write_content_size=True).compress(data))
    digest = file_sha256(dest)
    dest.with_name(dest.name + ".sha256").write_text(f"{digest}  {dest.name}\n", encoding="utf-8")
    return digest


def load(path: Path) -> Dict[str, Any]:
    raw = path.read_bytes()
    if path.name.endswith(".zst"):
        import zstandard
        with zstandard.ZstdDecompressor().stream_reader(io.BytesIO(raw)) as reader:
            raw = reader.read()
    return json.loads(raw.decode("utf-8"))


def sha_problem(path: Path) -> Optional[str]:
    """O .sha256 ao lado do .zst existe e bate com ele."""
    sha = path.with_name(path.name + ".sha256")
    if not sha.exists():
        return f"falta {sha.name}"
    if sha.read_text(encoding="utf-8").split()[:1] != [file_sha256(path)]:
        return f"{sha.name} não bate com {path.name}"
    return None


def summary(doc: Mapping[str, Any]) -> Dict[str, Any]:
    """Quantos casos por seção, por tipo e por UF (para o relatório e para o log)."""
    by_type: Dict[str, int] = {}
    by_uf: Dict[str, int] = {}
    for c in doc["search"]:
        by_type[c["type"]] = by_type.get(c["type"], 0) + 1
        by_uf[c["db"]] = by_uf.get(c["db"], 0) + 1
    for c in doc["which_street"]:
        by_uf[c["db"]] = by_uf.get(c["db"], 0) + 1
    by_fn: Dict[str, int] = {}
    for c in doc["unit"]:
        by_fn[c["fn"]] = by_fn.get(c["fn"], 0) + 1
    return {"unit": len(doc["unit"]), "search": len(doc["search"]), "which_street": len(doc["which_street"]),
            "by_type": dict(sorted(by_type.items())), "by_db": dict(sorted(by_uf.items())),
            "by_fn": dict(sorted(by_fn.items()))}


# --- O verificador --------------------------------------------------------------------------------------------------

class Reference:
    """A busca de referência do jeito que o verificador chama um porte: cada método recebe só o que está no caso e
    devolve valores JSON (listas, dicionários, números, textos). Um porte escreve o mesmo adaptador para o código dele
    (ver docs/CONFORMIDADE.md)."""

    def __init__(self, doc: Mapping[str, Any], db_paths: Mapping[str, Path]):
        self.rules_db = fixture_db(doc["rules"], doc["unit_fixtures"])
        self.db_paths = dict(db_paths)
        self._open: Dict[str, sqlite3.Connection] = {}

    def db(self, name: str) -> sqlite3.Connection:
        if name not in self._open:
            self._open[name] = sqlite3.connect(f"file:{self.db_paths[name]}?mode=ro", uri=True)
        return self._open[name]

    def close(self) -> None:
        for db in self._open.values():
            db.close()
        self.rules_db.close()

    def unit(self, fn: str, args: Mapping[str, Any]) -> Any:
        return _plain(reference_unit(fn, args, self.rules_db))

    def search(self, db: str, query: str, near: Optional[Sequence[float]], limit: int) -> List[Dict[str, Any]]:
        point = (near[0], near[1]) if near else None
        return [result_dict(r) for r in search.search(self.db(db), query, near=point, limit=limit)]

    def which_street(self, db: str, lat: float, lng: float) -> Optional[Dict[str, Any]]:
        return which_street_dict(search.which_street(self.db(db), lat, lng))

    def trace(self, db: str, query: str, near: Optional[Sequence[float]], limit: int) -> Dict[str, Any]:
        return trace(self.db(db), query, (near[0], near[1]) if near else None, limit)


def check(doc: Mapping[str, Any], impl: Any, available: Iterable[str]) -> Dict[str, Any]:
    """Roda os casos no porte `impl` (com os métodos de Reference; `trace` é opcional) e devolve o relatório:
    {seção: {"passed", "failed", "warned", "skipped"}, "failures": [...], "warnings": [...]}. Os casos de um banco
    fora de `available` (ausente ou de outra geração) são pulados. Caso `informative` (Unicode raro) ou `known_gap`
    (lacuna conhecida) que difere vira aviso, não falha; as etapas (`trace`) que diferem também."""
    available = set(available)
    report: Dict[str, Any] = {s: {"passed": 0, "failed": 0, "warned": 0, "skipped": 0}
                              for s in ("unit", "search", "which_street")}
    report["failures"], report["warnings"] = [], []

    def record(section: str, case: Mapping[str, Any], problems: List[str]) -> None:
        if not problems:
            report[section]["passed"] += 1
        elif case.get("informative") or case.get("known_gap"):
            report[section]["warned"] += 1
            report["warnings"].append({"id": case["id"], "problems": problems})
        else:
            report[section]["failed"] += 1
            report["failures"].append({"id": case["id"], "problems": problems})

    for case in doc["unit"]:
        try:
            record("unit", case, compare_unit(case, impl.unit(case["fn"], case["args"])))
        except Exception as e:  # noqa: BLE001 - uma função que falta ou quebra é uma falha do caso, não do verificador
            record("unit", case, [f"{case['fn']}: {e.__class__.__name__}: {e}"])
    for case in doc["search"]:
        if case["db"] not in available:
            report["search"]["skipped"] += 1
            continue
        got = impl.search(case["db"], case["query"], case.get("near"), case["limit"])
        problems = compare_search(case, got)
        record("search", case, problems)
        if problems and hasattr(impl, "trace") and "trace" in case:
            steps = compare_trace(case["trace"], impl.trace(case["db"], case["query"], case.get("near"),
                                                             case["limit"]))
            if steps:
                report["warnings"].append({"id": case["id"], "problems": ["etapas: " + s for s in steps]})
    for case in doc["which_street"]:
        if case["db"] not in available:
            report["which_street"]["skipped"] += 1
            continue
        record("which_street", case, compare_which_street(case, impl.which_street(case["db"], case["lat"],
                                                                                  case["lng"])))
    return report


def available_dbs(doc: Mapping[str, Any], db_paths: Mapping[str, Path]) -> Tuple[List[str], List[str]]:
    """(os bancos da geração do conjunto, avisos): um banco ausente ou de outra geração fica de fora."""
    ok, notes = [], []
    for name in doc["packages"]:
        path = db_paths.get(name)
        if path is None or not path.exists():
            notes.append(f"{name}: banco ausente, casos pulados")
            continue
        with closing(sqlite3.connect(f"file:{path}?mode=ro", uri=True)) as db:
            build_id = _meta(db).get("build_id")
        if build_id != doc["build_id"]:
            notes.append(f"{name}: banco da geração {build_id}, o conjunto é da {doc['build_id']}; casos pulados")
            continue
        ok.append(name)
    return ok, notes


def self_check(doc: Mapping[str, Any], db_paths: Mapping[str, Path]) -> List[str]:
    """A própria referência contra o conjunto que acabou de gerar (tem de passar inteira): os problemas."""
    ref = Reference(doc, db_paths)
    try:
        names, notes = available_dbs(doc, db_paths)
        report = check(doc, ref, names)
    finally:
        ref.close()
    problems = [f"{f['id']}: {'; '.join(f['problems'])}" for f in report["failures"]]
    problems += [f"{w['id']}: {'; '.join(w['problems'])}" for w in report["warnings"]]
    return notes + problems


# O exemplo versionado no repositório (conformidade-exemplo.json): as funções puras inteiras e alguns casos de busca
# e de "que rua é esta?" da base, de GO e do DF.
EXAMPLE_SEARCH = ("base-01", "base-04", "GO-municipio", "GO-normalizacao", "GO-erro_digitacao", "GO-prefixo",
                  "GO-numero_casa", "GO-categoria_perto", "GO-marca", "GO-lacuna", "DF-rua", "DF-frase_categoria")
EXAMPLE_WHICH_STREET = ("GO-que_rua-rua", "GO-que_rua-sem_rua")


def example(doc: Mapping[str, Any]) -> Dict[str, Any]:
    """O conjunto pequeno de exemplo, tirado do conjunto inteiro."""
    out = dict(doc)
    out["search"] = [c for c in doc["search"] if c["id"] in EXAMPLE_SEARCH]
    out["which_street"] = [c for c in doc["which_street"] if c["id"] in EXAMPLE_WHICH_STREET]
    used = {c["db"] for c in out["search"] + out["which_street"]}
    out["packages"] = {k: v for k, v in doc["packages"].items() if k in used}
    out["states"] = [s for s in doc["states"] if s in used]
    return out
