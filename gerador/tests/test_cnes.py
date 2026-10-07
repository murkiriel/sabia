"""Os hospitais, UPAs e prontos-socorros do CNES (HS3): o arquivo conferido, a leitura (só urgência e emergência) e
os registros que entram, sem repetir o que o OpenStreetMap já tem."""
import io
import sys
import tempfile
import unittest
import zipfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from sabia import cnes, config, sources, text  # noqa: E402
from sabia.municipalities import MunicipalityIndex  # noqa: E402
from sabia.records import Item  # noqa: E402
from tests.osm_builder import MUNICIPALITIES, east  # noqa: E402

HEADER = ["CO_CNES", "CO_UF", "CO_IBGE", "NO_RAZAO_SOCIAL", "NO_FANTASIA", "TP_UNIDADE", "NU_LATITUDE",
          "NU_LONGITUDE", "CO_TURNO_ATENDIMENTO", "CO_MOTIVO_DESAB"]


def unit(name="HOSPITAL SÃO JOSÉ", kind="5", lat="-16.7", lng="-49.2", ibge="520870", uf="52", shift="06",
         closed="", company="HOSPITAL SAO JOSE LTDA"):
    """Uma linha do CSV do CNES (só as colunas lidas e o código do estabelecimento)."""
    return {"CO_CNES": "1", "CO_UF": uf, "CO_IBGE": ibge, "NO_RAZAO_SOCIAL": company, "NO_FANTASIA": name,
            "TP_UNIDADE": kind, "NU_LATITUDE": lat, "NU_LONGITUDE": lng, "CO_TURNO_ATENDIMENTO": shift,
            "CO_MOTIVO_DESAB": closed}


def one_per_state():
    return [unit(uf=code, ibge=f"{code}0000") for code in config.IBGE_STATE_CODES]


def write_zip(path: Path, rows, copies=1, header=HEADER, inner="cnes_estabelecimentos.csv"):
    """O zip do CNES de mentira: um CSV separado por ponto e vírgula, com aspas, em latin-1, como o do Ministério."""
    out = io.StringIO()
    out.write(";".join(f'"{h}"' for h in header) + "\r\n")
    for row in list(rows) * copies:
        out.write(";".join(f'"{row.get(h, "")}"' for h in header) + "\r\n")
    with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as z:
        z.writestr(inner, out.getvalue().encode("latin-1"))


