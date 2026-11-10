"""Renova as cópias versionadas das fontes que não respondem aos executores do GitHub Actions (IBGE malha e
municípios, marcos do SNV do DNIT, aeródromos da ANAC, postos da PRF da ANTT), de uma conexão que alcança as fontes:

    python scripts/update_copies.py              # grava em gerador/ e imprime os sha256 e as datas para o config

Cada fonte é baixada e conferida como a geração conferia o download (sabia/copies.py). Depois, à mão: as linhas
impressas no sabia/config.py (os sha256 e as datas), os testes e uma geração local, porque uma cópia nova muda o
resultado da geração. A geração avisa quando uma cópia passa de 180 dias (copies.stale); renovar 2 a 4 vezes por ano
basta (a malha do IBGE muda uma vez por ano, o SNV algumas vezes por ano).
"""
from __future__ import annotations

import sys
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from sabia import config, copies  # noqa: E402


def main() -> int:
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    found = copies.refresh(config.GENERATOR_DIR, today)
    print(f"[cópias] gravadas em {config.GENERATOR_DIR} em {today}; para o sabia/config.py:")
    for line in copies.config_lines(found, today):
        print(line)
    return 0


if __name__ == "__main__":
    sys.exit(main())
