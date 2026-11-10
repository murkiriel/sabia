"""As fontes de uma geração: o extrato do Brasil no OpenStreetMap, os municípios do IBGE (malha e nomes) e as fontes
novas da Parte 9 da pesquisa (localidades do IBGE, postos da PRF, CNES, Overture, SNV, ANAC, GeoNames, Wikidata, ANP).

O extrato só é baixado de novo quando o openstreetmap.fr tem versão mais nova (md5 publicado ao lado do arquivo);
depois do download, o md5 é conferido. Se o site troca o extrato durante o download, o md5 e a data são lidos de novo
e, se mudaram, a versão nova é baixada uma vez; se não mudaram, o arquivo veio corrompido e a geração para.

Para gerar aqui sem baixar o Brasil, `local_extract` usa um extrato já baixado (a data vem do cabeçalho do .pbf).

A malha municipal e a lista de municípios do IBGE vêm de cópias versionadas no repositório (gzip, sha256 no config),
sem rede: desde 2026-11-04 a API do IBGE não responde aos executores do GitHub Actions. Os outros arquivos ficam
guardados em data/raw/ e são conferidos sempre, no cache e no download: uma API pode
responder 200 com uma página de erro, e sem a conferência ela quebraria todas as gerações seguintes. Uma resposta
ruim é tentada de novo, com espera, e registrada no log (status, tipo, tamanho, começo do corpo); o corpo fica em
data/raw/ como `.invalido`, para o artefato do workflow. As fontes novas são baixadas e conferidas do mesmo jeito.

A data de cada fonte conferida (o Last-Modified do site; sem ele, o dia do download) fica ao lado do arquivo, em
`<arquivo>.fonte.json`, e vai para o registro da geração (data/build/fontes.json, depois o geracao.json).
"""
from __future__ import annotations

import gzip
import hashlib
import json
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
from pathlib import Path
from typing import Callable, Dict, List, Optional, Sequence, Tuple

import osmium
from shapely.geometry import shape
from shapely.geometry.base import BaseGeometry

from . import config, net
from .util import file_hash

# Espera base entre tentativas, em segundos (multiplicada pelo número da tentativa). Os testes zeram.
RETRY_DELAY = 10

# Arquivos do IBGE: quantas vezes baixar quando a resposta vem ruim, e a espera base entre elas (multiplicada pelo
# número da tentativa: 60 s, depois 120 s). Os testes zeram a espera.
IBGE_ATTEMPTS = 3
IBGE_RETRY_DELAY = 60

MESH_FILE = "ibge_malha_municipios.json"
NAMES_FILE = "ibge_municipios.json"
LOCALITIES_FILE = "ibge_localidades.zip"
PRF_FILE = "antt_postos_prf.json"
CNES_FILE = "cnes_estabelecimentos.zip"
OVERTURE_FILE = "overture_lugares.parquet"
SNV_FILE = "dnit_snv.json"
ANAC_PUBLIC_FILE = "anac_aerodromos_publicos.json"
ANAC_PRIVATE_FILE = "anac_aerodromos_privados.json"
GEONAMES_PLACES_FILE = "geonames_lugares.zip"
GEONAMES_NAMES_FILE = "geonames_nomes.zip"
WIKIDATA_FILE = "wikidata_turismo.json"
ANP_FILE = "anp_postos.json"


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


def _record_path(name: str) -> Path:
    return config.RAW / (name + ".fonte.json")


def _source_date(last_modified: str, downloaded_at: datetime) -> str:
    """'Fri, 28 Aug 2026 18:27:01 GMT' -> '2026-08-28'; sem o cabeçalho (ou ilegível), o dia do download."""
    try:
        return parsedate_to_datetime(last_modified).strftime("%Y-%m-%d")
    except (TypeError, ValueError, IndexError):
        return downloaded_at.strftime("%Y-%m-%d")


