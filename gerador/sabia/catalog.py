"""O catalogo.json: o índice que quem usa os pacotes lê para saber o que baixar, de onde e como conferir.

    {
      "schema": 1,                          a versão deste formato de catálogo
      "format_version": 1,                  a versão do formato dos bancos (meta.format_version); recuse maior
      "build_id": "2026-10-05-93a54bc6",    data + 8 primeiros do md5 do extrato; também o nome da release
      "built_at": "2026-10-05T12:00:00Z",
      "generator_commit": "2d3c2f6",
      "osm": {"timestamp", "md5", "url"},   o extrato do OpenStreetMap usado
      "release_url": "https://github.com/Murkiriel/sabia/releases/download/2026-10-05-93a54bc6/",
      "attribution": "...",
      "base": {"file", "bytes", "sha256", "bytes_db", "bbox", "counts": {"municipality", "road"}},
      "states": {"GO": {"name", "file", "bytes", "sha256", "bytes_db", "bbox",
                        "counts": {"items", "place", "street", "road", "poi", "district", "street_line",
                                   "municipality", "house_number", "house_number_rungs"}}, ...},
      "conformance": {"file", "bytes", "sha256", "bytes_unpacked", "conformance_version",
                      "cases": {"unit", "search", "which_street"}},   o conjunto de conformidade da busca, se houver
      "contract": {...}                     o contrato de catálogo comum v1 (abaixo)
    }

`bytes` é o tamanho do .sqlite.zst (o que se baixa); `bytes_db`, o do banco descompactado (o espaço no aparelho).
`counts` do estado: os registros (`items`) e por classe, os bairros, os pedaços de traçado, os municípios, as ruas com
número das casas (`house_number`, as linhas da tabela) e os degraus das escadas delas (`house_number_rungs`).
`bbox` = [lat mín, lng mín, lat máx, lng máx] dos municípios do estado (na base, o Brasil), arredondado para fora: a
latitude primeiro, ao contrário do GeoJSON (D13 em docs/DECISOES.md), em graus WGS84.

`conformance` é o conjunto de conformidade da busca da geração (docs/CONFORMIDADE.md), anexo da mesma release; só
existe quando a etapa `conformance` deixou em data/dist/ um conjunto desta geração e deste formato.

A chave `contract` é o mesmo catálogo no formato comum aos quatro geradores irmãos (docs/CATALOGO.md, esquema em
docs/catalogo-v1.schema.json): só acrescenta, nenhuma chave acima muda. Sai inteira das chaves acima e do config, então
dá para refazê-la de um catálogo já publicado (scripts/recatalog.py).
"""
from __future__ import annotations

import json
import math
import subprocess
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, Iterable, List, Mapping, Optional, Sequence, Tuple

from . import config, conformance, database
from .sources import Municipality
from .util import file_hash

SCHEMA = 1


def bbox_of(boxes: Iterable[Tuple[float, float, float, float]]) -> List[float]:
    """O retângulo que contém todos (lat mín, lng mín, lat máx, lng máx), arredondado para fora em 2 casas."""
    boxes = list(boxes)
    lat_min = min(b[0] for b in boxes)
    lng_min = min(b[1] for b in boxes)
    lat_max = max(b[2] for b in boxes)
    lng_max = max(b[3] for b in boxes)
    return [math.floor(lat_min * 100) / 100, math.floor(lng_min * 100) / 100,
            math.ceil(lat_max * 100) / 100, math.ceil(lng_max * 100) / 100]


def _bounds(municipalities: Sequence[Municipality]) -> List[Tuple[float, float, float, float]]:
    out = []
    for m in municipalities:
        if m.geometry is not None:
            x0, y0, x1, y1 = m.geometry.bounds
            out.append((y0, x0, y1, x1))
    return out


