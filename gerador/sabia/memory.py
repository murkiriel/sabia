"""A memória da geração: o RSS e o pico do processo para o log de cada etapa do build (`usage`), e a memória já liberada
devolvida ao sistema entre as etapas (`release`).

O glibc guarda para si a memória que o Python e o pyosmium liberam (ex.: ~1,7 GB depois da leitura do extrato, medido no
Centro-Oeste); no executor do Actions (7,8 GB de RAM) isso vira swap. `malloc_trim(0)` devolve as páginas livres. Fora
do Linux com glibc, as duas funções não fazem nada.
"""
from __future__ import annotations

import ctypes
import ctypes.util
import functools
from typing import Optional


def _status() -> Optional[str]:
    try:
        with open("/proc/self/status", encoding="utf-8") as f:
            return f.read()
    except OSError:
        return None


def _kb(status: str, key: str) -> int:
    for line in status.splitlines():
        if line.startswith(key + ":"):
            return int(line.split()[1])
    return 0


def usage() -> str:
    """'memória 5.0 GB, pico 7.1 GB' (o RSS agora e o maior até aqui); vazio sem /proc."""
    status = _status()
    if status is None:
        return ""
    return f"memória {_kb(status, 'VmRSS') / 2**20:.1f} GB, pico {_kb(status, 'VmHWM') / 2**20:.1f} GB"


@functools.lru_cache(maxsize=1)
def _libc():
    name = ctypes.util.find_library("c")
    try:
        libc = ctypes.CDLL(name) if name else None
    except OSError:
        return None
    return libc if libc is not None and hasattr(libc, "malloc_trim") else None


def release() -> None:
    """Devolve ao sistema a memória livre que o malloc guarda (glibc); sem glibc, nada."""
    libc = _libc()
    if libc is not None:
        libc.malloc_trim(0)