def source_record(name: str) -> Optional[dict]:
    """{url, date, downloaded_at} do arquivo `name` de data/raw/, ou None se ele nunca foi baixado por aqui."""
    path = _record_path(name)
    if not path.exists():
        return None
    try:
        found = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    return found if isinstance(found, dict) else None


def _checked_download(url: str, name: str, problem: Callable[[Path], Optional[str]], label: str,
                      tag: str = "ibge", origin: str = "do IBGE") -> Path:
    """Garante data/raw/<name>, conferido por `problem` no cache e no download; nunca grava um arquivo ruim com o
    nome final. `tag` vai no começo de cada linha do log; `origin` diz de quem é o arquivo no erro final.

    Resposta ruim (status de erro, mesmo depois das tentativas do net.download, ou conteúdo que não passa na
    conferência) é tentada de novo, até IBGE_ATTEMPTS tentativas, com espera crescente. Cada uma vai para o log com o
    status, o tipo, o tamanho e o começo do corpo, e o corpo fica em data/raw/<name>.<tentativa>.invalido (o workflow
    leva esses arquivos para o artefato)."""
    config.RAW.mkdir(parents=True, exist_ok=True)
    dest = config.RAW / name
    if dest.exists():
        found = problem(dest)
        if found is None:
            return dest
        print(f"[{tag}] {label} guardada inválida ({found}); guardada em {name}.guardado.invalido, baixando de novo")
        dest.replace(dest.with_name(name + ".guardado.invalido"))
    updated = dest.with_name(dest.name + ".novo")
    failure = ""
    for attempt in range(1, IBGE_ATTEMPTS + 1):
        print(f"[{tag}] baixando {label} (tentativa {attempt} de {IBGE_ATTEMPTS})...")
        try:
            answer = net.download(url, updated, delay=RETRY_DELAY)
        except net.DownloadError as e:
            failure = str(e)
        else:
            found = problem(updated)
            if found is None:
                updated.replace(dest)
                now = datetime.now(timezone.utc)
                _write_record(name, {"url": url, "date": _source_date(answer.last_modified, now),
                                     "downloaded_at": now.strftime("%Y-%m-%dT%H:%M:%SZ")})
                return dest
            kept = dest.with_name(f"{name}.{attempt}.invalido")
            updated.replace(kept)
            with open(kept, "rb") as f:
                start = net.body_start(f.read(net.BODY_START * 4))
            failure = (f"{found}; HTTP {answer.status}, Content-Type {answer.content_type or '(nenhum)'}, "
                       f"Content-Encoding {answer.content_encoding}, {answer.size} bytes, guardado em {kept.name}, "
                       f"início do corpo: {start}")
        print(f"[{tag}] {label} veio inválida na tentativa {attempt} de {IBGE_ATTEMPTS}: {failure}")
        if attempt < IBGE_ATTEMPTS:
            print(f"[{tag}] tentando de novo em {IBGE_RETRY_DELAY * attempt} s")
            time.sleep(IBGE_RETRY_DELAY * attempt)
    raise RuntimeError(f"{label} {origin} veio inválida nas {IBGE_ATTEMPTS} tentativas ({failure}): {url}")


def _versioned_copy(copy: Path, sha256: str, sha256_name: str, name: str, url: str,
                    problem: Callable[[Path], Optional[str]], label: str) -> Path:
    """data/raw/<name> a partir da cópia versionada `copy` (gzip): o sha256 do conteúdo tem de ser o do config e o
    conteúdo tem de passar em `problem`. Nada vai para a rede; um data/raw/<name> de outra geração é trocado."""
    body = gzip.decompress(copy.read_bytes())
    found = hashlib.sha256(body).hexdigest()
    if found != sha256:
        raise RuntimeError(f"{copy.name} mudou (sha256 {found}, o config espera {sha256}): uma cópia nova muda o "
                           f"município de registros; confira e atualize o {sha256_name}")
    config.RAW.mkdir(parents=True, exist_ok=True)
    dest = config.RAW / name
    updated = dest.with_name(name + ".novo")
    updated.write_bytes(body)
    bad = problem(updated)
    if bad is not None:
        updated.unlink()
        raise RuntimeError(f"{label} em {copy.name} não serve ({bad})")
    updated.replace(dest)
    _write_record(name, {"url": url, "date": config.IBGE_COPIES_DATE, "copy": copy.name})
    print(f"[ibge] {label}: {copy.name}, sha256 confere")
    return dest


