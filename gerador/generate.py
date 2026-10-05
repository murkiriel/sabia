"""Gera uma geração do Sabiá em data/dist/: um banco por estado, a base nacional e o catalogo.json.

    python generate.py                                  # tudo, os 27 estados
    python generate.py --states DF,GO                   # só esses estados (a base sai com o país inteiro)
    python generate.py --osm-file data/raw/x.osm.pbf    # um extrato já baixado, sem baixar o do Brasil
    python generate.py --from validate                  # só valida e remonta o catálogo sobre os bancos já gerados

Etapas, em ordem: sources (extrato do OpenStreetMap e arquivos do IBGE), build (lê o extrato e grava os bancos),
validate (as travas), catalog. Depois, `python scripts/publish.py` publica.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Dict, List, Optional

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
# Pythons sem venv (ex.: a distribuição "embeddable" do Windows) podem instalar as dependências com
# `pip install --target .pylib -r requirements.txt`; esta pasta entra no caminho de import se existir.
if (HERE / ".pylib").exists():
    sys.path.insert(0, str(HERE / ".pylib"))

from sabia import config, sources  # noqa: E402

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
    config.BUILD.mkdir(parents=True, exist_ok=True)
    (config.BUILD / "osm.json").write_text(json.dumps(osm, indent=2), encoding="utf-8")
    print(f"[fontes] OpenStreetMap de {osm['timestamp']} ({osm['url']}), municípios do IBGE conferidos")
    return osm


def _utf8_output() -> None:
    # Log redirecionado para arquivo sai na codificação do Windows (cp1252) e os acentos quebram; UTF-8 sempre.
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8", errors="replace")  # type: ignore[union-attr]
        except (AttributeError, ValueError):
            pass


def main() -> None:
    _utf8_output()
    args = build_parser().parse_args()
    if STAGES.index(args.from_stage) <= STAGES.index("sources"):
        sources_stage(args.osm_file)
    sys.exit(f"[gerar] etapas seguintes ainda não escritas; estados pedidos: {', '.join(args.states)}")


if __name__ == "__main__":
    main()
