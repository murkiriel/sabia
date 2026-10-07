"""Os quilômetros das rodovias federais (HS6): o SNV do DNIT conferido, os trechos lidos e um ponto por km ao longo
de cada um ("BR-060 km 120"), sem repetir."""
import json
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from sabia import config, geo, snv, sources  # noqa: E402
from sabia.municipalities import MunicipalityIndex  # noqa: E402
from sabia.records import Item  # noqa: E402
from tests.osm_builder import MUNICIPALITIES, east  # noqa: E402


def segment(br="060", uf="GO", start=10.0, end=12.0, coords=None, kind="B", surface="DUP", version="202607A",
            day="2026-07-28Z"):
    """Um trecho do SNV como o WFS do DNIT devolve (só as propriedades lidas). Por padrão, 2 km para o leste a partir
    de (-16.7, -49.4), em Goiânia."""
    if coords is None:
        lat, lng = -16.7, -49.4
        coords = [[lng, lat], [east(lat, lng, 2000)[1], lat]]
    return {"type": "Feature", "geometry": {"type": "MultiLineString", "coordinates": [coords]},
            "properties": {"Codigo_BR": br, "Unidade_Federacao": uf, "Sigla_Tipo_Trecho": kind,
                           "Superficie_Federal": surface, "Quilometragem_Inicio": start, "Quilometragem_Fim": end,
                           "Versao_SNV": version, "dt_ini": day}}


def one_per_state():
    return [segment(uf=uf) for uf in config.STATES]


def write_snv(path: Path, features, copies=1):
    path.write_text(json.dumps({"type": "FeatureCollection", "features": list(features) * copies}),
                    encoding="utf-8")