def municipal_mesh() -> Path:
    """data/raw/ibge_malha_municipios.json: o polígono de cada município (código em `codarea`), da cópia versionada
    (config.IBGE_MESH_COPY). Desde 2026-11-04 a API do IBGE não responde aos executores do Actions."""
    return _versioned_copy(config.IBGE_MESH_COPY, config.IBGE_MESH_COPY_SHA256, "IBGE_MESH_COPY_SHA256", MESH_FILE,
                           config.IBGE_MESH_URL, mesh_problem, "a malha municipal")


def municipality_names() -> Path:
    """data/raw/ibge_municipios.json: código, nome oficial e UF de cada município, da cópia versionada
    (config.IBGE_NAMES_COPY)."""
    return _versioned_copy(config.IBGE_NAMES_COPY, config.IBGE_NAMES_COPY_SHA256, "IBGE_NAMES_COPY_SHA256",
                           NAMES_FILE, config.IBGE_NAMES_URL, names_problem, "a lista de municípios")


def ibge_localities() -> Path:
    """data/raw/ibge_localidades.zip: a Base de Localidades do IBGE, conferida (HS1; localities.problem)."""
    from . import localities  # aqui: localities usa records, que usa sources
    return _checked_download(config.IBGE_LOCALITIES_URL, LOCALITIES_FILE, localities.problem, "as localidades")


def prf_units() -> Path:
    """data/raw/antt_postos_prf.json: as unidades da PRF nas rodovias concedidas, da ANTT, conferidas (HS2;
    prf.problem)."""
    from . import prf
    return _checked_download(config.PRF_URL, PRF_FILE, prf.problem, "a lista de postos da PRF", "antt", "da ANTT")


def cnes_units() -> Path:
    """data/raw/cnes_estabelecimentos.zip: o CNES do Ministério da Saúde, conferido (HS3; cnes.problem)."""
    from . import cnes
    return _checked_download(config.CNES_URL, CNES_FILE, cnes.problem, "a base do CNES", "cnes",
                             "do CNES (Ministério da Saúde)")


def _write_record(name: str, record: dict) -> None:
    _record_path(name).write_text(json.dumps(record, indent=2), encoding="utf-8")


def overture_places() -> Path:
    """data/raw/overture_lugares.parquet: o recorte do Brasil dos lugares da versão mais nova da Overture, conferido
    (HS4; overture.problem). Um recorte guardado que passa na conferência é usado de novo; um que não passa vira
    `.guardado.invalido`, e um recorte novo que não passa fica em `.invalido` e para a geração."""
    from . import overture
    config.RAW.mkdir(parents=True, exist_ok=True)
    dest = config.RAW / OVERTURE_FILE
    if dest.exists():
        found = overture.problem(dest)
        if found is None:
            return dest
        print(f"[overture] recorte guardado inválido ({found}); guardado em {OVERTURE_FILE}.guardado.invalido")
        dest.replace(dest.with_name(OVERTURE_FILE + ".guardado.invalido"))
    release = overture.latest_release(net.fetch_text(config.OVERTURE_LISTING_URL, delay=RETRY_DELAY))
    source = f"{config.OVERTURE_BUCKET}/release/{release}/theme=places/type=place"
    print(f"[overture] recortando o Brasil dos lugares da versão {release}...", flush=True)
    updated = dest.with_name(OVERTURE_FILE + ".novo")
    overture.extract(source, overture.filesystem(), updated)
    found = overture.problem(updated)
    if found is not None:
        updated.replace(dest.with_name(OVERTURE_FILE + ".invalido"))
        raise RuntimeError(f"o recorte dos lugares da Overture veio inválido ({found}): {source}")
    updated.replace(dest)
    _write_record(OVERTURE_FILE, {"url": f"s3://{source}", "date": release[:10], "release": release,
                                  "downloaded_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")})
    return dest


