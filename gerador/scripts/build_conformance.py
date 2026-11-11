"""Gera o conjunto de conformidade da busca (docs/CONFORMIDADE.md) a partir da busca de referência e dos bancos de uma
geração.

    python scripts/build_conformance.py                          # os bancos de data/build/, para data/dist/
    python scripts/build_conformance.py --dbs PASTA --out x.json.zst
    python scripts/build_conformance.py --dbs PASTA --states DF,GO --out x.json
    python scripts/build_conformance.py --dbs PASTA --example conformidade-exemplo.json
    python scripts/build_conformance.py --dbs PASTA --validation-candidates

`--dbs`: a pasta com os bancos descompactados (`sabia-base.sqlite`, `sabia-<UF>.sqlite`); os de uma release se
baixam com `gh release download <build_id> -R Murkiriel/sabia -p 'sabia-*.sqlite.zst'` e se descompactam com
`zstd -d`. `--zst`: a pasta com os `.sqlite.zst` da mesma geração, para o sha256 de cada pacote ir junto (padrão: a
própria `--dbs`, se estiverem lá). A saída `.json.zst` sai compactada, com o sha256 em `<arquivo>.sha256`; `.json`,
legível. Antes de gravar, a própria referência roda contra o conjunto (tem de passar inteira).

`--example` grava também o exemplo pequeno versionado no repositório (as funções puras e alguns casos).
`--validation-candidates` só mostra os casos que a receita leva ao buscas.json (as travas), sem gravar nada.

A geração (generate.py, etapa conformance) faz o mesmo sobre data/build/ depois das travas.
"""
from __future__ import annotations

import argparse
import json
import sqlite3
import sys
from contextlib import closing
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from sabia import catalog, config, conformance  # noqa: E402


def find_dbs(folder: Path, states=None) -> dict:
    """{'base': caminho, 'GO': caminho, ...} dos bancos descompactados da pasta (só os `states`, se pedidos)."""
    out = {}
    for path in sorted(folder.glob("sabia-*.sqlite")):
        name = path.name[len("sabia-"):-len(".sqlite")]
        if name == "base" or (name in config.STATES and (not states or name in states)):
            out[name] = path
    return out


def main() -> None:
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8", errors="replace")  # type: ignore[union-attr]
        except (AttributeError, ValueError):
            pass
    ap = argparse.ArgumentParser(description=(__doc__ or "").splitlines()[0])
    ap.add_argument("--dbs", type=Path, default=config.BUILD, help="pasta dos bancos descompactados")
    ap.add_argument("--zst", type=Path, default=None, help="pasta dos .sqlite.zst (para o sha256 dos pacotes)")
    ap.add_argument("--out", type=Path, default=config.DIST / conformance.FILE, help="arquivo de saída")
    ap.add_argument("--states", default="", help="só estas UFs (padrão: todas as da pasta)")
    ap.add_argument("--cases", type=Path, default=config.SEARCH_CASES, help="as buscas das travas (buscas.json)")
    ap.add_argument("--example", type=Path, default=None, help="grava também o exemplo pequeno neste arquivo")
    ap.add_argument("--validation-candidates", action="store_true",
                    help="só mostra os casos que a receita leva ao buscas.json")
    args = ap.parse_args()
    states = {s.strip().upper() for s in args.states.split(",") if s.strip()}
    dbs = find_dbs(args.dbs, states)
    if not dbs:
        sys.exit(f"Nenhum banco sabia-*.sqlite em {args.dbs}")

    if args.validation_candidates:
        for uf in sorted(k for k in dbs if k != "base"):
            with closing(sqlite3.connect(f"file:{dbs[uf]}?mode=ro", uri=True)) as db:
                for case in conformance.validation_candidates(db, uf):
                    print(json.dumps(case, ensure_ascii=False) + ",")
        return

    zst_dir = args.zst or (args.dbs if any(args.dbs.glob("sabia-*.sqlite.zst")) else None)
    try:
        doc = conformance.build(dbs, conformance.load_validation_cases(args.cases), zst_dir,
                                catalog.git_commit_hash(), log=print)
    except ValueError as e:
        sys.exit(f"Conjunto não gerado: {e}")
    problems = conformance.self_check(doc, dbs)
    if problems:
        print("A referência não passa no próprio conjunto:")
        for p in problems[:50]:
            print("  -", p)
        sys.exit(1)
    digest = conformance.save(doc, args.out)
    s = conformance.summary(doc)
    print(f"Conjunto da geração {doc['build_id']}: {s['unit']} casos das funções puras, {s['search']} buscas, "
          f"{s['which_street']} 'que rua é esta?'; {args.out} ({args.out.stat().st_size / 1e3:.0f} kB"
          + (f", sha256 {digest})" if digest else ")"))
    if args.example:
        conformance.save(conformance.example(doc), args.example)
        print(f"Exemplo: {args.example}")


if __name__ == "__main__":
    main()
