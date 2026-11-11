"""O conjunto de conformidade da busca (sabia/conformance.py, docs/CONFORMIDADE.md): a receita dos casos, a saída da
referência, a comparação que um porte reproduz, os dois scripts e o exemplo versionado."""
import json
import sqlite3
import subprocess
import sys
import tempfile
import unittest
from contextlib import closing
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from sabia import conformance, search  # noqa: E402
from sabia.text import fold  # noqa: E402
from tests.test_search import Pack  # noqa: E402

GENERATOR_DIR = Path(__file__).resolve().parent.parent
EXAMPLE = GENERATOR_DIR / "conformidade-exemplo.json"

ITEM = {"name": "Rua 10", "cls": "street", "kind": "highway=residential", "municipality": "Goiânia",
        "district": "Setor Oeste", "lat": -16.67, "lng": -49.258, "house_number": None, "label": "Rua 10",
        "hits": 2, "house": False, "elsewhere": False, "kind_match": False, "score": 0.5}


def item(name, score=0.5, **kw):
    return dict(ITEM, name=name, score=score, **kw)


def case(expected, order_exact=3, same_set=None, **kw):
    return {"id": "x", "expected": expected, "limit": 10,
            "compare": {"order_exact": order_exact, "same_set": len(expected) if same_set is None else same_set,
                        "score_tol": conformance.SCORE_TOL, "coord_tol_m": conformance.COORD_TOL_M,
                        "distance_tol_m": conformance.DISTANCE_TOL_M}, **kw}


class CompareSearchTest(unittest.TestCase):
    """A comparação de um porte com a referência (o que docs/CONFORMIDADE.md manda reproduzir)."""

    def setUp(self):
        self.expected = [item(f"Rua {n}", score=1.0 - n / 10) for n in range(1, 6)]
        self.case = case(self.expected)

    def test_identical_passes(self):
        self.assertEqual([], conformance.compare_search(self.case, [dict(i) for i in self.expected]))

    def test_order_counts_only_in_the_first_ones(self):
        swapped = self.expected[:3] + [self.expected[4], self.expected[3]]
        self.assertEqual([], conformance.compare_search(self.case, swapped))
        swapped = [self.expected[1], self.expected[0]] + self.expected[2:]
        problems = conformance.compare_search(self.case, swapped)
        self.assertEqual(2, len(problems))
        self.assertIn("posição 1", problems[0])

    def test_missing_extra_or_different_item(self):
        self.assertIn("4 resultados", conformance.compare_search(self.case, self.expected[:4])[0])
        other = self.expected[:4] + [item("Rua 99")]
        self.assertEqual(["Rua 5 (highway=residential, Goiânia) (posição 5) não está entre os 5 primeiros"],
                         conformance.compare_search(self.case, other))

    def test_the_item_is_name_kind_municipality_and_point_not_the_id(self):
        moved = [dict(i) for i in self.expected]
        moved[0]["lat"] += 1.0 / 111_320  # 1 m: o mesmo registro
        moved[0]["id"] = 12345
        self.assertEqual([], conformance.compare_search(self.case, moved))
        moved[0]["lat"] += 5.0 / 111_320  # 6 m: outro
        self.assertTrue(conformance.compare_search(self.case, moved))
        other_kind = [dict(self.expected[0], kind="highway=primary")] + self.expected[1:]
        self.assertTrue(conformance.compare_search(self.case, other_kind))

    def test_score_and_criteria_within_tolerance(self):
        close = [dict(i, score=i["score"] + 1e-8) for i in self.expected]
        self.assertEqual([], conformance.compare_search(self.case, close))
        far = [dict(self.expected[0], score=0.95)] + self.expected[1:]
        self.assertIn("nota", conformance.compare_search(self.case, far)[0])
        hits = [dict(self.expected[0], hits=1)] + self.expected[1:]
        self.assertIn("hits", conformance.compare_search(self.case, hits)[0])
        house = [dict(self.expected[0], house_number=12)] + self.expected[1:]
        self.assertIn("house_number", conformance.compare_search(self.case, house)[0])

    def test_empty_expected(self):
        self.assertEqual([], conformance.compare_search(case([]), []))
        self.assertEqual(["1 resultados, esperados 0"], conformance.compare_search(case([]), [ITEM]))

    def test_which_street(self):
        street = {k: ITEM[k] for k in ("name", "cls", "kind", "municipality", "district", "lat", "lng")}
        c = {"id": "x", "expected": dict(street, distance_m=8.0), "compare": {"coord_tol_m": 1.5,
                                                                              "distance_tol_m": 0.5}}
        self.assertEqual([], conformance.compare_which_street(c, dict(street, distance_m=8.2)))
        self.assertTrue(conformance.compare_which_street(c, dict(street, distance_m=9.0)))
        self.assertTrue(conformance.compare_which_street(c, None))
        self.assertEqual([], conformance.compare_which_street(dict(c, expected=None), None))

    def test_unit_values(self):
        self.assertTrue(conformance.same_value([1, "a", {"b": 0.1}], [1, "a", {"b": 0.1 + 1e-12}]))
        self.assertFalse(conformance.same_value(True, 1))  # bool não é número
        self.assertFalse(conformance.same_value(3, 3.5))
        self.assertTrue(conformance.same_value(1000.0, 1000.0000001, 1e-9))
        self.assertFalse(conformance.same_value([1, 2], [1, 2, 3]))
        unit = {"fn": "edit_distance", "args": {"a": "ca", "b": "abc"}, "expected": 3}
        self.assertEqual([], conformance.compare_unit(unit, 3))
        self.assertIn("esperado 3, veio 2", conformance.compare_unit(unit, 2)[0])


