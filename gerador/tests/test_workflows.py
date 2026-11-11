"""Os workflows do GitHub Actions: o que precisa continuar valendo neles, lido do texto dos arquivos (sem YAML)."""
import re
import unittest
from pathlib import Path
from typing import Dict, List

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


class ActionsPinTest(unittest.TestCase):
    """Toda action fixada pelo SHA do commit (40 caracteres), com a tag exata em comentário: uma tag (`@v7`) pode ser
    movida para outro código sem que nada mude aqui."""

    USES = re.compile(r"^\s*(?:- )?uses:\s*(\S+)(.*)$", flags=re.MULTILINE)

    def uses(self):
        return [(name, m.group(1), m.group(2)) for name, text in workflows().items() for m in self.USES.finditer(text)]

    def test_there_are_actions(self):
        self.assertGreaterEqual(len(self.uses()), 6)

    def test_every_action_is_pinned_by_commit_sha(self):
        for name, ref, comment in self.uses():
            self.assertRegex(ref, r"^[\w.-]+/[\w./-]+@[0-9a-f]{40}$", f"{name}: {ref}")
            self.assertRegex(comment, r"^  # v\d+\.\d+\.\d+$", f"{name}: {ref}{comment}")

    def test_same_action_same_commit_and_tag(self):
        seen = {}
        for name, ref, comment in self.uses():
            action, sha = ref.split("@")
            self.assertEqual((sha, comment), seen.setdefault(action, (sha, comment)), f"{name}: {action}")


class TestsWorkflowTest(unittest.TestCase):
    def setUp(self):
        self.text = workflows().get("testes.yml", "")

    def test_runs_on_every_push_and_pull_request(self):
        self.assertRegex(self.text, r"(?m)^on:\n  push:\n  pull_request:\n")

    def test_read_only_token(self):
        self.assertRegex(self.text, r"(?m)^permissions:\n  contents: read\n")

    def test_installs_the_pinned_requirements(self):
        self.assertIn("pip install --require-hashes -r requirements.txt", self.text)

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
        self.assertRegex(self.interval, r"- uses: actions/checkout@[0-9a-f]{40}  # v[\d.]+\n"
                                        r"\s+with:\n\s+ref: \$\{\{ github\.ref \}\}\n")

    def test_can_still_be_started_by_hand_without_publishing(self):
        self.assertIn("  workflow_dispatch:\n", self.text)
        self.assertRegex(self.text, r"(?s)publish:\n.*?type: boolean\n\s+default: false\n")

    def test_interval_job_asks_the_tested_rule(self):
        """A data vem do catálogo do checkout: com o repositório privado (até 2026-11-11), raw.githubusercontent.com
        responde 404; público, pode servir por alguns minutos o catálogo de antes de uma publicação."""
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

    def step(self, name: str) -> str:
        """O texto de um passo do job generate, do `- name:` até o próximo passo."""
        m = re.search(rf"(?ms)^      - name: {re.escape(name)}\n(.*?)(?=^      - |\Z)", self.generate)
        return m.group(1) if m else ""

    def test_frees_disk_before_anything_else(self):
        """O executor de repositório privado chegava com ~14 GB livres em / (o público, desde 2026-11-11, ainda não foi
        medido): sem apagar as ferramentas que a geração não usa, o extrato, os bancos e o swap não cabem."""
        free = self.step("Liberar disco")
        self.assertIn("sudo rm -rf /usr/share/dotnet /usr/local/lib/android", free)
        self.assertIn("docker image prune", free)
        self.assertLess(self.generate.find("- name: Liberar disco"),
                        self.generate.find("- name: Dados e swap no disco com mais espaço"))

    def test_data_and_swap_on_the_disk_with_more_space(self):
        """data/ e o swap vão para o disco com mais espaço livre (/mnt, quando há, ou o de $HOME), antes do SQLite
        3.22, que também grava em data/."""
        place = self.step("Dados e swap no disco com mais espaço")
        self.assertIn('ln -s "$base/sabia-data" gerador/data', place)
        self.assertIn('sudo swapon "$base/swap-sabia"', place)
        self.assertIn('if [ "$mnt" -gt "$root" ]; then base=/mnt; else base="$HOME"; fi', place)
        self.assertLess(self.generate.find("- name: Dados e swap no disco com mais espaço"),
                        self.generate.find("python scripts/install_sqlite.py"))
        self.assertNotIn("/swap-sabia\n", self.generate.replace('"$base/swap-sabia"', ""))

    def test_generation_log_is_live(self):
        """Sem buffer: num run de horas, o log do passo mostra o progresso enquanto roda, não tudo no fim."""
        self.assertIn('PYTHONUNBUFFERED: "1"', self.step("Gerar"))

    def test_invalid_downloads_go_to_the_artifact(self):
        """O corpo de uma resposta ruim do IBGE (data/raw/*.invalido) vai para o artefato: a falha diz a causa."""
        self.assertIn("gerador/data/raw/*.invalido", self.step("Guardar logs e medições"))

    def test_conformance_set_goes_to_the_artifact(self):
        """O conjunto de conformidade da busca vai para o artefato, também numa geração à mão sem publicar."""
        self.assertIn("gerador/data/dist/sabia-conformidade.json.zst", self.step("Guardar logs e medições"))

    def test_no_ibge_cache(self):
        """A malha e a lista de municípios vêm das cópias versionadas (2026-11-10): o cache por mês do Actions, que
        guardava as duas, saiu (em novembro não havia cache e a API não respondia ao executor)."""
        self.assertNotIn("actions/cache", self.generate)
        self.assertNotIn("ibge_*.json", self.generate)

    def test_one_generation_at_a_time(self):
        self.assertRegex(self.text, r"(?m)^concurrency:\n  group: generate\n  cancel-in-progress: false")


