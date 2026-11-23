"""Sonda de pré-voo: confere que as fontes baixadas na hora respondem, antes de uma geração de ~90 min.

    python scripts/preflight.py                  # as fontes ao vivo, para os 27 estados
    python scripts/preflight.py --states DF,GO   # o CNEFE é o do primeiro estado
    python scripts/preflight.py --osm-file x.osm.pbf   # extrato local: não sonda o OpenStreetMap

Sai com código 1 e a lista do que não respondeu. A lógica fica em sabia/preflight.py.
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path
from typing import List, Optional, Sequence

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from sabia import config, preflight  # noqa: E402


def _states(text: str) -> List[str]:
    chosen = [s.strip().upper() for s in text.split(",") if s.strip()]
    unknown = sorted(set(chosen) - set(config.STATES))
    if unknown:
        raise argparse.ArgumentTypeError(f"UF desconhecida: {', '.join(unknown)}")
    return chosen


def main(argv: Optional[Sequence[str]] = None) -> None:
    for stream in (sys.stdout, sys.stderr):  # acentos certos também com a saída redirecionada para arquivo
        try:
            stream.reconfigure(encoding="utf-8", errors="replace")  # type: ignore[union-attr]
        except (AttributeError, ValueError):
            pass
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--states", type=_states, default=[], metavar="UF,UF", help="estados da geração (padrão: todos)")
    ap.add_argument("--osm-file", type=Path, default=None, metavar="ARQUIVO", help="extrato local: sem sonda do OSM")
    args = ap.parse_args(argv)
    found = preflight.sources(args.states, osm_local=args.osm_file is not None)
    lines, failed = preflight.check(found)
    print("\n".join(lines))
    if failed:
        sys.exit(f"{len(failed)} de {len(found)} fontes não responderam: {'; '.join(failed)}")
    print(f"{len(found)} fontes responderam.")


if __name__ == "__main__":
    main()
