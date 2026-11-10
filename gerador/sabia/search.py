"""A busca de referência sobre um pacote: as regras que quem consome aplica (docs/CONSUMO.md), escritas aqui para as
travas de buscas de verdade (G7a) medirem o pacote do jeito que ele vai ser usado.

`db` é qualquer coisa com `execute(sql, params)` que devolve linhas (sqlite3.Connection ou o SQLite 3.22 da trava
G7e). Passos:

1. Dobrar o texto (sem acento, minúsculo); tirar a expressão dispensável do começo (`word_form`, `drop_prefix`).
2. Achar o município citado: a sequência de palavras que é o nome inteiro de um município (o mais longo) puxa os
   registros dele para cima.
3. Tirar as palavras vazias ("de", "da", "do", "dos", "das", "e").
4. Palavras de categoria (`category`) viram filtro de `kind`; as outras casam no texto.
5. Cada palavra vira alternativas: ela mesma, as abreviações nos dois sentidos, a outra forma e o número por extenso
   (`word_form`; este, só inteiro). O último número depois de outra palavra pode ser o número da casa ("rua 10 152"):
   as ruas com as outras palavras também entram, e a que tem o número na escada (`house_number`) vem antes, no ponto
   dele. Uma MATCH por combinação de alternativas, só com AND implícito (nunca OR: a precedência dele muda
   entre a sintaxe padrão e a estendida do FTS), juntadas por UNION. Toda palavra é prefixo (`termo*`), menos número e
   letra solta, que valem inteiros, exceto a última (quem digita ainda não terminou).
6. Ordem: mais palavras no nome; do município citado; do tipo da categoria; classe (município e cidade, vila e
   bairro, rua, rodovia, ponto de interesse); o mais perto (com `near`) ou o nome mais curto.
"""
from __future__ import annotations

import itertools
import math
import struct
from dataclasses import dataclass
from typing import Dict, Iterable, List, Optional, Sequence, Set, Tuple

from . import database, geo, kinds as osm_kinds, street_lines
from .text import fold

STOPWORDS = {"de", "da", "do", "dos", "das", "e"}
MAX_COMBINATIONS = 16
MAX_ROWS = 2000
# "Que rua é esta?": mais longe que isto do traçado mais próximo, não há rua.
MAX_STREET_DISTANCE_M = 75.0

# Número da casa: o último número da busca, depois de outra palavra, é o número da casa ("rua 10, 152, setor oeste"),
# a não ser que venha logo depois de uma palavra que leva número no nome ("rua 14", "quadra 3", "km 120", "br 153") ou
# de uma letra solta ("avenida t 63"). "n", "nº", "nr", "num" e "numero" antes dele saem junto.
NAME_NUMBER_WORDS = {
    "rua", "r", "avenida", "av", "avda", "alameda", "al", "travessa", "tv", "trav", "quadra", "qd", "lote", "lt",
    "bloco", "bl", "conjunto", "conj", "km", "rodovia", "rod", "estrada", "est", "estr", "setor", "st", "etapa",
    "modulo", "area", "linha", "vicinal", "ramal", "via", "praca", "pca", "pc", "viela", "beco", "galeria", "casa",
    "residencial", "res", "chacara", "chac", "gleba", "ladeira", "acesso", "marginal", "anel", "vila", "vl", "jardim",
    "jd", "parque", "pq", "lago", "eixo", "trecho", "nucleo", "colonia", "loteamento", "condominio", "cond", "br",
    "ac", "al", "ap", "am", "ba", "ce", "df", "es", "go", "ma", "mt", "ms", "mg", "pa", "pb", "pr", "pe", "pi", "rj",
    "rn", "rs", "ro", "rr", "sc", "sp", "se", "to",
}
HOUSE_NUMBER_CONNECTORS = {"n", "no", "nr", "num", "numero"}
MAX_HOUSE_NUMBER = 99999

CLASS_RANK = {"municipality": 0, "place=city": 0, "place=town": 0, "place=village": 1, "place=suburb": 1,
              "place=neighbourhood": 1, "place=quarter": 1}
CLS_RANK = {"place": 2, "street": 2, "road": 3, "poi": 4}


@dataclass
class Result:
    id: int
    cls: str
    kind: str
    name: str
    municipality: str
    district: Optional[str]
    lat: float
    lng: float
    distance_m: Optional[float] = None
    house_number: Optional[int] = None

    @property
    def label(self) -> str:
        """'Rua 10, Setor Oeste, Goiânia'."""
        parts = [self.name or self.kind]
        if self.house_number is not None:
            parts.append(str(self.house_number))
        parts += [p for p in (self.district, self.municipality) if p and p != self.name]
        return ", ".join(parts)


