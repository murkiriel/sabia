"""O texto como o índice de busca guarda: sem acento, minúsculo, pontuação vira espaço.

Quem consome dobra o que a pessoa digita do mesmo jeito (regra em docs/CONSUMO.md), e assim não depende de como o
SQLite do aparelho trata acento."""
from __future__ import annotations

import unicodedata


def fold(s: str) -> str:
    """'R. Cap. Caldas, 280' -> 'r cap caldas 280'; 'São-José' -> 'sao jose'."""
    decomposed = unicodedata.normalize("NFKD", s.lower())
    plain = "".join(c for c in decomposed if not unicodedata.combining(c))
    return " ".join("".join(c if c.isalnum() else " " for c in plain).split())


# Palavras que ficam minúsculas no meio de um nome, e siglas que ficam como estão.
_SMALL = {"a", "o", "as", "os", "de", "da", "do", "das", "dos", "e", "em", "na", "no", "nas", "nos"}
_ACRONYMS = {"UPA", "UBS", "UTI", "SUS", "SAMU", "CAIS", "UFG", "HC", "PS", "PA", "AME", "CTI", "II", "III", "IV",
             "VI", "VII", "VIII", "IX", "XI", "XII"}
_VOWELS = set("AEIOUÁÉÍÓÚÂÊÔÃÕÀÜ")


def title_pt(s: str) -> str:
    """Nome em caixa alta de cadastro para caixa de título: 'HOSPITAL DAS CLÍNICAS DA UFG' -> 'Hospital das Clínicas
    da UFG'. Ficam como siglas as conhecidas e as palavras sem vogal ('HGG'); '24H' -> '24h'."""
    out = []
    for i, word in enumerate(s.split()):
        upper = word.upper()
        if upper in _ACRONYMS or (word.isalpha() and not _VOWELS & set(upper)):
            out.append(upper)
        elif i > 0 and word.lower() in _SMALL:
            out.append(word.lower())
        else:
            out.append(word[:1].upper() + word[1:].lower())
    return " ".join(out)
