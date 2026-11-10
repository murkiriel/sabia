"""A busca de referência sobre um pacote: as regras que quem consome aplica (docs/CONSUMO.md), escritas aqui para as
travas de buscas de verdade (G7a) medirem o pacote do jeito que ele vai ser usado.

`db` é qualquer coisa com `execute(sql, params)` que devolve linhas (sqlite3.Connection ou o SQLite 3.22 da trava
G7e). Passos:

1. Dobrar o texto (sem acento, minúsculo); trocar a palavra que não está no pacote pela mais parecida (`vocab`:
   erros de digitação); tirar a expressão dispensável do começo (`word_form`, `drop_prefix`).
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
6. Sem nenhum resultado, de novo com cada palavra trocada pela vizinha mais comum ("goiana" -> "goiania").
7. Ordem: mais palavras no nome; a rua com o número da casa; do município citado; do tipo da categoria; e então uma
   nota que soma, com pesos, o casamento das palavras em ordem com o nome, o município no nome, quanto do nome a
   busca cobre, a importância (item.rank), a do município e, com `near`, a distância.
"""
from __future__ import annotations

import itertools
import math
import struct
from dataclasses import dataclass
from typing import Dict, Iterable, List, Optional, Sequence, Set, Tuple

from . import database, geo, ranks, street_lines
from .records import Item
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

# Erros de digitação: quantos aceitar pelo tamanho da palavra digitada (menos de 4 letras, nenhum), como no Organic
# Maps; a primeira letra é a mesma ou do mesmo som (ou um h mudo no começo). A troca é pela mais perto, e entre as
# mais perto pela mais comum no pacote.
SOUND_GROUPS = ["ckqszx", "gj", "iy", "uvw"]


def max_errors(length: int) -> int:
    return 0 if length < 4 else 1 if length < 8 else 2


def edit_distance(a: str, b: str) -> int:
    """Letras a mais, a menos, trocadas, ou duas vizinhas trocadas de lugar (cada uma conta 1)."""
    prev2: List[int] = []
    prev = list(range(len(b) + 1))
    for i in range(1, len(a) + 1):
        cur = [i] + [0] * len(b)
        for j in range(1, len(b) + 1):
            cost = 0 if a[i - 1] == b[j - 1] else 1
            cur[j] = min(prev[j] + 1, cur[j - 1] + 1, prev[j - 1] + cost)
            if i > 1 and j > 1 and a[i - 1] == b[j - 2] and a[i - 2] == b[j - 1]:
                cur[j] = min(cur[j], prev2[j - 2] + 1)
        prev2, prev = prev, cur
    return prev[len(b)]


def _same_sound(a: str, b: str) -> bool:
    return a == b or any(a in g and b in g for g in SOUND_GROUPS)