class _Rules:
    """As tabelas de busca do pacote, lidas uma vez."""

    def __init__(self, db) -> None:
        # palavra -> {(alternativa, só a palavra inteira?)}
        self.alternatives: Dict[str, Set[Tuple[str, bool]]] = {}
        self.drop: List[str] = []
        for word, form, rule in db.execute("SELECT word, form, rule FROM word_form"):
            if rule == "drop_prefix":
                self.drop.append(word)
                continue
            # o número por extenso vale só inteiro: "10" casa com "dez", nunca com o começo de "dezesseis"
            self.alternatives.setdefault(word, set()).add((form, rule == "number"))
            if rule == "abbr":  # nos dois sentidos; a abreviação no nome vale só inteira ("St.", nunca "Styles")
                self.alternatives.setdefault(form, set()).add((word, True))
        self.categories = {w: k.split(",") for w, k in db.execute("SELECT word, kinds FROM category")}
        self.municipalities = {fold(name): (mid, name)
                               for mid, name in db.execute("SELECT id, name FROM municipality")}
        self.names = {mid: name for _, (mid, name) in self.municipalities.items()}
        self.districts: Dict[int, str] = (dict(db.execute("SELECT id, name FROM district"))
                                          if _has_table(db, "district") else {})

    def options(self, word: str, last: bool) -> List[Tuple[str, bool]]:
        """(termo, inteiro?) de uma palavra digitada: ela mesma e as alternativas. Número e letra solta valem
        inteiros, menos na última palavra (quem digita ainda não terminou)."""
        own = (word, (word.isdigit() or len(word) == 1) and not last)
        others = sorted(a for a in self.alternatives.get(word, set()) if a[0] and a[0] != word)
        return [own] + [(a, exact or ((a.isdigit() or len(a) == 1) and not last)) for a, exact in others]


def _has_table(db, name: str) -> bool:
    return bool(list(db.execute("SELECT 1 FROM sqlite_master WHERE name = ?", (name,))))


def _parse(rules: _Rules, query: str) -> Tuple[List[str], List[str], Optional[int], Set[str]]:
    """(palavras de texto, tipos da categoria, município citado, palavras do nome dele)."""
    folded = fold(query)
    for prefix in sorted(rules.drop, key=len, reverse=True):
        if folded.startswith(prefix + " "):
            folded = folded[len(prefix) + 1:]
            break
    words = folded.split()
    # o município citado fecha a busca ("rua 90 goiania", "rua 10 aparecida de goiania"); o nome mais longo vence.
    # No meio da busca, o nome de um município é só palavra ("avenida anhanguera goiania": Anhanguera também é
    # município)
    target = None
    mun_words: Set[str] = set()
    for i in range(len(words)):
        phrase = " ".join(words[i:])
        if phrase in rules.municipalities:
            target, mun_words = rules.municipalities[phrase][0], set(words[i:])
            break
    words = [w for w in words if w not in STOPWORDS] or words
    kinds: List[str] = []
    text: List[str] = []
    for w in words:
        if w in rules.categories and not kinds:
            kinds = rules.categories[w]
        else:
            text.append(w)
    return text, kinds, target, mun_words


def house_number_in(words: Sequence[str]) -> Optional[Tuple[int, List[str]]]:
    """(número da casa, as palavras sem ele e sem o "n"/"numero" antes dele), ou None se a busca não traz um."""
    for i in range(len(words) - 1, 0, -1):
        if not words[i].isdigit():
            continue
        start = i - 1 if words[i - 1] in HOUSE_NUMBER_CONNECTORS else i
        before = words[start - 1] if start >= 1 else ""
        number = int(words[i])
        if (start == i and (before in NAME_NUMBER_WORDS or (len(before) == 1 and not before.isdigit()))) \
                or not before or not 0 < number <= MAX_HOUSE_NUMBER:
            return None
        return number, list(words[:start]) + list(words[i + 1:])
    return None


def _combinations(rules: _Rules, words: Sequence[str], prefix_last: bool = True) -> List[str]:
    options = []
    for n, w in enumerate(words):
        options.append([a if exact else a + "*" for a, exact in rules.options(w, prefix_last and n == len(words) - 1)])
    out = []
    for combo in itertools.islice(itertools.product(*options), MAX_COMBINATIONS):
        out.append(" ".join(combo))
    return out


