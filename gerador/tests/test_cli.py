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


if __name__ == "__main__":
    unittest.main()
