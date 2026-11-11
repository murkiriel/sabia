"""Verificador de referência: roda a busca de referência (sabia/search.py) contra um conjunto de conformidade e diz o
que difere. Passa 100% com a própria referência; é o modelo do verificador de um porte (docs/CONFORMIDADE.md).

    python scripts/check_conformance.py sabia-conformidade.json.zst --dbs PASTA
    python scripts/check_conformance.py conformidade-exemplo.json            # só as funções puras, sem bancos

`--dbs`: a pasta com os bancos da mesma geração do conjunto (`sabia-<UF>.sqlite` ou `.sqlite.zst`; os compactados
são descompactados numa pasta temporária). Os casos de um banco ausente ou de outra geração são pulados, com aviso.
Sai com código 1 se algum caso falhar (os `informative` e os `known_gap` que diferem só avisam).

Para um porte, o que muda é só o adaptador (a classe Reference de sabia/conformance.py): quatro chamadas,
`unit(fn, args)`, `search(db, query, near, limit)`, `which_street(db, lat, lng)` e, opcional, `trace(...)`, que
devolvem os mesmos campos que a referência; a leitura do arquivo e a comparação (conformance.check) seguem iguais.
"""
from __future__ import annotations

import argparse
import shutil
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from sabia import conformance  # noqa: E402


def db_paths(doc: dict, folder: Path, work: Path) -> dict:
    """{nome: caminho do .sqlite} dos pacotes do conjunto achados na pasta (o .zst é descompactado em `work`)."""
    out = {}
    for name in doc["packages"]:
        plain, packed = folder / f"sabia-{name}.sqlite", folder / f"sabia-{name}.sqlite.zst"
        if plain.exists():
            out[name] = plain
        elif packed.exists():
            import zstandard
            out[name] = work / plain.name
            with open(packed, "rb") as src, open(out[name], "wb") as dst:
                zstandard.ZstdDecompressor().copy_stream(src, dst)
    return out


def main() -> None:
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8", errors="replace")  # type: ignore[union-attr]
        except (AttributeError, ValueError):
            pass
    ap = argparse.ArgumentParser(description=(__doc__ or "").splitlines()[0])
    ap.add_argument("file", type=Path, help="o conjunto (.json ou .json.zst)")
    ap.add_argument("--dbs", type=Path, default=None, help="pasta dos bancos da mesma geração")
    ap.add_argument("--show", type=int, default=30, help="quantas falhas mostrar (padrão 30)")
    args = ap.parse_args()

    if args.file.name.endswith(".zst"):
        problem = conformance.sha_problem(args.file)
        if problem and args.file.with_name(args.file.name + ".sha256").exists():
            sys.exit(f"Conjunto corrompido: {problem}")
    doc = conformance.load(args.file)
    if doc.get("conformance_version") != conformance.CONFORMANCE_VERSION:
        sys.exit(f"Conjunto na versão {doc.get('conformance_version')}; este verificador conhece a "
                 f"{conformance.CONFORMANCE_VERSION}")
    work = Path(tempfile.mkdtemp(prefix="sabia-conformidade-"))
    try:
        paths = db_paths(doc, args.dbs, work) if args.dbs else {}
        names, notes = conformance.available_dbs(doc, paths)
        reference = conformance.Reference(doc, paths)
        try:
            report = conformance.check(doc, reference, names)
        finally:
            reference.close()
    finally:
        shutil.rmtree(work, ignore_errors=True)

    print(f"Conjunto da geração {doc['build_id']} (formato {doc['format_version']}, conformidade "
          f"{doc['conformance_version']})")
    for note in notes:
        print(f"  aviso: {note}")
    for section in ("unit", "search", "which_street"):
        r = report[section]
        print(f"  {section}: {r['passed']} passaram, {r['failed']} falharam, {r['warned']} com aviso, "
              f"{r['skipped']} pulados")
    for kind, items in (("FALHA", report["failures"]), ("aviso", report["warnings"])):
        for item in items[:args.show]:
            print(f"  {kind} {item['id']}: {'; '.join(item['problems'])}")
    failed = sum(report[s]["failed"] for s in ("unit", "search", "which_street"))
    if failed:
        sys.exit(1)


if __name__ == "__main__":
    main()
