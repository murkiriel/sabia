"""O mesmo lugar duas vezes (sabia/dedup.py): o ponto e a área do OpenStreetMap, ou o mapa e a Overture com o nome
escrito de outro jeito ("Rodoviária do Plano Piloto" e "Rodoviria do Plano Piloto", a 30 m) viram um registro só."""
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from sabia import dedup  # noqa: E402
from sabia.records import Item  # noqa: E402
from tests.osm_builder import east  # noqa: E402

BSB = "5300108"
LAT, LNG = -15.7939, -47.8828


def poi(name, kind="amenity=bus_station", meters=0.0, **kw):
    lat, lng = east(LAT, LNG, meters)
    return Item("poi", kind, name, BSB, lat, lng, **kw)


class SameNameTest(unittest.TestCase):
    def test_names(self):
        same = dedup.same_name
        self.assertTrue(same("Rodoviária do Plano Piloto", "Rodoviaria do Plano Piloto"))
        self.assertTrue(same("Rodoviária do Plano Piloto", "Rodoviria do Plano Piloto"))     # uma letra a menos
        self.assertTrue(same("Posto Ipiranga Ltda", "POSTO IPIRANGA"))                       # "Ltda" não conta
        self.assertFalse(same("Bloco A", "Bloco B"))                                         # letra solta: igual
        self.assertFalse(same("Quadra 10", "Quadra 11"))                                     # número: igual
        self.assertFalse(same("Edifício 1234", "Edifício 1235"))                             # mesmo comprido
        self.assertFalse(same("Posto Ipiranga", "Posto Ipiranga Norte"))                     # palavra a mais
        self.assertFalse(same("Farmácia Popular", "Farmácia Pague Menos"))
        # direção e lado: iguais ("oeste" e "leste" diferem numa letra; são as paradas dos dois lados da pista)
        self.assertFalse(same("EPDB, km 24 oeste", "EPDB, km 24 leste"))
        self.assertFalse(same("Terminal Norte", "Terminal Sul"))
        self.assertFalse(same("Portaria Entrada", "Portaria Saída"))


class CollapseTest(unittest.TestCase):
    def test_the_map_one_stays_and_the_other_name_becomes_an_alias(self):
        items = {"DF": [poi("Rodoviria do Plano Piloto", meters=30, origin="overture"),
                        poi("Rodoviária do Plano Piloto")]}
        self.assertEqual(1, dedup.collapse(items))
        (kept,) = items["DF"]
        self.assertEqual(("Rodoviária do Plano Piloto", ""), (kept.name, kept.origin))
        self.assertEqual(["Rodoviria do Plano Piloto"], kept.aliases)

    def test_point_and_area_of_the_map(self):
        items = {"DF": [poi("Rodoviária do Plano Piloto"), poi("Rodoviaria do Plano Piloto", meters=60)]}
        self.assertEqual(1, dedup.collapse(items))
        self.assertEqual(1, len(items["DF"]))

    def test_the_name_with_accents_stays_when_both_are_from_the_map(self):
        items = {"DF": [poi("Rodoviaria do Plano Piloto"), poi("Rodoviária do Plano Piloto", meters=30)]}
        dedup.collapse(items)
        self.assertEqual("Rodoviária do Plano Piloto", items["DF"][0].name)

    def test_far_apart_both_stay(self):
        for meters in (200, 400):
            items = {"DF": [poi("Rodoviária do Plano Piloto"), poi("Rodoviária do Plano Piloto", meters=meters)]}
            self.assertEqual(0, dedup.collapse(items), meters)
            self.assertEqual(2, len(items["DF"]))

    def test_another_kind_stays(self):
        items = {"DF": [poi("Ipiranga", "amenity=fuel"), poi("Ipiranga", "amenity=bank", meters=10)]}
        self.assertEqual(0, dedup.collapse(items))

    def test_streets_and_roads_never(self):
        items = {"DF": [Item("street", "highway=residential", "Rua 1", BSB, LAT, LNG),
                        Item("street", "highway=residential", "Rua 1", BSB, LAT, LNG + 0.0001)]}
        self.assertEqual(0, dedup.collapse(items))

    def test_anp_only_station_gives_way_to_the_map(self):
        """O posto que só a ANP tinha (posição não conferida) sai para o do mapa, que fica com a origem dele."""
        items = {"DF": [poi("Posto Shell", "amenity=fuel", source="anp"),
                        poi("Posto Shell", "amenity=fuel", meters=40)]}
        self.assertEqual(1, dedup.collapse(items))
        self.assertEqual("", items["DF"][0].source)

    def test_three_of_the_same_become_one_with_every_other_name(self):
        items = {"DF": [poi("Rodoviária do Plano Piloto"),
                        poi("Rodoviaria do Plano Piloto", meters=20, origin="overture"),
                        poi("Rodoviria do Plano Piloto", meters=40, origin="overture")]}
        self.assertEqual(2, dedup.collapse(items))
        # "Rodoviaria" sem acento é o mesmo nome dobrado: não vira alternativo
        self.assertEqual(["Rodoviria do Plano Piloto"], items["DF"][0].aliases)

    def test_the_order_of_the_generation_is_kept(self):
        a, b = poi("Aeroporto", "aeroway=aerodrome", meters=5000), poi("Rodoviária")
        items = {"DF": [a, poi("Rodoviaria", meters=10, origin="overture"), b]}
        dedup.collapse(items)
        self.assertEqual([a, b], items["DF"])


if __name__ == "__main__":
    unittest.main()
