"""Os postos de combustível da ANP (HS10): a API de revendedores baixada por UF e conferida, a leitura e os postos que
entram; o posto sem nome do pacote ganha o nome da ANP."""
import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from sabia import anp, config, sources  # noqa: E402
from sabia.municipalities import MunicipalityIndex  # noqa: E402
from sabia.records import Item  # noqa: E402
from tests.fake_server import FakeServer  # noqa: E402
from tests.osm_builder import MUNICIPALITIES, east  # noqa: E402


def station(company="COMERCIO DE DERIVADOS DE PETROLEO SOUZA LTDA", brand="BANDEIRA BRANCA", lat="-16.7",
            lng="-49.2", uf="GO", cnpj="01016509000195", sigaf=""):
    """Um posto como a API de revendedores devolve (só os campos lidos e alguns vizinhos)."""
    return {"codigoSIMP": "1", "razaoSocial": company, "cnpj": cnpj, "endereco": "AVENIDA PIO 12, 555", "uf": uf,
            "municipio": "GOIANIA", "distribuidora": brand, "latitude": lat, "longitude": lng, "statusSIGAF": sigaf}


def page(rows, number=1, total=1):
    return json.dumps({"status": 200, "succeeded": True,
                       "searchPageFilter": {"numeroPagina": number, "tamanhoPagina": 5000,
                                            "totalRegistro": len(rows), "totalPagina": total},
                       "data": rows}, ensure_ascii=False).encode("utf-8")


def write_stations(path: Path, rows):
    path.write_text(json.dumps(list(rows), ensure_ascii=False), encoding="utf-8")


def one_per_state():
    return [station(uf=uf) for uf in config.STATES]


