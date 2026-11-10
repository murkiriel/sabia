"""Os nomes alternativos do OpenStreetMap (item 9): `alt_name`, `short_name`, `old_name`, `official_name`, `loc_name`,
`name:pt` e outros vão para o índice de busca do registro (o nome mostrado não muda): "eixão" acha o Eixo Rodoviário."""
import sqlite3
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from sabia import database, osm_reader, records, search, street_lines  # noqa: E402
from tests.osm_builder import MUNICIPALITIES, OsmBuilder, east  # noqa: E402


def sample():
    osm = OsmBuilder()
    osm.street((-15.79, -47.88), 400, "Eixo Rodoviário", highway="trunk", alt_name="Eixão;Eixo Rodoviário Sul")
    osm.street(east(-15.79, -47.88, 400), 400, "Eixo Rodoviário", highway="trunk", short_name="Eixão",
               old_name="Eixo Rodoviário Norte")  # emenda
    osm.node(-15.794, -47.882, amenity="bus_station", name="Rodoviária do Plano Piloto", short_name="Rodô",
             old_name="Estação Rodoviária de Brasília")
    osm.node(-16.70, -49.30, place="city", name="Goiânia", official_name="Município de Goiânia",
             loc_name="Goiânia")
    osm.node(-16.68, -49.25, amenity="fuel", name="Posto Cerrado", **{"name:pt": "Posto do Cerrado"})
    return osm


class AliasTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls._tmp = tempfile.TemporaryDirectory()
        folder = Path(cls._tmp.name)
        cls.data = osm_reader.read(sample().write(folder / "x.osm.pbf"))
        cls.items = records.build(cls.data, MUNICIPALITIES, ["DF", "GO"])
        path = folder / "sabia-DF.sqlite"
        database.write_state(path, "DF", cls.items["DF"], [], street_lines.build(cls.items["DF"], cls.data),
                             MUNICIPALITIES, {"build_id": "x", "osm_timestamp": "y"})
        cls.db = sqlite3.connect(path)

    @classmethod
    def tearDownClass(cls):
        cls.db.close()
        cls._tmp.cleanup()

    def aliases(self, uf, name):
        return sorted({a for i in self.items[uf] if i.name == name for a in i.aliases})

    def test_street_aliases_from_every_piece(self):
        """Os dois trechos emendados viram uma rua com os nomes de todos, sem repetir ("Eixão" está nos dois), cada
        valor separado por ";"."""
        (street,) = [i for i in self.items["DF"] if i.name == "Eixo Rodoviário"]
        self.assertEqual(["Eixão", "Eixo Rodoviário Sul", "Eixo Rodoviário Norte"], street.aliases)

    def test_the_reader_drops_an_alias_equal_to_the_name(self):
        """loc_name="Goiânia" é o próprio nome: não entra."""
        (goiania,) = [p for p in self.data.places if p.name == "Goiânia"]
        self.assertEqual(("Município de Goiânia",), goiania.aliases)

    def test_poi_aliases(self):
        self.assertEqual(["Estação Rodoviária de Brasília", "Rodô"], self.aliases("DF", "Rodoviária do Plano Piloto"))
        self.assertEqual(["Posto do Cerrado"], self.aliases("GO", "Posto Cerrado"))

    def test_the_seat_gives_its_aliases_to_the_municipality_but_not_its_own_name(self):
        self.assertEqual(["Município de Goiânia"], self.aliases("GO", "Goiânia"))

    def test_the_search_finds_by_the_alias_and_shows_the_name(self):
        """"estacao" e "sul" só estão nos nomes alternativos."""
        self.assertEqual("Rodoviária do Plano Piloto", search.search(self.db, "estacao rodoviaria")[0].name)
        self.assertEqual("Eixo Rodoviário", search.search(self.db, "eixo rodoviario sul")[0].name)


if __name__ == "__main__":
    unittest.main()