def snv_roads() -> Path:
    """data/raw/dnit_snv.json: os trechos de eixo principal do SNV em vigor hoje, do WFS do DNIT, conferidos (HS6;
    snv.problem). A data da fonte é o começo da versão do SNV (não há Last-Modified), e a versão vai junto."""
    from . import snv
    path = _checked_download(snv.url(datetime.now(timezone.utc).strftime("%Y-%m-%d")), SNV_FILE, snv.problem,
                             "a malha do SNV", "dnit", "do DNIT")
    record = source_record(SNV_FILE)
    if record is not None and "version" not in record:
        record["version"], record["date"] = snv.version(path)
        _write_record(SNV_FILE, record)
    return path


def anac_aerodromes() -> List[Path]:
    """data/raw/anac_aerodromos_publicos.json e anac_aerodromos_privados.json: as listas de aeródromos da ANAC,
    conferidas cada uma com o seu mínimo (HS8; anac.problem)."""
    from . import anac
    return [_checked_download(config.ANAC_PUBLIC_URL, ANAC_PUBLIC_FILE,
                              lambda p: anac.problem(p, anac.MIN_PUBLIC), "a lista de aeródromos públicos", "anac",
                              "da ANAC"),
            _checked_download(config.ANAC_PRIVATE_URL, ANAC_PRIVATE_FILE,
                              lambda p: anac.problem(p, anac.MIN_PRIVATE), "a lista de aeródromos privados", "anac",
                              "da ANAC")]


def geonames_files() -> List[Path]:
    """data/raw/geonames_lugares.zip e geonames_nomes.zip: os lugares e os nomes alternativos do Brasil no GeoNames,
    conferidos (HS9; geonames.places_problem e names_problem)."""
    from . import geonames
    return [_checked_download(config.GEONAMES_PLACES_URL, GEONAMES_PLACES_FILE, geonames.places_problem,
                              "a lista de lugares do GeoNames", "geonames", "do GeoNames"),
            _checked_download(config.GEONAMES_NAMES_URL, GEONAMES_NAMES_FILE, geonames.names_problem,
                              "a lista de nomes do GeoNames", "geonames", "do GeoNames")]


def wikidata_tourism() -> Path:
    """data/raw/wikidata_turismo.json: os pontos turísticos do Brasil no Wikidata, pela consulta SPARQL, conferidos
    (HS9; wikidata.problem)."""
    from . import wikidata
    return _checked_download(wikidata.url(), WIKIDATA_FILE, wikidata.problem, "a consulta ao Wikidata", "wikidata",
                             "do Wikidata")


def cnefe_name(uf: str) -> str:
    """O arquivo do CNEFE de uma UF em data/raw: cnefe_52_GO.zip."""
    code = next(c for c, s in config.IBGE_STATE_CODES.items() if s == uf)
    return f"cnefe_{code}_{uf}.zip"


def cnefe_problem(path: Path) -> Optional[str]:
    """O que há de errado no zip do CNEFE guardado; None se é um zip com o CSV."""
    import zipfile
    try:
        with zipfile.ZipFile(path) as z:
            if not any(n.lower().endswith(".csv") for n in z.namelist()):
                return "zip sem CSV"
    except (zipfile.BadZipFile, OSError) as e:
        return f"não é zip ({e})"
    return None


