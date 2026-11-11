"""Refaz o catalogo.json de uma geração já publicada com o bloco `contract` (docs/CATALOGO.md), sem refazer os pacotes.

    python scripts/recatalog.py --catalog ../catalogo.json --out catalogo-refeito.json

Lê o catálogo publicado e acrescenta (ou refaz) só a chave `contract`; as outras saem iguais, na mesma ordem. O bloco
vem das chaves antigas e do config: o commit completo é o do `generator_commit` curto do catálogo (resolvido no git
deste checkout), e os checksums das entradas (`sources`) vêm do config **naquele commit**, para não atribuir à geração
um checksum que só entrou no config depois. Não publica nada: grava em --out e mostra o resumo.
"""
from __future__ import annotations

import argparse
import ast
import json
import subprocess
import sys
from pathlib import Path
from typing import Dict, Iterable, Optional

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from sabia import catalog, config  # noqa: E402

CONFIG_PATH = "gerador/sabia/config.py"


def _text(node: ast.AST, known: Dict[str, str]) -> Optional[str]:
    """O valor de texto de uma expressão feita só de literais, nomes já vistos e `+`; None para qualquer outra."""
    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        return node.value
    if isinstance(node, ast.Name):
        return known.get(node.id)
    if isinstance(node, ast.BinOp) and isinstance(node.op, ast.Add):
        left, right = _text(node.left, known), _text(node.right, known)
        return None if left is None or right is None else left + right
    return None


def constants_at(commit: str, names: Iterable[str], path: str = CONFIG_PATH) -> Dict[str, str]:
    """As constantes de texto `names` do arquivo `path` no `commit`, lidas sem executar o arquivo (atribuição simples
    de literal, de nome já visto ou de soma deles). A que não existe naquele commit fica de fora."""
    text = subprocess.run(["git", "-C", str(config.REPO), "show", f"{commit}:{path}"], capture_output=True, text=True,
                          check=True).stdout
    known: Dict[str, str] = {}
    for node in ast.parse(text).body:
        if isinstance(node, ast.Assign) and len(node.targets) == 1 and isinstance(node.targets[0], ast.Name):
            value = _text(node.value, known)
            if value is not None:
                known[node.targets[0].id] = value
    wanted = set(names)
    return {name: value for name, value in known.items() if name in wanted}


def rebuild(published: dict) -> dict:
    commit = catalog.git_commit_full(published["generator_commit"])
    if commit is None:
        raise SystemExit(f"o commit {published['generator_commit']} do catálogo não está neste checkout (git fetch?)")
    out = {key: value for key, value in published.items() if key != "contract"}
    out["contract"] = catalog.contract(out, commit, constants_at(commit, catalog.SOURCE_CONSTANTS))
    return out


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--catalog", default=str(config.REPO / "catalogo.json"), help="o catálogo publicado")
    ap.add_argument("--out", required=True, help="onde gravar o catálogo refeito")
    args = ap.parse_args(argv)
    published = json.loads(Path(args.catalog).read_text(encoding="utf-8"))
    out = rebuild(published)
    dest = Path(args.out)
    if dest.resolve() == Path(args.catalog).resolve():
        raise SystemExit("--out não pode ser o próprio catálogo publicado: confira antes e troque à mão")
    catalog.save(out, dest)
    block = out["contract"]
    print(f"{block['build_id']}: {len(block['files'])} arquivos, commit {block['generator']['commit']}, "
          f"{len(block['sources'])} fontes -> {dest}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
