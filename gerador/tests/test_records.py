"""Os registros de cada estado: lugares, ruas (regra D5), rodovias por município e pontos de interesse (D7), cada um
no município do polígono do IBGE em que cai."""
import sys
import tempfile
import unittest
from pathlib import Path

from shapely.geometry import Point

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from sabia import osm_reader, records, text  # noqa: E402
from tests.osm_builder import ANAPOLIS, BRASILIA, GOIANIA, MUNICIPALITIES, OsmBuilder, east, north  # noqa: E402

CENTER_GOIANIA = (-16.68, -49.26)
CENTER_ANAPOLIS = (-16.33, -48.95)
CENTER_BRASILIA = (-15.79, -47.88)


def build(osm: OsmBuilder, states=("GO", "DF")):
    with tempfile.TemporaryDirectory() as tmp:
        data = osm_reader.read(osm.write(Path(tmp) / "x.osm.pbf"))
    return records.build(data, MUNICIPALITIES, list(states))


def named(items, name, cls=None):
    return [i for i in items if i.name == name and (cls is None or i.cls == cls)]


class MemoryTest(unittest.TestCase):
    """O Brasil tem ~3 milhões de registros, ~3 milhões de vias e ~11 milhões de degraus do CNEFE na memória ao mesmo
    tempo: cada objeto sem __dict__ e os degraus num array (a geração passava de 15 GB com o swap no Actions)."""

    def test_the_many_objects_have_no_dict(self):
        from array import array
        objects = [records.Item("street", "highway=residential", "Rua 1", "5208707", -16.7, -49.2),
                   osm_reader.Way("Rua 1", "residential", "", array("q", [1, 2]), array("d", [0, 1]),
                                  array("d", [0, 1])),
                   osm_reader.Poi("Posto", "amenity=fuel", -16.7, -49.2),
                   osm_reader.Place("Centro", "suburb", -16.7, -49.2)]
        for obj in objects:
            self.assertFalse(hasattr(obj, "__dict__"), type(obj).__name__)

    def test_ladder_keeps_the_rungs_compact_and_the_same(self):
        rungs = [(k % 2, k // 100, 2 * k + 1, -16.7 - k * 1e-6, -49.2 + k * 1e-6) for k in range(10_000)]
        ladder = records.Ladder(rungs)
        self.assertEqual(rungs, list(ladder))
        self.assertEqual(10_000, len(ladder))
        self.assertTrue(all(type(v) is int for r in ladder for v in r[:3]))
        self.assertLess(sys.getsizeof(ladder), 10_000 * 48)  # ~240 bytes por degrau numa lista de tuplas
        ladder.extend([(1, 7, 99, -16.0, -49.0)])
        self.assertEqual((1, 7, 99, -16.0, -49.0), list(ladder)[-1])

    def test_an_empty_ladder_is_empty_and_each_item_has_its_own(self):
        a = records.Item("street", "highway=residential", "Rua 1", "5208707", -16.7, -49.2)
        b = records.Item("street", "highway=residential", "Rua 2", "5208707", -16.7, -49.2)
        self.assertFalse(a.numbers)
        self.assertEqual([], a.numbers)
        a.numbers.extend([(0, 0, 2, -16.7, -49.2)])
        self.assertEqual([], b.numbers)
        self.assertEqual([(0, 0, 2, -16.7, -49.2)], a.numbers)


class TextTest(unittest.TestCase):
    def test_fold(self):
        self.assertEqual("avenida goias", text.fold("Avenida Goiás"))
        self.assertEqual("r cap caldas 280", text.fold("R. Cap. Caldas, 280"))
        self.assertEqual("sao jose acai", text.fold("  São-José   AÇAÍ "))


class PlacesTest(unittest.TestCase):
    def test_named_places_in_a_municipality(self):
        osm = OsmBuilder()
        osm.node(*CENTER_GOIANIA, place="suburb", name="Setor Oeste")
        osm.node(*north(*CENTER_GOIANIA, 500), place="suburb")                       # sem nome
        osm.node(*north(*CENTER_GOIANIA, 900), place="city_block", name="Quadra 1")  # tipo que não entra
        osm.node(-10.0, -40.0, place="village", name="Fora de tudo")                  # fora dos municípios
        go = build(osm)["GO"]
        found = named(go, "Setor Oeste")
        self.assertEqual(1, len(found))
        self.assertEqual(("place", "place=suburb", GOIANIA.code), (found[0].cls, found[0].kind, found[0].municipality))
        self.assertEqual([], named(go, "Quadra 1"))
        self.assertEqual([], [i for i in go if i.name == "Fora de tudo"])
        self.assertEqual([], [i for i in go if i.cls == "place" and not i.name])

    def test_every_municipality_is_a_place_at_its_seat(self):
        """O município entra com o nome do IBGE; a sede é o ponto do OpenStreetMap de mesmo nome dentro dele (que não
        entra de novo); sem esse ponto, um ponto dentro do polígono."""
        osm = OsmBuilder()
        seat = north(*CENTER_GOIANIA, 1000)
        osm.node(*seat, place="city", name="Goiania")  # grafia diferente, mesmo nome dobrado
        result = build(osm)
        go = [i for i in result["GO"] if i.kind == "municipality"]
        self.assertEqual({GOIANIA.code, ANAPOLIS.code}, {i.municipality for i in go})
        goiania = next(i for i in go if i.municipality == GOIANIA.code)
        self.assertEqual("Goiânia", goiania.name)
        self.assertAlmostEqual(seat[0], goiania.lat, places=5)
        self.assertAlmostEqual(seat[1], goiania.lng, places=5)
        self.assertEqual([], named(result["GO"], "Goiania"))  # o ponto do OSM não vira um segundo registro
        anapolis = next(i for i in go if i.municipality == ANAPOLIS.code)
        self.assertTrue(ANAPOLIS.geometry.contains(Point(anapolis.lng, anapolis.lat)))

    def test_only_the_requested_states(self):
        osm = OsmBuilder()
        osm.node(*CENTER_BRASILIA, place="suburb", name="Asa Sul")
        osm.node(*CENTER_GOIANIA, place="suburb", name="Setor Oeste")
        result = build(osm, states=("DF",))
        self.assertEqual(["DF"], list(result))
        self.assertEqual(1, len(named(result["DF"], "Asa Sul")))
        self.assertEqual(BRASILIA.code, named(result["DF"], "Asa Sul")[0].municipality)


class StreetsTest(unittest.TestCase):
    """D5: mesmo município, mesmo nome, trechos que se tocam ou com as pontas a menos de 60 m."""

    def streets(self, osm, name, state="GO"):
        return named(build(osm)[state], name, "street")

    def test_segments_that_share_a_node_are_one_street(self):
        osm = OsmBuilder()
        a = osm.street(CENTER_GOIANIA, 300, "Rua 10")
        last = osm.ways[a - 1][1][-1]
        osm.way([last, east(*CENTER_GOIANIA, 600)], highway="residential", name="Rua 10")
        self.assertEqual(1, len(self.streets(osm, "Rua 10")))

    def test_touching_in_the_middle_is_one_street(self):
        """Um trecho que sai do meio de outro (nó em comum longe das pontas) é a mesma rua."""
        osm = OsmBuilder()
        a = osm.street(CENTER_GOIANIA, 600, "Rua 10", step=100)
        middle = osm.ways[a - 1][1][3]
        lat, lng, _ = osm.nodes[middle]
        osm.way([middle, north(lat, lng, 400)], highway="residential", name="Rua 10")
        self.assertEqual(1, len(self.streets(osm, "Rua 10")))

    def test_gap_under_60m_joins(self):
        osm = OsmBuilder()
        osm.street(CENTER_GOIANIA, 300, "Avenida Goiás", highway="primary")
        osm.street(east(*CENTER_GOIANIA, 340), 300, "Avenida Goiás", highway="primary")  # 40 m de folga
        found = self.streets(osm, "Avenida Goiás")
        self.assertEqual(1, len(found))
        self.assertEqual("highway=primary", found[0].kind)

    def test_gap_over_60m_separates(self):
        osm = OsmBuilder()
        osm.street(CENTER_GOIANIA, 300, "Rua 10")
        osm.street(east(*CENTER_GOIANIA, 400), 300, "Rua 10")  # 100 m de folga
        self.assertEqual(2, len(self.streets(osm, "Rua 10")))

    def test_chain_of_close_segments_is_one_street(self):
        osm = OsmBuilder()
        for k in range(5):
            osm.street(east(*CENTER_GOIANIA, k * 330), 300, "Avenida T-63", highway="secondary")
        self.assertEqual(1, len(self.streets(osm, "Avenida T-63")))

    def test_same_name_other_municipality_is_another_street(self):
        osm = OsmBuilder()
        osm.street(CENTER_GOIANIA, 300, "Avenida Brasil")
        osm.street(CENTER_ANAPOLIS, 300, "Avenida Brasil")
        found = self.streets(osm, "Avenida Brasil")
        self.assertEqual({GOIANIA.code, ANAPOLIS.code}, {s.municipality for s in found})

    def test_other_name_is_another_street(self):
        osm = OsmBuilder()
        a = osm.street(CENTER_GOIANIA, 300, "Rua 10")
        last = osm.ways[a - 1][1][-1]
        osm.way([last, east(*CENTER_GOIANIA, 600)], highway="residential", name="Rua 11")
        self.assertEqual(1, len(self.streets(osm, "Rua 10")))
        self.assertEqual(1, len(self.streets(osm, "Rua 11")))

    def test_position_is_on_the_central_segment(self):
        osm = OsmBuilder()
        for k in range(3):
            osm.street(east(*CENTER_GOIANIA, k * 1000), 1000, "Rua Longa")
        (street,) = self.streets(osm, "Rua Longa")
        middle = east(*CENTER_GOIANIA, 1500)
        self.assertAlmostEqual(middle[1], street.lng, delta=0.0005)
        self.assertAlmostEqual(middle[0], street.lat, delta=0.0001)
        self.assertEqual(3, len(street.ways))

    def test_footways_are_not_streets(self):
        osm = OsmBuilder()
        osm.street(CENTER_GOIANIA, 300, "Calçada Qualquer", highway="footway")
        self.assertEqual([], self.streets(osm, "Calçada Qualquer"))

    def test_long_local_street_is_flagged(self):
        """Rua local juntada com mais de 3 km de ponta a ponta: suspeita de junção errada, vai para o relatório."""
        osm = OsmBuilder()
        for k in range(4):
            osm.street(east(*CENTER_GOIANIA, k * 1000), 1000, "Rua Comprida")
        for k in range(4):
            osm.street(east(*north(*CENTER_GOIANIA, 3000), k * 1000), 1000, "Avenida Comprida", highway="primary")
        (local,) = self.streets(osm, "Rua Comprida")
        (avenue,) = self.streets(osm, "Avenida Comprida")
        self.assertTrue(local.suspect_long)
        self.assertGreater(local.extent_m, 3000)
        self.assertFalse(avenue.suspect_long)


class RoadsTest(unittest.TestCase):
    def test_one_record_per_ref_and_municipality(self):
        osm = OsmBuilder()
        osm.street(CENTER_GOIANIA, 2000, "Avenida Qualquer", highway="primary", ref="BR-153;GO-060")
        osm.street(north(*CENTER_GOIANIA, 3000), 2000, "", highway="trunk", ref="BR 153")
        osm.street(CENTER_ANAPOLIS, 2000, "", highway="trunk", ref="BR-153")
        go = build(osm)["GO"]
        roads = [(i.name, i.municipality) for i in go if i.cls == "road"]
        self.assertEqual(sorted([("BR-153", GOIANIA.code), ("GO-060", GOIANIA.code), ("BR-153", ANAPOLIS.code)]),
                         sorted(roads))
        self.assertEqual("road", next(i for i in go if i.cls == "road").kind)

    def test_ref_that_is_not_a_road_code_is_ignored(self):
        """No OpenStreetMap há `ref` com CEP ("74423020", "76327-390"): rodovia é sigla e número."""
        osm = OsmBuilder()
        osm.street(CENTER_GOIANIA, 2000, "Avenida Qualquer", highway="primary", ref="74423020;76327-390;GO-020")
        self.assertEqual(["GO-020"], [i.name for i in build(osm)["GO"] if i.cls == "road"])

    def test_minor_ways_with_ref_are_not_roads(self):
        osm = OsmBuilder()
        osm.street(CENTER_GOIANIA, 500, "Rua X", highway="residential", ref="GO-999")
        self.assertEqual([], [i for i in build(osm)["GO"] if i.cls == "road"])


class ReaderBoxTest(unittest.TestCase):
    def test_way_crossing_the_box_is_kept_whatever_its_middle_node(self):
        """Com o retângulo dos estados pedidos, uma via que entra nele fica, mesmo com o nó do meio fora (o
        município é decidido depois pelo meio do comprimento)."""
        osm = OsmBuilder()
        inside = (-16.0, -48.0)
        outside = [(-16.0, -47.0 + k * 0.001) for k in range(10)]
        osm.way([inside] + outside, highway="primary", name="Via Que Cruza")
        osm.way(outside, highway="primary", name="Via De Fora")
        with tempfile.TemporaryDirectory() as tmp:
            data = osm_reader.read(osm.write(Path(tmp) / "x.osm.pbf"), bbox=(-16.5, -48.5, -15.5, -47.5))
        self.assertEqual(["Via Que Cruza"], [w.name for w in data.ways])


class PoisTest(unittest.TestCase):
    def pois(self, osm):
        return [i for i in build(osm)["GO"] if i.cls == "poi"]

    def test_named_poi_node(self):
        osm = OsmBuilder()
        osm.node(*CENTER_GOIANIA, amenity="hospital", name="Hospital Araújo Jorge")
        (poi,) = self.pois(osm)
        self.assertEqual(("Hospital Araújo Jorge", "amenity=hospital"), (poi.name, poi.kind))

    def test_unnamed_travel_poi_enters_with_brand_or_no_name(self):
        osm = OsmBuilder()
        osm.node(*CENTER_GOIANIA, amenity="fuel", brand="Ipiranga")
        osm.node(*north(*CENTER_GOIANIA, 300), amenity="fuel")
        osm.node(*north(*CENTER_GOIANIA, 600), shop="tyres")
        osm.node(*north(*CENTER_GOIANIA, 900), amenity="restaurant")  # sem nome e não é de viagem: fora
        found = sorted((p.kind, p.name) for p in self.pois(osm))
        self.assertEqual([("amenity=fuel", ""), ("amenity=fuel", "Ipiranga"), ("shop=tyres", "")], found)

    def test_d7_extra_kinds(self):
        osm = OsmBuilder()
        osm.node(*CENTER_GOIANIA, natural="waterfall", name="Cachoeira dos Dragões")
        osm.node(*north(*CENTER_GOIANIA, 300), natural="peak", name="Pico dos Pireneus")
        osm.node(*north(*CENTER_GOIANIA, 600), tourism="viewpoint", name="Mirante")
        osm.way([north(*CENTER_GOIANIA, 900), north(*CENTER_GOIANIA, 1200), east(*north(*CENTER_GOIANIA, 1200), 300),
                 north(*CENTER_GOIANIA, 900)], aeroway="aerodrome", name="Aeroporto de Goiânia")
        osm.street(north(*CENTER_GOIANIA, 2000), 800, "Autódromo de Goiânia", highway="raceway")
        found = {p.name: p.kind for p in self.pois(osm)}
        self.assertEqual({"Cachoeira dos Dragões": "natural=waterfall", "Pico dos Pireneus": "natural=peak",
                          "Mirante": "tourism=viewpoint", "Aeroporto de Goiânia": "aeroway=aerodrome",
                          "Autódromo de Goiânia": "highway=raceway"}, found)
        self.assertEqual([], [i for i in build(osm)["GO"] if i.cls == "street"])  # o autódromo não é rua

    def test_poi_drawn_as_relation_enters_at_its_center(self):
        osm = OsmBuilder()
        lat, lng = CENTER_GOIANIA
        ring = [(lat, lng), (lat, lng + 0.01), (lat + 0.01, lng + 0.01), (lat + 0.01, lng)]
        osm.multipolygon(ring, leisure="park", name="Parque Vaca Brava")
        (park,) = self.pois(osm)
        self.assertEqual("leisure=park", park.kind)
        self.assertAlmostEqual(lat + 0.005, park.lat, places=4)
        self.assertAlmostEqual(lng + 0.005, park.lng, places=4)


if __name__ == "__main__":
    unittest.main()
