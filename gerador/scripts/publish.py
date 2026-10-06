"""Publica a geração de data/dist/: sobe os pacotes numa release do GitHub e grava o catalogo.json na raiz.

    python scripts/publish.py                  # só confere (nada é publicado)
    python scripts/publish.py --release        # confere, sobe a release <build_id> e grava o catálogo
    python scripts/publish.py --release --commit --push   # e ainda faz commit e push só do catalogo.json
    python scripts/publish.py --accept-drop    # passa por cima da trava de queda (publishing.drops)
    python scripts/publish.py --accept-older   # publica uma geração de OSM mais antigo que a publicada
    python scripts/publish.py --prune --dry-run   # só lista as releases antigas que a limpeza apagaria
    python scripts/publish.py --prune          # apaga as releases antigas (a publicação com --push já faz isso)

A ordem importa: primeiro os pacotes sobem para a release, só depois o catalogo.json e a tabela "Baixar por estado"
do README mudam (os dois no mesmo commit). Assim ninguém
lê um catálogo que aponta para arquivos que ainda não existem. A release sobe como rascunho e só é publicada
com todos os pacotes presentes e do tamanho certo; se a subida cair no meio, rodar de novo retoma do que falta.
Usa o `gh` (GitHub CLI) já logado.

Não publica se:
- a geração ainda roda ou caiu no meio (marca GERACAO_EM_ANDAMENTO em data/dist/),
- a versão do formato do catálogo não é a do gerador (database.FORMAT_VERSION),
- a geração foi feita de um extrato local (--osm-file),
- a geração não passou nas travas (data/dist/relatorio.json com problemas, ou sem ele),
- algum pacote falta, não bate o sha256 ou passa do limite do GitHub Releases,
- algum estado sumiu ou perdeu mais de 5% dos registros em relação ao catalogo.json publicado, no total ou numa
  classe com 1.000 registros ou mais (--accept-drop),
- a geração usa um OpenStreetMap mais antigo que o da publicada (--accept-older),
- já existe uma release PUBLICADA com o mesmo build_id (um rascunho é retomado),
- com --commit, o git do repositório não está com o e-mail anônimo do GitHub.

Depois do push do catálogo novo, as releases antigas são apagadas: ficam a do catálogo e as anteriores mais recentes,
config.KEEP_GENERATIONS no total (publishing.releases_to_delete). Só depois do push, porque até ali o catálogo
publicado ainda aponta para a geração anterior. Se a limpeza falhar, vira aviso: a geração já está publicada, e a
próxima publicação tenta de novo.

A lógica fica em sabia/publishing.py.
"""
from __future__ import annotations

import argparse
import json
import shutil
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from sabia import config, publishing  # noqa: E402


def _git(*args: str) -> subprocess.CompletedProcess:
    return subprocess.run(["git", "-C", str(config.REPO), *args], capture_output=True, text=True)


def prune(dry_run: bool) -> None:
    """O modo --prune: a limpeza das releases antigas sozinha, pela geração do catalogo.json da raiz."""
    root_catalog = config.REPO / "catalogo.json"
    if not root_catalog.exists():
        sys.exit("Sem catalogo.json na raiz: nada publicado, nada a apagar.")
    tag = json.loads(root_catalog.read_text(encoding="utf-8"))["build_id"]
    try:
        doomed = publishing.prune_releases(publishing.gh_real, tag, config.KEEP_GENERATIONS, dry_run)
    except (publishing.GhError, publishing.PruneRefused) as e:
        sys.exit(f"Limpeza não feita: {e}")
    kept = f"catálogo em {tag}, ficam {config.KEEP_GENERATIONS} gerações"
    if not doomed:
        print(f"Nenhuma release antiga a apagar ({kept}).")
    elif dry_run:
        print(f"Apagaria ({kept}): {', '.join(doomed)}.")
    else:
        print(f"Releases antigas apagadas ({kept}): {', '.join(doomed)}.")


