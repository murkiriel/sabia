"""Bairros (G4): áreas de bairro das relações e das vias fechadas, e o bairro de cada registro pelo polígono, com o
ponto de bairro mais próximo (até 3 km, no mesmo município) como reserva."""
import sys
import tempfile
import unittest
from pathlib import Path

from shapely.geometry import box

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from sabia import districts, osm_reader, records  # noqa: E402
from sabia.sources import Municipality  # noqa: E402
from tests.osm_builder import ANAPOLIS, GOIANIA, MUNICIPALITIES, OsmBuilder, east, north  # noqa: E402

LAT, LNG = -16.68, -49.26  # dentro de Goiânia


def square(lat, lng, size_deg):
    return [(lat, lng), (lat, lng + size_deg), (lat + size_deg, lng + size_deg), (lat + size_deg, lng)]


def closed_way(osm, ring, **tags):
    refs = [osm.node(*p) for p in ring]
    return osm.way(refs + [refs[0]], **tags)


def run(osm, states=("GO",), municipalities=MUNICIPALITIES):
    with tempfile.TemporaryDirectory() as tmp:
        data = osm_reader.read(osm.write(Path(tmp) / "x.osm.pbf"))
    items = records.build(data, municipalities, list(states))
    found = districts.build(data, municipalities, list(states))
    districts.assign(items, found)
    return items, found


def district_of(items, name, cls="street"):
    (item,) = [i for i in items["GO"] if i.name == name and i.cls == cls]
    return item.district


class PolygonTest(unittest.TestCase):
    def test_street_inside_a_suburb_relation(self):
        osm = OsmBuilder()
        osm.multipolygon(square(LAT, LNG, 0.01), place="suburb", name="Setor Oeste")
        osm.street((LAT + 0.005, LNG + 0.001), 300, "Rua 10")
        items, found = run(osm)
        self.assertEqual("Setor Oeste", district_of(items, "Rua 10"))
        (d,) = found["GO"]
        self.assertEqual(("Setor Oeste", GOIANIA.code, "suburb"), (d.name, d.municipality, d.kind))
        self.assertIsNotNone(d.polygon)

    def test_street_inside_a_closed_way_neighbourhood(self):
        osm = OsmBuilder()
        closed_way(osm, square(LAT, LNG, 0.01), place="neighbourhood", name="Jardim América")
        osm.street((LAT + 0.005, LNG + 0.001), 300, "Rua C-1")
        items, _ = run(osm)
        self.assertEqual("Jardim América", district_of(items, "Rua C-1"))

    def test_admin_level_10_boundary_is_a_district(self):
        osm = OsmBuilder()
        osm.multipolygon(square(LAT, LNG, 0.01), boundary="administrative", admin_level="10", name="Centro")
        osm.multipolygon(square(LAT + 0.02, LNG, 0.01), boundary="administrative", admin_level="8", name="Distrito")
        osm.street((LAT + 0.005, LNG + 0.001), 300, "Rua 3")
        items, found = run(osm)
        self.assertEqual("Centro", district_of(items, "Rua 3"))
        self.assertEqual(["Centro"], [d.name for d in found["GO"]])

    def test_suburb_wins_over_a_neighbourhood_inside_it(self):
        osm = OsmBuilder()
        osm.multipolygon(square(LAT, LNG, 0.02), place="suburb", name="Setor Bueno")
        closed_way(osm, square(LAT + 0.005, LNG + 0.005, 0.005), place="neighbourhood", name="Condomínio Azul")
        osm.street((LAT + 0.007, LNG + 0.006), 200, "Rua T-30")
        items, _ = run(osm)
        self.assertEqual("Setor Bueno", district_of(items, "Rua T-30"))

    def test_smallest_wins_between_overlapping_suburbs(self):
        osm = OsmBuilder()
        osm.multipolygon(square(LAT, LNG, 0.03), place="suburb", name="Grande")
        osm.multipolygon(square(LAT + 0.01, LNG + 0.01, 0.01), place="suburb", name="Pequeno")
        osm.street((LAT + 0.015, LNG + 0.011), 200, "Rua 5")
        items, _ = run(osm)
        self.assertEqual("Pequeno", district_of(items, "Rua 5"))

    def test_poi_gets_a_district_too_and_the_suburb_place_does_not(self):
        osm = OsmBuilder()
        osm.multipolygon(square(LAT, LNG, 0.01), place="suburb", name="Setor Marista")
        osm.node(LAT + 0.004, LNG + 0.004, amenity="pharmacy", name="Drogaria X")
        items, _ = run(osm)
        self.assertEqual("Setor Marista", district_of(items, "Drogaria X", cls="poi"))
        self.assertIsNone(district_of(items, "Setor Marista", cls="place"))


class FallbackPointTest(unittest.TestCase):
    def test_nearest_district_point_within_3km(self):
        osm = OsmBuilder()
        osm.node(LAT, LNG, place="suburb", name="Vila Nova")
        osm.node(*north(LAT, LNG, -4000), place="suburb", name="Longe")
        osm.street(north(LAT, LNG, 1500), 200, "Rua 200")
        items, found = run(osm)
        self.assertEqual("Vila Nova", district_of(items, "Rua 200"))
        self.assertEqual({"Vila Nova", "Longe"}, {d.name for d in found["GO"]})
        self.assertTrue(all(d.polygon is None for d in found["GO"]))

    def test_beyond_3km_there_is_no_district(self):
        osm = OsmBuilder()
        osm.node(LAT, LNG, place="suburb", name="Vila Nova")
        osm.street(east(LAT, LNG, 3500), 200, "Rua Afastada")
        items, _ = run(osm)
        self.assertIsNone(district_of(items, "Rua Afastada"))

    def test_point_of_another_municipality_is_not_used(self):
        """Dois municípios vizinhos: o ponto de bairro a 1 km, do outro lado da divisa, não vale."""
        left = Municipality("5200001", "Esquerda", "GO", box(-50.0, -17.0, -49.9, -16.9))
        right = Municipality("5200002", "Direita", "GO", box(-49.9, -17.0, -49.8, -16.9))
        osm = OsmBuilder()
        osm.node(-16.95, -49.895, place="suburb", name="Bairro da Direita")
        osm.street((-16.95, -49.907), 100, "Rua da Divisa")
        items, _ = run(osm, municipalities=[left, right])
        self.assertIsNone(district_of(items, "Rua da Divisa"))

    def test_polygon_and_point_of_same_name_are_one_district(self):
        osm = OsmBuilder()
        osm.multipolygon(square(LAT, LNG, 0.01), place="suburb", name="Setor Sul")
        osm.node(LAT + 0.005, LNG + 0.005, place="suburb", name="Setor Sul")
        _, found = run(osm)
        (d,) = found["GO"]
        self.assertIsNotNone(d.polygon)

    def test_districts_of_each_state(self):
        osm = OsmBuilder()
        osm.node(-16.33, -48.95, place="suburb", name="Jundiaí")
        osm.node(-15.79, -47.88, place="suburb", name="Asa Sul")
        _, found = run(osm, states=("GO", "DF"))
        self.assertEqual(["Jundiaí"], [d.name for d in found["GO"]])
        self.assertEqual(ANAPOLIS.code, found["GO"][0].municipality)
        self.assertEqual(["Asa Sul"], [d.name for d in found["DF"]])


if __name__ == "__main__":
    unittest.main()