def git_commit_full(revision: str = "HEAD") -> Optional[str]:
    """O SHA completo (40 dígitos) de `revision` no repositório, ou None fora de um checkout do git."""
    try:
        r = subprocess.run(["git", "-C", str(config.REPO), "rev-parse", "--verify", "--quiet",
                            f"{revision}^{{commit}}"], capture_output=True, text=True, timeout=10)
    except (OSError, subprocess.SubprocessError):
        return None
    sha = r.stdout.strip()
    return sha if r.returncode == 0 and len(sha) == 40 else None


def git_commit_hash() -> str:
    """Hash curto do commit do repositório, ou 'desconhecido' fora de um checkout do git."""
    try:
        r = subprocess.run(["git", "-C", str(config.REPO), "rev-parse", "--short", "HEAD"],
                           capture_output=True, text=True, timeout=10)
    except (OSError, subprocess.SubprocessError):
        return "desconhecido"
    return r.stdout.strip() if r.returncode == 0 and r.stdout.strip() else "desconhecido"


def _entry(package: dict, boxes: List[Tuple[float, float, float, float]], counts: dict) -> dict:
    path = config.DIST / package["file"]
    return {"file": package["file"], "bytes": path.stat().st_size, "sha256": file_hash(path),
            "bytes_db": package["bytes_db"], "bbox": bbox_of(boxes), "counts": counts}


def build_catalog(packages: dict, municipalities: Sequence[Municipality],
                  generator_commit: Optional[str] = None, generator_commit_full: Optional[str] = None) -> dict:
    """O catálogo a partir do pacotes.json da etapa build e dos arquivos em data/dist/. `generator_commit` (curto) e
    `generator_commit_full` (40 dígitos) vêm do git quando não são dados; um SHA completo em `generator_commit` vale
    para os dois."""
    if generator_commit_full is None:
        if generator_commit and len(generator_commit) == 40:
            generator_commit_full = generator_commit
        elif not generator_commit:
            generator_commit_full = git_commit_full()
    gid = packages["build_id"]
    osm = packages["osm"]
    states: Dict[str, dict] = {}
    for uf in sorted(packages["states"]):
        p = packages["states"][uf]
        states[uf] = {"name": config.STATES[uf],
                      **_entry(p, _bounds([m for m in municipalities if m.uf == uf]), dict(p["counts"]))}
    base_counts = {k: v for k, v in packages["base"]["counts"].items() if k != "without_point"}
    cat = {
        "schema": SCHEMA,
        "format_version": database.FORMAT_VERSION,
        "build_id": gid,
        "built_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "generator_commit": generator_commit or git_commit_hash(),
        "osm": {"timestamp": osm["timestamp"], "md5": osm["md5"], "url": osm["url"]},
        "release_url": config.RELEASE_URL.format(tag=gid),
        "attribution": config.ATTRIBUTION,
        "base": _entry(packages["base"], _bounds(municipalities), base_counts),
        "states": states,
    }
    found = conformance_entry(config.DIST / conformance.FILE, gid, cat["format_version"])
    if found is not None:
        cat["conformance"] = found
    cat["contract"] = contract(cat, generator_commit_full)
    return cat


def conformance_entry(path: Path, build_id: str, format_version: int) -> Optional[dict]:
    """A chave `conformance` do catálogo: o conjunto de conformidade em `path`, se existe e é desta geração e deste
    formato dos bancos (outro fica de fora; o scripts/publish.py barra a publicação nesse caso)."""
    if not path.exists():
        return None
    doc = conformance.load(path)
    if doc.get("build_id") != build_id or doc.get("format_version") != format_version:
        print(f"[catálogo] AVISO: {path.name} é de {doc.get('build_id')} (formato {doc.get('format_version')}): "
              "fica fora do catálogo")
        return None
    import zstandard
    size = zstandard.frame_content_size(path.read_bytes()[:18])
    cases = conformance.summary(doc)
    return {"file": path.name, "bytes": path.stat().st_size, "sha256": file_hash(path),
            "bytes_unpacked": size if size > 0 else None, "conformance_version": doc["conformance_version"],
            "cases": {key: cases[key] for key in ("unit", "search", "which_street")}}


