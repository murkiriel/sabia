"""Gera uma geração do Sabiá em data/dist/: um banco por estado, a base nacional e o catalogo.json.

    python generate.py                                  # tudo, os 27 estados
    python generate.py --states DF,GO                   # só esses estados (a base sai com o país inteiro)
    python generate.py --osm-file data/raw/x.osm.pbf    # um extrato já baixado, sem baixar o do Brasil
    python generate.py --from validate                  # só valida e remonta o catálogo sobre os bancos já gerados

Etapas, em ordem: sources (extrato do OpenStreetMap, arquivos do IBGE e as outras fontes), build (lê o extrato e
grava os bancos), validate (as travas), catalog. Depois, `python scripts/publish.py` publica.
"""
from __future__ import annotations

import argparse
import json
import sqlite3
import sys
from contextlib import closing
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, List, Optional

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
# Pythons sem venv (ex.: a distribuição "embeddable" do Windows) podem instalar as dependências com
# `pip install --target .pylib -r requirements.txt`; esta pasta entra no caminho de import se existir.
if (HERE / ".pylib").exists():
    sys.path.insert(0, str(HERE / ".pylib"))

from sabia import build, catalog, config, run_record, sources, sqlite_old, validation  # noqa: E402

STAGES = ["sources", "build", "validate", "catalog"]


def parse_states(text: str) -> List[str]:
    """'go, df' -> ['DF', 'GO']; vazio = os 27 estados. Sigla desconhecida é erro de linha de comando."""
    chosen = {s.strip().upper() for s in text.split(",") if s.strip()}
    unknown = sorted(chosen - set(config.STATES))
    if unknown:
        raise argparse.ArgumentTypeError(f"UF desconhecida: {', '.join(unknown)}")
    return sorted(chosen or config.STATES)


def build_parser() -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(description=(__doc__ or "").splitlines()[0])
    ap.add_argument("--states", type=parse_states, default=parse_states(""), metavar="UF,UF",
                    help="estados a gerar (padrão: todos)")
    ap.add_argument("--osm-file", type=Path, default=None, metavar="ARQUIVO",
                    help="extrato do OpenStreetMap já baixado (padrão: baixa o do Brasil)")
    ap.add_argument("--from", dest="from_stage", choices=STAGES, default="sources",
                    help="começa nesta etapa, reaproveitando as anteriores")
    return ap


