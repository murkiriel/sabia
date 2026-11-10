"""O mesmo lugar duas vezes vira um registro só, no fim da junção das fontes (build, antes dos bairros).

As fontes já não repetem o que encontram registrado (merge.add), mas sobra o que nenhuma regra de fonte pega: o ponto
e a área do mesmo lugar no OpenStreetMap, e o nome escrito de outro jeito ("Rodoviária do Plano Piloto",
"Rodoviaria do Plano Piloto" e "Rodoviria do Plano Piloto", a 40 m uma da outra, no DF de 2026-10).

- **Quem**: pontos de interesse e lugares (nunca ruas e rodovias) do mesmo `kind`, a até DUPLICATE_M, com o mesmo
  nome (same_name; palavras de direção e lado, DISTINCT_WORDS, só iguais).
- **Quem fica**: o do mapa antes do de outra fonte (Overture, e o posto que só a ANP tinha, de posição não
  conferida); no empate, o nome com acento ("Rodoviária" antes de "Rodoviaria") e o primeiro na ordem da geração.
  Os nomes dos outros viram nomes alternativos dele (só no índice de busca), e a ordem dos registros não muda.
"""
from __future__ import annotations

from typing import Dict, List

from . import geo, merge
from .records import Item
from .search import edit_distance, max_errors
from .text import fold

DUPLICATE_M = 150.0
# Palavras que distinguem dois lugares vizinhos de nome quase igual: só valem iguais, sem erro de digitação ("oeste" e
# "leste" diferem numa letra; "EPDB, km 24 oeste" e "... leste" são as paradas dos dois lados da pista).
DISTINCT_WORDS = {"norte", "sul", "leste", "oeste", "nordeste", "noroeste", "sudeste", "sudoeste", "entrada", "saida",
                  "centro", "ida", "volta", "superior", "inferior", "alto", "baixo", "novo", "nova", "velho", "velha",
                  "interno", "externo", "interna", "externa"}


def _tokens(name: str) -> List[str]:
    return [w for w in fold(name).split() if w not in merge._FILLER]


def same_name(a: str, b: str) -> bool:
    """O mesmo nome, palavra por palavra (sem artigo, preposição nem "Ltda"): iguais, ou, nas palavras só de letras
    com 4 ou mais, com os erros de digitação da busca (search.max_errors). Número e letra solta têm de ser iguais
    ("Bloco A" não é "Bloco B")."""
    ta, tb = _tokens(a), _tokens(b)
    if not ta or len(ta) != len(tb):
        return False
    for x, y in zip(ta, tb):
        if x == y:
            continue
        if not (x.isalpha() and y.isalpha() and min(len(x), len(y)) >= 4) or x in DISTINCT_WORDS \
                or y in DISTINCT_WORDS:
            return False
        if edit_distance(x, y) > max_errors(max(len(x), len(y))):
            return False
    return True


def _priority(item: Item, position: int):
    """O do mapa; depois o nome escrito com acento ("Rodoviária" antes de "Rodoviaria"); depois a ordem."""
    return (item.origin != "", item.source != "", -sum(1 for c in item.name if ord(c) > 127), position)


def collapse(items: Dict[str, List[Item]]) -> int:
    """Junta os repetidos de cada estado (em `items`, por UF); devolve quantos registros saíram."""
    removed_total = 0
    for state, state_items in items.items():
        candidates = [(n, it) for n, it in enumerate(state_items) if it.cls in ("poi", "place") and it.name.strip()]
        grid = merge._Grid(DUPLICATE_M)
        position = {}
        for n, it in candidates:
            grid.put(it)
            position[id(it)] = n
        parent = {id(it): id(it) for _, it in candidates}

        def find(x: int) -> int:
            while parent[x] != x:
                parent[x] = parent[parent[x]]
                x = parent[x]
            return x

        for n, it in candidates:
            for other in grid.near(it.lat, it.lng):
                if other is it or position[id(other)] < n or other.kind != it.kind:
                    continue
                if geo.dist_m(it.lat, it.lng, other.lat, other.lng) <= DUPLICATE_M and same_name(it.name, other.name):
                    ra, rb = find(id(it)), find(id(other))
                    if ra != rb:
                        parent[max(ra, rb, key=lambda r: position[r])] = min(ra, rb, key=lambda r: position[r])
        groups: Dict[int, List[Item]] = {}
        for _, it in candidates:
            groups.setdefault(find(id(it)), []).append(it)
        removed = set()
        for group in groups.values():
            if len(group) < 2:
                continue
            keeper = min(group, key=lambda it: _priority(it, position[id(it)]))
            known = {fold(keeper.name)} | {fold(a) for a in keeper.aliases}
            for it in sorted(group, key=lambda it: position[id(it)]):
                if it is keeper:
                    continue
                removed.add(id(it))
                for name in [it.name, *it.aliases]:
                    if len(keeper.aliases) < merge.MAX_ALIASES and fold(name) not in known:
                        known.add(fold(name))
                        keeper.aliases.append(name)
        items[state] = [it for it in state_items if id(it) not in removed]
        removed_total += len(removed)
    return removed_total
