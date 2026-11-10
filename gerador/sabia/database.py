"""Os bancos SQLite (G6): um por estado e a base nacional, e a compactação zstd (D3).

Banco do estado (`format_version` 1; nomes em inglês, a convenção do projeto):

    meta          key, value: format_version, build_id, uf, osm_timestamp, attribution
    municipality  id (código do IBGE), name, lat, lng (a sede)
    district      id, municipality, name, kind, lat, lng, polygon (blob; NULL = bairro só com ponto)
    item          id, cls (place, street, road, poi), kind, name, municipality, district, lat, lng, cell, rank
                  (ranks.py; os ids vão do mais importante ao menos)
    item_text     FTS4 sem conteúdo (docid = item.id), tokenizador simples, prefix="2,3": name (e os nomes
                  alternativos, HS9); area
    street_line   item, cell, coords (blob)                       "que rua é esta?" (street_lines.py)
    word_form     word, form, rule                                 abreviações, formas, números (search_rules.py)
    category      word, kinds                                      "posto" -> amenity=fuel; frases ("posto de saude")
    brand         word, kinds                                      "ipiranga" -> amenity=fuel (a marca fica no texto)
    item_source   item, source                                     origem sem conferência no mapa: "anp" (HP5b1);
                  só os registros marcados (o que não está aqui veio do mapa); um leitor antigo não a lê
    vocab         word, n                                          as palavras do índice e em quantos registros: a
                  correção de erros de digitação (search.corrected); um leitor antigo não a lê
    house_number  street, rungs (blob)                              número das casas (SE1, docs/ENDERECOS.md): a
                  escada do CNEFE de cada rua numa linha (a chave é o rowid, sem índice à parte); os degraus em
                  int32 little-endian, de 5 em 5: lado (0 par, 1 ímpar), pedaço, número, lat, lng x 100.000, em
                  ordem; entre dois degraus do mesmo lado e pedaço se interpola; um leitor antigo não a lê

Base nacional: `municipality` com `uf` (todos os municípios), `item` com os municípios e as rodovias federais,
`road_state` (item, uf: os estados de cada rodovia federal), `item_text`, `word_form`, `category` e `meta` (uf "base").

Coordenadas em inteiros, graus x 100.000 (5 casas, ~1 m). `cell` é o quadrado do zoom 13 (geo.cell). O texto do
índice vem dobrado (sem acento, minúsculo) e com os números nas duas formas ("14 quatorze"); `area` é o município e o
bairro. Só o que o SQLite do Android (3.22, sem FTS5 nem R-Tree) lê; arquivo em modo rollback, não WAL.

Polígono do bairro: os anéis (externos e buracos, regra par-ímpar), cada um como int32 little-endian: o número de
vértices e depois lat, lng de cada vértice x 100.000, sem repetir o primeiro no fim. Simplificado a 10 m.
"""
from __future__ import annotations

import math
import sqlite3
import struct
from collections import defaultdict
from pathlib import Path
from typing import Dict, List, Optional, Sequence, Tuple

import shapely.affinity
import zstandard
from shapely.geometry import MultiPolygon, Polygon
from shapely.geometry.base import BaseGeometry

from . import config, geo, ranks, search_rules
from .districts import District
from .records import Item
from .sources import Municipality
from .street_lines import StreetLine
from .text import fold

FORMAT_VERSION = 1
ZSTD_LEVEL = 19
SCALE = 100_000
POLYGON_SIMPLIFY_M = 10.0