# O contrato de catálogo comum (docs/CATALOGO.md). Os nomes e valores fixos são os da especificação v1.
CONTRACT_NAME = "catalogo-comum"
CONTRACT_VERSION = 1
CONTRACT_MIN_READER_VERSION = 1
DATASET = "sabia"
BBOX_ORDER = "lat_min,lon_min,lat_max,lon_max"
DATA_FORMAT = "sabia-sqlite"
# Os pacotes são .sqlite.zst: um banco SQLite num quadro zstd (build.py).
PACKAGE_FORMAT = "sqlite"
PACKAGE_MEDIA_TYPE = "application/zstd"
PACKAGE_UNPACK = ["zstd"]
# Onde estão, no repositório, o formato dos bancos, a busca (o passo a passo para outra linguagem) e a implementação de
# referência; o catálogo aponta para eles no commit da geração.
FORMAT_SPEC = "docs/FORMATO.md"
SEARCH_SPEC = "docs/CONSUMO.md#buscar"
SEARCH_REFERENCE = "gerador/sabia/search.py"
# O conjunto de conformidade da busca (docs/CONFORMIDADE.md): o arquivo `kind` conformance da lista uniforme.
CONFORMANCE_ID = "conformidade"
CONFORMANCE_FORMAT = "sabia-search-cases"
CONFORMANCE_SPEC = "docs/CONFORMIDADE.md"

# As cópias versionadas no repositório (sabia/sources.py, _versioned_copy): (id, nome, constante do sha256, constante
# da data, constante da URL de origem). O sha256 é o do conteúdo descompactado; o scripts/recatalog.py lê as constantes
# do config no commit da geração, para não atribuir a ela uma cópia que entrou depois.
COPIES = (
    ("ibge-malha-municipios", "IBGE, malha municipal", "IBGE_MESH_COPY_SHA256", "IBGE_COPIES_DATE", "IBGE_MESH_URL"),
    ("ibge-municipios", "IBGE, lista de municípios", "IBGE_NAMES_COPY_SHA256", "IBGE_COPIES_DATE", "IBGE_NAMES_URL"),
    ("dnit-snv-marcos", "DNIT, marcos de quilômetro do SNV", "SNV_COPY_SHA256", "SNV_COPY_DATE", "SNV_WFS_URL"),
    ("anac-aerodromos-publicos", "ANAC, aeródromos públicos", "ANAC_PUBLIC_COPY_SHA256", "ANAC_COPIES_DATE",
     "ANAC_PUBLIC_URL"),
    ("anac-aerodromos-privados", "ANAC, aeródromos privados", "ANAC_PRIVATE_COPY_SHA256", "ANAC_COPIES_DATE",
     "ANAC_PRIVATE_URL"),
    ("antt-postos-prf", "ANTT, postos da PRF", "PRF_COPY_SHA256", "PRF_COPY_DATE", "PRF_URL"),
)
SOURCE_CONSTANTS = tuple(sorted({name for copy in COPIES for name in copy[2:]}))


def config_sources() -> Dict[str, str]:
    return {name: getattr(config, name) for name in SOURCE_CONSTANTS}


def _sources(cat: dict, constants: Mapping[str, str]) -> list:
    osm = cat["osm"]
    sources = [{"id": "openstreetmap", "name": "OpenStreetMap (extrato do Brasil)", "url": osm["url"],
                "date": osm["timestamp"], "license": "ODbL-1.0", "checksums": {"md5": osm["md5"]}}]
    for source_id, name, sha_name, date_name, url_name in COPIES:
        if constants.get(sha_name):
            sources.append({"id": source_id, "name": f"{name} (cópia versionada no repositório)",
                            "url": constants.get(url_name), "date": constants.get(date_name), "license": None,
                            "checksums": {"sha256": constants[sha_name]},
                            "note": "sha256 do conteúdo descompactado da cópia gzip versionada em gerador/"})
    return sources


