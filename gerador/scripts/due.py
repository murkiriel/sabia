"""Diz se está na hora de gerar de novo: a geração publicada completou o intervalo?

    python scripts/due.py                     # lê o catalogo.json da raiz; intervalo de 29 dias
    python scripts/due.py --interval-days 14
    python scripts/due.py --manual            # disparo à mão: sempre gera
    python scripts/due.py --generate-from 2026-10-02   # geração extra: desse dia em diante, se a publicada for anterior

Imprime o motivo e, no GitHub Actions, grava run=true ou run=false em $GITHUB_OUTPUT (o workflow gerar só segue
para o build com run=true). Sem catálogo publicado, gera. A lógica fica em sabia/schedule.py.
"""
from __future__ import annotations

import argparse
import os
import sys
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Optional

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from sabia import config, schedule  # noqa: E402


def _day(text: str) -> Optional[date]:
    """O dia da geração extra; vazio é nenhum (o workflow passa a variável mesmo vazia)."""
    try:
        return date.fromisoformat(text) if text else None
    except ValueError:
        raise argparse.ArgumentTypeError(f"não é uma data AAAA-MM-DD: {text!r}") from None


def main() -> None:
    for stream in (sys.stdout, sys.stderr):  # acentos certos também com a saída redirecionada para arquivo
        try:
            stream.reconfigure(encoding="utf-8", errors="replace")  # type: ignore[union-attr]
        except (AttributeError, ValueError):
            pass
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--interval-days", type=int, default=config.GENERATION_INTERVAL_DAYS,
                    help="dias entre gerações (padrão: %(default)s)")
    ap.add_argument("--catalog", type=Path, default=config.REPO / "catalogo.json",
                    help="catálogo publicado (padrão: o da raiz do repositório)")
    ap.add_argument("--manual", action="store_true", help="disparo à mão: gera sem olhar a data")
    ap.add_argument("--generate-from", type=_day, default=None, metavar="AAAA-MM-DD",
                    help="geração extra: a partir desse dia (UTC), gera se a publicada for anterior; vazio = nenhuma")
    args = ap.parse_args()

    due, reason = schedule.generation_due(schedule.catalog_built_at(args.catalog), datetime.now(timezone.utc),
                                          args.interval_days, manual=args.manual, generate_from=args.generate_from)
    print(reason)
    output = os.environ.get("GITHUB_OUTPUT")
    if output:
        with open(output, "a", encoding="utf-8") as f:
            f.write(f"run={'true' if due else 'false'}\n")


if __name__ == "__main__":
    main()
