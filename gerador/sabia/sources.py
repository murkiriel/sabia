"""As fontes de uma geração: o extrato do Brasil no OpenStreetMap e os municípios do IBGE (malha e nomes).

O extrato só é baixado de novo quando o openstreetmap.fr tem versão mais nova (md5 publicado ao lado do arquivo);
depois do download, o md5 é conferido. Se o site troca o extrato durante o download, o md5 e a data são lidos de novo
e, se mudaram, a versão nova é baixada uma vez; se não mudaram, o arquivo veio corrompido e a geração para.

Para gerar aqui sem baixar o Brasil, `local_extract` usa um extrato já baixado (a data vem do cabeçalho do .pbf).

Os arquivos do IBGE ficam guardados em data/raw/ e são conferidos sempre, no cache e no download: uma API pode
responder 200 com uma página de erro, e sem a conferência ela quebraria todas as gerações seguintes.
"""
from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Dict, List, Optional, Tuple

import osmium
from shapely.geometry import shape
from shapely.geometry.base import BaseGeometry

from . import config, net
from .util import file_hash

# Espera base entre tentativas, em segundos (multiplicada pelo número da tentativa). Os testes zeram.
RETRY_DELAY = 10

MESH_FILE = "ibge_malha_municipios.json"
NAMES_FILE = "ibge_municipios.json"


@dataclass
class Municipality:
    code: str                          # código do IBGE, 7 dígitos; os 2 primeiros são a UF
    name: str
    uf: str
    geometry: Optional[BaseGeometry]   # None: município que a malha ainda não tem


def _published() -> Tuple[str, str]:
    """(timestamp, md5) do extrato publicado agora."""
    state = dict(line.split("=", 1) for line in net.fetch_text(config.OSM_STATE_URL, delay=RETRY_DELAY).splitlines()
                 if "=" in line)
    timestamp = state["timestamp"].replace("\\:", ":")
    md5 = net.fetch_text(config.OSM_MD5_URL, delay=RETRY_DELAY).split()[0]
    return timestamp, md5


def _local_matches(pbf: Path, local_meta: Path, md5: str) -> bool:
    """O extrato local é o publicado? Confia no .meta.json só se o tamanho também bater; senão confere pelo md5."""
    if not pbf.exists():
        return False
    if local_meta.exists():
        meta = json.loads(local_meta.read_text(encoding="utf-8"))
        if meta.get("md5") == md5 and meta.get("size") == pbf.stat().st_size:
            return True
    return file_hash(pbf, "md5") == md5  # extrato copiado à mão, meta antigo ou arquivo mexido


def osm_extract() -> Dict[str, object]:
    """Garante data/raw/brazil-latest.osm.pbf na versão mais nova. Devolve {path, url, timestamp, md5, size}."""
    config.RAW.mkdir(parents=True, exist_ok=True)
    pbf = config.RAW / "brazil-latest.osm.pbf"
    local_meta = config.RAW / "brazil-latest.meta.json"

    timestamp, md5 = _published()
    if _local_matches(pbf, local_meta, md5):
        print(f"[osm] extrato local já é o mais novo ({timestamp})")
    else:
        for attempt in (1, 2):
            print(f"[osm] baixando o extrato de {timestamp}...")
            net.download(config.OSM_PBF_URL, pbf, identity=md5, delay=RETRY_DELAY)
            local = file_hash(pbf, "md5")
            if local == md5:
                break
            timestamp_now, md5_now = _published()
            if attempt == 1 and md5_now != md5:
                print(f"[osm] o extrato foi atualizado durante o download ({timestamp_now}); baixando a versão nova")
                timestamp, md5 = timestamp_now, md5_now
                continue
            pbf.unlink()
            raise RuntimeError(f"md5 do extrato não confere: {local} != {md5_now} publicado")
        print(f"[osm] {pbf.stat().st_size / 1e9:.2f} GB, md5 confere")
    meta = {"path": str(pbf), "url": config.OSM_PBF_URL, "timestamp": timestamp, "md5": md5,
            "size": pbf.stat().st_size}
    local_meta.write_text(json.dumps(meta, indent=2), encoding="utf-8")
    return meta


