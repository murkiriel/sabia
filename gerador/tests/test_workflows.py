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

    def test_old_sqlite_is_installed_before_the_tests(self):
        """Sem o SQLite 3.22, o teste que abre o pacote nele seria pulado em silêncio."""
        install = self.text.find("python scripts/install_sqlite.py")
        self.assertGreater(install, 0)
        self.assertLess(install, self.text.find("python -m unittest discover"))


def job(text: str, name: str) -> str:
    """O trecho de um job: da linha `  nome:` até o próximo job (ou o fim do arquivo)."""
    m = re.search(rf"^  {name}:\n(.*?)(?=^  \w[\w-]*:\n|\Z)", text, flags=re.MULTILINE | re.DOTALL)
    return m.group(1) if m else ""


class ScheduledGenerationTest(unittest.TestCase):
    """O workflow gerar roda todo dia e só segue para a geração quando a publicada completa o intervalo (D11)."""

    def setUp(self):
        self.text = workflows().get("gerar.yml", "")
        self.interval = job(self.text, "interval")
        self.generate = job(self.text, "generate")

    def crons(self):
        return re.findall(r'(?m)^    - cron: "([^"]+)"', self.text)

    def test_both_workflows_exist(self):
        self.assertEqual(["gerar.yml", "testes.yml"], list(workflows()))

    def test_runs_twice_a_day(self):
        """Dois disparos por dia: um disparo que o GitHub pula não avisa ninguém, o segundo cobre o primeiro."""
        crons = self.crons()
        self.assertEqual(2, len(crons))
        self.assertEqual(1, len({c.split()[0] for c in crons}), crons)  # o mesmo minuto, horas diferentes
        self.assertEqual(2, len({c.split()[1] for c in crons}), crons)
        self.assertEqual(["* * *"] * 2, [" ".join(c.split()[2:]) for c in crons])

    def test_never_on_the_hour(self):
        """Na hora cheia o GitHub atrasa ou pula os disparos agendados."""
        for cron in self.crons():
            self.assertNotEqual("0", cron.split()[0], cron)

    def test_extra_generation_day_reaches_the_rule(self):
        self.assertRegex(self.interval, r'(?m)^\s+GENERATE_FROM: "(\d{4}-\d{2}-\d{2})?"')
        self.assertIn('--generate-from "$GENERATE_FROM"', self.interval)

    def test_published_date_is_the_one_on_the_branch_now(self):
        """Um run que esperou na fila atrás de outro que publicou lê o catálogo de agora, não o do disparo."""
        self.assertRegex(self.interval, r"- uses: actions/checkout@v\d+\n\s+with:\n\s+ref: \$\{\{ github\.ref \}\}\n")

    def test_can_still_be_started_by_hand_without_publishing(self):
        self.assertIn("  workflow_dispatch:\n", self.text)
        self.assertRegex(self.text, r"(?s)publish:\n.*?type: boolean\n\s+default: false\n")

    def test_interval_job_asks_the_tested_rule(self):
        """A data vem do catálogo do checkout: com o repositório privado, raw.githubusercontent.com responde 404."""
        self.assertIn("scripts/due.py", self.interval)
        self.assertIn("run: ${{ steps.age.outputs.run }}", self.interval)
        commands = "\n".join(line for line in self.text.splitlines() if not line.lstrip().startswith("#"))
        self.assertNotIn("raw.githubusercontent.com", commands)

    def test_manual_run_always_generates(self):
        self.assertIn("github.event_name != 'schedule' && '--manual' || ''", self.interval)

    def test_a_fork_does_not_generate_on_schedule(self):
        self.assertIn("if: github.event_name != 'schedule' || github.repository == 'Murkiriel/sabia'",
                      self.interval)

    def test_generation_waits_for_the_interval_job(self):
        self.assertIn("needs: interval\n", self.generate)
        self.assertIn("if: needs.interval.outputs.run == 'true'\n", self.generate)

    def test_scheduled_run_publishes_and_manual_only_if_asked(self):
        self.assertIn("PUBLISH: ${{ github.event_name == 'schedule' || inputs.publish == true }}", self.generate)
        publish_step = self.generate[self.generate.index("- name: Publicar"):]
        self.assertIn("if: env.PUBLISH == 'true'\n", publish_step)
        self.assertNotIn("inputs.publish }}", publish_step)
        self.assertIn("python scripts/publish.py --release --commit --push", publish_step)

    def test_old_sqlite_before_the_generation(self):
        """Sem o SQLite 3.22, a trava G7e falha e nada é publicado."""
        install = self.generate.find("python scripts/install_sqlite.py")
        self.assertGreater(install, 0)
        self.assertLess(install, self.generate.find("python generate.py"))

    def test_generates_the_whole_country_from_the_downloaded_extract(self):
        self.assertIn("python generate.py", self.generate)
        self.assertNotIn("--osm-file", self.generate)
        self.assertNotIn("--states", self.generate)

    def test_one_generation_at_a_time(self):
        self.assertRegex(self.text, r"(?m)^concurrency:\n  group: generate\n  cancel-in-progress: false")


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
