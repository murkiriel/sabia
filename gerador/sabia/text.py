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