def main() -> None:
    for stream in (sys.stdout, sys.stderr):  # acentos certos também com a saída redirecionada para arquivo
        try:
            stream.reconfigure(encoding="utf-8", errors="replace")  # type: ignore[union-attr]
        except (AttributeError, ValueError):
            pass
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--release", action="store_true", help="sobe a release e grava o catalogo.json na raiz")
    ap.add_argument("--commit", action="store_true", help="commit só do catalogo.json (exige --release)")
    ap.add_argument("--push", action="store_true", help="push do commit (exige --commit)")
    ap.add_argument("--accept-drop", action="store_true", help="publica mesmo com estado que perdeu registros")
    ap.add_argument("--accept-older", action="store_true",
                    help="publica mesmo com OpenStreetMap mais antigo que o da geração publicada")
    ap.add_argument("--prune", action="store_true",
                    help=f"só apaga as releases antigas (ficam {config.KEEP_GENERATIONS} gerações); não publica nada")
    ap.add_argument("--dry-run", action="store_true", help="com --prune: lista o que apagaria, sem apagar")
    args = ap.parse_args()
    problem = publishing.flags_problem(args.release, args.commit, args.push, args.prune, args.dry_run)
    if problem:
        ap.error(problem)
    if args.prune:
        prune(args.dry_run)
        return

    cat = json.loads((config.DIST / "catalogo.json").read_text(encoding="utf-8"))
    root_catalog = config.REPO / "catalogo.json"
    published = json.loads(root_catalog.read_text(encoding="utf-8")) if root_catalog.exists() else None

    problems = publishing.check(cat, published, args.accept_drop, args.accept_older)
    if args.commit:
        identity = publishing.identity_problem(_git("config", "user.email").stdout)
        if identity:
            problems.append(identity)
    if problems:
        print("Não publicado:")
        for p in problems:
            print("  -", p)
        sys.exit(1)
    packages = publishing.entries(cat)
    total = sum(e["bytes"] for e in packages.values())
    print(f"Geração {cat['build_id']} conferida: {len(packages)} pacotes, {total / 1e6:.1f} MB, "
          f"formato {cat['format_version']}, OSM de {cat['osm']['timestamp']}")
    if not args.release:
        print("Nada publicado (use --release).")
        return

    tag = cat["build_id"]
    files = [config.DIST / name for name in publishing.package_files(cat)]
    notes = (f"Busca de lugares sem internet, um banco por estado (formato {cat['format_version']}), OpenStreetMap "
             f"de {cat['osm']['timestamp']}. Índice: catalogo.json na raiz do repositório.\n\n{config.ATTRIBUTION}")
    try:
        publishing.publish_release(publishing.gh_real, tag, files, f"Sabiá {tag}", notes)
    except (publishing.GhError, publishing.ReleaseAlreadyPublished) as e:
        sys.exit(f"Release não publicada: {e}")
    print(f"Release {tag} publicada com {len(files)} pacotes.")

    shutil.copyfile(config.DIST / "catalogo.json", root_catalog)
    readme = config.REPO / "README.md"
    readme.write_text(publishing.update_readme(readme.read_text(encoding="utf-8"), publishing.downloads_table(cat)),
                      encoding="utf-8")
    print(f"catalogo.json e a tabela de downloads do README gravados ({config.REPO})")
    if args.commit:
        commit_files = ["catalogo.json", "README.md"]
        for command in (["add", *commit_files], ["commit", "-m", f"Geração {tag}", "--", *commit_files]) + \
                       ((["push"],) if args.push else ()):
            r = _git(*command)
            if r.returncode != 0:
                sys.exit(f"git {' '.join(command)} falhou: {r.stderr.strip() or r.stdout.strip()}")
    if args.push:  # só agora o catálogo publicado aponta para a geração nova
        deleted, warning = publishing.prune_after_publish(publishing.gh_real, tag, config.KEEP_GENERATIONS)
        if deleted:
            print(f"Releases antigas apagadas: {', '.join(deleted)}.")
        if warning:
            print(f"::warning::{warning}")


if __name__ == "__main__":
    main()
