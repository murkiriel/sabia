"""O registro de uma geração em data/dist/geracao.json: tempo de cada etapa, pico de disco e resultado."""
import json
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from sabia import run_record  # noqa: E402

GB = 1_000_000_000


class RunRecorderTest(unittest.TestCase):
    def test_saves_stages_disk_peak_and_result(self):
        with tempfile.TemporaryDirectory() as tmp:
            folder = Path(tmp)
            (folder / "a.bin").write_bytes(b"x" * 5000)
            recorder = run_record.RunRecorder(folder, interval=0.01)
            with recorder.stage("packages"):
                (folder / "b.bin").write_bytes(b"y" * 7000)
            recorder.save(folder / "geracao.json", "ok")
            data = json.loads((folder / "geracao.json").read_text(encoding="utf-8"))
        self.assertEqual("ok", data["result"])
        self.assertEqual(["packages"], [e["stage"] for e in data["stages"]])
        self.assertGreaterEqual(data["stages"][0]["minutes"], 0)
        self.assertGreaterEqual(data["peak_disk_gb"], 12000 / GB)

    def test_failed_stage_is_recorded(self):
        with tempfile.TemporaryDirectory() as tmp:
            recorder = run_record.RunRecorder(Path(tmp), interval=0.01)
            with self.assertRaises(ValueError):
                with recorder.stage("tiles"):
                    raise ValueError("caiu")
            recorder.save(Path(tmp) / "geracao.json", "failed: caiu")
            data = json.loads((Path(tmp) / "geracao.json").read_text(encoding="utf-8"))
        self.assertEqual("failed", data["stages"][0]["status"])
        self.assertEqual("failed: caiu", data["result"])


if __name__ == "__main__":
    unittest.main()
