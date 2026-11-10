"""O banco de cada estado e a base nacional (G6): FTS4, tabelas de busca (D8), `meta` e a compactação zstd (D3)."""
import hashlib
import sqlite3
import sys
import tempfile
import unittest
from pathlib import Path

import zstandard
from shapely.geometry import box

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from sabia import database, districts, geo, osm_reader, ranks, records, street_lines  # noqa: E402
from sabia.sources import Municipality  # noqa: E402
from tests.osm_builder import ANAPOLIS, BRASILIA, GOIANIA, MUNICIPALITIES, OsmBuilder, north  # noqa: E402

LAT, LNG = -16.68, -49.26
META = {"build_id": "2026-09-29-aaaaaaaa", "osm_timestamp": "2026-09-29T00:59:51Z"}


def sample_osm():
    osm = OsmBuilder()
    osm.multipolygon([(LAT, LNG), (LAT, LNG + 0.02), (LAT + 0.02, LNG + 0.02), (LAT + 0.02, LNG)],
                     place="suburb", name="Setor Oeste")
    osm.street((LAT + 0.01, LNG + 0.002), 400, "Rua 10")
    osm.street((LAT + 0.05, LNG), 400, "Rua 10")
    osm.street((LAT + 0.012, LNG + 0.002), 400, "Avenida Goiás", highway="primary")
    osm.street((LAT - 0.05, LNG), 400, "Rua Quatorze")
    osm.street((LAT - 0.06, LNG), 400, "Rua 14")
    osm.street((LAT - 0.1, LNG), 3000, "", highway="trunk", ref="BR-153", step=500)
    osm.street(north(-16.33, -48.95, 100), 3000, "", highway="trunk", ref="BR-153", step=500)
    osm.street((-15.79, -47.95), 3000, "", highway="trunk", ref="BR-040", step=500)
    osm.node(LAT + 0.011, LNG + 0.01, amenity="fuel", brand="Ipiranga")
    osm.node(-16.70, -49.30, place="city", name="Goiânia")
    return osm


class Built:
    """Os bancos de GO e da base a partir do extrato de exemplo, gerados uma vez para a classe."""

    def __init__(self, folder: Path, municipalities=MUNICIPALITIES):
        data = osm_reader.read(sample_osm().write(folder / "x.osm.pbf"))
        states = ["DF", "GO"]
        self.items = records.build(data, municipalities, states)
        found = districts.build(data, municipalities, states)
        districts.assign(self.items, found)
        self.go = folder / "sabia-GO.sqlite"
        self.counts = database.write_state(self.go, "GO", self.items["GO"], found["GO"],
                                           street_lines.build(self.items["GO"], data), municipalities, META)
        self.base = folder / "sabia-base.sqlite"
        self.base_counts = database.write_base(self.base, municipalities, self.items, META)


class StateDatabaseTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls._tmp = tempfile.TemporaryDirectory()
        cls.built = Built(Path(cls._tmp.name))
        cls.db = sqlite3.connect(cls.built.go)

    @classmethod
    def tearDownClass(cls):
        cls.db.close()
        cls._tmp.cleanup()

    def match(self, query):
        return [r[0] for r in self.db.execute(
            "SELECT i.name FROM item_text JOIN item i ON i.id = item_text.docid WHERE item_text MATCH ? "
            "ORDER BY i.id", (query,))]

    def test_tables(self):
        names = {r[0] for r in self.db.execute("SELECT name FROM sqlite_master WHERE type IN ('table', 'index')")}
        self.assertTrue({"meta", "municipality", "district", "item", "item_text", "street_line", "word_form",
                         "category", "item_cell", "street_line_cell"} <= names, names)

    def test_only_what_android_sqlite_has(self):
        """FTS4, nunca FTS5 nem R-Tree (o SQLite do Android não tem)."""
        sql = " ".join(r[0] or "" for r in self.db.execute("SELECT sql FROM sqlite_master")).lower()
        self.assertIn("using fts4", sql)
        self.assertNotIn("fts5", sql)
        self.assertNotIn("rtree", sql)
        self.assertIn('prefix="2,3"', sql.replace("'", '"'))

    def test_every_item_is_written_with_its_cell(self):
        """Na ordem dos ids: do mais importante ao menos (ranks.rank), no empate a ordem da geração."""
        rows = self.db.execute("SELECT cls, name, lat, lng, cell FROM item ORDER BY id").fetchall()
        self.assertEqual(len(self.built.items["GO"]), len(rows))
        by_rank = sorted(self.built.items["GO"], key=lambda i: -ranks.rank(i))
        for (cls, name, lat, lng, cell), item in zip(rows, by_rank):
            self.assertEqual((item.cls, item.name), (cls, name))
            self.assertEqual((round(item.lat * 1e5), round(item.lng * 1e5)), (lat, lng))
            self.assertEqual(geo.cell(item.lat, item.lng), cell)

    def test_search_by_name_and_district(self):
        self.assertEqual(["Rua 10"], self.match("rua* 10* setor* oeste*"))
        self.assertEqual(["Rua 10", "Rua 10"], self.match("rua* 10* goiania*"))

    def test_text_is_folded(self):
        self.assertEqual(["Avenida Goiás"], self.match("avenida* goias*"))

    def test_numbers_in_both_forms(self):
        self.assertEqual(["Rua 14", "Rua Quatorze"], sorted(self.match("rua* 14")))
        self.assertEqual(["Rua 14", "Rua Quatorze"], sorted(self.match("rua* quatorze")))

    def test_municipality_and_district_tables(self):
        self.assertEqual([(int(GOIANIA.code), "Goiânia"), (int(ANAPOLIS.code), "Anápolis")],
                         sorted(self.db.execute("SELECT id, name FROM municipality").fetchall(), reverse=True))
        ((did, name, mun, blob),) = self.db.execute("SELECT id, name, municipality, polygon FROM district").fetchall()
        self.assertEqual(("Setor Oeste", int(GOIANIA.code)), (name, mun))
        rings = database.decode_polygon(blob)
        self.assertTrue(database.point_in_rings(LAT + 0.01, LNG + 0.01, rings))
        self.assertFalse(database.point_in_rings(LAT + 0.03, LNG + 0.01, rings))
        districts_of_rua10 = sorted(r[0] or 0 for r in self.db.execute(
            "SELECT district FROM item WHERE name = 'Rua 10'"))
        self.assertEqual([0, did], districts_of_rua10)

    def test_street_lines_point_to_streets_and_roads(self):
        rows = self.db.execute("SELECT i.cls, count(*) FROM street_line s JOIN item i ON i.id = s.item "
                               "GROUP BY i.cls").fetchall()
        self.assertEqual({"street", "road"}, {r[0] for r in rows})
        orphans = self.db.execute("SELECT count(*) FROM street_line WHERE item NOT IN (SELECT id FROM item)")
        self.assertEqual(0, orphans.fetchone()[0])

    def test_search_tables(self):
        forms = set(self.db.execute("SELECT word, form, rule FROM word_form"))
        self.assertIn(("av", "avenida", "abbr"), forms)
        self.assertIn(("cap", "capitao", "abbr"), forms)
        self.assertIn(("rodoviaria", "rodoviario", "form"), forms)
        self.assertIn(("14", "quatorze", "number"), forms)
        self.assertIn(("cidade de", "", "drop_prefix"), forms)
        categories = dict(self.db.execute("SELECT word, kinds FROM category"))
        self.assertEqual("amenity=fuel", categories["posto"])
        self.assertIn("amenity=clinic", categories["posto de saude"].split(","))  # frase (item 10)
        brands = dict(self.db.execute("SELECT word, kinds FROM brand"))
        self.assertEqual("amenity=fuel", brands["ipiranga"])
        self.assertIn("shop=tyres", categories["borracharia"].split(","))

    def test_meta(self):
        meta = dict(self.db.execute("SELECT key, value FROM meta"))
        self.assertEqual(str(database.FORMAT_VERSION), meta["format_version"])
        self.assertEqual("GO", meta["uf"])
        self.assertEqual(META["build_id"], meta["build_id"])
        self.assertEqual(META["osm_timestamp"], meta["osm_timestamp"])
        self.assertIn("OpenStreetMap", meta["attribution"])

    def test_counts(self):
        c = self.built.counts
        self.assertEqual(len(self.built.items["GO"]), c["items"])
        self.assertEqual(sum(1 for i in self.built.items["GO"] if i.cls == "street"), c["street"])
        self.assertEqual(1, c["district"])
        self.assertGreater(c["street_line"], 0)

    def test_vocab(self):
        """`vocab`: as palavras do índice (nome e área), só letras, com 3 letras ou mais, e em quantos registros cada
        uma aparece: o dicionário da correção de erros de digitação."""
        vocab = dict(self.db.execute("SELECT word, n FROM vocab"))
        self.assertEqual(1, vocab["goias"])
        self.assertEqual(2, vocab["quatorze"])  # Rua Quatorze e Rua 14 ("14 quatorze catorze")
        self.assertIn("oeste", vocab)         # da área (o bairro)
        self.assertIn("goiania", vocab)       # da área (o município)
        # por registro, não por vez: o município Goiânia tem "goiania" no nome e na área e conta 1
        in_goiania = self.db.execute("SELECT count(*) FROM item WHERE municipality = ?", (int(GOIANIA.code),))
        self.assertEqual(in_goiania.fetchone()[0], vocab["goiania"])
        self.assertNotIn("10", vocab)
        self.assertNotIn("br", vocab)
        sql = self.db.execute("SELECT sql FROM sqlite_master WHERE name = 'vocab'").fetchone()[0]
        self.assertIn("word TEXT PRIMARY KEY", sql)

    def test_not_wal(self):
        """Arquivo em modo rollback (o padrão), lido por qualquer SQLite desde o 3.0."""
        header = self.built.go.read_bytes()[:20]
        self.assertEqual(b"SQLite format 3\x00", header[:16])
        self.assertEqual((1, 1), (header[18], header[19]))


