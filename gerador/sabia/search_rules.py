"""As tabelas de busca que vão dentro de cada pacote (decisão D8): quem consome lê daqui, e uma regra nova melhora a
busca sem trocar o código de quem consome.

`word_form` (palavra, forma, regra), tudo já dobrado (sem acento, minúsculo):

| rule          | O que quem consome faz |
|---------------|------------------------|
| `abbr`        | nos dois sentidos: "dr" digitado casa com "doutor"; "doutor" digitado casa com nome que traz "dr" |
| `form`        | a palavra também casa com a outra forma: "rodoviaria" -> "rodoviario" |
| `number`      | número e número por extenso casam ("14" e "quatorze"); o gerador já grava os dois no índice |
| `drop_prefix` | a expressão no começo da busca pode ser ignorada: "cidade de goias" -> "goias" |

`category` (palavra, tipos): a palavra vira filtro de `kind` (separados por vírgula) e a busca passa a ser por
distância: "posto ipiranga" -> postos (`amenity=fuel`) com "ipiranga" no nome.
"""
from __future__ import annotations

from typing import Dict, List, Tuple

ABBREVIATIONS = {
    "av": "avenida", "avda": "avenida", "r": "rua", "rod": "rodovia", "al": "alameda", "tv": "travessa",
    "trav": "travessa", "pca": "praca", "pc": "praca", "est": "estrada", "estr": "estrada", "lgo": "largo",
    "lg": "largo", "vd": "viaduto", "pte": "ponte", "cap": "capitao", "cel": "coronel", "cmte": "comandante",
    "dr": "doutor", "dra": "doutora", "eng": "engenheiro", "gen": "general", "gov": "governador", "mal": "marechal",
    "pres": "presidente", "prof": "professor", "profa": "professora", "sen": "senador", "dep": "deputado",
    "ver": "vereador", "des": "desembargador", "min": "ministro", "ten": "tenente", "sgt": "sargento",
    "brig": "brigadeiro", "alm": "almirante", "pe": "padre", "fr": "frei", "d": "dom", "sta": "santa",
    "sto": "santo", "s": "sao", "nsa": "nossa", "sra": "senhora", "jd": "jardim", "jdm": "jardim",
    "res": "residencial", "resid": "residencial", "cond": "condominio", "conj": "conjunto", "st": "setor",
    "vl": "vila", "pq": "parque", "qd": "quadra", "lt": "lote", "bl": "bloco", "ed": "edificio", "faz": "fazenda",
    "chac": "chacara", "hosp": "hospital", "esc": "escola", "univ": "universidade", "fac": "faculdade",
    "aerop": "aeroporto", "ctr": "centro", "cto": "centro",
}

# Formas da mesma palavra que o prefixo não pega (masculino e feminino, singular e plural irregular). Valem nos dois
# sentidos.
FORMS = [("rodoviaria", "rodoviario"), ("ferroviaria", "ferroviario"), ("aerea", "aereo"),
         ("municipal", "municipio"), ("bombeiro", "bombeiros"), ("correio", "correios")]

# Números de uma palavra só (o que aparece em nome de rua: "Rua Quatorze", "Avenida Vinte").
NUMBERS = {
    0: ["zero"], 1: ["um", "uma"], 2: ["dois", "duas"], 3: ["tres"], 4: ["quatro"], 5: ["cinco"], 6: ["seis"],
    7: ["sete"], 8: ["oito"], 9: ["nove"], 10: ["dez"], 11: ["onze"], 12: ["doze"], 13: ["treze"],
    14: ["quatorze", "catorze"], 15: ["quinze"], 16: ["dezesseis"], 17: ["dezessete"], 18: ["dezoito"],
    19: ["dezenove"], 20: ["vinte"], 30: ["trinta"], 40: ["quarenta"], 50: ["cinquenta"], 60: ["sessenta"],
    70: ["setenta"], 80: ["oitenta"], 90: ["noventa"], 100: ["cem"], 200: ["duzentos"], 300: ["trezentos"],
    400: ["quatrocentos"], 500: ["quinhentos"], 600: ["seiscentos"], 700: ["setecentos"], 800: ["oitocentos"],
    900: ["novecentos"], 1000: ["mil"],
}
# "um" e "uma" são artigo antes de número: no índice, só "1" -> "um" (nunca "um" -> "1", que poria "1" em todo nome
# com "uma"). Na tabela, os dois sentidos valem só com a palavra inteira.
_WORD_TO_NUMBER = {w: str(n) for n, words in NUMBERS.items() for w in words if w not in ("um", "uma")}

