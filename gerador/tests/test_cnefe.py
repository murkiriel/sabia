"""O número das casas pelo CNEFE do IBGE (SE1, docs/ENDERECOS.md): a leitura do arquivo da UF, a escada de números por
rua e lado (um degrau a cada STEP números, quebrada onde dois números seguidos ficam a mais de GAP_M) e o casamento com
as ruas do pacote. A rua do CNEFE que o pacote não tem fica de fora (SE1c: como registro novo, sem traçado, dobrava o
pacote de GO e passava na frente da rodovia na busca "br-153 anapolis")."""
import csv
import io
import sys
import tempfile
import unittest
import zipfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from sabia import cnefe  # noqa: E402
from sabia import records  # noqa: E402
from sabia.records import Item  # noqa: E402
from tests.osm_builder import east  # noqa: E402

GYN = "5208707"
HEAD = ["COD_UNICO_ENDERECO", "COD_UF", "COD_MUNICIPIO", "NOM_TIPO_SEGLOGR", "NOM_TITULO_SEGLOGR", "NOM_SEGLOGR",
        "NUM_ENDERECO", "DSC_MODIFICADOR", "LATITUDE", "LONGITUDE", "NV_GEO_COORD"]


def _zip(path, rows):
    out = io.StringIO()
    w = csv.writer(out, delimiter=";", lineterminator="\n")
    w.writerow(HEAD)
    w.writerows(rows)
    with zipfile.ZipFile(path, "w") as z:
        z.writestr("52_GO.csv", out.getvalue().encode("utf-8"))
    return path


def _row(mun, kind, title, name, number, lat, lng, level="1"):
    return ["1", mun[:2], mun, kind, title, name, str(number), "", f"{lat:.6f}", f"{lng:.6f}", level]


class Ladder(unittest.TestCase):
    def test_a_rung_every_step_numbers_on_each_side_and_the_last_one(self):
        # números ímpares de 1 a 99 e pares de 2 a 40 ao longo de 1 km para leste
        addrs = [(n, *east(-16.70, -49.25, n * 10.0)) for n in list(range(1, 100, 2)) + list(range(2, 41, 2))]
        rungs = cnefe.ladder(addrs)
        self.assertEqual(20, cnefe.STEP)
        self.assertEqual([1, 21, 41, 61, 81, 99], [r[2] for r in rungs if r[0] == 1])
        self.assertEqual([2, 22, 40], [r[2] for r in rungs if r[0] == 0])
        self.assertEqual({0}, {r[1] for r in rungs}, "one piece per side")

    def test_the_same_name_far_away_is_another_piece(self):
        here = [(n, *east(-16.70, -49.25, n * 10.0)) for n in (1, 3, 5)]
        there = [(n, *east(-16.70, -49.20, n * 10.0)) for n in (7, 9)]
        rungs = cnefe.ladder(here + there)
        self.assertEqual(300.0, cnefe.GAP_M)
        self.assertEqual([(1, 0, 1), (1, 0, 5), (1, 1, 7), (1, 1, 9)], [r[:3] for r in rungs])