class SourceTableTest(unittest.TestCase):
    """HP5b1: `item_source` diz a origem dos registros que não vêm do mapa conferido (hoje só os postos da ANP)."""

    def test_only_the_marked_items_with_their_ids(self):
        items = [records.Item("place", "municipality", "Goiânia", "5208707", -16.68, -49.25),
                 records.Item("poi", "amenity=fuel", "Posto Ipiranga", "5208707", -16.70, -49.20, source="anp"),
                 records.Item("poi", "amenity=fuel", "Posto Shell", "5208707", -16.71, -49.21)]
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "sabia-GO.sqlite"
            database.write_state(path, "GO", items, [], [], MUNICIPALITIES, META)
            db = sqlite3.connect(path)
            try:
                rows = db.execute("SELECT s.source, i.name FROM item_source s JOIN item i ON i.id = s.item").fetchall()
                sql = db.execute("SELECT sql FROM sqlite_master WHERE name = 'item_source'").fetchone()[0]
            finally:
                db.close()
        self.assertEqual([("anp", "Posto Ipiranga")], rows)
        self.assertIn("item INTEGER PRIMARY KEY", sql)


class HouseNumberTableTest(unittest.TestCase):
    """SE1 (docs/ENDERECOS.md): `house_number` guarda a escada de números do CNEFE de cada rua numa linha, com o id do
    registro como chave (o rowid, sem índice à parte) e os degraus num blob de int32 little-endian: lado, pedaço,
    número, lat e lng x 100.000, em ordem."""

    def test_one_row_per_street_with_its_rungs_in_a_blob(self):
        import struct
        rua = records.Item("street", "highway=residential", "Rua 9", "5208707", -16.70, -49.25,
                           numbers=[(1, 0, 21, -16.70, -49.2481), (0, 0, 2, -16.7001, -49.25),
                                    (1, 0, 1, -16.700001, -49.250004)])
        items = [records.Item("place", "municipality", "Goiânia", "5208707", -16.68, -49.25), rua,
                 records.Item("street", "highway=residential", "Rua 10", "5208707", -16.71, -49.25)]
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "sabia-GO.sqlite"
            counts = database.write_state(path, "GO", items, [], [], MUNICIPALITIES, META)
            db = sqlite3.connect(path)
            try:
                tables = {r[0] for r in db.execute("SELECT name FROM sqlite_master WHERE type = 'table'")}
                self.assertIn("house_number", tables)
                self.assertEqual(["street", "rungs"], [r[1] for r in db.execute("PRAGMA table_info(house_number)")])
                rows = db.execute("SELECT i.name, h.rungs FROM house_number h "
                                  "JOIN item i ON i.id = h.street").fetchall()
                sql = db.execute("SELECT sql FROM sqlite_master WHERE name = 'house_number'").fetchone()[0]
            finally:
                db.close()
        self.assertEqual(["Rua 9"], [r[0] for r in rows])
        values = struct.unpack(f"<{len(rows[0][1]) // 4}i", rows[0][1])
        self.assertEqual([(0, 0, 2, -1670010, -4925000), (1, 0, 1, -1670000, -4925000), (1, 0, 21, -1670000, -4924810)],
                         [values[i:i + 5] for i in range(0, len(values), 5)])
        self.assertEqual((1, 3), (counts["house_number"], counts["house_number_rungs"]))
        self.assertIn("street INTEGER PRIMARY KEY", sql)


class BaseDatabaseTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls._tmp = tempfile.TemporaryDirectory()
        new = Municipality("5101837", "Boa Esperança do Norte", "MT", None)
        far = Municipality("5100102", "Acorizal", "MT", box(-56.5, -15.3, -56.2, -15.0))
        cls.built = Built(Path(cls._tmp.name), municipalities=MUNICIPALITIES + [new, far])
        cls.db = sqlite3.connect(cls.built.base)

    @classmethod
    def tearDownClass(cls):
        cls.db.close()
        cls._tmp.cleanup()

    def test_every_municipality_with_a_point(self):
        rows = {r[0]: r[1:] for r in self.db.execute("SELECT id, name, uf, lat, lng FROM municipality")}
        self.assertEqual({int(GOIANIA.code), int(ANAPOLIS.code), int(BRASILIA.code), 5100102}, set(rows))
        self.assertEqual(("Goiânia", "GO", -1670000, -4930000), rows[int(GOIANIA.code)])  # a sede do OSM
        self.assertEqual("MT", rows[5100102][1])  # estado não gerado: ponto dentro do polígono
        self.assertEqual(4, self.built.base_counts["municipality"])
        self.assertEqual(["5101837"], self.built.base_counts["without_point"])

    def test_municipalities_are_searchable(self):
        rows = self.db.execute("SELECT i.name, i.kind FROM item_text JOIN item i ON i.id = item_text.docid "
                               "WHERE item_text MATCH 'anapolis*'").fetchall()
        self.assertEqual([("Anápolis", "municipality")], rows)

    def test_federal_roads_with_their_states(self):
        rows = self.db.execute("SELECT i.name, group_concat(r.uf) FROM item i JOIN road_state r ON r.item = i.id "
                               "WHERE i.cls = 'road' GROUP BY i.id ORDER BY i.name").fetchall()
        self.assertEqual([("BR-040", "DF"), ("BR-153", "GO")], rows)

    def test_meta(self):
        meta = dict(self.db.execute("SELECT key, value FROM meta"))
        self.assertEqual("base", meta["uf"])

    def test_vocab(self):
        vocab = dict(self.db.execute("SELECT word, n FROM vocab"))
        self.assertEqual(1, vocab["anapolis"])
        self.assertIn("goias", vocab)  # a área: o nome do estado


class CompressionTest(unittest.TestCase):
    def test_roundtrip_with_content_size_and_level(self):
        with tempfile.TemporaryDirectory() as tmp:
            src = Path(tmp) / "a.sqlite"
            src.write_bytes(b"SQLite format 3\x00" + bytes(range(256)) * 4000)
            dest = Path(tmp) / "a.sqlite.zst"
            database.compress(src, dest)
            params = zstandard.get_frame_parameters(dest.read_bytes())
            self.assertEqual(src.stat().st_size, params.content_size)
            self.assertTrue(params.has_checksum)
            back = Path(tmp) / "b.sqlite"
            database.decompress(dest, back)
            self.assertEqual(src.read_bytes(), back.read_bytes())
            self.assertEqual(19, database.ZSTD_LEVEL)

    def test_same_input_same_bytes(self):
        """Pacotes reproduzíveis: o mesmo extrato gera o mesmo arquivo, byte a byte."""
        digests = []
        for _ in range(2):
            with tempfile.TemporaryDirectory() as tmp:
                built = Built(Path(tmp))
                dest = Path(tmp) / "go.zst"
                database.compress(built.go, dest)
                digests.append(hashlib.sha256(dest.read_bytes()).hexdigest())
        self.assertEqual(digests[0], digests[1])


class IndexTextTest(unittest.TestCase):
    def test_index_text(self):
        self.assertEqual("rua 14 quatorze catorze", database.index_text("Rua 14"))  # as duas grafias
        self.assertEqual("rua quatorze 14", database.index_text("Rua Quatorze"))
        self.assertEqual("rua catorze 14", database.index_text("Rua Catorze"))
        self.assertEqual("avenida t 63", database.index_text("Avenida T-63"))
        self.assertEqual("rua 1001", database.index_text("Rua 1001"))


if __name__ == "__main__":
    unittest.main()
