"""Os workflows do GitHub Actions: o que precisa continuar valendo neles, lido do texto dos arquivos (sem YAML)."""
import re
import unittest
from pathlib import Path

WORKFLOWS = Path(__file__).resolve().parent.parent.parent / ".github" / "workflows"


def workflows():
    return {f.name: f.read_text(encoding="utf-8").replace("\r\n", "\n") for f in sorted(WORKFLOWS.glob("*.yml"))}


class RunnerTest(unittest.TestCase):
    def test_tests_workflow_exists(self):
        self.assertIn("testes.yml", workflows())

    def test_runner_image_is_pinned(self):
        """Imagem com versão, nunca `-latest`: quando o GitHub troca a imagem por trás do `ubuntu-latest`, os passos
        passam a rodar numa máquina em que nunca foram testados."""
        for name, text in workflows().items():
            images = re.findall(r"^\s*runs-on:\s*(\S+)\s*$", text, flags=re.MULTILINE)
            self.assertTrue(images, f"{name}: nenhum runs-on")
            for image in images:
                self.assertRegex(image, r"^ubuntu-\d+\.\d+$", f"{name}: runs-on {image}")


class TestsWorkflowTest(unittest.TestCase):
    def setUp(self):
        self.text = workflows().get("testes.yml", "")

    def test_runs_on_every_push_and_pull_request(self):
        self.assertRegex(self.text, r"(?m)^on:\n  push:\n  pull_request:\n")

    def test_read_only_token(self):
        self.assertRegex(self.text, r"(?m)^permissions:\n  contents: read\n")

    def test_installs_the_pinned_requirements(self):
        self.assertIn("pip install -r requirements.txt", self.text)

    def test_runs_the_whole_suite(self):
        self.assertIn("python -m unittest discover -s tests -t . -v", self.text)


class RequirementsTest(unittest.TestCase):
    def test_versions_are_pinned(self):
        lines = (Path(__file__).resolve().parent.parent / "requirements.txt").read_text(encoding="utf-8").splitlines()
        packages = [line.split("#")[0].strip() for line in lines if line.split("#")[0].strip()]
        self.assertTrue(packages)
        for p in packages:
            self.assertRegex(p, r"^[A-Za-z0-9_.-]+==[0-9][0-9A-Za-z.]*$", p)
        names = {p.split("==")[0].lower() for p in packages}
        self.assertTrue({"osmium", "shapely", "zstandard"} <= names, names)


if __name__ == "__main__":
    unittest.main()