# Ordem, depois das palavras casadas, do número da casa, do município citado e do tipo da categoria: uma soma com
# estes pesos de notas de 0 a 1 (a ideia do modelo linear do Organic Maps, com os pesos calibrados nas buscas de
# verdade de buscas.json e nos testes):
# - W_FULL: o casamento das palavras da busca, em ordem, com o nome (name_score / 3), contando o município citado;
# - W_NAME: o mesmo sem as palavras do município citado ("rodoviaria de goiania" -> "Rodoviária de Campinas");
# - W_MUNICIPALITY: quanto do nome do município citado está no nome do registro;
# - W_COVER: quanto do nome a busca cobre (o nome comercial comprido, "Pet shop - banho e tosa - Jardim América", vale
#   menos que o bairro "Jardim América");
# - W_RANK: a importância (item.rank / 255);
# - W_PLACE: a importância do município do registro (das duas "Praça Cívica", a da capital);
# - W_DISTANCE: a perto, pelo logaritmo da distância (1 km e 10 km valem bem diferente; 500 e 600 km, quase igual),
#   zero a MAX_DISTANCE_KM ou mais.
# Só a categoria, com a posição: quantos quadrados em volta, um anel de cada vez, até achar `limit` registros.
CATEGORY_RINGS = (1, 2, 4)
W_FULL = 0.2
W_NAME = 0.4
W_MUNICIPALITY = 0.1
W_COVER = 0.2
W_RANK = 1.0
W_PLACE = 0.2
W_DISTANCE = 1.5
MAX_DISTANCE_KM = 2000.0


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
        self.db = db
        self.has_vocab = _has_table(db, "vocab")
        # pacote anterior sem item.rank: a importância sai do tipo (ranks.rank), sem a população
        has_rank = any(r[1] == "rank" for r in db.execute("PRAGMA table_info(item)"))
        self.columns = ITEM_COLUMNS + (", i.rank" if has_rank else ", -1")
        self.municipality_rank: Dict[int, int] = (
            dict(db.execute("SELECT municipality, rank FROM item WHERE kind = 'municipality'")) if has_rank else {})
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
        # palavras que a busca entende sem estar nos nomes: nunca são "corrigidas" e servem de candidatas
        self.known: Set[str] = set(self.categories) | set(self.alternatives) | STOPWORDS | HOUSE_NUMBER_CONNECTORS
        self.known |= {f for forms in self.alternatives.values() for f, _ in forms} | NAME_NUMBER_WORDS
        self.known |= {w for phrase in self.drop for w in phrase.split()}

    def correct_words(self, words: Sequence[str], force: bool = False) -> List[str]:
        return [self.correct(w, n == len(words) - 1, force) for n, w in enumerate(words)]

    def _in_vocab(self, word: str, prefix: bool) -> bool:
        if word in self.known or (prefix and any(k.startswith(word) for k in self.known)):
            return True
        if prefix:
            return bool(list(self.db.execute("SELECT 1 FROM vocab WHERE word >= ? AND word < ? LIMIT 1",
                                             (word, word + "{"))))
        return bool(list(self.db.execute("SELECT 1 FROM vocab WHERE word = ?", (word,))))

    def _candidates(self, word: str, k: int, prefix: bool) -> List[Tuple[str, int]]:
        """(palavra, registros) do pacote e das tabelas de busca que começam por uma letra do mesmo som, com o tamanho
        perto o bastante (a palavra digitada pela metade é comparada com o começo das outras)."""
        letters = next((g for g in SOUND_GROUPS if word[0] in g), word[0])
        low, high = len(word) - k, len(word) + k
        out: List[Tuple[str, int]] = []
        for first in letters:
            for start in (first, "h" + first):
                params = (start, start[:-1] + chr(ord(start[-1]) + 1), low + len(start) - 1,
                          10 ** 6 if prefix else high + len(start) - 1)
                out += list(self.db.execute("SELECT word, n FROM vocab WHERE word >= ? AND word < ? "
                                            "AND length(word) BETWEEN ? AND ?", params))
        out += [(w, 0) for w in self.known if w and _same_sound(w[0], word[0]) and (prefix or low <= len(w) <= high)]
        return out

    def correct(self, word: str, prefix: bool, force: bool = False) -> str:
        """A palavra digitada, ou a mais parecida do pacote se ela não existe nele (ver max_errors e SOUND_GROUPS).
        Com `prefix` (a última palavra, ainda sendo digitada), vale o começo de uma palavra. Com `force` (a busca não
        achou nada), também a palavra que existe no pacote vira a vizinha mais comum, menos as das tabelas de busca."""
        k = max_errors(len(word))
        if not self.has_vocab or k == 0 or not word.isalpha():
            return word
        if (word in self.known) if force else self._in_vocab(word, prefix):
            return word
        best: Optional[Tuple[int, int, bool, str]] = None
        for cand, n in self._candidates(word, k, prefix):
            bare = cand[1:] if cand[0] == "h" and word[0] != "h" else cand
            lengths = range(max(1, len(word) - 1), len(word) + 2) if prefix else [len(bare)]
            for length in lengths:
                piece = bare[:length]
                if not _same_sound(piece[0], word[0]):
                    continue
                d = edit_distance(word, piece)
                if d <= k:
                    chosen = cand[:length + (len(cand) - len(bare))] if prefix else cand
                    if force and (chosen == word or cand == word):
                        continue
                    if force:  # a vizinha mais comum, não a mais perto (a mais perto é a própria palavra)
                        d = 0
                    # no empate, a palavra inteira (diz o município: "goiana" -> "goiania", não "goiani")
                    option = (d, -n, chosen != cand, chosen)
                    if best is None or option < best:
                        best = option
        return best[3] if best else word

    def options(self, word: str, last: bool) -> List[Tuple[str, bool]]:
        """(termo, inteiro?) de uma palavra digitada: ela mesma e as alternativas. Número e letra solta valem
        inteiros, menos na última palavra (quem digita ainda não terminou)."""
        own = (word, (word.isdigit() or len(word) == 1) and not last)
        others = sorted(a for a in self.alternatives.get(word, set()) if a[0] and a[0] != word)
        return [own] + [(a, exact or ((a.isdigit() or len(a) == 1) and not last)) for a, exact in others]


