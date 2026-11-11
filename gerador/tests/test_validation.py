"""As travas da geração (G7): (a) buscas de verdade com resultado esperado, (b) todos os municípios do IBGE
presentes, (c) queda de registros em relação à geração publicada, (d) ruas locais longas no relatório, (e) o banco
abre no SQLite mais antigo suportado (3.22)."""
import json
import sqlite3
import sys
import tempfile
import unittest
from contextlib import closing
from pathlib import Path

from shapely.geometry import box

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from sabia import config, sqlite_old, validation  # noqa: E402
from sabia.sources import Municipality  # noqa: E402
from tests.test_search import LAT, LNG, MUNICIPALITIES, Pack  # noqa: E402


class SearchGateTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls._tmp = tempfile.TemporaryDirectory()
        cls.pack = Pack(Path(cls._tmp.name))

    @classmethod
    def tearDownClass(cls):
        cls._tmp.cleanup()

    def run_cases(self, *cases):
        with closing(sqlite3.connect(self.pack.path)) as db:
            return validation.search_gate(db, list(cases))

    def test_expected_results_pass(self):
        problems, rows = self.run_cases(
            {"uf": "GO", "query": "rua 10 setor oeste", "name": "Rua 10", "district": "Setor Oeste",
             "municipality": "Goiânia", "top": 1},
            {"uf": "GO", "query": "posto cerrado", "name": "posto cerrado", "lat": LAT - 0.2, "lng": LNG,
             "radius_m": 200, "top": 1})
        self.assertEqual([], problems)
        self.assertEqual([1, 1], [r["rank"] for r in rows])

    def test_wrong_name_fails_with_the_query_in_the_message(self):
        problems, rows = self.run_cases({"uf": "GO", "query": "rua 10 setor oeste", "name": "Rua 11", "top": 5})
        self.assertEqual(1, len(problems))
        self.assertIn("rua 10 setor oeste", problems[0])
        self.assertIsNone(rows[0]["rank"])

    def test_rank_must_be_within_top(self):
        """A posição relatada é a da busca; passa só até `top`."""
        # a outra Rua 10 de Goiânia, fora do Setor Oeste (a do Setor Oeste, secundária no exemplo, vem antes)
        case = {"uf": "GO", "query": "rua 10", "name": "Rua 10", "lat": LAT + 0.05, "lng": LNG + 0.002,
                "radius_m": 600}
        with closing(sqlite3.connect(self.pack.path)) as db:
            found = validation.search.search(db, "rua 10", limit=5)
        position = next(n for n, r in enumerate(found, 1) if validation._matches(case, r))
        self.assertGreater(position, 1)
        self.assertEqual(1, len(self.run_cases(dict(case, top=position - 1))[0]))
        problems, rows = self.run_cases(dict(case, top=position))
        self.assertEqual([], problems)
        self.assertEqual(position, rows[0]["rank"])

    def test_point_too_far_fails(self):
        problems, _ = self.run_cases({"uf": "GO", "query": "posto cerrado", "name": "Posto Cerrado",
                                      "lat": LAT, "lng": LNG, "radius_m": 200, "top": 1})
        self.assertEqual(1, len(problems))

    def test_a_case_with_the_position_the_kind_and_a_distance(self):
        """`near` é a posição de quem busca; `kind` e `within_m` (distância até `near`) conferem o resultado."""
        case = {"uf": "GO", "query": "posto", "near": [LAT - 0.19, LNG], "kind": "amenity=fuel", "within_m": 1500}
        self.assertEqual([], self.run_cases(case)[0])
        self.assertEqual(1, len(self.run_cases(dict(case, within_m=10))[0]))
        self.assertEqual(1, len(self.run_cases(dict(case, kind="amenity=hospital"))[0]))

    def test_a_case_with_the_house_number(self):
        case = {"uf": "GO", "query": "rua 10 152 setor oeste", "name": "Rua 10", "house_number": 152}
        self.assertEqual([], self.run_cases(case)[0])
        self.assertEqual(1, len(self.run_cases(dict(case, house_number=153))[0]))

    def test_cases_file_is_well_formed(self):
        """O arquivo das buscas do projeto: cada caso com UF, busca, top e ao menos um critério."""
        cases = validation.load_cases(config.SEARCH_CASES, list(config.STATES))
        self.assertGreaterEqual(len([c for c in cases if c["uf"] == "GO"]), 45)
        self.assertGreaterEqual(len([c for c in cases if c["uf"] == "DF"]), 15)
        for uf in config.STATES:  # item 11: casos em todas as UFs; com a receita da conformidade, 6 ou mais
            self.assertGreaterEqual(len([c for c in cases if c["uf"] == uf]), 6, uf)
        self.assertGreaterEqual(len(cases), 267)  # os 168 de antes e os 99 da receita (docs/CONFORMIDADE.md)
        self.assertEqual(len(cases), len({(c["uf"], c["query"], tuple(c.get("near", ()))) for c in cases}))
        self.assertGreaterEqual(len([c for c in cases if "near" in c]), 10)
        for c in cases:
            self.assertIn(c["uf"], config.STATES)
            self.assertIn(c["top"], (1, 3, 5))
            self.assertTrue({"name", "name_contains", "lat", "kind"} & set(c), c)
            if "lat" in c:
                self.assertIn("radius_m", c)
            if "within_m" in c:
                self.assertIn("near", c)
        civica = next(c for c in cases if c["query"] == "praca civica goiania")
        self.assertLessEqual(civica["radius_m"], 200)
        self.assertEqual([], [c for c in validation.load_cases(config.SEARCH_CASES, ["DF"]) if c["uf"] != "DF"])


class CoverageGateTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls._tmp = tempfile.TemporaryDirectory()
        cls.pack = Pack(Path(cls._tmp.name))

    @classmethod
    def tearDownClass(cls):
        cls._tmp.cleanup()

    def test_all_municipalities_present(self):
        self.assertEqual([], validation.coverage_gate(self.pack.path, MUNICIPALITIES, "GO"))

    def test_missing_municipality_fails(self):
        extra = Municipality("5299999", "Município Novo", "GO", box(-40.0, -10.0, -39.9, -9.9))
        problems = validation.coverage_gate(self.pack.path, MUNICIPALITIES + [extra], "GO")
        self.assertEqual(1, len(problems))
        self.assertIn("5299999", problems[0])

    def test_base_without_point_only_for_states_not_generated(self):
        counts = {"municipality": 10, "without_point": ["5101837"]}
        self.assertEqual([], validation.base_gate(counts, ["GO", "DF"]))
        self.assertEqual(1, len(validation.base_gate(counts, ["MT"])))


class DropsTest(unittest.TestCase):
    def counts(self, items=10000, street=6000, poi=3000, place=900, road=100):
        return {"items": items, "street": street, "poi": poi, "place": place, "road": road}

    def test_small_variation_passes(self):
        previous = {"GO": self.counts()}
        current = {"GO": self.counts(items=9700, street=5800)}
        self.assertEqual([], validation.drops(previous, current))

    def test_total_drop_over_5_percent_fails(self):
        problems = validation.drops({"GO": self.counts()}, {"GO": self.counts(items=9000)})
        self.assertEqual(1, len(problems))
        self.assertIn("GO", problems[0])

    def test_big_class_drop_fails_small_class_does_not(self):
        problems = validation.drops({"GO": self.counts()}, {"GO": self.counts(poi=2000)})
        self.assertEqual(1, len(problems))
        self.assertIn("poi", problems[0])
        self.assertEqual([], validation.drops({"GO": self.counts()}, {"GO": self.counts(road=80)}))

    def test_state_that_disappeared_fails(self):
        problems = validation.drops({"GO": self.counts(), "DF": self.counts()}, {"GO": self.counts()})
        self.assertEqual(["DF: sumiu da geração"], problems)


