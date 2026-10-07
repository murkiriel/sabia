"""A linha de comando do generate.py: escolha dos estados e das etapas."""
import argparse
import importlib.util
import sys
import unittest
from pathlib import Path

GENERATOR_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(GENERATOR_DIR))


def load_script():
    spec = importlib.util.spec_from_file_location("generate", GENERATOR_DIR / "generate.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class StatesArgumentTest(unittest.TestCase):
    def setUp(self):
        self.script = load_script()

    def test_empty_means_all_states(self):
        states = self.script.parse_states("")
        self.assertEqual(27, len(states))
        self.assertEqual(sorted(states), states)

    def test_list_is_normalized(self):
        self.assertEqual(["DF", "GO"], self.script.parse_states("go, df"))
        self.assertEqual(["DF"], self.script.parse_states("DF,DF"))

    def test_unknown_state_is_refused(self):
        with self.assertRaises(argparse.ArgumentTypeError):
            self.script.parse_states("DF,XX")


class StagesTest(unittest.TestCase):
    def setUp(self):
        self.script = load_script()

    def test_stage_order(self):
        self.assertEqual(["sources", "build", "validate", "catalog"], self.script.STAGES)

    def test_parser_defaults(self):
        args = self.script.build_parser().parse_args([])
        self.assertEqual("sources", args.from_stage)
        self.assertEqual(27, len(args.states))
        self.assertIsNone(args.osm_file)

    def test_parser_local_extract_and_states(self):
        args = self.script.build_parser().parse_args(["--states", "DF", "--osm-file", "x.osm.pbf",
                                                      "--from", "validate"])
        self.assertEqual(["DF"], args.states)
        self.assertEqual(Path("x.osm.pbf"), args.osm_file)
        self.assertEqual("validate", args.from_stage)


class SourcesStageTest(unittest.TestCase):
    """A etapa sources usa o extrato local quando pedido, baixa o do Brasil senão, e guarda os dados dele em
    data/build/osm.json para as etapas seguintes (e para --from build)."""

    def setUp(self):
        import tempfile
        from unittest import mock

        from sabia import config, sources

        self.script = load_script()
        self._tmp = tempfile.TemporaryDirectory()
        build = Path(self._tmp.name)
        self.calls = []
        local = {"path": "x.osm.pbf", "url": "local", "timestamp": "2026-09-29T20:22:51Z", "md5": "ab", "size": 1}
        remote = dict(local, url="https://exemplo/brazil-latest.osm.pbf", path="brazil-latest.osm.pbf")
        self._patches = [
            mock.patch.object(config, "BUILD", build),
            mock.patch.object(config, "RAW", build / "raw"),
            mock.patch.object(sources, "local_extract", lambda p: self.calls.append(("local", p)) or local),
            mock.patch.object(sources, "osm_extract", lambda: self.calls.append(("download",)) or remote),
            mock.patch.object(sources, "municipal_mesh", lambda: self.calls.append(("mesh",)) or Path("m")),
            mock.patch.object(sources, "municipality_names", lambda: self.calls.append(("names",)) or Path("n")),
            mock.patch.object(sources, "ibge_localities", lambda: self.calls.append(("localities",)) or Path("l")),
            mock.patch.object(sources, "prf_units", lambda: self.calls.append(("prf",)) or Path("p")),
        ]
        for p in self._patches:
            p.start()
        self.build = build

    def tearDown(self):
        for p in self._patches:
            p.stop()
        self._tmp.cleanup()

    def test_local_extract(self):
        import json

        meta = self.script.sources_stage(Path("x.osm.pbf"))
        self.assertEqual("local", meta["url"])
        self.assertEqual([("local", Path("x.osm.pbf")), ("mesh",), ("names",), ("localities",), ("prf",)],
                         self.calls)
        self.assertEqual(meta, json.loads((self.build / "osm.json").read_text(encoding="utf-8")))

    def test_download_when_no_local_extract(self):
        meta = self.script.sources_stage(None)
        self.assertEqual([("download",), ("mesh",), ("names",), ("localities",), ("prf",)], self.calls)
        self.assertTrue(meta["url"].startswith("https://"))

    def test_the_sources_and_their_dates_go_to_the_generation_record(self):
        """HS2: data/build/fontes.json, com a data de cada fonte, que o registro da geração (geracao.json) leva."""
        import json

        self.assertEqual({}, self.script.sources_record())
        self.script.sources_stage(Path("x.osm.pbf"))
        saved = json.loads((self.build / "fontes.json").read_text(encoding="utf-8"))
        self.assertEqual({"url": "local", "date": "2026-09-29T20:22:51Z"}, saved["openstreetmap"])
        self.assertIn("antt_postos_prf.json", saved)
        self.assertEqual(saved, self.script.sources_record())


if __name__ == "__main__":
    unittest.main()