def _has_table(db, name: str) -> bool:
    return bool(list(db.execute("SELECT 1 FROM sqlite_master WHERE name = ?", (name,))))


def _parse(rules: _Rules, folded: str) -> Tuple[List[str], List[str], Optional[int], Set[str], List[str]]:
    """(palavras de texto, tipos da categoria, município citado, palavras do nome dele, todas as palavras sem as
    vazias, na ordem)."""
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
    return text, kinds, target, mun_words, words


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
    folded = " ".join(rules.correct_words(fold(query).split()))
    text, kinds, _, _, _ = _parse(rules, folded)
    out = _combinations(rules, text) if text else []
    if kinds:
        out += _combinations(rules, text + [w for w in folded.split() if w in rules.categories][:1])
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


def _token_match(rules: _Rules, word: str, token: str, last: bool) -> int:
    """2 a palavra (ou uma alternativa) é a do nome; 1 é o começo dela (prefixo); 0 nada."""
    best = 0
    for a, exact in rules.options(word, last):
        if token == a:
            return 2
        if not exact and token.startswith(a):
            best = 1
    return best


def name_score(rules: _Rules, words: Sequence[str], name: str, prefix_last: bool = True) -> int:
    """Como as palavras da busca, em ordem, casam com o nome (sem as palavras vazias): 3 o nome é a busca, palavra
    por palavra inteira; 2 o nome começa com ela; 1 ela está no meio do nome; 0 o resto (palavras soltas)."""
    tokens = [t for t in fold(name).split() if t not in STOPWORDS]
    best = 0
    for start in range(0, len(tokens) - len(words) + 1 if words else 0):
        found = [_token_match(rules, w, tokens[start + j], prefix_last and j == len(words) - 1)
                 for j, w in enumerate(words)]
        if all(found):
            if start > 0:
                best = max(best, 1)
            elif len(words) == len(tokens) and all(m == 2 for m in found):
                return 3
            else:
                best = 2
    return best


def name_cover(rules: _Rules, words: Sequence[str], name: str, prefix_last: bool = True) -> float:
    """A fração das palavras do nome (sem as vazias) que alguma palavra da busca casa."""
    tokens = [t for t in fold(name).split() if t not in STOPWORDS]
    if not tokens:
        return 0.0
    hit = sum(1 for t in tokens if any(_token_match(rules, w, t, prefix_last and n == len(words) - 1)
                                       for n, w in enumerate(words)))
    return hit / len(tokens)


def _closeness(meters: float) -> float:
    """1 no ponto, 0 a MAX_DISTANCE_KM ou mais, pelo logaritmo da distância."""
    return 1.0 - min(1.0, math.log10(1.0 + meters / 1000.0) / math.log10(1.0 + MAX_DISTANCE_KM))