DROP_PREFIXES = ["cidade de", "cidade do", "cidade da", "municipio de", "municipio do", "municipio da"]

CATEGORIES = {
    "posto": ["amenity=fuel"], "postos": ["amenity=fuel"], "combustivel": ["amenity=fuel"],
    "gasolina": ["amenity=fuel"], "etanol": ["amenity=fuel"], "diesel": ["amenity=fuel"],
    "borracharia": ["shop=tyres"], "borracheiro": ["shop=tyres"],
    "oficina": ["shop=car_repair", "shop=motorcycle_repair"], "mecanica": ["shop=car_repair", "shop=motorcycle_repair"],
    "mecanico": ["shop=car_repair", "shop=motorcycle_repair"], "concessionaria": ["shop=car", "shop=motorcycle"],
    "hospital": ["amenity=hospital"], "upa": ["amenity=hospital", "amenity=clinic"],
    "clinica": ["amenity=clinic", "healthcare=clinic"], "farmacia": ["amenity=pharmacy"],
    "drogaria": ["amenity=pharmacy"], "pedagio": ["barrier=toll_booth"],
    "hotel": ["tourism=hotel"], "pousada": ["tourism=guest_house"], "motel": ["tourism=motel"],
    "camping": ["tourism=camp_site"], "restaurante": ["amenity=restaurant"], "lanchonete": ["amenity=fast_food"],
    "padaria": ["shop=bakery"], "mercado": ["shop=supermarket", "shop=convenience", "amenity=marketplace"],
    "supermercado": ["shop=supermarket"], "banco": ["amenity=bank"], "policia": ["amenity=police"],
    "delegacia": ["amenity=police"], "bombeiros": ["amenity=fire_station"], "rodoviaria": ["amenity=bus_station"],
    "aeroporto": ["aeroway=aerodrome"], "estacionamento": ["amenity=parking"],
    "igreja": ["amenity=place_of_worship"], "escola": ["amenity=school"], "banheiro": ["amenity=toilets"],
    "recarga": ["amenity=charging_station"], "cachoeira": ["natural=waterfall", "waterway=waterfall"],
    "mirante": ["tourism=viewpoint"], "descanso": ["highway=rest_area", "highway=services"],
    "estadio": ["leisure=stadium"], "shopping": ["shop=mall"], "parque": ["leisure=park"],
    "museu": ["tourism=museum"], "universidade": ["amenity=university"],
    "faculdade": ["amenity=college", "amenity=university"], "teatro": ["amenity=theatre"],
    "cinema": ["amenity=cinema"], "zoologico": ["tourism=zoo"], "feira": ["amenity=marketplace"],
    "praia": ["natural=beach"],
}


def number_forms(token: str) -> List[str]:
    """As outras formas de um número no índice: '14' -> ['quatorze', 'catorze']; 'quatorze' -> ['14']."""
    if token.isdigit() and int(token) in NUMBERS and token == str(int(token)):
        return list(NUMBERS[int(token)])
    if token in _WORD_TO_NUMBER:
        return [_WORD_TO_NUMBER[token]]
    return []


def word_forms() -> List[Tuple[str, str, str]]:
    """As linhas da tabela `word_form`, em ordem fixa."""
    rows = [(a, full, "abbr") for a, full in ABBREVIATIONS.items()]
    rows += [(a, b, "form") for a, b in FORMS] + [(b, a, "form") for a, b in FORMS]
    for n, words in NUMBERS.items():
        for w in words:
            rows += [(str(n), w, "number"), (w, str(n), "number")]
    rows += [(p, "", "drop_prefix") for p in DROP_PREFIXES]
    return sorted(set(rows))


def categories() -> Dict[str, str]:
    """As linhas da tabela `category`: palavra -> tipos separados por vírgula."""
    return {word: ",".join(kinds) for word, kinds in sorted(CATEGORIES.items())}