STATE_TABLES = """
CREATE TABLE meta(key TEXT PRIMARY KEY, value TEXT NOT NULL);
CREATE TABLE municipality(id INTEGER PRIMARY KEY, name TEXT NOT NULL, lat INTEGER NOT NULL, lng INTEGER NOT NULL);
CREATE TABLE district(id INTEGER PRIMARY KEY, municipality INTEGER NOT NULL, name TEXT NOT NULL, kind TEXT NOT NULL,
                      lat INTEGER NOT NULL, lng INTEGER NOT NULL, polygon BLOB);
CREATE TABLE item(id INTEGER PRIMARY KEY, cls TEXT NOT NULL, kind TEXT NOT NULL, name TEXT NOT NULL,
                  municipality INTEGER NOT NULL, district INTEGER, lat INTEGER NOT NULL, lng INTEGER NOT NULL,
                  cell INTEGER NOT NULL, rank INTEGER NOT NULL DEFAULT 0);
CREATE VIRTUAL TABLE item_text USING fts4(content="", name, area, tokenize=simple, prefix="2,3");
CREATE TABLE street_line(item INTEGER NOT NULL, cell INTEGER NOT NULL, coords BLOB NOT NULL);
CREATE TABLE word_form(word TEXT NOT NULL, form TEXT NOT NULL, rule TEXT NOT NULL);
CREATE TABLE category(word TEXT PRIMARY KEY, kinds TEXT NOT NULL);
CREATE TABLE brand(word TEXT PRIMARY KEY, kinds TEXT NOT NULL);
CREATE TABLE item_source(item INTEGER PRIMARY KEY, source TEXT NOT NULL);
CREATE TABLE house_number(street INTEGER PRIMARY KEY, rungs BLOB NOT NULL);
CREATE TABLE vocab(word TEXT PRIMARY KEY, n INTEGER NOT NULL);
"""
STATE_INDEXES = """
CREATE INDEX item_cell ON item(cell);
CREATE INDEX street_line_cell ON street_line(cell);
"""
BASE_TABLES = """
CREATE TABLE meta(key TEXT PRIMARY KEY, value TEXT NOT NULL);
CREATE TABLE municipality(id INTEGER PRIMARY KEY, name TEXT NOT NULL, uf TEXT NOT NULL, lat INTEGER NOT NULL,
                          lng INTEGER NOT NULL);
CREATE TABLE item(id INTEGER PRIMARY KEY, cls TEXT NOT NULL, kind TEXT NOT NULL, name TEXT NOT NULL,
                  municipality INTEGER NOT NULL, district INTEGER, lat INTEGER NOT NULL, lng INTEGER NOT NULL,
                  cell INTEGER NOT NULL, rank INTEGER NOT NULL DEFAULT 0);
CREATE VIRTUAL TABLE item_text USING fts4(content="", name, area, tokenize=simple, prefix="2,3");
CREATE TABLE road_state(item INTEGER NOT NULL, uf TEXT NOT NULL);
CREATE TABLE word_form(word TEXT NOT NULL, form TEXT NOT NULL, rule TEXT NOT NULL);
CREATE TABLE category(word TEXT PRIMARY KEY, kinds TEXT NOT NULL);
CREATE TABLE brand(word TEXT PRIMARY KEY, kinds TEXT NOT NULL);
CREATE TABLE vocab(word TEXT PRIMARY KEY, n INTEGER NOT NULL);
"""
BASE_INDEXES = """
CREATE INDEX item_cell ON item(cell);
CREATE INDEX road_state_uf ON road_state(uf);
"""


def _i(v: float) -> int:
    return round(v * SCALE)


def index_text(name: str) -> str:
    """O nome como vai para o índice: dobrado, e cada número com a outra forma logo depois ('Rua 14' ->
    'rua 14 quatorze')."""
    out: List[str] = []
    for token in fold(name).split():
        out.append(token)
        out.extend(search_rules.number_forms(token))
    return " ".join(out)


