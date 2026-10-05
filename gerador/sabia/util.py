"""Funções pequenas usadas em mais de um módulo."""
from __future__ import annotations

import hashlib
from pathlib import Path

CHUNK = 1 << 22  # 4 MB por leitura: arquivos de GB sem carregar tudo na memória


def file_hash(path: Path, algorithm: str = "sha256") -> str:
    """Hash hexadecimal do arquivo (sha256 dos pacotes, md5 do extrato do OpenStreetMap)."""
    h = hashlib.new(algorithm)
    with open(path, "rb") as f:
        while chunk := f.read(CHUNK):
            h.update(chunk)
    return h.hexdigest()