def _file(file_id: str, kind: str, region: str, entry: dict, release_url: str) -> dict:
    return {
        "id": file_id, "kind": kind, "region": region, "url": release_url + entry["file"],
        "sha256": entry["sha256"], "bytes": entry["bytes"], "bytes_unpacked": entry["bytes_db"],
        "media_type": PACKAGE_MEDIA_TYPE, "unpack": list(PACKAGE_UNPACK), "format": PACKAGE_FORMAT,
        "bbox": list(entry["bbox"]),
        "coverage_level": "BASE_HIGHWAYS_ONLY" if kind == "base" else "DETAILED",
        "requires": [],
    }


def _conformance_file(entry: dict, release_url: str) -> dict:
    return {"id": CONFORMANCE_ID, "kind": "conformance", "region": None, "url": release_url + entry["file"],
            "sha256": entry["sha256"], "bytes": entry["bytes"], "bytes_unpacked": entry.get("bytes_unpacked"),
            "media_type": PACKAGE_MEDIA_TYPE, "unpack": list(PACKAGE_UNPACK), "format": CONFORMANCE_FORMAT,
            "bbox": None, "coverage_level": None, "requires": [],
            "conformance_version": entry["conformance_version"]}


def _at_commit(path: str, commit: Optional[str]) -> str:
    return f"{config.REPOSITORY_URL}/blob/{commit or 'main'}/{path}"


def compatibility(cat: dict, commit: Optional[str]) -> dict:
    """O bloco `compatibility`: o formato dos bancos (o `format_version` do topo) e o SQLite que os abre."""
    block = {
        "format_version": cat["format_version"],
        "sqlite_min_version": config.SQLITE_MIN_VERSION,
        "sqlite_modules": list(config.SQLITE_MODULES),
        "sqlite_not_used": list(config.SQLITE_NOT_USED),
        "format_spec": _at_commit(FORMAT_SPEC, commit),
        "search_spec": _at_commit(SEARCH_SPEC, commit),
        "search_reference": _at_commit(SEARCH_REFERENCE, commit),
    }
    if cat.get("conformance"):
        block["conformance_version"] = cat["conformance"]["conformance_version"]
        block["conformance_spec"] = _at_commit(CONFORMANCE_SPEC, commit)
    return {
        "mix_generations": True,
        "data_format": {"name": DATA_FORMAT, "version": str(cat["format_version"])},
        DATASET: block,
    }


def contract(cat: dict, generator_commit_full: Optional[str],
             source_constants: Optional[Mapping[str, str]] = None) -> dict:
    """O bloco `contract` (docs/CATALOGO.md) a partir das chaves antigas do catálogo `cat` e do config."""
    if generator_commit_full is not None and not generator_commit_full.startswith(cat["generator_commit"]):
        raise ValueError(f"o commit {generator_commit_full} não é o {cat['generator_commit']} do catálogo")
    release_url = cat["release_url"]
    files = [_file("base", "base", "BR", cat["base"], release_url)]
    files += [_file(uf, "uf", uf, entry, release_url) for uf, entry in sorted(cat["states"].items())]
    if cat.get("conformance"):
        files.append(_conformance_file(cat["conformance"], release_url))
    return {
        "name": CONTRACT_NAME,
        "version": CONTRACT_VERSION,
        "min_reader_version": CONTRACT_MIN_READER_VERSION,
        "dataset": DATASET,
        "build_id": cat["build_id"],
        "built_at": cat["built_at"],
        "release_url": release_url,
        "generator": {"repository": config.REPOSITORY_URL, "commit": generator_commit_full},
        "license": {"data": config.DATA_LICENSE, "code": config.CODE_LICENSE, "attribution": cat["attribution"]},
        "coordinates": {"crs": "EPSG:4326", "bbox_order": BBOX_ORDER},
        "osm_snapshot": {"date": cat["osm"]["timestamp"], "md5": cat["osm"]["md5"]},
        "sources": _sources(cat, config_sources() if source_constants is None else source_constants),
        "compatibility": compatibility(cat, generator_commit_full),
        "files": files,
    }


def save(cat: dict, dest: Path) -> None:
    dest.write_text(json.dumps(cat, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
