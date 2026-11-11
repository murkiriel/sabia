"""A etapa build: lê o extrato uma vez e grava os bancos de cada estado e a base, compactados em data/dist/.

Saída:
    data/build/sabia-<UF>.sqlite, sabia-base.sqlite     os bancos (as travas da G7 leem daqui)
    data/dist/sabia-<UF>.sqlite.zst, sabia-base.sqlite.zst
    data/dist/pacotes.json                               build_id, extrato e, por pacote: arquivo, tamanhos e contagens
    data/build/ruas_suspeitas.json                       ruas locais juntadas com mais de 3 km (relatório da geração)
"""
from __future__ import annotations

import json
import time
from datetime import datetime, timezone
from typing import Dict, List, Mapping, Optional

from . import (anac, anp, cnefe, cnes, config, database, dedup, districts, geonames, localities, memory, osm_reader,
               overture, prf, records, snv, sources, street_lines, wikidata)
from .municipalities import MunicipalityIndex


def _log(message: str) -> None:
    """Uma linha do log do build, depois de devolver ao sistema a memória livre (memory.release), com a memória do
    processo no fim: a do Brasil inteiro no executor do Actions é o que mais aperta."""
    memory.release()
    used = memory.usage()
    print(f"{message} ({used})" if used else message, flush=True)


def build_id(day: str, extract_md5: str) -> str:
    """'2026-09-30' + md5 do extrato -> '2026-09-30-cb859dc3': o mesmo formato de id de geração dos tiles de rota
    feitos do mesmo extrato. Dois extratos diferentes nunca dão o mesmo id, nem no mesmo dia."""
    return f"{day}-{extract_md5[:8]}"


def clean_output() -> None:
    """Apaga os pacotes e o conjunto de conformidade de uma geração anterior em data/dist/ (um estado que não entra
    mais não pode sobrar)."""
    config.DIST.mkdir(parents=True, exist_ok=True)
    for old in [*config.DIST.glob("sabia-*.sqlite.zst*"), *config.DIST.glob("sabia-conformidade.json.zst*")]:
        old.unlink()
    for name in ("pacotes.json", "catalogo.json"):
        (config.DIST / name).unlink(missing_ok=True)


def _package(name: str, counts: Mapping[str, object]) -> Dict[str, object]:
    db = config.BUILD / f"{name}.sqlite"
    zst = config.DIST / f"{name}.sqlite.zst"
    database.compress(db, zst)
    return {"file": zst.name, "bytes": zst.stat().st_size, "bytes_db": db.stat().st_size, "counts": counts}