class ToleranceTest(unittest.TestCase):
    """A tolerância de cada caso sai da própria saída da referência: duas notas quase iguais podem trocar."""

    def result(self, score, hits=1):
        return search.Result(0, "street", "k", "n", "m", None, 0.0, 0.0,
                             criteria={"hits": hits, "house": False, "elsewhere": False, "kind_match": False,
                                       "score": score})

    def test_clear_order(self):
        found = [self.result(1.0 - n / 10) for n in range(8)]
        self.assertEqual((3, 8), tuple(conformance.tolerance(found, 10)[k] for k in ("order_exact", "same_set")))

    def test_almost_equal_scores(self):
        found = [self.result(0.9), self.result(0.5), self.result(0.5 - 1e-8), self.result(0.4)]
        self.assertEqual(1, conformance.tolerance(found, 10)["order_exact"])
        # na fronteira do limite: o 2º e o 3º podem trocar, o conjunto dos 2 primeiros não é seguro
        self.assertEqual(1, conformance.tolerance(found, 2)["same_set"])
        # notas iguais não trocam (o desempate é o tamanho do nome e o id); critérios diferentes também não
        same = [self.result(0.5), self.result(0.5), self.result(0.5 - 1e-8, hits=0)]
        self.assertEqual((3, 3), tuple(conformance.tolerance(same, 10)[k] for k in ("order_exact", "same_set")))