def sources_stage(osm_file: Optional[Path]) -> Dict[str, object]:
    """Extrato do OpenStreetMap (o local, se pedido; senão o do Brasil, baixado se houver versão nova) e os arquivos
    do IBGE. Os dados do extrato ficam em data/build/osm.json para as etapas seguintes."""
    osm = sources.local_extract(osm_file) if osm_file else sources.osm_extract()
    sources.municipal_mesh()
    sources.municipality_names()
    sources.ibge_localities()
    sources.prf_units()
    sources.cnes_units()
    config.BUILD.mkdir(parents=True, exist_ok=True)
    (config.BUILD / "osm.json").write_text(json.dumps(osm, indent=2), encoding="utf-8")
    found = sources.generation_sources(osm)
    (config.BUILD / "fontes.json").write_text(json.dumps(found, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"[fontes] OpenStreetMap de {osm['timestamp']} ({osm['url']}), municípios e localidades do IBGE, postos da "
          f"PRF e CNES conferidos")
    return osm


def sources_record() -> Dict[str, object]:
    """A data de cada fonte da geração (data/build/fontes.json, da etapa sources), para o geracao.json; {} sem ela."""
    path = config.BUILD / "fontes.json"
    return json.loads(path.read_text(encoding="utf-8")) if path.exists() else {}


def build_stage(states: List[str], osm: Dict[str, object], today: Optional[str] = None) -> Dict[str, object]:
    """Lê o extrato e grava os bancos de cada estado e a base em data/build/, compactados em data/dist/."""
    return build.run(states, osm, today)


def validate_stage(states: List[str], packages: Dict[str, object]) -> List[str]:
    """As travas (sabia/validation.py) sobre os bancos de data/build/; grava data/dist/relatorio.json. Devolve os
    problemas (vazio = pode montar o catálogo)."""
    municipalities = sources.load_municipalities(config.RAW / sources.MESH_FILE, config.RAW / sources.NAMES_FILE)
    cases = validation.load_cases(config.SEARCH_CASES, states)
    lib = sqlite_old.library_path()
    problems: List[str] = []
    searches: List[dict] = []
    version = ""
    for uf in states:
        db_path = config.BUILD / f"sabia-{uf}.sqlite"
        mine = [c for c in cases if c["uf"] == uf]
        with closing(sqlite3.connect(db_path)) as db:
            found, rows = validation.search_gate(db, mine)
        problems += found
        searches += rows
        problems += validation.coverage_gate(db_path, municipalities, uf)
        found, version = validation.old_sqlite_gate(db_path, mine, lib)
        problems += found
    found, version = validation.old_sqlite_gate(config.BUILD / "sabia-base.sqlite", [], lib)
    problems += found
    problems += validation.base_gate(packages["base"]["counts"], states)  # type: ignore[index]
    suspects_file = config.BUILD / "ruas_suspeitas.json"
    suspects = json.loads(suspects_file.read_text(encoding="utf-8")) if suspects_file.exists() else []
    problems = list(dict.fromkeys(problems))
    validation.write_report(config.DIST / "relatorio.json", suspects, searches, problems, version)
    passed = sum(1 for s in searches if s["rank"] is not None and s["rank"] <= s["top"])
    print(f"[validar] buscas: {passed} de {len(searches)}; ruas locais suspeitas: {len(suspects)}; "
          f"SQLite {version or 'antigo ausente'}; {len(problems)} problemas (data/dist/relatorio.json)")
    return problems


def catalog_stage(packages: Dict[str, object]) -> Dict[str, object]:
    """O catalogo.json em data/dist/, a partir do pacotes.json e dos arquivos compactados."""
    municipalities = sources.load_municipalities(config.RAW / sources.MESH_FILE, config.RAW / sources.NAMES_FILE)
    cat = catalog.build_catalog(packages, municipalities)
    catalog.save(cat, config.DIST / "catalogo.json")
    return cat


def _utf8_output() -> None:
    # Log redirecionado para arquivo sai na codificação do Windows (cp1252) e os acentos quebram; UTF-8 sempre.
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8", errors="replace")  # type: ignore[union-attr]
        except (AttributeError, ValueError):
            pass


def _generate(args: argparse.Namespace, recorder: run_record.RunRecorder) -> str:
    start = STAGES.index(args.from_stage)
    with recorder.stage("sources"):
        if start <= STAGES.index("sources"):
            osm = sources_stage(args.osm_file)
        else:
            osm = json.loads((config.BUILD / "osm.json").read_text(encoding="utf-8"))
    recorder.sources = sources_record()
    with recorder.stage("build"):
        if start <= STAGES.index("build"):
            packages = build_stage(args.states, osm)
        else:
            packages = json.loads((config.DIST / "pacotes.json").read_text(encoding="utf-8"))
    states = sorted(packages["states"])  # type: ignore[call-overload]
    if start <= STAGES.index("validate"):
        with recorder.stage("validate"):
            problems = validate_stage(states, packages)
        if problems:
            print()
            print("[gerar] AS TRAVAS FALHARAM; o catálogo não foi montado:")
            for p in problems:
                print("  -", p)
            raise SystemExit(1)
    else:
        print("[gerar] AVISO: --from catalog não roda as travas; o catálogo sai sobre a validação anterior")
    with recorder.stage("catalog"):
        cat = catalog_stage(packages)
    total = sum(e["bytes"] for e in [cat["base"], *cat["states"].values()])  # type: ignore[attr-defined]
    return f"geração {cat['build_id']}: {len(states)} estados e a base, {total / 1e6:.1f} MB compactados"


def main() -> None:
    _utf8_output()
    args = build_parser().parse_args()
    config.DIST.mkdir(parents=True, exist_ok=True)
    marker = config.DIST / config.IN_PROGRESS_MARKER
    marker.write_text(datetime.now(timezone.utc).isoformat(), encoding="utf-8")
    recorder = run_record.RunRecorder(config.DATA)
    result = "failed"
    try:
        summary = _generate(args, recorder)
        result = "ok"
    except SystemExit:
        result = "failed: validation"
        raise
    except BaseException as e:
        result = f"failed: {e.__class__.__name__}: {e}"
        raise
    finally:
        recorder.save(config.DIST / "geracao.json", result)
    minutes = sum(e["minutes"] for e in recorder.stages)
    print(f"[gerar] {summary}, em {minutes:.1f} min; pico de disco em data/: {recorder.peak / 1e9:.2f} GB "
          f"(detalhes em data/dist/geracao.json)")
    marker.unlink()


if __name__ == "__main__":
    main()
