"""Instala o SQLite 3.22 (o do Android 10) em data/tools/, para a trava que abre os bancos nele (G7e).

    python scripts/install_sqlite.py

No Linux (o GitHub Actions), baixa o código-fonte oficial (amalgamation) e compila uma biblioteca só com FTS3 e FTS4,
como o Android: sem FTS5, sem R-Tree, sem a sintaxe estendida do FTS. Precisa do gcc. No Windows, baixa a DLL
oficial. O sha256 de cada arquivo é conferido antes de usar.
"""
from __future__ import annotations

import io
import shutil
import subprocess
import sys
import tempfile
import zipfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from sabia import net, sqlite_old  # noqa: E402
from sabia.util import file_hash  # noqa: E402

BASE_URL = "https://www.sqlite.org/2018/"
SOURCES = {
    "amalgamation": ("sqlite-amalgamation-3220000.zip",
                     "0db7cb47613475c5060ce47ad24dc73875cddeda4d13196ab3a98b356326ac72"),
    "windows": ("sqlite-dll-win64-x64-3220000.zip",
                "e71699521e77dda11c6a5117ff5c3a336421f417737e452310d31ef01909732a"),
}
# As opções de FTS do Android (sem SQLITE_ENABLE_FTS3_PARENTHESIS: sintaxe padrão de consulta)
CFLAGS = ["-O2", "-shared", "-fPIC", "-DSQLITE_ENABLE_FTS3", "-DSQLITE_ENABLE_FTS4", "-DSQLITE_THREADSAFE=1"]


def _fetch(kind: str, folder: Path) -> bytes:
    name, sha256 = SOURCES[kind]
    dest = folder / name
    net.download(BASE_URL + name, dest, delay=5)
    found = file_hash(dest)
    if found != sha256:
        raise SystemExit(f"sha256 de {name} não confere: {found} != {sha256}")
    return dest.read_bytes()


def main() -> None:
    target = sqlite_old.library_path()
    if target.exists():
        print(f"já instalado: {target}")
        return
    target.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory() as tmp:
        folder = Path(tmp)
        if sys.platform == "win32":
            with zipfile.ZipFile(io.BytesIO(_fetch("windows", folder))) as z:
                target.write_bytes(z.read("sqlite3.dll"))
        else:
            with zipfile.ZipFile(io.BytesIO(_fetch("amalgamation", folder))) as z:
                source = folder / "sqlite3.c"
                source.write_bytes(z.read("sqlite-amalgamation-3220000/sqlite3.c"))
            compiler = shutil.which("gcc") or shutil.which("cc")
            if compiler is None:
                raise SystemExit("sem gcc para compilar o SQLite 3.22")
            subprocess.run([compiler, *CFLAGS, str(source), "-o", str(target), "-lpthread", "-ldl", "-lm"],
                           check=True)
    print(f"SQLite {sqlite_old.Library(target).version} instalado em {target}")


if __name__ == "__main__":
    main()