class RecipeHelpersTest(unittest.TestCase):
    def test_typo(self):
        self.assertEqual("goainia", conformance.typo("goiania"))
        self.assertEqual("rio brnaco", conformance.typo("rio branco"))
        self.assertEqual("sao lius", conformance.typo("sao luis"))
        self.assertEqual("rua 10", conformance.typo("rua 10"))  # nenhuma palavra que aceite erro
        self.assertEqual("blela", conformance.typo("bella"))
        self.assertEqual("aba", conformance.typo("abba"))  # letras do meio iguais: uma sai

    def test_styles_fold_back(self):
        for style in conformance.NORMALIZATION_STYLES:
            text = conformance.styled("São Luís", style)
            self.assertNotEqual("São Luís", text)
            expected = "cidade de sao luis" if style == "pontuacao" else "sao luis"
            self.assertEqual(expected, fold(text).lower(), style)  # a maiúscula matemática fica (ver fold-07)
        self.assertEqual("𝐆𝐨𝐢𝐚\u0302𝐧𝐢𝐚", conformance.styled("Goiânia", "matematico"))

    def test_unit_cases_are_the_reference(self):
        cases = conformance.unit_cases(conformance.rules_section(), conformance.unit_fixtures())
        self.assertEqual(len(cases), len({c["id"] for c in cases}))
        by_input = {(c["fn"], json.dumps(c["args"], ensure_ascii=False)): c["expected"] for c in cases}

        def expected(fn, **args):
            return by_input[(fn, json.dumps(args, ensure_ascii=False))]
        # as minúsculas vêm antes da decomposição: a maiúscula matemática não tem minúscula e vira "G" (o FTS acha
        # do mesmo jeito, mas o porte tem de dar o mesmo texto; docs/CONFORMIDADE.md)
        self.assertEqual("Goiania", expected("fold", text="𝐆𝐨𝐢𝐚\u0302𝐧𝐢𝐚"))
        self.assertEqual("goiania 10", expected("fold", text="ＧＯＩÂＮＩＡ １０"))
        self.assertEqual("rua no 5", expected("fold", text="Rua Nº 5"))
        self.assertEqual("goi ania", expected("fold", text="Goi\u00adânia"))  # o hífen suave separa
        self.assertEqual(3, expected("edit_distance", a="ca", b="abc"))  # transposição simples, não Damerau completo
        self.assertEqual({"number": 152, "words": ["rua", "10", "setor", "oeste"]},
                         expected("house_number_in", words=["rua", "10", "152", "setor", "oeste"]))
        self.assertIsNone(expected("house_number_in", words=["avenida", "t", "63"]))
        self.assertEqual([["10", True], ["dez", True]], expected("options", word="10", last=False))
        self.assertEqual("goiania", expected("correct", word="goiana", prefix=False, force=True))
        self.assertEqual("Goiás", expected("parse", folded="cidade de goias")["municipality"])
        self.assertEqual("amenity=fuel, Goiânia",  # o ponto sem nome mostra o tipo
                         expected("label", name="", kind="amenity=fuel", house_number=None, district=None,
                                  municipality="Goiânia"))
        self.assertTrue(all(c.get("informative") for c in cases if c["fn"] == "fold" and c["args"]["text"] == "٣"))


