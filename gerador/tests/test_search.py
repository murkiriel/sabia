"""A busca de referência (sabia/search.py): as regras que quem consome aplica sobre o pacote (docs/CONSUMO.md), e o
"que rua é esta?". As travas de buscas de verdade (G7a) usam este mesmo código."""
import sqlite3
import sys
import tempfile
import unittest
from pathlib import Path

from shapely.geometry import box

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from sabia import database, districts, geo, osm_reader, records, search, street_lines  # noqa: E402
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
    osm.street((LAT - 0.16, LNG), 400, "Rua R-16")
    return osm


# A escada de números do CNEFE da Rua 10 do Setor Oeste (a via vai 400 m para leste a partir de RUA_10): pares de 2 a
# 202 ao longo dela, ímpares de 1 a 101 só na primeira metade, e um segundo pedaço par (1002 a 1042) 100 m adiante.
RUA_10 = (LAT + 0.01, LNG + 0.002)
LADDER = [(0, 0, 2, *RUA_10), (0, 0, 102, *east(*RUA_10, 200)), (0, 0, 202, *east(*RUA_10, 400)),
          (1, 0, 1, *RUA_10), (1, 0, 101, *east(*RUA_10, 200)),
          (0, 1, 1002, *east(*RUA_10, 500)), (0, 1, 1042, *east(*RUA_10, 520))]


class Pack:
    def __init__(self, folder: Path):
        data = osm_reader.read(sample().write(folder / "x.osm.pbf"))
        items = records.build(data, MUNICIPALITIES, ["GO"])
        found = districts.build(data, MUNICIPALITIES, ["GO"])
        districts.assign(items, found)
        street = next(i for i in items["GO"] if i.name == "Rua 10" and i.district == "Setor Oeste")
        street.numbers = list(LADDER)
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

    def test_number_in_words_is_a_whole_word(self):
        """"10" também casa com "dez", mas nunca com o começo de "dezesseis" (a "Rua R-16" no índice é "rua r 16
        dezesseis")."""
        self.assertNotIn("Rua R-16", self.names("rua 10 goiania", n=10))
        self.assertNotIn("Rua R-16", self.names("rua 10 setor", n=10))

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


class HouseNumberTest(unittest.TestCase):
    """O número da casa na busca (o CNEFE, tabela house_number): "rua 10, 150, setor oeste" é a Rua 10 no ponto do
    150. Antes, o número era mais uma palavra que o nome tinha de ter, e a busca não achava nada."""

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

    def assertNear(self, r, point, meters):
        self.assertLess(geo.dist_m(r.lat, r.lng, *point), meters, f"{r.label} em ({r.lat}, {r.lng})")

    def test_number_on_the_even_side(self):
        r = self.first("rua 10, 152, setor oeste")
        self.assertEqual(("Rua 10", "Setor Oeste", 152), (r.name, r.district, r.house_number))
        self.assertNear(r, east(*RUA_10, 300), 3)  # entre o 102 (200 m) e o 202 (400 m)
        self.assertEqual("Rua 10, 152, Setor Oeste, Goiânia", r.label)

    def test_number_on_the_odd_side_and_the_municipality_at_the_end(self):
        r = self.first("rua 10 51 goiania")
        self.assertEqual(("Rua 10", "Setor Oeste", 51), (r.name, r.district, r.house_number))
        self.assertNear(r, east(*RUA_10, 100), 3)

    def test_a_number_of_a_rung(self):
        r = self.first("rua 10 102")
        self.assertEqual(102, r.house_number)
        self.assertNear(r, east(*RUA_10, 200), 1)

    def test_second_piece_of_the_street(self):
        r = self.first("rua 10 1022 setor oeste")
        self.assertEqual(1022, r.house_number)
        self.assertNear(r, east(*RUA_10, 510), 3)

    def test_written_with_n_or_numero(self):
        for query in ("rua 10 n 152", "rua 10 nº 152", "rua 10, número 152", "rua 10 nr 152"):
            self.assertEqual(152, self.first(query).house_number, query)

    def test_number_outside_the_ladder_is_the_street(self):
        """Sem degrau que cerque o número (o ímpar 151 passa do último ímpar), a rua, no ponto dela, sem número."""
        r = self.first("rua 10 151 setor oeste")
        self.assertEqual(("Rua 10", "Setor Oeste", None), (r.name, r.district, r.house_number))

    def test_between_two_pieces_there_is_no_number(self):
        """O 500 fica entre o fim do primeiro pedaço par (202) e o começo do segundo (1002): não se interpola de um
        pedaço para o outro (podem ser a mesma rua em dois bairros)."""
        self.assertIsNone(self.first("rua 10 500 setor oeste").house_number)

    def test_the_street_words_are_whole_when_the_number_ends_the_query(self):
        """"rua 1 152": o "1" já foi digitado inteiro (o número veio depois): não é o começo de "Rua 10"."""
        found = search.search(self.db, "rua 1 152")
        self.assertNotIn(152, [r.house_number for r in found])

    def test_the_numbered_street_beats_a_closer_one(self):
        """Perto da outra Rua 10, a que tem o 152 ainda vem antes."""
        r = self.first("rua 10 152", near=(LAT + 0.05, LNG))
        self.assertEqual(("Setor Oeste", 152), (r.district, r.house_number))

    def test_street_without_numbers_is_still_found(self):
        r = self.first("avenida goias 150")
        self.assertEqual(("Avenida Goiás", None), (r.name, r.house_number))

    def test_the_street_with_the_number_comes_first(self):
        """As duas "Rua 10" de Goiânia: a que tem o 152 vem antes."""
        self.assertEqual("Setor Oeste", self.first("rua 10 152 goiania").district)

    def test_a_number_in_the_name_is_not_a_house_number(self):
        """"rua 14", "rua 10 setor oeste": o número depois de rua, avenida, quadra, km... é do nome."""
        self.assertIsNone(self.first("rua 14").house_number)
        self.assertEqual("Rua 14", self.first("rua 14 goiania").name)
        r = self.first("rua 10 setor oeste")
        self.assertEqual(("Rua 10", None), (r.name, r.house_number))

    def test_house_position_reads_the_ladder(self):
        street = self.first("rua 10 setor oeste").id
        self.assertIsNone(search.house_position(self.db, street, 1500))
        self.assertIsNone(search.house_position(self.db, street, 0))
        lat, lng = search.house_position(self.db, street, 2)
        self.assertLess(geo.dist_m(lat, lng, *RUA_10), 1)


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