def encode_polygon(geometry: BaseGeometry) -> bytes:
    """Os anéis do polígono simplificado a 10 m (ver o cabeçalho do módulo)."""
    lat0 = geometry.centroid.y
    k = geo.M_PER_DEG * math.cos(math.radians(lat0))
    metric = shapely.affinity.scale(geometry, xfact=k, yfact=geo.M_PER_DEG, origin=(0, 0))
    simple = metric.simplify(POLYGON_SIMPLIFY_M, preserve_topology=True)
    if simple.is_empty:
        simple = metric
    back = shapely.affinity.scale(simple, xfact=1 / k, yfact=1 / geo.M_PER_DEG, origin=(0, 0))
    polygons = back.geoms if isinstance(back, MultiPolygon) else [back] if isinstance(back, Polygon) else []
    flat: List[int] = []
    for poly in polygons:
        for ring in [poly.exterior, *poly.interiors]:
            coords = list(ring.coords)[:-1]
            flat.append(len(coords))
            for x, y in coords:
                flat += [_i(y), _i(x)]
    return struct.pack(f"<{len(flat)}i", *flat)


def decode_polygon(blob: bytes) -> List[List[Tuple[float, float]]]:
    flat = struct.unpack(f"<{len(blob) // 4}i", blob)
    rings, i = [], 0
    while i < len(flat):
        n = flat[i]
        rings.append([(flat[i + 1 + 2 * j] / SCALE, flat[i + 2 + 2 * j] / SCALE) for j in range(n)])
        i += 1 + 2 * n
    return rings


def point_in_rings(lat: float, lng: float, rings: Sequence[Sequence[Tuple[float, float]]]) -> bool:
    """Ponto dentro do polígono pela regra par-ímpar sobre todos os anéis (a referência de quem consome)."""
    inside = False
    for ring in rings:
        n = len(ring)
        for a in range(n):
            (lat1, lng1), (lat2, lng2) = ring[a], ring[(a + 1) % n]
            if (lat1 > lat) != (lat2 > lat):
                cross = lng1 + (lat - lat1) * (lng2 - lng1) / (lat2 - lat1)
                if lng < cross:
                    inside = not inside
    return inside


def _connect(path: Path, tables: str) -> sqlite3.Connection:
    if path.exists():
        path.unlink()
    path.parent.mkdir(parents=True, exist_ok=True)
    db = sqlite3.connect(path)
    db.executescript("PRAGMA page_size=4096; PRAGMA journal_mode=OFF; PRAGMA synchronous=OFF;")
    db.executescript(tables)
    return db


def vocab_words(text: str) -> List[str]:
    """As palavras de um texto do índice que vão para `vocab`: só letras, 3 ou mais (os números nunca se corrigem)."""
    return [w for w in text.split() if len(w) >= 3 and w.isalpha()]


def _vocab(db: sqlite3.Connection, texts: Sequence[Tuple[str, str]]) -> None:
    """`vocab`: cada palavra do índice (nome e área) e em quantos registros ela aparece (a correção de erros de
    digitação, em search.corrected, escolhe a mais comum entre as parecidas)."""
    counts: Dict[str, int] = defaultdict(int)
    for name, area in texts:
        for w in set(vocab_words(name)) | set(vocab_words(area)):
            counts[w] += 1
    db.executemany("INSERT INTO vocab VALUES(?,?)", sorted(counts.items()))


def _search_tables(db: sqlite3.Connection) -> None:
    db.executemany("INSERT INTO word_form VALUES(?,?,?)", search_rules.word_forms())
    db.executemany("INSERT INTO category VALUES(?,?)", search_rules.categories().items())
    db.executemany("INSERT INTO brand VALUES(?,?)", search_rules.brands().items())


def _meta(db: sqlite3.Connection, uf: str, meta: Dict[str, str]) -> None:
    rows = {"format_version": str(FORMAT_VERSION), "build_id": meta["build_id"], "uf": uf,
            "osm_timestamp": meta["osm_timestamp"], "attribution": config.ATTRIBUTION}
    db.executemany("INSERT INTO meta VALUES(?,?)", sorted(rows.items()))


def _finish(db: sqlite3.Connection, indexes: str) -> None:
    db.executescript(indexes)
    db.execute("INSERT INTO item_text(item_text) VALUES('optimize')")
    db.commit()
    db.execute("VACUUM")
    db.close()


