"""Pontos de fontes novas juntados aos registros (merge.add): o município pelo polígono, só os estados pedidos, sem
repetir o que já está registrado a até o raio da fonte, e a ordem da geração."""
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from sabia import merge  # noqa: E402
from sabia.municipalities import MunicipalityIndex  # noqa: E402
from sabia.records import Item  # noqa: E402
from tests.osm_builder import ANAPOLIS, GOIANIA, MUNICIPALITIES, east  # noqa: E402

GO = "5208707"


def same_name(item, point):
    return item.name == point.name


def poi(name, lat, lng, kind="amenity=police", municipality=GO):
    return Item("poi", kind, name, municipality, lat, lng)


class AddTest(unittest.TestCase):
    def setUp(self):
        self.index = MunicipalityIndex(MUNICIPALITIES)

    def add(self, items, points, states=("GO",), radius=100.0, same=same_name):
        return merge.add(items, points, self.index, list(states), radius, same)

    def test_the_municipality_comes_from_the_point(self):
        items = {"GO": []}
        added, repeated = self.add(items, [merge.Point("A", "amenity=police", -16.3, -48.9),
                                           merge.Point("B", "amenity=police", -16.7, -49.2)])
        self.assertEqual((2, 0), (added, repeated))
        self.assertEqual({"A": ANAPOLIS.code, "B": GOIANIA.code}, {i.name: i.municipality for i in items["GO"]})
        self.assertTrue(all(i.cls == "poi" and i.kind == "amenity=police" for i in items["GO"]))

    def test_outside_every_municipality_or_in_a_state_not_asked_for_stays_out(self):
        items = {"GO": []}
        added, repeated = self.add(items, [merge.Point("Mar", "amenity=police", -20.0, -40.0),
                                           merge.Point("Brasília", "amenity=police", -15.8, -47.9)])
        self.assertEqual((0, 0), (added, repeated))
        self.assertEqual([], items["GO"])

    def test_inside_the_radius_and_the_same_is_repeated(self):
        lat, lng = east(-16.7, -49.2, 95)
        items = {"GO": [poi("Posto", -16.7, -49.2)]}
        self.assertEqual((0, 1), self.add(items, [merge.Point("Posto", "amenity=police", lat, lng)]))
        self.assertEqual(1, len(items["GO"]))

    def test_beyond_the_radius_comes_in(self):
        lat, lng = east(-16.7, -49.2, 105)
        items = {"GO": [poi("Posto", -16.7, -49.2)]}
        self.assertEqual((1, 0), self.add(items, [merge.Point("Posto", "amenity=police", lat, lng)]))

    def test_the_radius_is_the_one_given(self):
        lat, lng = east(-16.7, -49.2, 400)
        items = {"GO": [poi("Posto", -16.7, -49.2)]}
        self.assertEqual((0, 1), self.add(items, [merge.Point("Posto", "amenity=police", lat, lng)], radius=450))

    def test_close_but_not_the_same_comes_in(self):
        items = {"GO": [poi("Outro", -16.7, -49.2)]}
        self.assertEqual((1, 0), self.add(items, [merge.Point("Posto", "amenity=police", -16.7, -49.2)]))

    def test_two_new_points_that_are_the_same_come_in_once(self):
        items = {"GO": []}
        points = [merge.Point("Posto", "amenity=police", -16.7, -49.2),
                  merge.Point("Posto", "amenity=police", *east(-16.7, -49.2, 10))]
        self.assertEqual((1, 1), self.add(items, points))

    def test_the_records_stay_in_the_generation_order(self):
        items = {"GO": [poi("Zeta", -16.6, -49.1)]}
        self.add(items, [merge.Point("Alfa", "amenity=police", -16.7, -49.2)])
        self.assertEqual(["Alfa", "Zeta"], [i.name for i in items["GO"]])

    def test_the_class_can_be_another(self):
        items = {"GO": []}
        merge.add(items, [merge.Point("Vila", "x=y", -16.7, -49.2)], self.index, ["GO"], 10, same_name, cls="place")
        self.assertEqual(["place"], [i.cls for i in items["GO"]])


class NameTest(unittest.TestCase):
    def test_words_of_a_name(self):
        self.assertEqual({"pol", "rodoviaria", "federal"}, merge.words("Pol. Rodoviária-Federal"))


if __name__ == "__main__":
    unittest.main()
