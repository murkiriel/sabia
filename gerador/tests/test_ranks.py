"""A importância de cada registro (sabia/ranks.py, coluna item.rank): o que puxa para cima, na ordenação da busca e no
corte do FTS (os ids vão do mais importante ao menos), o lugar grande, a via principal e o ponto de referência."""
import math
import sqlite3
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from sabia import database, osm_reader, overture, ranks, records  # noqa: E402
from sabia.merge import Point  # noqa: E402
from sabia.municipalities import MunicipalityIndex  # noqa: E402
from sabia.records import Item  # noqa: E402
from tests.osm_builder import ANAPOLIS, GOIANIA, MUNICIPALITIES, OsmBuilder  # noqa: E402

META = {"build_id": "x", "osm_timestamp": "y"}


def item(cls, kind, name="X", **kw):
    return Item(cls, kind, name, GOIANIA.code, -16.68, -49.26, **kw)


class RankTest(unittest.TestCase):
    def test_population_like_the_organic_maps(self):
        """Com população: ln(população) / ln(1,1), até 255."""
        self.assertEqual(round(math.log(1_536_097) / math.log(1.1)),
                         ranks.rank(item("place", "municipality", population=1_536_097)))
        self.assertEqual(255, ranks.rank(item("place", "place=city", population=10 ** 12)))

    def test_places_without_population_by_kind(self):
        r = {k: ranks.rank(item("place", k)) for k in
             ("place=city", "municipality", "place=town", "place=village", "place=suburb", "place=hamlet",
              "ibge=povoado", "place=farm")}
        self.assertGreater(r["place=city"], r["municipality"])
        self.assertGreater(r["municipality"], r["place=village"])
        self.assertGreater(r["place=town"], r["place=village"])
        self.assertGreater(r["place=village"], r["place=hamlet"])
        self.assertGreater(r["place=suburb"], r["place=hamlet"])
        self.assertGreater(r["place=hamlet"], r["place=farm"])
        self.assertGreater(r["ibge=povoado"], r["place=farm"])

    def test_streets_by_highway(self):
        self.assertGreater(ranks.rank(item("street", "highway=primary")),
                           ranks.rank(item("street", "highway=residential")))
        self.assertGreater(ranks.rank(item("street", "highway=trunk")),
                           ranks.rank(item("street", "highway=secondary")))
        self.assertGreater(ranks.rank(item("road", "road")), ranks.rank(item("street", "highway=residential")))

    def test_landmarks_before_shops_and_markers(self):
        bus = ranks.rank(item("poi", "amenity=bus_station"))
        hospital = ranks.rank(item("poi", "amenity=hospital"))
        fuel = ranks.rank(item("poi", "amenity=fuel"))
        shop = ranks.rank(item("poi", "shop=clothes"))
        marker = ranks.rank(item("poi", "highway=milestone"))
        self.assertGreater(bus, fuel)
        self.assertGreater(hospital, fuel)
        self.assertGreater(fuel, shop)
        self.assertGreater(shop, marker)
        self.assertGreater(marker, 0)

    def test_overture_below_the_map(self):
        """O mesmo tipo vindo da Overture (lugar de comércio, sem conferência no mapa) vale menos que o do mapa."""
        self.assertLess(ranks.rank(item("poi", "amenity=university", origin="overture")),
                        ranks.rank(item("poi", "amenity=university")))
        self.assertLess(ranks.rank(item("poi", "overture=beauty_salon", origin="overture")),
                        ranks.rank(item("poi", "shop=clothes")))


class OriginTest(unittest.TestCase):
    def test_overture_places_are_marked(self):
        """Só na memória (para a importância): a origem não vai para o banco."""
        items = {"GO": [item("poi", "amenity=fuel", "Posto Cerrado")]}
        overture.add(items, [Point("Padaria Pão Quente", "shop=bakery", -16.69, -49.27)],
                     MunicipalityIndex(MUNICIPALITIES), ["GO"])
        self.assertEqual({"Posto Cerrado": "", "Padaria Pão Quente": "overture"},
                         {i.name: i.origin for i in items["GO"]})


