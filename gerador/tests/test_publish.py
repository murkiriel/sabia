"""As travas da publicação (publishing.check) e a tabela "Baixar por estado" do README."""
import json
import os
import shutil
import subprocess
import sys
import tempfile
import unicodedata
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from sabia import catalog, config, conformance, publishing  # noqa: E402
from tests.osm_builder import MUNICIPALITIES  # noqa: E402
from tests.test_catalog import packages  # noqa: E402


class CheckTest(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.dist = Path(self._tmp.name)
        self._patch = mock.patch.object(config, "DIST", self.dist)
        self._patch.start()
        self.cat = catalog.build_catalog(packages(self.dist), MUNICIPALITIES, generator_commit="abc1234")
        self.report({"problems": []})
        self.conformance(self.cat["build_id"])

    def conformance(self, build_id, format_version=None):
        doc = {"conformance_version": conformance.CONFORMANCE_VERSION, "build_id": build_id,
               "format_version": self.cat["format_version"] if format_version is None else format_version,
               "unit": [], "search": [], "which_street": []}
        conformance.save(doc, self.dist / conformance.FILE)

    def tearDown(self):
        self._patch.stop()
        self._tmp.cleanup()

    def report(self, data):
        (self.dist / "relatorio.json").write_text(json.dumps(data), encoding="utf-8")

    def check(self, published=None, **kw):
        return publishing.check(self.cat, published, kw.get("accept_drop", False), kw.get("accept_older", False))

    def test_good_generation_passes(self):
        self.assertEqual([], self.check())

    def test_generation_still_running(self):
        (self.dist / config.IN_PROGRESS_MARKER).write_text("x")
        self.assertEqual(1, len(self.check()))

    def test_newer_format_than_the_generator(self):
        self.cat["format_version"] = 99
        self.assertIn("formato", self.check()[0])

    def test_local_extract_is_never_published(self):
        self.cat["osm"]["url"] = "local"
        self.assertIn("local", self.check()[0])

    def test_missing_or_changed_file(self):
        (self.dist / "sabia-DF.sqlite.zst").unlink()
        (self.dist / "sabia-GO.sqlite.zst").write_bytes(b"outro")
        self.assertEqual(["DF: falta sabia-DF.sqlite.zst", "GO: sha256 de sabia-GO.sqlite.zst não bate com o catálogo"],
                         self.check())

    def test_file_over_the_release_limit(self):
        with mock.patch.object(config, "MAX_ASSET_BYTES", 10):
            self.assertEqual(3, len(self.check()))

    def test_gates_must_have_passed(self):
        self.report({"problems": ["GO: busca 'x' ..."]})
        self.assertIn("travas", self.check()[0])
        (self.dist / "relatorio.json").unlink()
        self.assertIn("relatorio.json", self.check()[0])

    def test_drop_against_the_published_catalog(self):
        published = json.loads(json.dumps(self.cat))
        published["states"]["GO"]["counts"]["items"] = 1000
        self.assertEqual(1, len(self.check(published)))
        self.assertEqual([], self.check(published, accept_drop=True))

    def test_older_osm_than_the_published(self):
        published = json.loads(json.dumps(self.cat))
        published["osm"]["timestamp"] = "2026-11-01T00:00:00Z"
        self.assertEqual(1, len(self.check(published)))
        self.assertEqual([], self.check(published, accept_older=True))

    def test_files_of_the_release(self):
        self.assertEqual(["sabia-base.sqlite.zst", "sabia-DF.sqlite.zst", "sabia-GO.sqlite.zst"],
                         publishing.package_files(self.cat))
        # o conjunto de conformidade sobe junto, depois dos pacotes, com o sha256 ao lado (fora do catálogo)
        self.assertEqual(publishing.package_files(self.cat) + ["sabia-conformidade.json.zst",
                                                                "sabia-conformidade.json.zst.sha256"],
                         publishing.release_files(self.cat))
        self.assertNotIn("conformidade", json.dumps(self.cat))

    def test_conformance_set_is_required(self):
        (self.dist / conformance.FILE).unlink()
        self.assertEqual(["falta sabia-conformidade.json.zst: a geração não passou pela etapa conformance"],
                         self.check())

    def test_conformance_set_of_another_generation(self):
        self.conformance("2026-01-01-00000000")
        self.assertIn("2026-01-01-00000000", self.check()[0])
        self.conformance(self.cat["build_id"], format_version=2)
        self.assertIn("formato 2", self.check()[0])

    def test_conformance_set_must_match_its_sha256(self):
        (self.dist / conformance.SHA_FILE).write_text("0" * 64 + "  " + conformance.FILE + "\n", encoding="utf-8")
        self.assertIn("não bate", self.check()[0])
        (self.dist / conformance.SHA_FILE).unlink()
        self.assertIn("falta", self.check()[0])


@unittest.skipUnless(shutil.which("git"), "sem git")
class CommitAndPushTest(unittest.TestCase):
    """O commit e o push do catálogo (publishing.commit_and_push) em repositórios git de verdade: um remoto vazio
    (bare) e dois clones, o do job de geração (`job`) e o de quem empurra no meio (`other`). Nada sai da pasta
    temporária."""

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        root = Path(self._tmp.name)
        self.env = {**os.environ, "GIT_CONFIG_GLOBAL": os.devnull, "GIT_CONFIG_SYSTEM": os.devnull,
                    "GIT_AUTHOR_NAME": "t", "GIT_AUTHOR_EMAIL": "t@users.noreply.github.com",
                    "GIT_COMMITTER_NAME": "t", "GIT_COMMITTER_EMAIL": "t@users.noreply.github.com"}
        self.remote = root / "remoto.git"
        self.sh("init", "--bare", "-b", "main", str(self.remote), cwd=root)
        self.job, self.other = root / "job", root / "outro"
        self.sh("clone", str(self.remote), str(self.job), cwd=root)
        (self.job / "catalogo.json").write_text('{"build_id": "antigo"}\n', encoding="utf-8")
        (self.job / "README.md").write_text("tabela antiga\n", encoding="utf-8")
        self.sh("add", ".", cwd=self.job)
        self.sh("commit", "-m", "base", cwd=self.job)
        self.sh("push", "origin", "HEAD:main", cwd=self.job)
        self.sh("clone", str(self.remote), str(self.other), cwd=root)

    def tearDown(self):
        self._tmp.cleanup()

    def sh(self, *args, cwd):
        r = subprocess.run(["git", *args], cwd=cwd, env=self.env, capture_output=True, text=True)
        self.assertEqual(0, r.returncode, r.stderr)
        return r.stdout

    def git(self, repo):
        return lambda *args: subprocess.run(["git", "-C", str(repo), *args], env=self.env, capture_output=True,
                                            text=True)

    def push_from_other(self, name, text):
        (self.other / name).write_text(text, encoding="utf-8")
        self.sh("add", ".", cwd=self.other)
        self.sh("commit", "-m", f"outro {name}", cwd=self.other)
        self.sh("pull", "--rebase", cwd=self.other)
        self.sh("push", cwd=self.other)

    def publish(self, git=None, push=True):
        (self.job / "catalogo.json").write_text('{"build_id": "novo"}\n', encoding="utf-8")
        (self.job / "README.md").write_text("tabela nova\n", encoding="utf-8")
        publishing.commit_and_push(git or self.git(self.job), "Geração novo", ["catalogo.json", "README.md"], push)

    def remote_file(self, name):
        return self.sh("show", f"main:{name}", cwd=self.remote)

    def remote_log(self):
        return self.sh("log", "--format=%s", "main", cwd=self.remote).splitlines()

    def test_push_with_nobody_in_the_way(self):
        self.publish()
        self.assertEqual(["Geração novo", "base"], self.remote_log())
        self.assertIn("novo", self.remote_file("catalogo.json"))

    def test_without_push_only_commits(self):
        self.publish(push=False)
        self.assertEqual(["base"], self.remote_log())
        self.assertEqual("Geração novo", self.sh("log", "-1", "--format=%s", cwd=self.job).strip())

    def test_commit_has_only_the_catalog_and_the_readme(self):
        (self.job / "lixo.txt").write_text("não vai", encoding="utf-8")
        self.publish()
        self.assertEqual(["README.md", "catalogo.json"],
                         sorted(self.sh("show", "--name-only", "--format=", "main", cwd=self.remote).split()))

    def test_push_by_someone_else_in_the_meantime_is_rebased(self):
        """O caso real: o job começou no commit do disparo e, 90 min depois, o ramo já andou."""
        self.push_from_other("NOTAS.md", "uma nota\n")
        self.publish()
        self.assertEqual(["Geração novo", "outro NOTAS.md", "base"], self.remote_log())
        self.assertIn("novo", self.remote_file("catalogo.json"))
        self.assertEqual("uma nota\n", self.remote_file("NOTAS.md"))

    def test_push_refused_once_is_tried_again(self):
        """Alguém empurra entre o pull e o push: a primeira tentativa é recusada e a segunda passa."""
        real, pushes = self.git(self.job), []

        def git(*args):
            if args[0] == "push":
                pushes.append(args)
                if len(pushes) == 1:
                    self.push_from_other("NOTAS.md", "entre o pull e o push\n")
            return real(*args)
        self.publish(git)
        self.assertEqual(2, len(pushes))
        self.assertEqual(["Geração novo", "outro NOTAS.md", "base"], self.remote_log())

    def test_gives_up_after_two_tries(self):
        real, calls = self.git(self.job), []

        def git(*args):
            calls.append(args[0])
            if args[0] == "push":
                return subprocess.CompletedProcess(args, 1, "", "remote: recusado")
            return real(*args)
        with self.assertRaises(publishing.GitError) as cm:
            self.publish(git)
        self.assertIn("2 tentativas", str(cm.exception))
        self.assertIn("recusado", str(cm.exception))
        self.assertEqual(2, calls.count("push"))
        self.assertEqual(2, calls.count("pull"))

    def test_conflict_aborts_the_rebase_and_keeps_the_commit(self):
        """Alguém mexeu no catalogo.json: não dá para resolver sozinho. O rebase é desfeito, nada fica pela metade."""
        self.push_from_other("catalogo.json", '{"build_id": "de outro"}\n')
        with self.assertRaises(publishing.GitError) as cm:
            self.publish()
        self.assertIn("pull --rebase", str(cm.exception))
        self.assertIn("release já subiu", str(cm.exception))
        git_dir = self.job / ".git"
        self.assertFalse((git_dir / "rebase-merge").exists() or (git_dir / "rebase-apply").exists())
        self.assertEqual("Geração novo", self.sh("log", "-1", "--format=%s", cwd=self.job).strip())
        self.assertIn("de outro", self.remote_file("catalogo.json"))

    def test_commit_failure_is_an_error(self):
        with self.assertRaises(publishing.GitError):
            publishing.commit_and_push(self.git(self.job), "x", ["nao-existe.json"], False)


def sample_catalog():
    def package(file, size):
        return {"file": file, "bytes": size, "sha256": "a" * 64, "bytes_db": size * 4, "bbox": [0, 0, 1, 1],
                "counts": {}}
    states = {uf: {"name": name, **package(f"sabia-{uf}.sqlite.zst", 1_000_000 + i)}
              for i, (uf, name) in enumerate(sorted(config.STATES.items()))}
    return {"build_id": "2026-10-05-93a54bc6", "format_version": 1, "osm": {"timestamp": "2026-10-05T00:58:57Z"},
            "release_url": "https://github.com/Murkiriel/sabia/releases/download/2026-10-05-93a54bc6/",
            "base": package("sabia-base.sqlite.zst", 312_909), "states": states}


class TableTest(unittest.TestCase):
    def test_one_row_per_package_with_release_link(self):
        table = publishing.downloads_table(sample_catalog())
        lines = [line for line in table.splitlines() if line.startswith("| ") and "sabia-" in line]
        self.assertEqual(28, len(lines))
        self.assertIn("(https://github.com/Murkiriel/sabia/releases/download/2026-10-05-93a54bc6/"
                      "sabia-GO.sqlite.zst)", table)

    def test_base_first_then_states_by_name(self):
        lines = [line for line in publishing.downloads_table(sample_catalog()).splitlines() if "sabia-" in line]
        self.assertIn("sabia-base.sqlite.zst", lines[0])
        names = [line.split("|")[1].strip() for line in lines[1:]]
        strip = lambda n: unicodedata.normalize("NFKD", n).encode("ascii", "ignore").decode()  # noqa: E731
        self.assertEqual(sorted(names, key=strip), names)
        self.assertLess(names.index("Pará (PA)"), names.index("Paraíba (PB)"))

    def test_size_and_generation_in_text(self):
        table = publishing.downloads_table(sample_catalog())
        self.assertIn("0,3 MB", table)
        self.assertIn("2026-10-05-93a54bc6", table)
        self.assertIn("2026-10-05", table)


class ReadmeTest(unittest.TestCase):
    def test_replaces_only_between_markers(self):
        text = "antes\n<!-- downloads:start -->\nvelho\n<!-- downloads:end -->\ndepois\n"
        updated = publishing.update_readme(text, "TABELA")
        self.assertEqual("antes\n<!-- downloads:start -->\nTABELA\n<!-- downloads:end -->\ndepois\n", updated)
        self.assertEqual(updated, publishing.update_readme(updated, "TABELA"))

    def test_missing_markers_is_error(self):
        with self.assertRaises(ValueError):
            publishing.update_readme("sem marcadores\n", "TABELA")

    def test_root_readme_has_markers(self):
        text = (config.REPO / "README.md").read_text(encoding="utf-8")
        publishing.update_readme(text, publishing.downloads_table(sample_catalog()))  # não levanta


class RulesTest(unittest.TestCase):
    def test_anonymous_identity(self):
        self.assertIsNone(publishing.identity_problem("14956419+Murkiriel@users.noreply.github.com"))
        self.assertIsNotNone(publishing.identity_problem("alguem@exemplo.com"))


if __name__ == "__main__":
    unittest.main()
