"""A busca de referência (sabia/search.py): as regras que quem consome aplica sobre o pacote (docs/CONSUMO.md), e o
"que rua é esta?". As travas de buscas de verdade (G7a) usam este mesmo código."""
import sqlite3
import sys
import tempfile
import unittest
from pathlib import Path

from shapely.geometry import box

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from sabia import database, districts, osm_reader, records, search, street_lines  # noqa: E402
from sabia.sources import Municipality  # noqa: E402
from tests.osm_builder import ANAPOLIS, GOIANIA, OsmBuilder, east, north  # noqa: E402

APARECIDA = Municipality("5201405", "Aparecida de Goiânia", "GO", box(-49.5, -17.0, -49.0, -16.9))
MUNICIPALITIES = [GOIANIA, APARECIDA, ANAPOLIS]
LAT, LNG = -16.68, -49.26


def sample():
    osm = OsmBuilder()
    osm.multipolygon([(LAT, LNG), (LAT, LNG + 0.02), (LAT + 0.02, LNG + 0.02), (LAT + 0.02, LNG)],
                     place="suburb", name="Setor Oeste")
    osm.street((LAT + 0.01, LNG + 0.002), 400, "Rua 10")
    osm.street((LAT + 0.05, LNG), 400, "Rua 10")
    osm.street((LAT + 0.012, LNG + 0.002), 400, "Avenida Goiás", highway="primary")
    osm.street((LAT - 0.05, LNG), 400, "Rua Quatorze")
    osm.street((LAT - 0.06, LNG), 400, "Rua 14")
    osm.street((LAT - 0.07, LNG), 400, "R. Cap. Caldas")
    osm.street((LAT - 0.08, LNG), 400, "Rua Doutor Olinto Manso")
    osm.street((-16.95, -49.30), 400, "Rua 90")       # Aparecida de Goiânia, antes na ordem do banco
    osm.street((LAT - 0.09, LNG), 400, "Rua 90")      # Goiânia
    osm.street((LAT - 0.1, LNG), 600, "Avenida Goiânia")
    osm.node(LAT + 0.011, LNG + 0.01, amenity="fuel", brand="Ipiranga")
    osm.node(LAT - 0.2, LNG, amenity="fuel", name="Posto Cerrado")
    osm.node(-16.33, -48.95, amenity="fuel", brand="Ipiranga")  # Anápolis
    osm.node(LAT - 0.03, LNG + 0.03, amenity="bus_station", name="Terminal Rodoviário de Goiânia")
    osm.node(-16.70, -49.30, place="city", name="Goiânia")
    osm.node(LAT - 0.03, LNG + 0.05, amenity="bus_station", name="Terminal Goiânia Viva")
    osm.node(LAT + 0.1, LNG + 0.1, place="suburb", name="Setor Marista")
    osm.node(LAT + 0.1, LNG + 0.101, place="town", name="Stella Marista")
    osm.node(LAT + 0.15, LNG + 0.1, place="suburb", name="Setor Central")
    osm.node(LAT + 0.15, LNG + 0.101, amenity="pharmacy", name="Farmácia St. Central Goiânia")
    osm.street((LAT - 0.12, LNG), 400, "Avenida Independência")
    osm.street((LAT - 0.115, LNG), 400, "Avenida Independência", highway="primary")
    osm.street((LAT - 0.14, LNG), 400, "Avenida Anápolis")
    osm.street((-16.30, -48.97), 400, "Avenida Goiânia")  # em Anápolis
    osm.node(LAT - 0.031, LNG + 0.04, amenity="bus_station", name="Rodoviária de Campinas")
    return osm


class Pack:
    def __init__(self, folder: Path):
        data = osm_reader.read(sample().write(folder / "x.osm.pbf"))
        items = records.build(data, MUNICIPALITIES, ["GO"])
        found = districts.build(data, MUNICIPALITIES, ["GO"])
        districts.assign(items, found)
        self.path = folder / "sabia-GO.sqlite"
        database.write_state(self.path, "GO", items["GO"], found["GO"], street_lines.build(items["GO"], data),
                             MUNICIPALITIES, {"build_id": "x", "osm_timestamp": "y"})


class SearchTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls._tmp = tempfile.TemporaryDirectory()
        cls.pack = Pack(Path(cls._tmp.name))
        cls.db = sqlite3.connect(cls.pack.path)

    @classmethod
    def tearDownClass(cls):
        cls.db.close()
        cls._tmp.cleanup()

    def first(self, query, **kw):
        found = search.search(self.db, query, **kw)
        self.assertTrue(found, f"nada para {query!r}")
        return found[0]

    def names(self, query, n=5, **kw):
        return [r.name for r in search.search(self.db, query, **kw)[:n]]

    def test_street_in_a_district(self):
        r = self.first("rua 10 setor oeste")
        self.assertEqual(("Rua 10", "Setor Oeste", "Goiânia"), (r.name, r.district, r.municipality))
        self.assertEqual("Rua 10, Setor Oeste, Goiânia", r.label)

    def test_accents_and_case_do_not_matter(self):
        self.assertEqual("Avenida Goiás", self.first("AVENIDA GOIÁS").name)

    def test_abbreviation_typed(self):
        self.assertEqual("Rua Doutor Olinto Manso", self.first("r dr olinto").name)

    def test_abbreviation_in_the_name(self):
        self.assertEqual("R. Cap. Caldas", self.first("rua capitao caldas").name)

    def test_numbers_in_words_and_digits(self):
        self.assertEqual({"Rua 14", "Rua Quatorze"}, set(self.names("rua quatorze", n=2)))
        self.assertEqual({"Rua 14", "Rua Quatorze"}, set(self.names("rua 14", n=2)))

    def test_number_is_not_a_prefix_except_the_last_word(self):
        """"rua 1 goiania" não traz "Rua 10"; "rua 1" (ainda digitando) traz."""
        self.assertNotIn("Rua 10", self.names("rua 1 goiania", n=10))
        self.assertIn("Rua 10", self.names("rua 1", n=10))

    def test_category_word_filters_by_kind(self):
        r = self.first("posto ipiranga", near=(LAT, LNG))
        self.assertEqual(("Ipiranga", "amenity=fuel", "Goiânia"), (r.name, r.kind, r.municipality))
        self.assertEqual("Anápolis", self.first("posto ipiranga anapolis").municipality)

    def test_category_word_that_is_also_in_the_name(self):
        self.assertEqual("Posto Cerrado", self.first("posto cerrado").name)

    def test_category_alone_is_the_nearest(self):
        r = self.first("posto", near=(LAT - 0.19, LNG))
        self.assertEqual("Posto Cerrado", r.name)
        self.assertLess(r.distance_m, 1500)

    def test_form_and_stopwords(self):
        self.assertEqual("Terminal Rodoviário de Goiânia", self.first("rodoviaria de goiania").name)

    def test_drop_prefix(self):
        r = self.first("cidade de goiania")
        self.assertEqual(("Goiânia", "municipality"), (r.name, r.kind))

    def test_city_before_street(self):
        self.assertEqual(["Goiânia", "Avenida Goiânia"], self.names("goiania", n=2))

    def test_municipality_name_pulls_its_records(self):
        """A palavra que é o nome inteiro de um município puxa os registros dele: "goiania" não é "Aparecida de
        Goiânia", embora case pelo prefixo."""
        r = self.first("rua 90 goiania")
        self.assertEqual(("Rua 90", "Goiânia"), (r.name, r.municipality))
        self.assertEqual("Aparecida de Goiânia", self.first("rua 90 aparecida de goiania").municipality)

    def test_abbreviation_in_a_name_is_a_whole_word(self):
        """"setor" também casa com "St." no nome, mas nunca com o começo de "Stella" (que, cidade, viria antes)."""
        self.assertEqual("Setor Marista", self.first("setor marista").name)

    def test_municipality_word_in_a_name_does_not_count(self):
        """"goiania" na busca diz o município; no nome de uma farmácia não a põe na frente do bairro."""
        self.assertEqual("Setor Central", self.first("setor central goiania").name)

    def test_municipality_name_in_the_middle_is_just_a_word(self):
        """Só o fim da busca diz o município: "avenida anapolis goiania" é a avenida chamada Anápolis, em Goiânia."""
        r = self.first("avenida anapolis goiania")
        self.assertEqual(("Avenida Anápolis", "Goiânia"), (r.name, r.municipality))

    def test_municipality_name_in_the_record_breaks_ties(self):
        self.assertEqual("Terminal Rodoviário de Goiânia", self.first("rodoviaria goiania", near=None).name)

    def test_more_important_street_first(self):
        r = self.first("avenida independencia goiania")
        self.assertEqual(("Avenida Independência", "highway=primary"), (r.name, r.kind))

    def test_category_word_in_the_name_counts(self):
        self.assertIn(self.first("rodoviaria").name, ("Terminal Rodoviário de Goiânia", "Rodoviária de Campinas"))

    def test_match_strings_never_mix_or_with_implicit_and(self):
        """A precedência de OR muda entre a sintaxe padrão e a estendida do FTS: cada MATCH é só AND."""
        for query in ("r dr olinto", "rua quatorze", "posto ipiranga anapolis", "rodoviaria de goiania"):
            for match in search.match_strings(self.db, query):
                self.assertNotIn(" OR ", match.upper())


class WhichStreetTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls._tmp = tempfile.TemporaryDirectory()
        cls.pack = Pack(Path(cls._tmp.name))
        cls.db = sqlite3.connect(cls.pack.path)

    @classmethod
    def tearDownClass(cls):
        cls.db.close()
        cls._tmp.cleanup()

    def test_point_on_a_street(self):
        lat, lng = north(*east(LAT + 0.01, LNG + 0.002, 200), 8)
        r = search.which_street(self.db, lat, lng)
        self.assertEqual(("Rua 10", "Setor Oeste"), (r.name, r.district))
        self.assertLess(r.distance_m, 10)

    def test_far_from_every_street(self):
        self.assertIsNone(search.which_street(self.db, LAT - 0.4, LNG - 0.2))


if __name__ == "__main__":
    unittest.main()
