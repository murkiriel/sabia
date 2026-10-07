"""Os aeródromos da ANAC (HS8): as duas listas conferidas, a leitura e os registros que entram, sem repetir os
aeródromos que o OpenStreetMap já tem."""
import json
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from sabia import anac, config, sources  # noqa: E402
from sabia.municipalities import MunicipalityIndex  # noqa: E402
from sabia.records import Item  # noqa: E402
from tests.osm_builder import MUNICIPALITIES, east  # noqa: E402


def aerodrome(name="Fazenda Boa Vista", icao="SWXX", lat="-16,7", lng="-49,2", situation=None):
    """Uma linha das listas da ANAC (só as colunas lidas e algumas vizinhas). A dos públicos tem SITUAÇÃO."""
    row = {"CódigoOACI": icao, "CIAD": "GO0001", "Nome": name, "Município": "GOIÂNIA", "UF": "GO",
           "LatGeoPoint": lat, "LonGeoPoint": lng, "Altitude": 700.0}
    if situation is not None:
        row["SITUAÇÃO"] = situation
    return row


def write_list(path: Path, rows, copies=1):
    """Como a ANAC grava: JSON em UTF-8 com BOM."""
    path.write_bytes(json.dumps(list(rows) * copies, ensure_ascii=False).encode("utf-8-sig"))


class ProblemTest(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.path = Path(self._tmp.name) / "a.json"

    def tearDown(self):
        self._tmp.cleanup()

    def test_a_good_list_has_no_problem(self):
        write_list(self.path, [aerodrome()], copies=5)
        self.assertIsNone(anac.problem(self.path, 5))

    def test_an_error_page_is_not_json(self):
        self.path.write_text("<html>erro</html>", encoding="utf-8")
        self.assertIn("JSON", anac.problem(self.path, 1))

    def test_not_a_list_of_aerodromes(self):
        self.path.write_text(json.dumps({"erro": 1}), encoding="utf-8")
        self.assertIn("lista", anac.problem(self.path, 1))

    def test_a_missing_column_is_named(self):
        row = aerodrome()
        del row["LonGeoPoint"]
        write_list(self.path, [row], copies=5)
        self.assertIn("LonGeoPoint", anac.problem(self.path, 1))

    def test_too_few_with_a_point(self):
        write_list(self.path, [aerodrome(), aerodrome(lat="")], copies=2)
        self.assertIn("2 aeródromos", anac.problem(self.path, 3))

    def test_the_minimums_of_each_list(self):
        self.assertEqual((400, 3000), (anac.MIN_PUBLIC, anac.MIN_PRIVATE))


class LoadTest(unittest.TestCase):
    def load(self, rows):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "a.json"
            write_list(path, rows)
            return anac.load(path)

    def test_name_kind_and_point(self):
        [found] = self.load([aerodrome()])
        self.assertEqual(("Aeródromo Fazenda Boa Vista (SWXX)", "aeroway=aerodrome", -16.7, -49.2),
                         (found.name, found.kind, found.lat, found.lng))

    def test_names_that_already_say_what_it_is_and_capitals(self):
        names = [p.name for p in self.load([aerodrome("Aeroporto de Goiânia", "SBGO"),
                                            aerodrome("MIGUEL RODRIGUES DE BARROS", ""),
                                            aerodrome("Aeroclube de Goiás", "SWGO", lat="-16.6", lng="-49.3")])]
        self.assertEqual(["Aeroporto de Goiânia (SBGO)", "Aeródromo Miguel Rodrigues de Barros",
                          "Aeroclube de Goiás (SWGO)"], names)

    def test_closed_or_without_a_point_stays_out(self):
        found = self.load([aerodrome("Interditado", situation="Interditado"), aerodrome("Sem ponto", lat=""),
                           aerodrome("Zero", lat="0", lng="0"), aerodrome("Cadastrado", situation="Cadastrado")])
        self.assertEqual(["Aeródromo Cadastrado (SWXX)"], [p.name for p in found])


def osm_aerodrome(name, lat, lng, kind="aeroway=aerodrome"):
    return Item("poi", kind, name, "5208707", lat, lng)


class AddTest(unittest.TestCase):
    def setUp(self):
        self.index = MunicipalityIndex(MUNICIPALITIES)
        self.new = anac.load_rows([aerodrome()])

    def add(self, existing):
        items = {"GO": list(existing)}
        return anac.add(items, self.new, self.index, ["GO"]), items

    def test_a_new_aerodrome_comes_in(self):
        counts, items = self.add([])
        self.assertEqual((1, 0), counts)
        self.assertEqual("5208707", items["GO"][0].municipality)

    def test_an_aerodrome_of_the_openstreetmap_nearby_is_the_same_whatever_the_name(self):
        lat, lng = east(-16.7, -49.2, 1450)
        self.assertEqual((0, 1), self.add([osm_aerodrome("Pista do Zé", lat, lng)])[0])

    def test_far_away_or_not_an_aerodrome_comes_in(self):
        lat, lng = east(-16.7, -49.2, 1550)
        self.assertEqual((1, 0), self.add([osm_aerodrome("Pista do Zé", lat, lng)])[0])
        self.assertEqual((1, 0), self.add([osm_aerodrome("Fazenda Boa Vista", -16.7, -49.2, kind="place=farm")])[0])

    def test_the_radius_measured(self):
        self.assertEqual(1500.0, anac.DUPLICATE_M)


class DownloadTest(unittest.TestCase):
    def test_the_urls_and_the_file_names(self):
        for url in (config.ANAC_PUBLIC_URL, config.ANAC_PRIVATE_URL):
            self.assertTrue(url.startswith("https://sistemas.anac.gov.br/dadosabertos/Aerodromos/"))
            self.assertTrue(url.endswith(".json"))
        self.assertEqual(("anac_aerodromos_publicos.json", "anac_aerodromos_privados.json"),
                         (sources.ANAC_PUBLIC_FILE, sources.ANAC_PRIVATE_FILE))
        self.assertIn(sources.ANAC_PUBLIC_FILE, sources.CHECKED_FILES)
        self.assertIn(sources.ANAC_PRIVATE_FILE, sources.CHECKED_FILES)

    def test_the_credit(self):
        self.assertIn("aeródromos: ANAC", config.ATTRIBUTION)


if __name__ == "__main__":
    unittest.main()