class BuildTest(unittest.TestCase):
    """O conjunto sobre um pacote pequeno de GO (o de tests/test_search.py), com a receita e o verificador."""

    @classmethod
    def setUpClass(cls):
        cls._tmp = tempfile.TemporaryDirectory()
        cls.folder = Path(cls._tmp.name)
        cls.pack = Pack(cls.folder)
        cls.dbs = {"GO": cls.pack.path}
        cls.travas = [{"uf": "GO", "query": "rua 10 setor oeste", "name": "Rua 10"},
                      {"uf": "GO", "query": "posto", "near": [-16.67, -49.26], "kind": "amenity=fuel"},
                      {"uf": "DF", "query": "brasilia", "name": "Brasília"}]
        cls.doc = conformance.build(cls.dbs, cls.travas)

    @classmethod
    def tearDownClass(cls):
        cls._tmp.cleanup()

    def test_header_ties_the_set_to_the_generation(self):
        doc = self.doc
        self.assertEqual((conformance.CONFORMANCE_VERSION, "x", "1"),
                         (doc["conformance_version"], doc["build_id"], str(doc["format_version"])))
        self.assertEqual(["GO"], doc["states"])
        self.assertEqual({"GO": {"file": "sabia-GO.sqlite.zst"}}, doc["packages"])
        self.assertEqual(conformance.rules_section(), doc["rules"])
        self.assertEqual(16, doc["constants"]["max_combinations"])

    def test_cases(self):
        ids = [c["id"] for c in self.doc["search"] + self.doc["which_street"] + self.doc["unit"]]
        self.assertEqual(len(ids), len(set(ids)))
        searches = {c["id"]: c for c in self.doc["search"]}
        # as travas da UF entram todas, as de outra UF não
        self.assertEqual(["trava-GO-001", "trava-GO-002"], [i for i in searches if i.startswith("trava")])
        self.assertEqual([0.0], [c["near"][0] + 16.67 for c in searches.values() if c["id"] == "trava-GO-002"])
        types = {c["type"] for c in searches.values()}
        for t in ("municipio", "normalizacao", "erro_digitacao", "bairro", "rua", "prefixo", "categoria",
                  "categoria_perto", "marca", "frase_categoria", "numero_casa", "lacuna"):
            self.assertIn(t, types)
        for c in searches.values():
            self.assertEqual({"order_exact", "same_set", "score_tol", "coord_tol_m", "distance_tol_m"},
                             set(c["compare"]))
            self.assertIn("corrected", c["trace"])
            for e in c["expected"]:
                self.assertNotIn("id", e)
                self.assertTrue({"name", "kind", "municipality", "lat", "lng", "score", "hits"} <= set(e))
        self.assertEqual("Goiânia", searches["GO-municipio"]["expected"][0]["name"])
        self.assertEqual("goiania", searches["GO-erro_digitacao"]["trace"]["corrected"])
        house = searches["GO-numero_casa"]
        self.assertEqual("rua 10 4 goiania", house["query"])
        self.assertEqual(("Rua 10", 4, True), tuple(house["expected"][0][k] for k in ("name", "house_number",
                                                                                       "house")))
        self.assertTrue(all(c.get("known_gap") and c["expected"] == [] for c in searches.values()
                            if c["type"] == "lacuna"))

    def test_which_street(self):
        cases = {c["id"]: c for c in self.doc["which_street"]}
        self.assertIn("GO-que_rua-sem_rua", cases)
        self.assertIsNone(cases["GO-que_rua-sem_rua"]["expected"])
        street = cases.get("GO-que_rua-rua")
        if street:
            self.assertAlmostEqual(conformance.STREET_OFFSET_M, street["expected"]["distance_m"], delta=1.0)

    def test_the_reference_passes_its_own_set(self):
        self.assertEqual([], conformance.self_check(self.doc, self.dbs))

    def test_a_wrong_port_fails(self):
        """Um porte com um erro clássico: dobrar sem tirar acento, e a ordem do FTS sem a nota."""
        class Port(conformance.Reference):
            def unit(self, fn, args):
                return args["text"].lower() if fn == "fold" else super().unit(fn, args)

            def search(self, db, query, near, limit):
                return sorted(super().search(db, query, near, limit), key=lambda r: r["name"])

        port = Port(self.doc, self.dbs)
        try:
            report = conformance.check(self.doc, port, ["GO"])
        finally:
            port.close()
        failed = {f["id"] for f in report["failures"]}
        self.assertIn("fold-07", failed)  # as letras matemáticas
        self.assertTrue(any(i.startswith("GO-") for i in failed))
        self.assertEqual(0, report["which_street"]["failed"])
        # as etapas da análise ajudam a achar onde o porte se separa (aqui, iguais: o erro é só na ordem)
        self.assertGreater(report["search"]["failed"], 0)

    def test_known_gaps_only_warn(self):
        class Port(conformance.Reference):
            def search(self, db, query, near, limit):
                if query == "74115-030":
                    return [dict(ITEM, name="Rua do CEP")]
                return super().search(db, query, near, limit)

        port = Port(self.doc, self.dbs)
        try:
            report = conformance.check(self.doc, port, ["GO"])
        finally:
            port.close()
        self.assertEqual([], report["failures"])
        self.assertEqual(["GO-lacuna-2"], [w["id"] for w in report["warnings"] if not w["id"].startswith("fold")])

    def test_cases_of_another_generation_are_skipped(self):
        other = dict(self.doc, build_id="outra")
        names, notes = conformance.available_dbs(other, self.dbs)
        self.assertEqual([], names)
        self.assertIn("outra", notes[0])
        ref = conformance.Reference(other, self.dbs)
        try:
            report = conformance.check(other, ref, names)
        finally:
            ref.close()
        self.assertEqual(len(self.doc["search"]), report["search"]["skipped"])
        self.assertEqual(len(self.doc["unit"]), report["unit"]["passed"])  # as funções puras não dependem do banco

    def test_save_and_load(self):
        packed = self.folder / "c" / conformance.FILE
        digest = conformance.save(self.doc, packed)
        self.assertEqual(f"{digest}  {conformance.FILE}\n",
                         packed.with_name(conformance.SHA_FILE).read_text(encoding="utf-8"))
        self.assertIsNone(conformance.sha_problem(packed))
        self.assertEqual(self.doc, conformance.load(packed))
        again = self.folder / "d" / conformance.FILE
        conformance.save(conformance.build(self.dbs, self.travas), again)
        self.assertEqual(packed.read_bytes(), again.read_bytes(), "o mesmo banco dá o mesmo arquivo")
        packed.write_bytes(packed.read_bytes() + b"x")
        self.assertIn("não bate", conformance.sha_problem(packed))
        plain = self.folder / "c" / "x.json"
        self.assertIsNone(conformance.save(self.doc, plain))
        self.assertEqual(self.doc, conformance.load(plain))

    def test_rules_of_the_pack_must_be_the_generator_ones(self):
        changed = self.folder / "mudado.sqlite"
        changed.write_bytes(self.pack.path.read_bytes())
        with closing(sqlite3.connect(changed)) as db:
            db.execute("DELETE FROM category WHERE word = 'posto'")
            db.commit()
        with self.assertRaises(ValueError) as e:
            conformance.build({"GO": changed}, [])
        self.assertIn("category", str(e.exception))

    def test_validation_candidates_pass_the_gate(self):
        with closing(sqlite3.connect(self.pack.path)) as db:
            found = conformance.validation_candidates(db, "GO")
        self.assertTrue(found)
        for c in found:
            self.assertEqual("GO", c["uf"])
            self.assertIn(c["top"], (1, 3))

    def test_example_is_a_subset(self):
        doc = dict(self.doc, search=self.doc["search"] + [dict(self.doc["search"][0], id="base-01", db="base")])
        doc["packages"] = dict(doc["packages"], base={"file": "sabia-base.sqlite.zst"})
        small = conformance.example(doc)
        self.assertEqual(doc["unit"], small["unit"])
        self.assertTrue(set(c["id"] for c in small["search"]) <= set(conformance.EXAMPLE_SEARCH))
        self.assertEqual({c["db"] for c in small["search"] + small["which_street"]}, set(small["packages"]))