class ProblemTest(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.path = Path(self._tmp.name) / "cnes.zip"
        self._mins = cnes.MIN_ROWS, cnes.MIN_UNITS
        cnes.MIN_ROWS, cnes.MIN_UNITS = 27, 27

    def tearDown(self):
        cnes.MIN_ROWS, cnes.MIN_UNITS = self._mins
        self._tmp.cleanup()

    def test_a_good_file_has_no_problem(self):
        write_zip(self.path, one_per_state())
        self.assertIsNone(cnes.problem(self.path))

    def test_an_error_page_is_not_a_zip(self):
        self.path.write_text("<html>erro</html>", encoding="utf-8")
        self.assertIn("zip", cnes.problem(self.path))

    def test_a_zip_without_the_csv(self):
        with zipfile.ZipFile(self.path, "w") as z:
            z.writestr("leia-me.txt", "nada")
        self.assertIn("csv", cnes.problem(self.path))

    def test_a_missing_column_is_named(self):
        write_zip(self.path, one_per_state(), header=[h for h in HEADER if h != "TP_UNIDADE"])
        self.assertIn("TP_UNIDADE", cnes.problem(self.path))

    def test_a_missing_state_is_named(self):
        write_zip(self.path, [r for r in one_per_state() if r["CO_UF"] != "52"], copies=2)
        self.assertIn("GO", cnes.problem(self.path))

    def test_too_few_rows(self):
        cnes.MIN_ROWS = 100
        write_zip(self.path, one_per_state())
        self.assertIn("27 estabelecimentos", cnes.problem(self.path))

    def test_too_few_emergency_units(self):
        write_zip(self.path, one_per_state() + [unit(shift="03")] * 30)
        cnes.MIN_UNITS = 28
        self.assertIn("27 de urgência", cnes.problem(self.path))


class LoadTest(unittest.TestCase):
    def load(self, rows):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "cnes.zip"
            write_zip(path, rows)
            return cnes.load(path)

    def test_name_kind_point_and_municipality(self):
        [found] = self.load([unit()])
        self.assertEqual(("Hospital São José", "amenity=hospital", -16.7, -49.2, "520870"),
                         (found.name, found.kind, found.lat, found.lng, found.municipality))

    def test_only_emergency_types_open_all_day(self):
        rows = [unit(name=f"T{t}", kind=t) for t in ("5", "7", "15", "20", "21", "73", "62", "2", "36")]
        rows.append(unit(name="Diurno", shift="03"))
        self.assertEqual(["T5", "T7", "T15", "T20", "T21", "T73"], [u.name for u in self.load(rows)])

    def test_a_closed_one_or_one_without_a_point_stays_out(self):
        rows = [unit(closed="04"), unit(lat="", lng=""), unit(lat="0", lng="0"), unit(lat="-16,7", lng="-49,2")]
        self.assertEqual([(-16.7, -49.2)], [(u.lat, u.lng) for u in self.load(rows)])

    def test_without_a_trade_name_the_company_name(self):
        [found] = self.load([unit(name="", company="SANTA CASA DE MISERICORDIA DE GOIAS")])
        self.assertEqual("Santa Casa de Misericordia de Goias", found.name)


class TitleTest(unittest.TestCase):
    def test_title_case_in_portuguese(self):
        self.assertEqual("Hospital das Clínicas da UFG", text.title_pt("HOSPITAL DAS CLÍNICAS DA UFG"))
        self.assertEqual("UPA 24h Jardim Itaipu", text.title_pt("UPA 24H JARDIM ITAIPU"))
        self.assertEqual("HGG Hospital Geral de Goiânia", text.title_pt("HGG HOSPITAL GERAL DE GOIÂNIA"))
        self.assertEqual("Hospital Municipal e Maternidade II", text.title_pt("hospital municipal e maternidade ii"))
        self.assertEqual("De Olho Clínica", text.title_pt("DE OLHO CLÍNICA"))


def health(name, lat, lng, kind="amenity=hospital"):
    return Item("poi", kind, name, "5208707", lat, lng)


class AddTest(unittest.TestCase):
    def setUp(self):
        self.index = MunicipalityIndex(MUNICIPALITIES)

    def add(self, existing, units=None):
        items = {"GO": list(existing)}
        found = units if units is not None else [cnes.Unit("Hospital São José", "amenity=hospital", -16.7, -49.2,
                                                           "520870")]
        return cnes.add(items, found, self.index, ["GO"]), items

    def test_a_new_unit_comes_in_its_municipality(self):
        counts, items = self.add([])
        self.assertEqual((1, 0, 0), counts)
        self.assertEqual(("5208707", "poi"), (items["GO"][0].municipality, items["GO"][0].cls))

    def test_a_point_outside_the_municipality_it_declares_stays_out(self):
        counts, items = self.add([], [cnes.Unit("Longe", "amenity=hospital", -16.3, -48.9, "520870")])
        self.assertEqual((0, 0, 1), counts)
        self.assertEqual([], items["GO"])

    def test_the_same_hospital_in_the_openstreetmap_is_not_repeated(self):
        lat, lng = east(-16.7, -49.2, 480)
        for existing in (health("Hospital São José", lat, lng), health("Hosp. Sao Jose", lat, lng),
                         health("", lat, lng), health("São José", lat, lng, kind="amenity=clinic"),
                         health("UPA São José", lat, lng, kind="healthcare=hospital")):
            with self.subTest(existing=existing):
                self.assertEqual((0, 1, 0), self.add([existing])[0])

    def test_another_name_far_away_or_not_health_comes_in(self):
        lat, lng = east(-16.7, -49.2, 520)
        self.assertEqual((1, 0, 0), self.add([health("Hospital São José", lat, lng)])[0])
        self.assertEqual((1, 0, 0), self.add([health("Hospital Municipal", -16.7, -49.2)])[0])
        self.assertEqual((1, 0, 0), self.add([health("São José", -16.7, -49.2, kind="amenity=police")])[0])

    def test_a_unit_of_a_state_not_asked_for_is_not_counted(self):
        counts, _ = self.add([], [cnes.Unit("Em SP", "amenity=hospital", -16.3, -48.9, "355030")])
        self.assertEqual((0, 0, 0), counts)

    def test_the_radius_measured(self):
        self.assertEqual(500.0, cnes.DUPLICATE_M)


class DownloadTest(unittest.TestCase):
    def test_the_url_and_the_file_name(self):
        self.assertTrue(config.CNES_URL.startswith("https://s3.sa-east-1.amazonaws.com/ckan.saude.gov.br/CNES/"))
        self.assertTrue(config.CNES_URL.endswith(".zip"))
        self.assertEqual("cnes_estabelecimentos.zip", sources.CNES_FILE)

    def test_the_credit_names_the_cnes(self):
        self.assertIn("hospitais, UPAs e prontos-socorros: CNES (Ministério da Saúde)", config.ATTRIBUTION)


if __name__ == "__main__":
    unittest.main()