def write_state(path: Path, uf: str, items: Sequence[Item], districts: Sequence[District],
                lines: Sequence[StreetLine], municipalities: Sequence[Municipality],
                meta: Dict[str, str]) -> Dict[str, int]:
    """Grava o banco de um estado e devolve as contagens (para o catálogo e as travas)."""
    names = {m.code: m.name for m in municipalities}
    db = _connect(path, STATE_TABLES)
    seats = sorted((int(i.municipality), i.name, _i(i.lat), _i(i.lng)) for i in items if i.kind == "municipality")
    db.executemany("INSERT INTO municipality VALUES(?,?,?,?)", seats)
    db.executemany("INSERT INTO district VALUES(?,?,?,?,?,?,?)",
                   ((d.id, int(d.municipality), d.name, d.kind, _i(d.lat), _i(d.lng),
                     encode_polygon(d.polygon) if d.polygon is not None else None) for d in districts))
    # os ids do mais importante ao menos (ranks.rank), no empate a ordem da geração: o FTS devolve em ordem de docid
    # e o corte (LIMIT) de uma busca curta fica com os mais importantes
    item_ranks = [ranks.rank(i) for i in items]
    order = sorted(range(len(items)), key=lambda k: (-item_ranks[k], k))
    new_id = {k: n for n, k in enumerate(order, 1)}
    db.executemany("INSERT INTO item VALUES(?,?,?,?,?,?,?,?,?,?)",
                   ((n, items[k].cls, items[k].kind, items[k].name, int(items[k].municipality), items[k].district_id,
                     _i(items[k].lat), _i(items[k].lng), geo.cell(items[k].lat, items[k].lng), item_ranks[k])
                    for n, k in enumerate(order, 1)))
    texts = [(index_text(" ".join([i.name, *i.aliases])), fold(f"{names.get(i.municipality, '')} {i.district or ''}"))
             for i in items]
    db.executemany("INSERT INTO item_text(docid, name, area) VALUES(?,?,?)",
                   ((n, *texts[k]) for n, k in enumerate(order, 1)))
    _vocab(db, texts)
    db.executemany("INSERT INTO street_line VALUES(?,?,?)", ((new_id[x.item], x.cell, x.coords) for x in lines))
    db.executemany("INSERT INTO item_source VALUES(?,?)",
                   sorted((new_id[k], i.source) for k, i in enumerate(items) if i.source))
    ladders = sorted((new_id[k], sorted((side, seg, number, _i(lat), _i(lng)) for side, seg, number, lat, lng in
                                        i.numbers))
                     for k, i in enumerate(items) if i.numbers)
    db.executemany("INSERT INTO house_number VALUES(?,?)",
                   ((n, struct.pack(f"<{5 * len(r)}i", *(v for rung in r for v in rung))) for n, r in ladders))
    _search_tables(db)
    _meta(db, uf, meta)
    _finish(db, STATE_INDEXES)
    counts = {"items": len(items), "district": len(districts), "street_line": len(lines),
              "municipality": len(seats), "house_number": len(ladders),
              "house_number_rungs": sum(len(r) for _, r in ladders)}
    for cls in ("place", "street", "road", "poi"):
        counts[cls] = sum(1 for i in items if i.cls == cls)
    return counts


def _central(items: Sequence[Item]) -> Item:
    mean_lat = sum(i.lat for i in items) / len(items)
    mean_lng = sum(i.lng for i in items) / len(items)
    return min(items, key=lambda i: (geo.dist_m(i.lat, i.lng, mean_lat, mean_lng), i.municipality))