class ScriptsTest(unittest.TestCase):
    """Os dois scripts de ponta a ponta: gerar sobre uma pasta de bancos e verificar com a referência."""

    @classmethod
    def setUpClass(cls):
        cls._tmp = tempfile.TemporaryDirectory()
        cls.folder = Path(cls._tmp.name)
        Pack(cls.folder)

    @classmethod
    def tearDownClass(cls):
        cls._tmp.cleanup()

    def run_script(self, name, *args):
        return subprocess.run([sys.executable, str(GENERATOR_DIR / "scripts" / name), *map(str, args)],
                              capture_output=True, text=True, encoding="utf-8")

    def test_build_then_check(self):
        out = self.folder / "conj" / conformance.FILE
        example = self.folder / "conj" / "exemplo.json"
        r = self.run_script("build_conformance.py", "--dbs", self.folder, "--out", out, "--example", example)
        self.assertEqual(0, r.returncode, r.stdout + r.stderr)
        self.assertIn("Conjunto da geração x", r.stdout)
        self.assertTrue(out.with_name(conformance.SHA_FILE).exists())
        r = self.run_script("check_conformance.py", out, "--dbs", self.folder)
        self.assertEqual(0, r.returncode, r.stdout + r.stderr)
        self.assertIn("0 falharam", r.stdout)
        self.assertNotIn("FALHA", r.stdout)
        # um caso adulterado: o verificador acusa e sai com 1
        doc = conformance.load(out)
        first = next(c for c in doc["search"] if c["expected"])
        first["expected"][0]["name"] = "Outro Nome"
        changed = self.folder / "conj" / "mudado.json"
        conformance.save(doc, changed)
        r = self.run_script("check_conformance.py", changed, "--dbs", self.folder)
        self.assertEqual(1, r.returncode)
        self.assertIn(f"FALHA {first['id']}", r.stdout)
        # sem os bancos, só as funções puras (o exemplo)
        r = self.run_script("check_conformance.py", example)
        self.assertEqual(0, r.returncode, r.stdout + r.stderr)
        self.assertIn("pulados", r.stdout)

    def test_validation_candidates(self):
        r = self.run_script("build_conformance.py", "--dbs", self.folder, "--validation-candidates")
        self.assertEqual(0, r.returncode, r.stderr)
        lines = [json.loads(line.rstrip(",")) for line in r.stdout.splitlines()]
        self.assertTrue(lines)
        self.assertTrue(all(c["uf"] == "GO" for c in lines))


