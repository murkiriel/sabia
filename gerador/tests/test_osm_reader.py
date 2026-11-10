"""A leitura do extrato em duas passadas (osm_reader.write_reduced): a cópia reduzida guarda só o que a leitura usa
(os objetos com as chaves de KEYS, as relações de área e o que eles referenciam), para o pyosmium não guardar a
coordenada de todos os nós do Brasil na memória (~7 GB no Actions, que tem 7,8)."""
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

import osmium

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from sabia import osm_reader  # noqa: E402
from tests.osm_builder import OsmBuilder, east  # noqa: E402

START = (-16.70, -49.25)


def sample() -> OsmBuilder:
    osm = OsmBuilder()
    osm.street(START, 300, "Rua 10")                                         # nós sem tag, referenciados
    osm.node(-16.701, -49.251, amenity="fuel", name="Posto Bandeira")        # ponto de interesse
    osm.node(-16.702, -49.252, place="suburb", name="Setor Oeste")           # lugar
    ring = [START, east(*START, 400), (START[0] - 0.004, START[1] + 0.004), (START[0] - 0.004, START[1])]
    osm.multipolygon(ring, name="Setor Sul", place="suburb")                # a via do anel não tem tag
    osm.way([(-16.71, -49.26), (-16.711, -49.26), (-16.711, -49.261), (-16.71, -49.26)], building="yes")
    for k in range(40):                                                      # nós soltos (árvores, postes)
        osm.node(-16.72 + k * 1e-4, -49.27, natural="tree")
    street = osm.ways[0][0]
    osm.relations.append((99, [("w", street, "")], {"type": "route", "route": "bus", "name": "Linha 1"}))
    return osm


def contents(path: Path):
    nodes, ways, relations = set(), set(), set()
    for obj in osmium.FileProcessor(str(path)):
        {"n": nodes, "w": ways, "r": relations}[obj.type_str()].add(obj.id)
    return nodes, ways, relations


class ReduceTest(unittest.TestCase):
    def test_the_reduced_file_keeps_only_what_the_reading_uses(self):
        osm = sample()
        with tempfile.TemporaryDirectory() as tmp:
            src = osm.write(Path(tmp) / "x.osm.pbf")
            dest = Path(tmp) / "reduzido.osm.pbf"
            osm_reader.write_reduced(src, dest)
            nodes, ways, relations = contents(dest)
            all_nodes, all_ways, _ = contents(src)
        street, ring = osm.ways[0], osm.ways[1]
        self.assertTrue(set(street[1]) <= nodes, "os nós da rua")
        self.assertIn(street[0], ways)
        self.assertIn(ring[0], ways, "a via sem tag do anel da relação de área")
        self.assertTrue(set(ring[1]) <= nodes)
        self.assertEqual({1}, relations, "só a relação de área; a da linha de ônibus fica de fora")
        trees = {nid for nid, (_, _, tags) in osm.nodes.items() if tags.get("natural") == "tree"}
        self.assertFalse(trees & nodes, "nós soltos ficam de fora")
        self.assertNotIn(osm.ways[2][0], ways, "prédio sem nome fica de fora")
        self.assertLess(len(nodes), len(all_nodes) - 40)
        self.assertLess(len(ways), len(all_ways))

    def test_reading_the_reduced_file_gives_the_same_data(self):
        with tempfile.TemporaryDirectory() as tmp:
            src = sample().write(Path(tmp) / "x.osm.pbf")
            whole = osm_reader.read(src, reduce=False)
            with mock.patch.object(osm_reader, "write_reduced", wraps=osm_reader.write_reduced) as spy, \
                    mock.patch.object(osm_reader, "_read", wraps=osm_reader._read) as reading:
                reduced = osm_reader.read(src, workdir=Path(tmp))
            spy.assert_called_once()  # a leitura padrão é a reduzida...
            self.assertEqual(spy.call_args[0][1], reading.call_args[0][0])  # ...e lê a cópia, não o original
            self.assertEqual(["x.osm.pbf"], sorted(p.name for p in Path(tmp).iterdir()), "a cópia reduzida é apagada")
        self.assertEqual(whole.places, reduced.places)
        self.assertEqual(whole.pois, reduced.pois)
        self.assertEqual(whole.ways, reduced.ways)
        self.assertEqual([(a.name, a.kind, a.geometry.wkt) for a in whole.district_areas],
                         [(a.name, a.kind, a.geometry.wkt) for a in reduced.district_areas])
        self.assertEqual(["Rua 10"], [w.name for w in reduced.ways])
        self.assertEqual(["Setor Sul"], [a.name for a in reduced.district_areas])


if __name__ == "__main__":
    unittest.main()