def match_strings(db, query: str) -> List[str]:
    """As MATCH que a busca faria (para conferir que nenhuma mistura OR e AND)."""
    rules = _Rules(db)
    text, kinds, _, _ = _parse(rules, query)
    out = _combinations(rules, text) if text else []
    if kinds:
        out += _combinations(rules, text + [w for w in fold(query).split() if w in rules.categories][:1])
    return out


def _name_hits(rules: _Rules, words: Sequence[str], name: str, last_word: str = "") -> int:
    """Quantas palavras da busca casam com uma palavra do nome (com as alternativas)."""
    tokens = database.index_text(name).split()
    hits = 0
    for w in words:
        for a, exact in rules.options(w, w == last_word):
            if any(t == a if exact else t.startswith(a) for t in tokens):
                hits += 1
                break
    return hits


def _rows(db, sql: str, params: Iterable) -> List[tuple]:
    return list(db.execute(sql, tuple(params)))


ITEM_COLUMNS = "i.id, i.cls, i.kind, i.name, i.municipality, i.district, i.lat, i.lng"


def search(db, query: str, near: Optional[Tuple[float, float]] = None, limit: int = 10) -> List[Result]:
    rules = _Rules(db)
    text, kinds, target, mun_words = _parse(rules, query)
    found: Dict[int, tuple] = {}
    for match in (_combinations(rules, text) if text else []):
        for row in _rows(db, f"SELECT {ITEM_COLUMNS} FROM item_text JOIN item i ON i.id = item_text.docid "
                             f"WHERE item_text MATCH ? LIMIT {MAX_ROWS}", [match]):
            found[row[0]] = row
    # O número da casa ("rua 10 152"): as ruas com as outras palavras; as palavras da rua já estão completas quando o
    # número fecha a busca. Quem tem o número na escada vem antes, no ponto dele.
    house_number = house_number_in(text)
    prefix_last = True
    if house_number is not None:
        text = house_number[1]
        prefix_last = not fold(query).split()[-1].isdigit()
        for match in _combinations(rules, text, prefix_last):
            for row in _rows(db, f"SELECT {ITEM_COLUMNS} FROM item_text JOIN item i ON i.id = item_text.docid "
                                 f"WHERE item_text MATCH ? AND i.cls = 'street' LIMIT {MAX_ROWS}", [match]):
                found[row[0]] = row
    if kinds:
        marks = ",".join("?" * len(kinds))
        if text:
            # a categoria também pode ser parte do nome ("Posto Cerrado"): as duas buscas valem
            category_word = next(w for w in fold(query).split() if w in rules.categories)
            for match in _combinations(rules, text + [category_word]):
                for row in _rows(db, f"SELECT {ITEM_COLUMNS} FROM item_text JOIN item i ON i.id = item_text.docid "
                                     f"WHERE item_text MATCH ? LIMIT {MAX_ROWS}", [match]):
                    found[row[0]] = row
            for match in _combinations(rules, text):
                for row in _rows(db, f"SELECT {ITEM_COLUMNS} FROM item_text JOIN item i ON i.id = item_text.docid "
                                     f"WHERE item_text MATCH ? AND i.kind IN ({marks}) LIMIT {MAX_ROWS}",
                                 [match, *kinds]):
                    found[row[0]] = row
        else:
            sql = f"SELECT {ITEM_COLUMNS} FROM item i WHERE i.kind IN ({marks})"
            params: List[object] = list(kinds)
            if near is not None:
                cells = _cells_around(*near)
                sql += f" AND i.cell IN ({','.join('?' * len(cells))})"
                params += cells
            for row in _rows(db, sql + f" LIMIT {MAX_ROWS}", params):
                found[row[0]] = row

    category_words = [w for w in fold(query).split() if w in rules.categories][:1]
    # O nome do município citado é palavra de área: não conta no nome de um registro ("Farmácia Central Goiânia"
    # não passa na frente do bairro Setor Central), a não ser que a busca seja só ele ("goiania", "rio verde").
    only_municipality = bool(text) and not kinds and all(w in mun_words for w in text)
    counted = text if only_municipality else [w for w in text if w not in mun_words]
    last_word = text[-1] if text and prefix_last else ""

    def hits_of(row: tuple) -> int:
        _, _, kind, name, _, _, _, _ = row
        hits = _name_hits(rules, counted, name, last_word)
        # a categoria conta pelo tipo e de novo se a palavra (ou a outra forma dela) estiver no nome
        return hits + int(kind in kinds) + (_name_hits(rules, category_words, name) if category_words else 0)

    hits = {rid: hits_of(row) for rid, row in found.items()}
    houses: Dict[int, Tuple[float, float]] = {}
    if house_number is not None:
        # a escada só das ruas com mais palavras casadas (as outras não passariam na frente por causa do número)
        best = max((hits[rid] for rid, row in found.items() if row[1] == "street"), default=None)
        for rid, row in found.items():
            if row[1] == "street" and hits[rid] == best:
                point = house_position(db, rid, house_number[0])
                if point is not None:
                    houses[rid] = point

    def key(row: tuple):
        rid, cls, kind, name, mun, _, lat, lng = row
        rank = CLASS_RANK.get(kind, CLS_RANK.get(cls, 4))
        importance = osm_kinds.HIGHWAY_RANK.get(kind.removeprefix("highway="), 99) if cls == "street" else 0
        far = geo.dist_m(lat / database.SCALE, lng / database.SCALE, *near) if near else float(len(name))
        # o nome do município no nome do registro só desempata, depois da classe ("shopping goiania")
        mun_hits = 0 if only_municipality else _name_hits(rules, sorted(mun_words), name, last_word)
        return (-hits[rid], rid not in houses, mun != target if target else False,
                kind not in kinds if kinds else False, rank, importance, -mun_hits, far, rid)

    ordered = sorted(found.values(), key=key)[:limit]
    out = []
    for rid, cls, kind, name, mun, district, lat, lng in ordered:
        r = Result(rid, cls, kind, name, rules.names.get(mun, str(mun)), rules.districts.get(district),
                   lat / database.SCALE, lng / database.SCALE)
        if rid in houses:
            r.lat, r.lng = houses[rid]
            r.house_number = house_number[0] if house_number else None
        if near is not None:
            r.distance_m = geo.dist_m(r.lat, r.lng, *near)
        out.append(r)
    return out