class ExampleFileTest(unittest.TestCase):
    """O exemplo versionado (conformidade-exemplo.json): as funções puras são as da referência de hoje (mudou o
    código, regenere o exemplo com scripts/build_conformance.py --example)."""

    @classmethod
    def setUpClass(cls):
        cls.doc = json.loads(EXAMPLE.read_text(encoding="utf-8"))

    def test_header(self):
        self.assertEqual(conformance.CONFORMANCE_VERSION, self.doc["conformance_version"])
        self.assertRegex(self.doc["build_id"], r"^\d{4}-\d{2}-\d{2}-[0-9a-f]{8}$")
        self.assertEqual(1, self.doc["format_version"])
        self.assertEqual(conformance.rules_section(), self.doc["rules"])
        self.assertEqual(json.loads(json.dumps(conformance.constants_section())), self.doc["constants"])
        self.assertEqual(json.loads(json.dumps(conformance.unit_fixtures())), self.doc["unit_fixtures"])

    def test_unit_cases_match_the_reference(self):
        fresh = conformance.unit_cases(self.doc["rules"], self.doc["unit_fixtures"])
        self.assertEqual(json.loads(json.dumps(fresh, ensure_ascii=False)), self.doc["unit"])

    def test_small_and_with_a_few_searches(self):
        self.assertLess(EXAMPLE.stat().st_size, 300_000)
        self.assertTrue(5 <= len(self.doc["search"]) <= 20)
        self.assertTrue(self.doc["which_street"])
        for c in self.doc["search"]:
            self.assertIn(c["db"], self.doc["packages"])
            self.assertIn("sha256", self.doc["packages"][c["db"]])

    def test_reference_passes_the_unit_cases_without_databases(self):
        ref = conformance.Reference(self.doc, {})
        try:
            report = conformance.check(self.doc, ref, [])
        finally:
            ref.close()
        self.assertEqual((len(self.doc["unit"]), 0), (report["unit"]["passed"], report["unit"]["failed"]))
        self.assertEqual(len(self.doc["search"]), report["search"]["skipped"])

    def test_no_local_paths(self):
        text = EXAMPLE.read_text(encoding="utf-8")
        for needle in ("/home/", "/tmp/", "C:\\\\", "@"):
            self.assertNotIn(needle, text)


class SearchCriteriaTest(unittest.TestCase):
    """O que a conformidade pede de search.py: os critérios da ordem em cada resultado e a nota como função."""

    def test_score_is_the_sum_of_the_weights(self):
        self.assertAlmostEqual(search.W_FULL + search.W_NAME + search.W_RANK + search.W_PLACE + search.W_COVER,
                               search.score(3, 3, 255, 255, 0, 0, 1.0, None))
        self.assertAlmostEqual(search.W_DISTANCE, search.score(0, 0, 0, 0, 0, 0, None, 0.0))

    def test_results_carry_the_criteria(self):
        with tempfile.TemporaryDirectory() as tmp:
            pack = Pack(Path(tmp))
            with closing(sqlite3.connect(pack.path)) as db:
                found = search.search(db, "rua 10 152 setor oeste")
        self.assertEqual({"hits", "house", "elsewhere", "kind_match", "score"}, set(found[0].criteria))
        self.assertTrue(found[0].criteria["house"])
        self.assertEqual(152, found[0].house_number)


if __name__ == "__main__":
    unittest.main()
