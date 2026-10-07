"""Os postos e unidades da Polícia Rodoviária Federal (HS2): o arquivo da ANTT conferido, a leitura e os registros que
entram, sem repetir os postos que o OpenStreetMap já tem."""
import json
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from sabia import config, merge, prf, sources  # noqa: E402
from sabia.municipalities import MunicipalityIndex  # noqa: E402
from sabia.records import Item  # noqa: E402
from tests.osm_builder import MUNICIPALITIES, east  # noqa: E402


def unit(name="PRF02-BR060_KM182+250", road="BR-60", km="182.25", uf="GO", lat="-16.7", lng="-49.2",
         status="Ativo"):
    """Uma linha do arquivo da ANTT (só as colunas lidas e algumas vizinhas)."""
    return {"concessionaria": "ROTA DE TESTE", "nome_do_prf": name, "rodovia": road, "uf": uf, "km_m": km,
            "municipio": "Goiânia", "situacao": status, "data_da_inativacao": "", "latitude": lat, "longitude": lng}


def write_prf(path: Path, rows, copies=1):
    path.write_text(json.dumps({"PRF": list(rows) * copies}, ensure_ascii=False), encoding="utf-8")


class ProblemTest(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.path = Path(self._tmp.name) / "prf.json"
        self._min = prf.MIN_UNITS
        prf.MIN_UNITS = 3

    def tearDown(self):
        prf.MIN_UNITS = self._min
        self._tmp.cleanup()

    def test_a_good_file_has_no_problem(self):
        write_prf(self.path, [unit()], copies=3)
        self.assertIsNone(prf.problem(self.path))

    def test_an_error_page_is_not_json(self):
        self.path.write_text("<html>erro</html>", encoding="utf-8")
        self.assertIn("JSON", prf.problem(self.path))

    def test_without_the_list_of_units(self):
        self.path.write_text(json.dumps({"outra": []}), encoding="utf-8")
        self.assertIn("PRF", prf.problem(self.path))

    def test_a_row_without_the_columns_read(self):
        row = unit()
        del row["latitude"]
        write_prf(self.path, [row], copies=3)
        self.assertIn("latitude", prf.problem(self.path))

    def test_too_few_units_with_a_point(self):
        write_prf(self.path, [unit(), unit(), unit(lat="")])
        self.assertIn("2 postos", prf.problem(self.path))


class LoadTest(unittest.TestCase):
    def load(self, rows):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "prf.json"
            write_prf(path, rows)
            return prf.load(path)

    def test_name_road_and_km_of_a_unit(self):
        [found] = self.load([unit()])
        self.assertEqual(("PRF - Polícia Rodoviária Federal, BR-060 km 182", "amenity=police", -16.7, -49.2),
                         (found.name, found.kind, found.lat, found.lng))

    def test_decimal_comma_and_a_road_already_with_three_digits(self):
        [found] = self.load([unit(road="BR-153", km="525,9")])
        self.assertEqual("PRF - Polícia Rodoviária Federal, BR-153 km 525", found.name)

    def test_without_km_or_road(self):
        names = [p.name for p in self.load([unit(km=""), unit(road="", km="")])]
        self.assertEqual(["PRF - Polícia Rodoviária Federal, BR-060", "PRF - Polícia Rodoviária Federal"], names)

    def test_only_the_active_ones(self):
        self.assertEqual([], self.load([unit(status="Inativo")]))

    def test_a_point_outside_brazil_or_unreadable_stays_out(self):
        self.assertEqual([], self.load([unit(lat="0", lng="0"), unit(lat="-16.7", lng="x"), unit(lat="", lng="")]))


def police(name, lat, lng, kind="amenity=police"):
    return Item("poi", kind, name, "5208707", lat, lng)


class AddTest(unittest.TestCase):
    """O que o OpenStreetMap já tem (o posto de polícia a até 250 m com nome de PRF ou sem nome) não entra de novo."""

    def setUp(self):
        self.index = MunicipalityIndex(MUNICIPALITIES)
        self.new = prf.load_rows([unit()])[0]

    def add(self, existing):
        items = {"GO": list(existing)}
        return prf.add(items, [self.new], self.index, ["GO"]), items

    def test_a_new_unit_comes_in(self):
        (added, repeated), items = self.add([])
        self.assertEqual((1, 0), (added, repeated))
        self.assertEqual("5208707", items["GO"][0].municipality)

    def test_the_prf_already_in_the_openstreetmap_is_not_repeated(self):
        for name in ("PRF", "Polícia Rodoviária Federal", "PRF - Policia Rodoviaria Federal", ""):
            with self.subTest(name=name):
                lat, lng = east(-16.7, -49.2, 240)
                self.assertEqual((0, 1), self.add([police(name, lat, lng)])[0])

    def test_beyond_the_radius_or_another_police_comes_in(self):
        lat, lng = east(-16.7, -49.2, 260)
        self.assertEqual((1, 0), self.add([police("PRF", lat, lng)])[0])
        self.assertEqual((1, 0), self.add([police("Polícia Federal", -16.7, -49.2)])[0])
        self.assertEqual((1, 0), self.add([police("PRF", -16.7, -49.2, kind="amenity=fuel")])[0])

    def test_two_units_at_the_same_point_come_in_once(self):
        items = {"GO": []}
        both = prf.load_rows([unit(name="UOP Jataí"), unit(name="Delegacia DEL 05")])
        self.assertEqual((1, 1), prf.add(items, both, self.index, ["GO"]))


class DownloadTest(unittest.TestCase):
    def test_the_url_and_the_file_name(self):
        self.assertTrue(config.PRF_URL.startswith("https://dados.antt.gov.br/"))
        self.assertTrue(config.PRF_URL.endswith(".json"))
        self.assertEqual("antt_postos_prf.json", sources.PRF_FILE)

    def test_the_credit_names_the_antt(self):
        self.assertIn("postos da PRF: ANTT", config.ATTRIBUTION)

    def test_the_radius_measured(self):
        self.assertEqual(250.0, prf.DUPLICATE_M)
        self.assertIsInstance(self.new_point(), merge.Point)

    def new_point(self):
        return prf.load_rows([unit()])[0]


if __name__ == "__main__":
    unittest.main()