class OldSqliteTest(unittest.TestCase):
    def test_schema_with_newer_features_is_refused(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "novo.sqlite"
            with closing(sqlite3.connect(path)) as db:
                db.execute("CREATE TABLE a(x INTEGER) STRICT")
                db.execute("CREATE VIRTUAL TABLE b USING fts5(x)")
                db.execute("CREATE TABLE c(x INTEGER PRIMARY KEY) WITHOUT ROWID")
                db.commit()
            problems = validation.schema_problems(path)
        self.assertEqual(3, len(problems), problems)

    def test_package_schema_is_accepted(self):
        with tempfile.TemporaryDirectory() as tmp:
            pack = Pack(Path(tmp))
            self.assertEqual([], validation.schema_problems(pack.path))

    def test_package_reads_the_same_in_sqlite_3_22(self):
        lib = sqlite_old.library_path()
        if not lib.exists():
            self.skipTest(f"SQLite 3.22 não instalado ({lib}); rode python scripts/install_sqlite.py")
        with tempfile.TemporaryDirectory() as tmp:
            pack = Pack(Path(tmp))
            cases = [{"uf": "GO", "query": "rua 10 setor oeste", "name": "Rua 10", "top": 1},
                     {"uf": "GO", "query": "r dr olinto", "name": "Rua Doutor Olinto Manso", "top": 1},
                     {"uf": "GO", "query": "posto ipiranga anapolis", "name": "Ipiranga", "top": 1},
                     # com a posição: as duas pontas buscam dela (sem ela, "posto" dá outra lista)
                     {"uf": "GO", "query": "posto", "near": [LAT - 0.19, LNG], "kind": "amenity=fuel", "top": 1}]
            problems, version = validation.old_sqlite_gate(pack.path, cases, lib)
        self.assertEqual("3.22.0", version)
        self.assertEqual([], problems)


class ReportTest(unittest.TestCase):
    def test_report_lists_long_streets_and_searches(self):
        with tempfile.TemporaryDirectory() as tmp:
            dest = Path(tmp) / "relatorio.json"
            suspects = [{"uf": "GO", "name": "Rua Comprida", "extent_m": 4100.0}]
            searches = [{"uf": "GO", "query": "x", "rank": 1, "top": 1},
                        {"uf": "GO", "query": "y", "rank": 2, "top": 3},
                        {"uf": "DF", "query": "z", "rank": None, "top": 1}]
            validation.write_report(dest, suspects, searches, ["um problema"], "3.22.0")
            data = json.loads(dest.read_text(encoding="utf-8"))
        # item 11: a posição média do certo (MRR: 1/posição, 0 sem achar) e o placar de cada UF
        self.assertAlmostEqual((1 + 0.5 + 0) / 3, data["searches"]["mrr"], places=3)
        self.assertEqual({"DF": {"passed": 0, "total": 1}, "GO": {"passed": 2, "total": 2}},
                         data["searches"]["by_state"])
        self.assertEqual({"GO": 1}, data["long_local_streets"]["count"])
        self.assertEqual("Rua Comprida", data["long_local_streets"]["streets"][0]["name"])
        self.assertEqual(2, data["searches"]["passed"])
        self.assertEqual(["um problema"], data["problems"])
        self.assertEqual("3.22.0", data["oldest_sqlite"])
        self.assertEqual([], data["old_copies"])

    def test_report_lists_old_copies(self):
        with tempfile.TemporaryDirectory() as tmp:
            dest = Path(tmp) / "relatorio.json"
            validation.write_report(dest, [], [], [], "3.22.0", old_copies=["a cópia do IBGE é velha"])
            data = json.loads(dest.read_text(encoding="utf-8"))
        self.assertEqual(["a cópia do IBGE é velha"], data["old_copies"])
        self.assertEqual([], data["problems"])  # não trava


if __name__ == "__main__":
    unittest.main()