def write_base(path: Path, municipalities: Sequence[Municipality], items_by_state: Dict[str, List[Item]],
               meta: Dict[str, str]) -> Dict[str, object]:
    """Grava a base nacional: todos os municípios (a sede dos estados gerados; dos outros, um ponto dentro do
    polígono) e as rodovias federais dos estados gerados. Devolve as contagens e os municípios sem ponto."""
    seats = {i.municipality: (i.lat, i.lng) for items in items_by_state.values() for i in items
             if i.kind == "municipality"}
    people = {i.municipality: i.population for items in items_by_state.values() for i in items
              if i.kind == "municipality"}
    rows: List[Tuple[int, str, str, float, float]] = []
    without_point: List[str] = []
    for m in sorted(municipalities, key=lambda m: m.code):
        point: Optional[Tuple[float, float]] = seats.get(m.code)
        if point is None and m.geometry is not None:
            p = m.geometry.representative_point()
            point = (p.y, p.x)
        if point is None:
            without_point.append(m.code)
            continue
        rows.append((int(m.code), m.name, m.uf, point[0], point[1]))
    federal: Dict[str, List[Item]] = defaultdict(list)
    for items in items_by_state.values():
        for i in items:
            if i.cls == "road" and i.name.startswith("BR-"):
                federal[i.name].append(i)

    db = _connect(path, BASE_TABLES)
    db.executemany("INSERT INTO municipality VALUES(?,?,?,?,?)",
                   ((code, name, uf, _i(lat), _i(lng)) for code, name, uf, lat, lng in rows))
    # (rank, linha de item sem id, texto, área, UFs da rodovia), na ordem da geração; os ids saem por importância
    entries: List[Tuple[int, tuple, str, str, List[str]]] = []
    for code, name, uf, lat, lng in rows:
        population = people.get(str(code), 0)
        rank = ranks.population_rank(population) if population > 1 else ranks.PLACE_RANKS["municipality"]
        entries.append((rank, ("place", "municipality", name, code, None, _i(lat), _i(lng), geo.cell(lat, lng)),
                        index_text(name), fold(f"{config.STATES[uf]} {uf}"), []))
    for ref in sorted(federal):
        c = _central(federal[ref])
        ufs = sorted({i.uf for i in federal[ref]})
        entries.append((ranks.ROAD_RANK, ("road", "road", ref, int(c.municipality), None, _i(c.lat), _i(c.lng),
                                          geo.cell(c.lat, c.lng)),
                        index_text(ref), fold(" ".join(config.STATES[u] for u in ufs) + " " + " ".join(ufs)), ufs))
    ordered = sorted(enumerate(entries), key=lambda e: (-e[1][0], e[0]))
    db.executemany("INSERT INTO item VALUES(?,?,?,?,?,?,?,?,?,?)",
                   ((n, *entry[1], entry[0]) for n, (_, entry) in enumerate(ordered, 1)))
    db.executemany("INSERT INTO item_text(docid, name, area) VALUES(?,?,?)",
                   ((n, entry[2], entry[3]) for n, (_, entry) in enumerate(ordered, 1)))
    _vocab(db, [(entry[2], entry[3]) for entry in entries])
    db.executemany("INSERT INTO road_state VALUES(?,?)",
                   [(n, u) for n, (_, entry) in enumerate(ordered, 1) for u in entry[4]])
    _search_tables(db)
    _meta(db, "base", meta)
    _finish(db, BASE_INDEXES)
    return {"municipality": len(rows), "road": len(federal), "without_point": without_point}


def compress(src: Path, dest: Path) -> None:
    """zstd nível 19, com o tamanho original e o checksum no cabeçalho do quadro. Sem threads: o mesmo banco dá
    sempre o mesmo arquivo."""
    cctx = zstandard.ZstdCompressor(level=ZSTD_LEVEL, write_checksum=True, write_content_size=True)
    partial = dest.with_name(dest.name + ".parcial")
    with open(src, "rb") as fin, open(partial, "wb") as fout:
        cctx.copy_stream(fin, fout, size=src.stat().st_size)
    partial.replace(dest)


def decompress(src: Path, dest: Path) -> None:
    with open(src, "rb") as fin, open(dest, "wb") as fout:
        zstandard.ZstdDecompressor().copy_stream(fin, fout)
