"""As localidades do IBGE (HS1): o arquivo conferido, a leitura e os registros que entram, sem repetir o
OpenStreetMap."""
import sqlite3
import sys
import tempfile
import unittest
import zipfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from sabia import config, localities, sources  # noqa: E402
from sabia.records import Item  # noqa: E402

TABLE = "BR_localidades_2022"
COLUMNS = ("SIGLA_UF", "CD_MUN", "CT_LOCALIDADE", "SCT_LOCALIDADE", "NM_LOCALIDADE", "LAT_LOCALIDADE",
           "LONG_LOCALIDADE")


def one_per_state(category="Povoado"):
    """Uma localidade em cada UF, num município de mentira dela ("<código da UF>00001")."""
    return [(uf, f"{code}00001", category, None, f"Lugar {uf}", -10.0, -50.0)
            for code, uf in config.IBGE_STATE_CODES.items()]


def write_zip(path: Path, rows, table=TABLE, copies=1):
    """O zip do IBGE de mentira: um GeoPackage com a tabela das localidades (só as colunas lidas)."""
    with tempfile.TemporaryDirectory() as tmp:
        gpkg = Path(tmp) / "BR_localidades_2022.gpkg"
        with sqlite3.connect(gpkg) as db:
            db.execute("CREATE TABLE gpkg_contents (table_name TEXT, data_type TEXT)")
            db.execute("INSERT INTO gpkg_contents VALUES (?, 'features')", (table,))
            db.execute(f"CREATE TABLE '{table}' ({', '.join(COLUMNS)})")
            db.executemany(f"INSERT INTO '{table}' VALUES ({', '.join('?' * len(COLUMNS))})", list(rows) * copies)
        db.close()
        with zipfile.ZipFile(path, "w") as z:
            z.write(gpkg, gpkg.name)


class ProblemTest(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.path = Path(self._tmp.name) / "loc.zip"
        self._min = localities.MIN_LOCALITIES
        localities.MIN_LOCALITIES = 27

    def tearDown(self):
        localities.MIN_LOCALITIES = self._min
        self._tmp.cleanup()

    def test_a_good_file_has_no_problem(self):
        write_zip(self.path, one_per_state())
        self.assertIsNone(localities.problem(self.path))

    def test_an_error_page_is_not_a_zip(self):
        self.path.write_text("<html>erro</html>", encoding="utf-8")
        self.assertIn("zip", localities.problem(self.path))

    def test_a_missing_state_is_named(self):
        write_zip(self.path, [r for r in one_per_state() if r[0] != "GO"])
        self.assertIn("GO", localities.problem(self.path))

    def test_too_few_localities_is_a_problem(self):
        localities.MIN_LOCALITIES = 100
        write_zip(self.path, one_per_state())
        self.assertIn("27", localities.problem(self.path))


class LoadTest(unittest.TestCase):
    def test_reads_name_category_municipality_and_point(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "loc.zip"
            indigenous = ("GO", "5200050", "Localidade Indígena", "Agrupamento Indígena", "Aldeia Tal", -16.2, -48.8)
            write_zip(path, [("GO", "5200050", "Vila", None, "Posse d'Abadia", -16.1, -48.7), indigenous])
            found = localities.load(path)
        self.assertEqual([("Posse d'Abadia", "Vila", "5200050", -16.1, -48.7),
                          ("Aldeia Tal", "Localidade Indígena", "5200050", -16.2, -48.8)],
                         [(f.name, f.category, f.municipality, f.lat, f.lng) for f in found])


def place(name, municipality, lat, lng, kind="place=village"):
    return Item("place", kind, name, municipality, lat, lng)


class AddTest(unittest.TestCase):
    MUN = "5208707"  # Goiânia

    def loc(self, name, category="Povoado", lat=-16.60, lng=-49.30, municipality=None):
        return localities.Locality(name, category, municipality or self.MUN, lat, lng)

    def test_each_category_gets_its_kind_and_the_seats_stay_out(self):
        items = {"GO": []}
        added = localities.add(items, [self.loc("A", "Povoado"), self.loc("B", "Vila"), self.loc("C", "Lugarejo"),
                                       self.loc("D", "Localidade Indígena"), self.loc("E", "Localidade Quilombola"),
                                       self.loc("F", "Agrovila do PA"), self.loc("G", "Outras Localidades"),
                                       self.loc("H", "Cidade")], ["GO"])
        self.assertEqual(7, added)
        self.assertEqual({"A": "ibge=povoado", "B": "ibge=vila", "C": "ibge=lugarejo", "D": "ibge=indigena",
                          "E": "ibge=quilombola", "F": "ibge=agrovila", "G": "ibge=localidade"},
                         {i.name: i.kind for i in items["GO"]})
        self.assertTrue(all(i.cls == "place" and i.municipality == self.MUN for i in items["GO"]))

    def test_a_category_the_ibge_adds_later_still_comes_in(self):
        items = {"GO": []}
        localities.add(items, [self.loc("Nova", "Categoria Nova")], ["GO"])
        self.assertEqual(["ibge=localidade"], [i.kind for i in items["GO"]])

    def test_the_same_place_in_the_openstreetmap_is_not_repeated(self):
        # "Souzânia" a 1,1 km de um lugar de mesmo nome (sem acento e em maiúsculas) no mesmo município: fica de fora.
        items = {"GO": [place("Souzania", self.MUN, -16.60, -49.29)]}
        self.assertEqual(0, localities.add(items, [self.loc("SOUZÂNIA")], ["GO"]))
        self.assertEqual(1, len(items["GO"]))

    def test_the_same_name_far_away_or_in_another_municipality_comes_in(self):
        items = {"GO": [place("Souzânia", self.MUN, -16.70, -49.30)]}          # 11 km
        added = localities.add(items, [self.loc("Souzânia"), self.loc("Souzânia", municipality="5201108")], ["GO"])
        self.assertEqual(2, added)

    def test_two_localities_of_the_same_name_close_together_come_in_once(self):
        items = {"GO": []}
        self.assertEqual(1, localities.add(items, [self.loc("Boa Vista"), self.loc("Boa Vista", lat=-16.601)], ["GO"]))

    def test_only_the_states_asked_for(self):
        items = {"GO": []}
        self.assertEqual(0, localities.add(items, [self.loc("Fora", municipality="3550308")], ["GO"]))

    def test_the_records_stay_in_the_generation_order(self):
        items = {"GO": [place("Zeta", self.MUN, -16.0, -49.0)]}
        localities.add(items, [self.loc("Alfa")], ["GO"])
        self.assertEqual(["Alfa", "Zeta"], [i.name for i in items["GO"]])


class DownloadTest(unittest.TestCase):
    def test_the_url_and_the_file_name(self):
        self.assertTrue(config.IBGE_LOCALITIES_URL.startswith("https://geoftp.ibge.gov.br/"))
        self.assertTrue(config.IBGE_LOCALITIES_URL.endswith("Localidades_Brasil_gpkg.zip"))
        self.assertEqual("ibge_localidades.zip", sources.LOCALITIES_FILE)

    def test_the_credit_names_the_ibge_localities(self):
        self.assertIn("localidades: IBGE", config.ATTRIBUTION)


if __name__ == "__main__":
    unittest.main()