class PopulationTest(unittest.TestCase):
    def test_osm_population_goes_to_the_place_and_the_seat(self):
        osm = OsmBuilder()
        osm.node(-16.70, -49.30, place="city", name="Goiânia", population="1.536.097")
        osm.node(-16.65, -49.28, place="suburb", name="Setor Norte", population="12000")
        osm.node(-16.66, -49.28, place="suburb", name="Setor Sul", population="cerca de 9 mil")
        with tempfile.TemporaryDirectory() as tmp:
            data = osm_reader.read(osm.write(Path(tmp) / "x.osm.pbf"))
        self.assertEqual({"Goiânia": 1536097, "Setor Norte": 12000, "Setor Sul": 0},
                         {p.name: p.population for p in data.places})
        items = records.build(data, MUNICIPALITIES, ["GO"])["GO"]
        by_name = {(i.kind, i.name): i.population for i in items}
        self.assertEqual(1536097, by_name[("municipality", "Goiânia")])
        self.assertEqual(12000, by_name[("place=suburb", "Setor Norte")])


class RankColumnTest(unittest.TestCase):
    """item.rank no banco do estado, e os ids do mais importante ao menos: o FTS devolve em ordem de docid, e o corte
    (LIMIT) de uma busca curta ("ru") fica com os mais importantes, não com os primeiros do alfabeto."""

    def test_rank_column_and_ids_by_importance(self):
        items = [item("poi", "amenity=fuel", "Posto B", source="anp"),
                 item("poi", "overture=clothing_store", "Loja A", origin="overture"),
                 item("street", "highway=residential", "Rua A",
                      numbers=[(0, 0, 2, -16.68, -49.26)]),
                 item("place", "municipality", "Goiânia", population=1_536_097),
                 item("street", "highway=primary", "Avenida Goiás")]
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "sabia-GO.sqlite"
            database.write_state(path, "GO", items, [], [], MUNICIPALITIES, META)
            db = sqlite3.connect(path)
            try:
                rows = db.execute("SELECT id, name, rank FROM item ORDER BY id").fetchall()
                source = db.execute("SELECT i.name FROM item_source s JOIN item i ON i.id = s.item").fetchall()
                house = db.execute("SELECT i.name FROM house_number h JOIN item i ON i.id = h.street").fetchall()
                text = db.execute("SELECT i.name FROM item_text t JOIN item i ON i.id = t.docid "
                                  "WHERE item_text MATCH 'loja*'").fetchall()
            finally:
                db.close()
        self.assertEqual(["Goiânia", "Avenida Goiás", "Posto B", "Rua A", "Loja A"], [r[1] for r in rows])
        self.assertEqual([1, 2, 3, 4, 5], [r[0] for r in rows])
        self.assertEqual([ranks.rank(i) for i in sorted(items, key=ranks.rank, reverse=True)], [r[2] for r in rows])
        self.assertEqual([("Posto B",)], source)
        self.assertEqual([("Rua A",)], house)
        self.assertEqual([("Loja A",)], text)

    def test_base_by_importance(self):
        """Na base, o município com população vem antes, com a importância dela; as rodovias seguem com os estados."""
        anapolis = Item("place", "municipality", "Anápolis", ANAPOLIS.code, -16.33, -48.95)
        goiania = Item("place", "municipality", "Goiânia", GOIANIA.code, -16.68, -49.26, population=1_536_097)
        road = Item("road", "road", "BR-153", GOIANIA.code, -16.70, -49.20)
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "sabia-base.sqlite"
            database.write_base(path, [ANAPOLIS, GOIANIA], {"GO": [anapolis, goiania, road]}, META)
            db = sqlite3.connect(path)
            try:
                rows = db.execute("SELECT name, rank FROM item ORDER BY id").fetchall()
                states = db.execute("SELECT i.name, r.uf FROM road_state r JOIN item i ON i.id = r.item").fetchall()
            finally:
                db.close()
        self.assertEqual([("Goiânia", ranks.population_rank(1_536_097)),
                          ("Anápolis", ranks.PLACE_RANKS["municipality"]), ("BR-153", ranks.ROAD_RANK)], rows)
        self.assertEqual([("BR-153", "GO")], states)

    def test_same_rank_keeps_the_generation_order(self):
        items = [item("street", "highway=residential", "Rua B"), item("street", "highway=residential", "Rua A")]
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "sabia-GO.sqlite"
            database.write_state(path, "GO", items, [], [], MUNICIPALITIES, META)
            db = sqlite3.connect(path)
            try:
                names = [r[0] for r in db.execute("SELECT name FROM item ORDER BY id")]
            finally:
                db.close()
        self.assertEqual(["Rua B", "Rua A"], names)


if __name__ == "__main__":
    unittest.main()
