"""As cópias versionadas das fontes que não respondem aos executores do GitHub Actions (desde 2026-11-04 o IBGE; o
DNIT e a ANAC na sonda de 2026-11-10; a ANTT na tarde do mesmo dia): a geração usa só as cópias
(sources._versioned_copy), conferidas pelo sha256 do config. `refresh` as baixa de novo de uma conexão que alcança as
fontes (scripts/update_copies.py), confere cada uma como a geração conferia o download e grava em gzip sem data no
cabeçalho (os mesmos bytes para o mesmo conteúdo); depois, os sha256 novos vão para o config à mão (a cópia nova muda
o resultado da geração).

| Cópia | Fonte | Conteúdo |
|---|---|---|
| `ibge_malha_municipios.json.gz` | API de malhas do IBGE | A malha municipal, como a API devolve |
| `ibge_municipios.json.gz` | API de localidades do IBGE | A lista dos municípios, como a API devolve |
| `dnit_snv_marcos.json.gz` | WFS do SNV do DNIT | Os marcos de km já calculados (snv.markers_json; o SNV, 128 MB) |
| `anac_aerodromos_publicos.json.gz`, `..._privados.json.gz` | Dados abertos da ANAC | As listas, como a ANAC publica |
| `antt_postos_prf.json.gz` | Dados abertos da ANTT | Os postos da PRF, como a ANTT publica |
"""
from __future__ import annotations

import functools
import gzip
import hashlib
import shutil
import tempfile
from pathlib import Path
from typing import Dict, List, Tuple

from . import anac, config, snv, sources


def write_copy(body: bytes, path: Path) -> str:
    """Grava `body` em gzip (nível 9, sem data nem nome no cabeçalho) e devolve o sha256 do conteúdo."""
    path.write_bytes(gzip.compress(body, compresslevel=9, mtime=0))
    return hashlib.sha256(body).hexdigest()


def refresh(dest: Path, today: str) -> Dict[str, str]:
    """Baixa e confere as cinco fontes e grava as cópias em `dest` só se todas passarem. Devolve {nome da constante
    do sha256 no config: sha256}."""
    bodies: List[Tuple[str, str, bytes]] = []  # (constante, arquivo da cópia, conteúdo)
    mesh = sources._checked_download(config.IBGE_MESH_URL, sources.MESH_FILE, sources.mesh_problem,
                                     "a malha municipal")
    bodies.append(("IBGE_MESH_COPY_SHA256", config.IBGE_MESH_COPY.name, mesh.read_bytes()))
    names = sources._checked_download(config.IBGE_NAMES_URL, sources.NAMES_FILE, sources.names_problem,
                                      "a lista de municípios")
    bodies.append(("IBGE_NAMES_COPY_SHA256", config.IBGE_NAMES_COPY.name, names.read_bytes()))
    raw_snv = sources._checked_download(snv.url(today), "dnit_snv.json", snv.problem, "a malha do SNV", "dnit",
                                        "do DNIT")
    version, day = snv.version(raw_snv)
    markers = snv.markers_json(snv.markers(snv.load(raw_snv)), version, day)
    with tempfile.TemporaryDirectory() as tmp:
        check = Path(tmp) / "marcos.json"
        check.write_bytes(markers)
        problem = snv.markers_problem(check)
    if problem is not None:
        raise RuntimeError(f"os marcos do SNV {version} não servem ({problem})")
    bodies.append(("SNV_COPY_SHA256", config.SNV_COPY.name, markers))
    for constant, url, name, copy, minimum, label in (
            ("ANAC_PUBLIC_COPY_SHA256", config.ANAC_PUBLIC_URL, sources.ANAC_PUBLIC_FILE, config.ANAC_PUBLIC_COPY,
             anac.MIN_PUBLIC, "a lista de aeródromos públicos"),
            ("ANAC_PRIVATE_COPY_SHA256", config.ANAC_PRIVATE_URL, sources.ANAC_PRIVATE_FILE, config.ANAC_PRIVATE_COPY,
             anac.MIN_PRIVATE, "a lista de aeródromos privados")):
        path = sources._checked_download(url, name, functools.partial(anac.problem, minimum=minimum), label,
                                         "anac", "da ANAC")
        bodies.append((constant, copy.name, path.read_bytes()))
    from . import prf
    path = sources._checked_download(config.PRF_URL, sources.PRF_FILE, prf.problem, "a lista de postos da PRF",
                                     "antt", "da ANTT")
    bodies.append(("PRF_COPY_SHA256", config.PRF_COPY.name, path.read_bytes()))
    dest.mkdir(parents=True, exist_ok=True)
    out = {}
    with tempfile.TemporaryDirectory() as tmp:
        staged = []
        for constant, file_name, body in bodies:
            out[constant] = write_copy(body, Path(tmp) / file_name)
            staged.append(file_name)
        for file_name in staged:
            shutil.move(str(Path(tmp) / file_name), str(dest / file_name))
    return out