def local_extract(path: Path) -> Dict[str, object]:
    """Um extrato já baixado, no lugar do do Brasil: {path, url: 'local', timestamp, md5, size}. A data vem do
    cabeçalho do arquivo; sem ela, recusa (o catálogo e a trava de geração mais velha dependem da data)."""
    reader = osmium.io.Reader(str(path))
    try:
        header = reader.header()
        timestamp = header.get("osmosis_replication_timestamp") or header.get("timestamp")
    finally:
        reader.close()
    if not timestamp:
        raise RuntimeError(f"o extrato {path} não tem a data no cabeçalho (osmosis_replication_timestamp)")
    return {"path": str(path), "url": "local", "timestamp": timestamp, "md5": file_hash(path, "md5"),
            "size": path.stat().st_size}


def _coverage_problem(codes: List[str]) -> Optional[str]:
    """Falta alguma UF (dito pelo nome, o erro mais útil) ou há municípios de menos?"""
    present = {c[:2] for c in codes}
    missing = sorted(uf for code, uf in config.IBGE_STATE_CODES.items() if code not in present)
    if missing:
        return f"faltam as UFs {', '.join(missing)}"
    if len(codes) < config.MIN_MUNICIPALITIES:
        return f"só {len(codes)} municípios (mínimo {config.MIN_MUNICIPALITIES})"
    return None


def mesh_problem(path: Path) -> Optional[str]:
    """O que há de errado com a malha municipal, ou None se é um GeoJSON com os municípios do país inteiro."""
    try:
        gj = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as e:
        return f"não é JSON ({e.__class__.__name__})"
    features = gj.get("features") if isinstance(gj, dict) else None
    if not isinstance(features, list):
        return "sem a lista `features`"
    codes = [str((f.get("properties") or {}).get("codarea")) for f in features if isinstance(f, dict)]
    return _coverage_problem(codes)


def names_problem(path: Path) -> Optional[str]:
    """O que há de errado com a lista de municípios, ou None se ela tem o país inteiro."""
    try:
        rows = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as e:
        return f"não é JSON ({e.__class__.__name__})"
    if not isinstance(rows, list) or not all(isinstance(r, dict) and "municipio-id" in r and "municipio-nome" in r
                                             and "UF-sigla" in r for r in rows):
        return "não é a lista de municípios (municipio-id, municipio-nome, UF-sigla)"
    return _coverage_problem([str(r["municipio-id"]) for r in rows])


def _checked_download(url: str, name: str, problem: Callable[[Path], Optional[str]], label: str) -> Path:
    """Garante data/raw/<name>, conferido por `problem` no cache e no download; nunca grava um arquivo ruim."""
    config.RAW.mkdir(parents=True, exist_ok=True)
    dest = config.RAW / name
    if dest.exists():
        found = problem(dest)
        if found is None:
            return dest
        print(f"[ibge] {label} guardada inválida ({found}); baixando de novo")
        dest.unlink()
    updated = dest.with_name(dest.name + ".novo")
    print(f"[ibge] baixando {label}...")
    net.download(url, updated, delay=RETRY_DELAY)
    found = problem(updated)
    if found is not None:
        updated.unlink()
        raise RuntimeError(f"{label} do IBGE veio inválida ({found}): {url}")
    updated.replace(dest)
    return dest


def municipal_mesh() -> Path:
    """data/raw/ibge_malha_municipios.json: o polígono de cada município (código em `codarea`)."""
    return _checked_download(config.IBGE_MESH_URL, MESH_FILE, mesh_problem, "a malha municipal")


def municipality_names() -> Path:
    """data/raw/ibge_municipios.json: código, nome oficial e UF de cada município."""
    return _checked_download(config.IBGE_NAMES_URL, NAMES_FILE, names_problem, "a lista de municípios")


def load_municipalities(mesh: Path, names: Path) -> List[Municipality]:
    """Os municípios da lista de nomes, cada um com o polígono da malha (None se a malha ainda não tem)."""
    geometries: Dict[str, BaseGeometry] = {}
    for f in json.loads(mesh.read_text(encoding="utf-8"))["features"]:
        if f.get("geometry"):
            geometries[str(f["properties"]["codarea"])] = shape(f["geometry"])
    out = []
    for r in json.loads(names.read_text(encoding="utf-8")):
        code = str(r["municipio-id"])
        out.append(Municipality(code, r["municipio-nome"], r["UF-sigla"], geometries.get(code)))
    return sorted(out, key=lambda m: m.code)