def house_position(db, street: int, number: int) -> Optional[Tuple[float, float]]:
    """O ponto do número na escada do CNEFE da rua (tabela house_number), ou None se nenhum pedaço do lado do número
    o cerca: um degrau com o número, ou a interpolação entre os dois degraus do mesmo pedaço que o cercam."""
    if number <= 0 or not _has_table(db, "house_number"):
        return None
    row = next(iter(db.execute("SELECT rungs FROM house_number WHERE street = ?", (street,))), None)
    if row is None:
        return None
    flat = struct.unpack(f"<{len(row[0]) // 4}i", row[0])
    side = number % 2
    pieces: Dict[int, List[Tuple[int, int, int]]] = {}
    for k in range(0, len(flat), 5):
        if flat[k] == side:
            pieces.setdefault(flat[k + 1], []).append((flat[k + 2], flat[k + 3], flat[k + 4]))
    for _, rungs in sorted(pieces.items()):
        rungs.sort()
        for (n1, lat1, lng1), (n2, lat2, lng2) in zip(rungs, rungs[1:] + rungs[-1:]):
            if n1 == number:
                return lat1 / database.SCALE, lng1 / database.SCALE
            if n1 < number < n2:
                t = (number - n1) / (n2 - n1)
                return (lat1 + t * (lat2 - lat1)) / database.SCALE, (lng1 + t * (lng2 - lng1)) / database.SCALE
    return None


def _cells_around(lat: float, lng: float) -> List[int]:
    n = 1 << geo.CELL_ZOOM
    x, y = divmod(geo.cell(lat, lng), n)
    return [(x + dx) * n + (y + dy) for dx in (-1, 0, 1) for dy in (-1, 0, 1)]


def which_street(db, lat: float, lng: float) -> Optional[Result]:
    """"Que rua é esta?": a rua (ou rodovia) do traçado mais perto do ponto, nos 9 quadrados em volta; None se a
    mais perta passa de MAX_STREET_DISTANCE_M."""
    cells = _cells_around(lat, lng)
    best, best_d = None, math.inf
    for item, coords in _rows(db, f"SELECT item, coords FROM street_line WHERE cell IN "
                                  f"({','.join('?' * len(cells))})", cells):
        d = street_lines.distance_to_line(lat, lng, street_lines.decode(bytes(coords)))
        if d < best_d:
            best, best_d = item, d
    if best is None or best_d > MAX_STREET_DISTANCE_M:
        return None
    rules = _Rules(db)
    ((rid, cls, kind, name, mun, district, ilat, ilng),) = _rows(
        db, f"SELECT {ITEM_COLUMNS} FROM item i WHERE i.id = ?", [best])
    return Result(rid, cls, kind, name, rules.names.get(mun, str(mun)), rules.districts.get(district),
                  ilat / database.SCALE, ilng / database.SCALE, distance_m=best_d)