class ProblemTest(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.path = Path(self._tmp.name) / "snv.json"
        self._min = snv.MIN_SEGMENTS
        snv.MIN_SEGMENTS = 27

    def tearDown(self):
        snv.MIN_SEGMENTS = self._min
        self._tmp.cleanup()

    def test_a_good_file_has_no_problem(self):
        write_snv(self.path, one_per_state())
        self.assertIsNone(snv.problem(self.path))

    def test_an_error_page_is_not_json(self):
        self.path.write_text("<html>erro</html>", encoding="utf-8")
        self.assertIn("JSON", snv.problem(self.path))

    def test_a_wfs_exception_is_not_a_feature_collection(self):
        self.path.write_text(json.dumps({"exceptions": [{"text": "erro"}]}), encoding="utf-8")
        self.assertIn("features", snv.problem(self.path))

    def test_a_missing_property_is_named(self):
        bad = segment()
        del bad["properties"]["Quilometragem_Fim"]
        write_snv(self.path, one_per_state() + [bad])
        self.assertIn("Quilometragem_Fim", snv.problem(self.path))

    def test_a_missing_state_is_named(self):
        write_snv(self.path, [s for s in one_per_state() if s["properties"]["Unidade_Federacao"] != "GO"], copies=2)
        self.assertIn("GO", snv.problem(self.path))

    def test_too_few_segments(self):
        snv.MIN_SEGMENTS = 30
        write_snv(self.path, one_per_state())
        self.assertIn("27 trechos", snv.problem(self.path))

    def test_the_version(self):
        write_snv(self.path, one_per_state())
        self.assertEqual(("202607A", "2026-07-28"), snv.version(self.path))

    def test_the_newest_version_if_two_come(self):
        write_snv(self.path, one_per_state() + [segment(version="202604A", day="2026-04-15Z")])
        self.assertEqual(("202607A", "2026-07-28"), snv.version(self.path))


class LoadTest(unittest.TestCase):
    def load(self, features):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "snv.json"
            write_snv(path, features)
            return snv.load(path)

    def test_only_the_main_axis_already_built(self):
        found = self.load([segment(), segment(kind="A"), segment(kind="C"), segment(surface="PLA"),
                           segment(surface="LEN")])
        self.assertEqual([("060", "GO", 10.0, 12.0), ("060", "GO", 10.0, 12.0)],
                         [(s.road, s.uf, s.start, s.end) for s in found])


class MarkersTest(unittest.TestCase):
    def markers(self, features):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "snv.json"
            write_snv(path, features)
            return snv.markers(snv.load(path))

    def test_one_point_per_whole_km_along_the_line(self):
        found = self.markers([segment(start=10.0, end=12.0)])
        self.assertEqual(["BR-060 km 10", "BR-060 km 11", "BR-060 km 12"], [p.name for p in found])
        self.assertTrue(all(p.kind == "highway=milestone" for p in found))
        lat0, lng0 = -16.7, -49.4
        self.assertAlmostEqual(0, geo.dist_m(found[0].lat, found[0].lng, lat0, lng0), delta=1)
        self.assertAlmostEqual(1000, geo.dist_m(found[1].lat, found[1].lng, lat0, lng0), delta=1)
        self.assertAlmostEqual(2000, geo.dist_m(found[2].lat, found[2].lng, lat0, lng0), delta=1)

    def test_proportional_when_the_line_is_not_the_nominal_length(self):
        # 2 km nominais (de 10,5 a 12,5) numa linha de 4 km: o km 11 fica a 1 km do começo
        lat, lng = -16.7, -49.4
        coords = [[lng, lat], [east(lat, lng, 4000)[1], lat]]
        found = self.markers([segment(start=10.5, end=12.5, coords=coords)])
        self.assertEqual(["BR-060 km 11", "BR-060 km 12"], [p.name for p in found])
        k11, k12 = found
        self.assertAlmostEqual(1000, geo.dist_m(k11.lat, k11.lng, lat, lng), delta=1)
        self.assertAlmostEqual(3000, geo.dist_m(k12.lat, k12.lng, lat, lng), delta=1)

    def test_the_shared_km_of_two_segments_comes_once_and_each_state_has_its_own_count(self):
        lat, lng = -16.7, -49.4
        a = segment(start=10.0, end=11.0, coords=[[lng, lat], [east(lat, lng, 1000)[1], lat]])
        b = segment(start=11.0, end=12.0, coords=[[east(lat, lng, 1000)[1], lat], [east(lat, lng, 2000)[1], lat]])
        other_state = segment(uf="DF", start=11.0, end=11.0)
        names = [p.name for p in self.markers([a, b, other_state])]
        self.assertEqual(["BR-060 km 10", "BR-060 km 11", "BR-060 km 12", "BR-060 km 11"], names)

    def test_three_digit_road_name(self):
        self.assertEqual(["BR-153 km 0"], [p.name for p in self.markers([segment(br="153", start=0.0, end=0.4)])])
        self.assertEqual(["BR-060 km 0"], [p.name for p in self.markers([segment(br="60", start=0.0, end=0.4)])])

    def test_a_long_nominal_segment_on_a_short_line(self):
        # 4 km nominais numa linha de 2 km: o km 1 fica a 500 m do começo
        found = self.markers([segment(start=0.0, end=4.0)])
        self.assertEqual(5, len(found))
        self.assertAlmostEqual(500, geo.dist_m(found[1].lat, found[1].lng, -16.7, -49.4), delta=1)


class AddTest(unittest.TestCase):
    def test_comes_in_once_and_the_same_marker_nearby_is_not_repeated(self):
        index = MunicipalityIndex(MUNICIPALITIES)
        items = {"GO": [Item("poi", "highway=milestone", "BR-060 km 11", "5208707", -16.7, -49.39)]}
        points = [snv.Point("BR-060 km 11", "highway=milestone", -16.7, -49.391),
                  snv.Point("BR-060 km 12", "highway=milestone", -16.7, -49.38)]
        self.assertEqual((1, 1), snv.add(items, points, index, ["GO"]))


class DownloadTest(unittest.TestCase):
    def test_the_url_asks_for_the_version_in_force_the_main_axis_and_geojson(self):
        import urllib.parse

        url = snv.url("2026-10-07")
        self.assertTrue(url.startswith("https://servicos.dnit.gov.br/dnitgeo/geoserver/"))
        query = dict(urllib.parse.parse_qsl(urllib.parse.urlsplit(url).query))
        self.assertEqual(("vgeo:vw_snv_rod", "application/json"), (query["typeNames"], query["outputFormat"]))
        self.assertEqual("dt_ini<='2026-10-07' AND dt_fim>='2026-10-07' AND Sigla_Tipo_Trecho='B' "
                         "AND Superficie_Federal<>'PLA'", query["CQL_FILTER"])
        self.assertEqual("dnit_snv.json", sources.SNV_FILE)

    def test_the_credit(self):
        self.assertIn("quilômetros das rodovias federais: DNIT (SNV)", config.ATTRIBUTION)


if __name__ == "__main__":
    unittest.main()