class Read(unittest.TestCase):
    def test_the_numbered_addresses_with_their_own_point_by_municipality_and_street(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = _zip(Path(tmp) / "52_GO.zip", [
                _row(GYN, "RUA", "", "9", 1, -16.70, -49.25),
                _row(GYN, "RUA", "", "9", 3, -16.7001, -49.25),
                _row(GYN, "AVENIDA", "DEPUTADO", "JAMEL CECILIO", 120, -16.71, -49.24),
                _row(GYN, "RUA", "", "9", 0, -16.70, -49.25),               # sem número
                _row(GYN, "RUA", "", "9", 5, -16.70, -49.25, level="4"),     # ponto estimado pelo setor
                _row("5201108", "RUA", "", "9", 7, -16.33, -48.95),
            ])
            got = cnefe.read(path)
        self.assertEqual({(GYN, "rua 9"), (GYN, "avenida deputado jamel cecilio"), ("5201108", "rua 9")}, set(got))
        name, rungs = got[(GYN, "rua 9")]
        self.assertEqual("Rua 9", name)
        self.assertEqual([1, 3], [r[2] for r in rungs])
        self.assertEqual("Avenida Deputado Jamel Cecilio", got[(GYN, "avenida deputado jamel cecilio")][0])


    def test_a_municipality_spread_over_the_file_keeps_its_whole_ladder(self):
        # o arquivo do IBGE não vem agrupado por município: as linhas de um se intercalam com as de outro
        rows = []
        for n in range(1, 120, 2):
            rows.append(_row(GYN, "RUA", "", "9", n, *east(-16.70, -49.25, n * 5.0)))
            rows.append(_row("5201108", "RUA", "", "1", n, *east(-16.33, -48.95, n * 5.0)))
        with tempfile.TemporaryDirectory() as tmp:
            got = cnefe.read(_zip(Path(tmp) / "52_GO.zip", rows))
        self.assertEqual([1, 21, 41, 61, 81, 101, 119], [r[2] for r in got[(GYN, "rua 9")][1]])
        self.assertEqual([1, 21, 41, 61, 81, 101, 119], [r[2] for r in got[("5201108", "rua 1")][1]])
        # compacto desde a leitura (SP: 1,1 milhão de pedaços)
        self.assertIsInstance(got[(GYN, "rua 9")][1], records.Ladder)


class Add(unittest.TestCase):
    def test_each_piece_goes_to_the_nearest_street_of_that_name_and_the_rest_stays_out(self):
        near = Item("street", "highway=residential", "R. 9", GYN, *east(-16.70, -49.25, 20.0))
        other = Item("street", "highway=residential", "Rua 9", GYN, *east(-16.70, -49.25, 1_500.0))  # a 1,5 km
        avenue = Item("street", "highway=primary", "Av. Dep. Jamel Cecílio", GYN, -16.71, -49.24)
        items = {"GO": [near, other, avenue]}
        groups = {
            (GYN, "rua 9"): ("Rua 9", [(1, 0, 1, -16.70, -49.25), (1, 0, 21, *east(-16.70, -49.25, 200.0))]),
            (GYN, "rua 10"): ("Rua 10", [(0, 0, 2, -16.72, -49.26)]),
        }
        matched, unmatched = cnefe.add(items, groups, "GO")
        self.assertEqual((1, 1), (matched, unmatched))
        self.assertEqual([1, 21], [r[2] for r in near.numbers])
        self.assertEqual([], other.numbers)
        self.assertEqual(3, len(items["GO"]), "no new street")

    def test_two_spellings_on_one_street_keep_their_pieces_apart(self):
        # "Rua 9" e "R 9" no CNEFE caem na mesma rua do pacote: cada pedaço com o seu número, sem colidir
        rua = Item("street", "highway=residential", "Rua 9", GYN, -16.70, -49.25)
        items = {"GO": [rua]}
        groups = {(GYN, "rua 9"): ("Rua 9", [(1, 0, 1, -16.70, -49.25), (1, 0, 21, -16.70, -49.2481)]),
                  (GYN, "r 9"): ("R 9", [(1, 0, 5, -16.70, -49.2495)])}
        self.assertEqual((2, 0), cnefe.add(items, groups, "GO"))
        segs = {r[2]: r[1] for r in rua.numbers}
        self.assertEqual([1, 5, 21], sorted(segs))
        self.assertEqual(segs[1], segs[21], "Rua 9's piece stays one")
        self.assertNotEqual(segs[1], segs[5], "R 9's piece is another")

    def test_the_even_and_the_odd_pieces_go_each_to_its_own_street(self):
        here = Item("street", "highway=residential", "Rua 9", GYN, -16.70, -49.25)
        there = Item("street", "highway=residential", "Rua 9", GYN, -16.60, -49.30)
        items = {"GO": [here, there]}
        groups = {(GYN, "rua 9"): ("Rua 9", [(0, 0, 2, -16.70, -49.25), (1, 0, 1, -16.60, -49.30)])}
        self.assertEqual((2, 0), cnefe.add(items, groups, "GO"))
        self.assertEqual(([2], [1]), ([r[2] for r in here.numbers], [r[2] for r in there.numbers]))

    def test_a_street_of_that_name_too_far_from_the_piece_is_not_it(self):
        far = Item("street", "highway=residential", "Rua 9", GYN, -16.60, -49.30)
        items = {"GO": [far]}
        matched, unmatched = cnefe.add(items, {(GYN, "rua 9"): ("Rua 9", [(1, 0, 1, -16.70, -49.25)])}, "GO")
        self.assertEqual((0, 1), (matched, unmatched))
        self.assertEqual([], far.numbers)
        self.assertEqual(2_000.0, cnefe.MATCH_M)


class SourceFile(unittest.TestCase):
    """O arquivo de cada UF em data/raw, a conferência do zip e o crédito do IBGE (SE1c)."""

    def test_the_name_the_check_and_the_credit(self):
        from sabia import config, sources
        self.assertEqual("cnefe_52_GO.zip", sources.cnefe_name("GO"))
        with tempfile.TemporaryDirectory() as tmp:
            good = _zip(Path(tmp) / "a.zip", [_row(GYN, "RUA", "", "9", 1, -16.7, -49.25)])
            bad = Path(tmp) / "b.zip"
            bad.write_bytes(b"<html>erro</html>")
            empty = Path(tmp) / "c.zip"
            with zipfile.ZipFile(empty, "w") as z:
                z.writestr("leia.txt", "x")
            self.assertIsNone(sources.cnefe_problem(good))
            self.assertIn("não é zip", sources.cnefe_problem(bad) or "")
            self.assertEqual("zip sem CSV", sources.cnefe_problem(empty))
        self.assertIn("números das casas: IBGE (CNEFE, Censo 2022)", config.ATTRIBUTION)


if __name__ == "__main__":
    unittest.main()