def _rows(db, sql: str, params: Iterable) -> List[tuple]:
    return list(db.execute(sql, tuple(params)))


ITEM_COLUMNS = "i.id, i.cls, i.kind, i.name, i.municipality, i.district, i.lat, i.lng"


def corrected(db, query: str) -> str:
    """A busca dobrada com cada palavra que não está no pacote trocada pela mais parecida (a última, ainda sendo
    digitada, pelo começo de uma palavra)."""
    return " ".join(_Rules(db).correct_words(fold(query).split()))


def search(db, query: str, near: Optional[Tuple[float, float]] = None, limit: int = 10) -> List[Result]:
    rules = _Rules(db)
    words = fold(query).split()
    # cada palavra que não está no pacote, trocada pela mais parecida (erro de digitação); daqui em diante, só esta
    folded = " ".join(rules.correct_words(words))
    found = _search(db, rules, folded, near, limit)
    if not found and rules.has_vocab:
        # nada: o erro pode ter dado outra palavra do pacote ("goiana" por "goiania"); de novo, com a vizinha mais comum
        forced = " ".join(rules.correct_words(words, force=True))
        if forced != folded:
            found = _search(db, rules, forced, near, limit)
    return found


def _search(db, rules: _Rules, folded: str, near: Optional[Tuple[float, float]], limit: int) -> List[Result]:
    text, kinds, target, mun_words, all_words = _parse(rules, folded)
    columns = rules.columns
    found: Dict[int, tuple] = {}
    for match in (_combinations(rules, text) if text else []):
        for row in _rows(db, f"SELECT {columns} FROM item_text JOIN item i ON i.id = item_text.docid "
                             f"WHERE item_text MATCH ? LIMIT {MAX_ROWS}", [match]):
            found[row[0]] = row
    # O número da casa ("rua 10 152"): as ruas com as outras palavras; as palavras da rua já estão completas quando o
    # número fecha a busca. Quem tem o número na escada vem antes, no ponto dele.
    house_number = house_number_in(text)
    prefix_last = True
    if house_number is not None:
        text = house_number[1]
        prefix_last = not folded.split()[-1].isdigit()
        for match in _combinations(rules, text, prefix_last):
            for row in _rows(db, f"SELECT {columns} FROM item_text JOIN item i ON i.id = item_text.docid "
                                 f"WHERE item_text MATCH ? AND i.cls = 'street' LIMIT {MAX_ROWS}", [match]):
                found[row[0]] = row
    if kinds:
        marks = ",".join("?" * len(kinds))
        if text:
            # a categoria também pode ser parte do nome ("Posto Cerrado"): as duas buscas valem
            category_word = next(w for w in folded.split() if w in rules.categories)
            for match in _combinations(rules, text + [category_word]):
                for row in _rows(db, f"SELECT {columns} FROM item_text JOIN item i ON i.id = item_text.docid "
                                     f"WHERE item_text MATCH ? LIMIT {MAX_ROWS}", [match]):
                    found[row[0]] = row
            for match in _combinations(rules, text):
                for row in _rows(db, f"SELECT {columns} FROM item_text JOIN item i ON i.id = item_text.docid "
                                     f"WHERE item_text MATCH ? AND i.kind IN ({marks}) LIMIT {MAX_ROWS}",
                                 [match, *kinds]):
                    found[row[0]] = row
        else:
            sql = f"SELECT {columns} FROM item i WHERE i.kind IN ({marks})"
            if near is None:
                for row in _rows(db, sql + f" LIMIT {MAX_ROWS}", kinds):
                    found[row[0]] = row
            else:
                # os quadrados em volta, abrindo a vizinhança (3x3, 5x5, 9x9: até ~20 km) até achar o bastante
                for ring in CATEGORY_RINGS:
                    cells = _cells_around(*near, ring=ring)
                    for row in _rows(db, sql + f" AND i.cell IN ({','.join('?' * len(cells))}) LIMIT {MAX_ROWS}",
                                     [*kinds, *cells]):
                        found[row[0]] = row
                    if len(found) >= limit:
                        break

    # Só a categoria ("posto") com a posição: a busca é por perto; o nome não conta (o posto sem nome ao lado vem
    # antes do "Posto Central" a 1 km)
    only_category = bool(kinds) and not text and near is not None
    category_words = [] if only_category else [w for w in folded.split() if w in rules.categories][:1]
    # O nome do município citado é palavra de área: não conta no nome de um registro ("Farmácia Central Goiânia"
    # não passa na frente do bairro Setor Central), a não ser que a busca seja só ele ("goiania", "rio verde").
    only_municipality = bool(text) and not kinds and all(w in mun_words for w in text)
    counted = text if only_municipality else [w for w in text if w not in mun_words]
    last_word = text[-1] if text and prefix_last else ""
    # as palavras para o casamento com o nome: as da busca, na ordem, sem o número da casa; sem as do município
    # citado, a não ser que o nome as tenha ("Universidade de Brasília - Campus Planaltina" para "universidade de
    # brasilia")
    full_words = (house_number_in(all_words) or (0, all_words))[1]
    in_name = [w for w in full_words if only_municipality or w not in mun_words]

    def hits_of(row: tuple) -> int:
        kind, name = row[2], row[3]
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

    def name_scores(name: str) -> Tuple[int, int]:
        """(casamento com as palavras todas, casamento sem as do município citado); "posto ipiranga": o posto chamado
        só "Ipiranga" casa o nome inteiro sem "posto" (só o nome inteiro: "Universidade Católica de Brasília" não
        ganha por "brasilia" sem "universidade")."""
        if only_category:
            return 0, 0
        out = []
        for words in (full_words, in_name):
            score = name_score(rules, words, name, prefix_last)
            if category_words and name_score(rules, [w for w in words if w not in category_words], name,
                                             prefix_last) == 3:
                score = 3
            out.append(score)
        return out[0], out[1]

    def key(row: tuple):
        rid, cls, kind, name, mun, _, lat, lng, rank = row
        if rank < 0:
            rank = ranks.rank(Item(cls, kind, name, str(mun), 0.0, 0.0))
        mun_hits = 0 if only_municipality else _name_hits(rules, sorted(mun_words), name, last_word)
        full, partial = name_scores(name)
        weight = (W_FULL * full / 3 + W_NAME * partial / 3 + W_RANK * rank / ranks.MAX_RANK
                  + W_PLACE * rules.municipality_rank.get(mun, 0) / ranks.MAX_RANK
                  + (W_MUNICIPALITY * mun_hits / len(mun_words) if mun_words else 0.0)
                  + (0.0 if only_category else W_COVER * name_cover(rules, full_words, name, prefix_last)))
        if near is not None:
            weight += W_DISTANCE * _closeness(geo.dist_m(lat / database.SCALE, lng / database.SCALE, *near))
        # fora do município citado vai para baixo, a não ser que o nome tenha as palavras dele ("avenida anapolis" é
        # também a Avenida Anápolis de Goiânia)
        elsewhere = bool(target) and mun != target and mun_hits < len(mun_words)
        return (-hits[rid], rid not in houses, elsewhere, kind not in kinds if kinds else False, -round(weight, 9),
                len(name), rid)

    ordered = sorted(found.values(), key=key)[:limit]
    out = []
    for rid, cls, kind, name, mun, district, lat, lng, _ in ordered:
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


def _cells_around(lat: float, lng: float, ring: int = 1) -> List[int]:
    """O quadrado do ponto e os `ring` quadrados em volta em cada direção (1: os 9; 2: os 25)."""
    n = 1 << geo.CELL_ZOOM
    x, y = divmod(geo.cell(lat, lng), n)
    return [(x + dx) * n + (y + dy) for dx in range(-ring, ring + 1) for dy in range(-ring, ring + 1)]


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