GENERATOR = Path(__file__).resolve().parent.parent
COMPILE = "uv pip compile requirements.in --generate-hashes --python-version 3.12 -o requirements.txt"


def requirements(name: str) -> List[str]:
    """As linhas de requisito de um arquivo do pip, com as continuações (`\\`) juntadas e sem os comentários."""
    text = (GENERATOR / name).read_text(encoding="utf-8").replace("\r\n", "\n").replace("\\\n", " ")
    return [" ".join(line.split("#")[0].split()) for line in text.splitlines() if line.split("#")[0].strip()]


def pins(lines: List[str]) -> Dict[str, str]:
    return {line.split()[0].split("==")[0].lower(): line.split()[0].split("==")[1] for line in lines}


class RequirementsTest(unittest.TestCase):
    """As dependências diretas no requirements.in; o requirements.txt, o que se instala, com todas as transitivas
    fixadas e com hash, gerado dele pelo uv."""

    def test_direct_dependencies_are_pinned(self):
        lines = requirements("requirements.in")
        for line in lines:
            self.assertRegex(line, r"^[A-Za-z0-9_.-]+==[0-9][0-9A-Za-z.]*$", line)
        self.assertTrue({"osmium", "shapely", "zstandard", "pyarrow"} <= set(pins(lines)), lines)

    def test_lock_pins_everything_with_hashes(self):
        lines = requirements("requirements.txt")
        self.assertTrue(lines)
        for line in lines:
            self.assertRegex(line, r"^[A-Za-z0-9_.-]+==[0-9][0-9A-Za-z.]*( --hash=sha256:[0-9a-f]{64})+$", line[:80])

    def test_lock_has_the_direct_versions_and_the_transitive_ones(self):
        """O lock tem cada dependência direta na versão do .in, e mais (numpy, do shapely; requests, do osmium)."""
        direct, locked = pins(requirements("requirements.in")), pins(requirements("requirements.txt"))
        for name, version in direct.items():
            self.assertEqual(version, locked.get(name), name)
        self.assertTrue({"numpy", "requests"} <= set(locked), locked)

    def test_lock_says_how_to_regenerate(self):
        head = (GENERATOR / "requirements.txt").read_text(encoding="utf-8").splitlines()[:3]
        self.assertIn(f"#    {COMPILE}", head)

    def test_workflows_install_only_with_hashes(self):
        """Todo `pip install` dos workflows é do lock, em modo de hash: nada entra sem versão e hash."""
        installs = [line.strip() for text in workflows().values() for line in text.splitlines()
                    if "pip install" in line and not line.lstrip().startswith("#")]
        self.assertEqual(2, len(installs), installs)
        for line in installs:
            self.assertRegex(line, r"^run: pip install --require-hashes -r (gerador/)?requirements\.txt$", line)


if __name__ == "__main__":
    unittest.main()