class ProblemTest(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.path = Path(self._tmp.name) / "anp.json"
        self._min = anp.MIN_STATIONS
        anp.MIN_STATIONS = 27

    def tearDown(self):
        anp.MIN_STATIONS = self._min
        self._tmp.cleanup()

    def test_a_good_file(self):
        write_stations(self.path, one_per_state())
        self.assertIsNone(anp.problem(self.path))

    def test_not_json_or_not_a_list(self):
        self.path.write_text("<html>erro</html>", encoding="utf-8")
        self.assertIn("JSON", anp.problem(self.path))
        self.path.write_text(json.dumps({"data": []}), encoding="utf-8")
        self.assertIn("lista", anp.problem(self.path))

    def test_a_missing_field_or_state_or_too_few(self):
        row = station()
        del row["distribuidora"]
        write_stations(self.path, one_per_state() + [row])
        self.assertIn("distribuidora", anp.problem(self.path))
        write_stations(self.path, [s for s in one_per_state() if s["uf"] != "GO"] * 2)
        self.assertIn("GO", anp.problem(self.path))
        anp.MIN_STATIONS = 30
        write_stations(self.path, one_per_state())
        self.assertIn("27 postos", anp.problem(self.path))


class LoadTest(unittest.TestCase):
    def load(self, rows):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "anp.json"
            write_stations(path, rows)
            return anp.load(path)

    def test_names_of_branded_and_unbranded_stations(self):
        found = self.load([station(brand="IPIRANGA"), station(brand="VIBRA"), station(brand="RAIZEN"),
                           station(brand="NEXTA"), station(), station(company="AUTO POSTO BOA VIAGEM EIRELI ME")])
        self.assertEqual(["Posto Ipiranga", "Posto Petrobras", "Posto Shell", "Posto Nexta",
                          "Posto Comercio de Derivados de Petroleo Souza", "Auto Posto Boa Viagem"],
                         [p.name for p in found])
        self.assertTrue(all(p.kind == "amenity=fuel" for p in found))
        self.assertEqual((-16.7, -49.2), (found[0].lat, found[0].lng))

    def test_without_a_point_or_closed_stays_out(self):
        found = self.load([station(lat="", lng=""), station(lat="0", lng="0"), station(sigaf="INTERDITADO"),
                           station(lat="-16,5", lng="-49,1")])
        self.assertEqual([(-16.5, -49.1)], [(p.lat, p.lng) for p in found])


def fuel(name, lat, lng, kind="amenity=fuel"):
    return Item("poi", kind, name, "5208707", lat, lng)


class AddTest(unittest.TestCase):
    def setUp(self):
        self.index = MunicipalityIndex(MUNICIPALITIES)
        self.new = [anp.Point("Posto Ipiranga", "amenity=fuel", -16.7, -49.2)]

    def add(self, existing):
        items = {"GO": list(existing)}
        return anp.add(items, self.new, self.index, ["GO"]), items

    def test_a_new_station_comes_in(self):
        counts, items = self.add([])
        self.assertEqual((1, 0, 0), counts)

    def test_a_station_of_the_package_nearby_is_the_same_and_gets_the_name_if_it_has_none(self):
        lat, lng = east(-16.7, -49.2, 95)
        counts, items = self.add([fuel("", lat, lng)])
        self.assertEqual((0, 1, 1), counts)
        self.assertEqual("Posto Ipiranga", items["GO"][0].name)
        counts, items = self.add([fuel("Auto Posto Cerrado", lat, lng)])
        self.assertEqual((0, 1, 0), counts)
        self.assertEqual("Auto Posto Cerrado", items["GO"][0].name)

    def test_far_away_or_not_a_station_comes_in(self):
        lat, lng = east(-16.7, -49.2, 105)
        self.assertEqual((1, 0, 0), self.add([fuel("", lat, lng)])[0])
        self.assertEqual((1, 0, 0), self.add([fuel("", -16.7, -49.2, kind="shop=car_repair")])[0])

    def test_two_new_stations_side_by_side_come_in_once_in_order_and_only_in_the_states_asked_for(self):
        items = {"GO": [fuel("Zeta", -16.6, -49.1, kind="shop=tyres")]}
        points = [anp.Point("Posto Ipiranga", "amenity=fuel", -16.7, -49.2),
                  anp.Point("Posto Shell", "amenity=fuel", *east(-16.7, -49.2, 30)),
                  anp.Point("Posto Brasília", "amenity=fuel", -15.8, -47.9)]
        self.assertEqual((1, 1, 0), anp.add(items, points, self.index, ["GO"]))
        self.assertEqual(["Posto Ipiranga", "Zeta"], [i.name for i in items["GO"]])
        self.assertNotIn("DF", items)

    def test_the_radius_measured(self):
        self.assertEqual(100.0, anp.DUPLICATE_M)


class DownloadTest(unittest.TestCase):
    """sources.anp_stations: cada UF, página por página, num arquivo só, conferido."""

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.raw = Path(self._tmp.name)
        self.server = FakeServer().__enter__()
        for uf in config.STATES:
            rows = [station(uf=uf, cnpj=f"{uf}1"), station(uf=uf, cnpj=f"{uf}2")]
            self.server.files[f"/v1/combustivel?uf={uf}&numeropagina=1"] = page(rows[:1], 1, 2)
            self.server.files[f"/v1/combustivel?uf={uf}&numeropagina=2"] = page(rows[1:], 2, 2)
        self._patches = [mock.patch.object(config, "RAW", self.raw),
                         mock.patch.object(config, "ANP_API_URL", self.server.url("/v1/combustivel")),
                         mock.patch.object(anp, "MIN_STATIONS", 54),
                         mock.patch.object(anp, "PAUSE", 0),
                         mock.patch.object(sources, "RETRY_DELAY", 0)]
        for p in self._patches:
            p.start()

    def tearDown(self):
        for p in self._patches:
            p.stop()
        self.server.__exit__(None, None, None)
        self._tmp.cleanup()

    def test_every_state_and_page(self):
        path = sources.anp_stations()
        self.assertEqual(self.raw / "anp_postos.json", path)
        rows = json.loads(path.read_text(encoding="utf-8"))
        self.assertEqual(54, len(rows))
        self.assertEqual({"GO1", "GO2"}, {r["cnpj"] for r in rows if r["uf"] == "GO"})
        self.assertEqual(datetime_today(), sources.source_record(sources.ANP_FILE)["date"])
        self.assertIn(sources.ANP_FILE, sources.CHECKED_FILES)

    def test_a_bad_answer_is_not_saved_and_the_error_names_the_anp(self):
        self.server.files["/v1/combustivel?uf=GO&numeropagina=2"] = b"<html>erro</html>"
        with self.assertRaises(RuntimeError) as ctx:
            sources.anp_stations()
        self.assertFalse((self.raw / sources.ANP_FILE).exists())
        self.assertIn("ANP", str(ctx.exception))

    def test_a_pause_between_requests(self):
        """A API fica atrás de um Cloudflare que responde 429 a pedidos seguidos (2026-10-07, na 12ª UF)."""
        with mock.patch.object(anp, "PAUSE", 4), mock.patch.object(sources.time, "sleep") as sleep:
            sources.anp_stations()
        self.assertEqual(54, sleep.call_args_list.count(mock.call(4)))
        self.assertGreaterEqual(anp.PAUSE_DEFAULT, 3)

    def test_a_state_without_stations_is_not_saved(self):
        self.server.files["/v1/combustivel?uf=GO&numeropagina=1"] = page([], 1, 1)
        with self.assertRaises(RuntimeError) as ctx:
            sources.anp_stations()
        self.assertFalse((self.raw / sources.ANP_FILE).exists())
        self.assertIn("GO", str(ctx.exception))

    def test_a_good_cached_file_is_not_downloaded_again(self):
        sources.anp_stations()
        before = len(self.server.requests)
        sources.anp_stations()
        self.assertEqual(before, len(self.server.requests))

    def test_the_credit(self):
        self.assertIn("postos de combustível: ANP", config.ATTRIBUTION)


def datetime_today():
    from datetime import datetime, timezone
    return datetime.now(timezone.utc).strftime("%Y-%m-%d")


if __name__ == "__main__":
    unittest.main()
