"""Renova as cópias versionadas das fontes que não respondem aos executores do GitHub Actions (IBGE malha e
municípios, marcos do SNV do DNIT, aeródromos da ANAC), de uma conexão que alcança as fontes:

    python scripts/update_copies.py              # grava em gerador/ e imprime os sha256 para o sabia/config.py

Cada fonte é baixada e conferida como a geração conferia o download (sabia/copies.py). Depois, à mão: os sha256 e as
datas no config (IBGE_*_SHA256 e IBGE_COPIES_DATE, SNV_COPY_SHA256, ANAC_*_SHA256 e ANAC_COPIES_DATE), os testes e
uma geração local, porque uma cópia nova muda o resultado da geração.
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
    for constant, sha256 in sorted(found.items()):
        print(f'{constant} = "{sha256}"')
    return 0


if __name__ == "__main__":
    sys.exit(main())
