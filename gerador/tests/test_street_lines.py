"""Traçado das ruas (G5, D6): cada trecho simplificado a 10 m, em pedaços de até 2 km com o quadrado do meio, para o
"que rua é esta?"."""
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from sabia import geo, osm_reader, records, street_lines  # noqa: E402
from tests.osm_builder import MUNICIPALITIES, OsmBuilder, east, north  # noqa: E402

LAT, LNG = -16.68, -49.26


def build(osm):
    with tempfile.TemporaryDirectory() as tmp:
        data = osm_reader.read(osm.write(Path(tmp) / "x.osm.pbf"))
    items = records.build(data, MUNICIPALITIES, ["GO"])["GO"]
    return items, street_lines.build(items, data)


def index_of(items, name, cls="street"):
    return next(i for i, it in enumerate(items) if it.name == name and it.cls == cls)


class SimplifyTest(unittest.TestCase):
    def test_straight_street_keeps_only_the_ends(self):
        osm = OsmBuilder()
        osm.street((LAT, LNG), 1000, "Rua Reta", step=20)  # 51 nós em linha reta
        items, lines = build(osm)
        (line,) = lines
        self.assertEqual(index_of(items, "Rua Reta"), line.item)
        self.assertEqual(2, len(street_lines.decode(line.coords)))

    def test_corners_over_10m_are_kept(self):
        osm = OsmBuilder()
        pts = [(LAT, LNG), north(*east(LAT, LNG, 100), 30), east(LAT, LNG, 200), north(*east(LAT, LNG, 300), 5),
               east(LAT, LNG, 400)]
        osm.way(pts, highway="residential", name="Rua Torta")
        _, lines = build(osm)
        (line,) = lines
        coords = street_lines.decode(line.coords)
        self.assertEqual(4, len(coords))  # o desvio de 30 m fica; o de 5 m sai
        self.assertAlmostEqual(pts[1][0], coords[1][0], places=4)

    def test_long_street_is_cut_in_pieces_with_their_own_cell(self):
        osm = OsmBuilder()
        osm.street((LAT, LNG), 5000, "Avenida Longa", highway="primary", step=100)
        _, lines = build(osm)
        self.assertEqual(3, len(lines))
        for line in lines:
            coords = street_lines.decode(line.coords)
            length = sum(geo.dist_m(*a, *b) for a, b in zip(coords, coords[1:]))
            self.assertLessEqual(length, street_lines.MAX_PIECE_M + 1)
            mid = geo.midpoint([c[0] for c in coords], [c[1] for c in coords])
            self.assertEqual(geo.cell(*mid), line.cell)
        total = sum(geo.dist_m(*street_lines.decode(x.coords)[0], *street_lines.decode(x.coords)[-1]) for x in lines)
        self.assertAlmostEqual(5000, total, delta=5)

    def test_encoding_roundtrip(self):
        coords = [(-16.68123, -49.26456), (-15.0, -47.99999)]
        self.assertEqual(coords, street_lines.decode(street_lines.encode(coords)))
        self.assertEqual(16, len(street_lines.encode(coords)))  # int32: lat, lng por vértice


class WhichStreetTest(unittest.TestCase):
    def test_point_beside_the_street_finds_it(self):
        """Duas ruas paralelas a 40 m; um ponto a 10 m de uma, no meio de um segmento longo, acha essa."""
        osm = OsmBuilder()
        osm.street((LAT, LNG), 1000, "Rua A", step=1000)
        osm.street(north(LAT, LNG, 40), 1000, "Rua B", step=1000)
        items, lines = build(osm)
        probe = north(*east(LAT, LNG, 500), 10)
        best = street_lines.nearest(lines, *probe)
        self.assertEqual("Rua A", items[best.item].name)
        probe = north(*east(LAT, LNG, 500), 31)
        self.assertEqual("Rua B", items[street_lines.nearest(lines, *probe).item].name)

    def test_unnamed_road_has_lines_on_the_road_record(self):
        osm = OsmBuilder()
        osm.street((LAT, LNG), 1500, "", highway="trunk", ref="BR-153", step=500)
        osm.street(north(LAT, LNG, 2000), 1500, "Avenida Brasil", highway="trunk", ref="BR-153", step=500)
        items, lines = build(osm)
        owners = sorted((items[line.item].cls, items[line.item].name) for line in lines)
        self.assertEqual([("road", "BR-153"), ("street", "Avenida Brasil")], owners)


if __name__ == "__main__":
    unittest.main()