def cnefe_files(states: Optional[Sequence[str]] = None) -> List[Path]:
    """O CNEFE de cada UF pedida (todas, sem lista) em data/raw, baixado do IBGE uma vez: é o retrato do Censo."""
    out = []
    for uf in states or sorted(config.IBGE_STATE_CODES.values()):
        name = cnefe_name(uf)
        out.append(_checked_download(config.CNEFE_UF_URL + name[len("cnefe_"):], name, cnefe_problem,
                                     f"CNEFE de {uf}", tag="cnefe"))
    return out


def anp_stations() -> Path:
    """data/raw/anp_postos.json: os postos em operação da API de revendedores da ANP, UF por UF e página por página,
    num arquivo só, conferido (HS10; anp.problem). Um arquivo guardado que passa na conferência é usado de novo; um
    novo que não passa fica em `.invalido` e para a geração."""
    from . import anp
    config.RAW.mkdir(parents=True, exist_ok=True)
    dest = config.RAW / ANP_FILE
    if dest.exists():
        found = anp.problem(dest)
        if found is None:
            return dest
        print(f"[anp] postos guardados inválidos ({found}); guardados em {ANP_FILE}.guardado.invalido")
        dest.replace(dest.with_name(ANP_FILE + ".guardado.invalido"))
    rows: list = []
    for uf in sorted(config.STATES):
        page = 1
        while True:
            url = f"{config.ANP_API_URL}?uf={uf}&numeropagina={page}"
            time.sleep(anp.PAUSE)
            text = net.fetch_text(url, attempts=5, delay=max(RETRY_DELAY, 6 * anp.PAUSE))
            try:
                answer = json.loads(text)
                got = answer["data"] or []
                pages = int((answer.get("searchPageFilter") or {}).get("totalPagina") or 1)
            except (ValueError, KeyError, TypeError, AttributeError) as e:
                raise RuntimeError(f"a API de postos da ANP respondeu algo que não é a lista de postos "
                                   f"({e.__class__.__name__}; início: {net.body_start(text.encode('utf-8'))}): "
                                   f"{url}") from e
            rows += got
            if not got or page >= pages:
                break
            page += 1
        print(f"[anp] {uf}: {sum(1 for r in rows if r.get('uf') == uf)} postos", flush=True)
    updated = dest.with_name(ANP_FILE + ".novo")
    updated.write_text(json.dumps(rows, ensure_ascii=False), encoding="utf-8")
    found = anp.problem(updated)
    if found is not None:
        updated.replace(dest.with_name(ANP_FILE + ".invalido"))
        raise RuntimeError(f"os postos da ANP vieram inválidos ({found}): {config.ANP_API_URL}")
    updated.replace(dest)
    now = datetime.now(timezone.utc)
    _write_record(ANP_FILE, {"url": config.ANP_API_URL, "date": now.strftime("%Y-%m-%d"),
                             "downloaded_at": now.strftime("%Y-%m-%dT%H:%M:%SZ")})
    return dest


# Os arquivos conferidos de uma geração, na ordem da etapa sources: os que vão para o registro da geração.
CHECKED_FILES = (MESH_FILE, NAMES_FILE, LOCALITIES_FILE, PRF_FILE, CNES_FILE, OVERTURE_FILE, SNV_FILE,
                 ANAC_PUBLIC_FILE, ANAC_PRIVATE_FILE, GEONAMES_PLACES_FILE, GEONAMES_NAMES_FILE, WIKIDATA_FILE,
                 ANP_FILE)


def generation_sources(osm: Dict[str, object]) -> Dict[str, Optional[dict]]:
    """A data de cada fonte da geração: o extrato do OpenStreetMap (a data dele) e cada arquivo conferido (None se não
    se sabe: baixado antes de haver o registro)."""
    out: Dict[str, Optional[dict]] = {"openstreetmap": {"url": osm["url"], "date": osm["timestamp"]}}
    for name in CHECKED_FILES:
        out[name] = source_record(name)
    return out


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