def run(states: List[str], osm: Dict[str, object], today: Optional[str] = None) -> Dict[str, object]:
    t0 = time.time()
    clean_output()
    config.BUILD.mkdir(parents=True, exist_ok=True)
    gid = build_id(today or datetime.now(timezone.utc).strftime("%Y-%m-%d"), str(osm["md5"]))
    meta = {"build_id": gid, "osm_timestamp": str(osm["timestamp"])}
    municipalities = sources.load_municipalities(config.RAW / sources.MESH_FILE, config.RAW / sources.NAMES_FILE)
    index = MunicipalityIndex([m for m in municipalities if m.uf in states])
    bbox = index.bbox()
    _log(f"[build] lendo {osm['path']} ({len(states)} estados)...")
    data = osm_reader.read(str(osm["path"]), bbox, workdir=config.BUILD)
    _log(f"[build] lido em {time.time() - t0:.0f} s: {len(data.places)} lugares, {len(data.pois)} pontos de "
          f"interesse, {len(data.ways)} vias, {len(data.district_areas)} áreas de bairro")
    items = records.build(data, municipalities, states)
    # HS1: as localidades do IBGE que o OpenStreetMap não tem, antes dos bairros (elas também ganham bairro)
    added = localities.add(items, localities.load(config.RAW / sources.LOCALITIES_FILE), states)
    _log(f"[build] {added} localidades do IBGE juntadas")
    # HS2: os postos da PRF que o OpenStreetMap não tem
    added, repeated = prf.add(items, prf.load(config.RAW / sources.PRF_FILE), index, states)
    _log(f"[build] {added} postos da PRF juntados ({repeated} já estavam no OpenStreetMap)")
    # HS3: hospitais, UPAs e prontos-socorros 24 horas do CNES que o OpenStreetMap não tem
    added, repeated, misplaced = cnes.add(items, cnes.load(config.RAW / sources.CNES_FILE), index, states)
    _log(f"[build] {added} unidades de urgência do CNES juntadas ({repeated} já estavam no OpenStreetMap, "
          f"{misplaced} com o ponto fora do município declarado)")
    # HS4: os lugares da Overture que o OpenStreetMap não tem, estado por estado (a memória fica a do maior)
    added = repeated = 0
    for uf in states:
        box = MunicipalityIndex([m for m in municipalities if m.uf == uf]).bbox()
        if box is None:
            continue
        places = overture.load(config.RAW / sources.OVERTURE_FILE, box)
        a, r = overture.add(items, places, index, [uf])
        added, repeated = added + a, repeated + r
    _log(f"[build] {added} lugares da Overture juntados ({repeated} já estavam registrados)")
    # HS6: um marco por km das rodovias federais, pelo SNV do DNIT
    added, repeated = snv.add(items, snv.load_markers(config.RAW / sources.SNV_FILE), index, states)
    _log(f"[build] {added} marcos de km das rodovias federais juntados ({repeated} repetidos)")
    # HS8: os aeródromos públicos e privados da ANAC que o OpenStreetMap não tem
    aerodromes = (anac.load(config.RAW / sources.ANAC_PUBLIC_FILE) + anac.load(config.RAW / sources.ANAC_PRIVATE_FILE))
    added, repeated = anac.add(items, aerodromes, index, states)
    _log(f"[build] {added} aeródromos da ANAC juntados ({repeated} já estavam no OpenStreetMap)")
    # HS9: nomes alternativos e pontos turísticos do GeoNames e do Wikidata
    added, repeated, aliased = geonames.add(items, geonames.load(config.RAW / sources.GEONAMES_PLACES_FILE,
                                                                  config.RAW / sources.GEONAMES_NAMES_FILE),
                                            index, states)
    _log(f"[build] GeoNames: {added} pontos turísticos juntados ({repeated} já registrados), {aliased} registros com "
          f"nome alternativo")
    added, repeated, aliased = wikidata.add(items, wikidata.load(config.RAW / sources.WIKIDATA_FILE), index, states)
    _log(f"[build] Wikidata: {added} pontos turísticos juntados ({repeated} já registrados), {aliased} registros com "
          f"nome alternativo")
    # HS10: os postos da ANP que o pacote não tem; o posto sem nome do pacote ganha o da ANP
    added, repeated, named = anp.add(items, anp.load(config.RAW / sources.ANP_FILE), index, states)
    _log(f"[build] {added} postos da ANP juntados ({repeated} já estavam no pacote, {named} deles ganharam nome)")
    # SE1: o número das casas pelo CNEFE do IBGE, o arquivo de cada UF (baixado na etapa das fontes)
    for uf in states:
        path = config.RAW / sources.cnefe_name(uf)
        if not path.exists():
            _log(f"[build] {uf}: sem o CNEFE ({path.name}), sem números")
            continue
        matched, unmatched = cnefe.add(items, cnefe.read(path), uf)
        _log(f"[build] {uf}: números do CNEFE em {matched} pedaços de ruas do mapa ({unmatched} sem rua de mesmo "
              f"nome por perto, de fora)")
    # item 8: o mesmo lugar duas vezes (ponto e área do mapa, o mapa e a Overture com o nome escrito de outro jeito)
    removed = dedup.collapse(items)
    _log(f"[build] {removed} registros repetidos juntados (o mesmo lugar, tipo e nome a até "
          f"{dedup.DUPLICATE_M:.0f} m)")
    found = districts.build(data, municipalities, states)
    districts.assign(items, found)

    packages: Dict[str, object] = {"build_id": gid, "osm": osm, "states": {}}
    suspects = []
    for uf in states:
        lines = street_lines.build(items[uf], data)
        counts = database.write_state(config.BUILD / f"sabia-{uf}.sqlite", uf, items[uf], found[uf], lines,
                                      municipalities, meta)
        packages["states"][uf] = _package(f"sabia-{uf}", counts)  # type: ignore[index]
        suspects += [{"uf": uf, "municipality": i.municipality, "name": i.name, "extent_m": i.extent_m,
                      "lat": round(i.lat, 5), "lng": round(i.lng, 5)} for i in items[uf] if i.suspect_long]
        _log(f"[build] {uf}: {counts['items']} registros, {counts['street_line']} pedaços de traçado, "
              f"{packages['states'][uf]['bytes'] / 1e6:.1f} MB compactado")  # type: ignore[index]
    base_counts = database.write_base(config.BUILD / "sabia-base.sqlite", municipalities, items, meta)
    packages["base"] = _package("sabia-base", base_counts)
    (config.BUILD / "ruas_suspeitas.json").write_text(json.dumps(suspects, ensure_ascii=False, indent=1),
                                                      encoding="utf-8")
    (config.DIST / "pacotes.json").write_text(json.dumps(packages, ensure_ascii=False, indent=2), encoding="utf-8")
    _log(f"[build] {len(states)} estados e a base em {time.time() - t0:.0f} s")
    return packages
