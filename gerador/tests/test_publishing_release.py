"""Publicação da release com um `gh` falso em memória: NENHUM teste aqui chama o GitHub nem o programa gh."""
import json
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from sabia import publishing  # noqa: E402


class FakeGh:
    """Imita as respostas do `gh release ...` usadas pela publicação. `fail_upload_of`: nomes de arquivo cujo
    próximo upload falha (uma vez cada), como uma conexão que cai no meio."""

    def __init__(self):
        self.releases = {}  # tag -> {"draft": bool, "assets": {nome: tamanho}}
        self.commands = []
        self.fail_upload_of = set()
        self.fixed_error = None  # (código, stderr) devolvido para qualquer comando

    def __call__(self, args):
        self.commands.append(list(args))
        if self.fixed_error:
            return self.fixed_error[0], "", self.fixed_error[1]
        action, tag = args[1], args[2]
        rel = self.releases.get(tag)
        if action == "view":
            if rel is None:
                return 1, "", "release not found"
            assets = [{"name": n, "size": s} for n, s in rel["assets"].items()]
            return 0, json.dumps({"isDraft": rel["draft"], "assets": assets}), ""
        if action == "create":
            self.releases[tag] = {"draft": "--draft" in args, "assets": {}}
            return 0, "", ""
        if action == "upload":
            path = Path(args[3])
            if path.name in self.fail_upload_of:
                self.fail_upload_of.discard(path.name)
                return 1, "", f"upload of {path.name} failed: connection reset"
            if path.name in rel["assets"] and "--clobber" not in args:
                return 1, "", f"asset {path.name} already exists"
            rel["assets"][path.name] = path.stat().st_size
            return 0, "", ""
        if action == "edit":
            rel["draft"] = False
            return 0, "", ""
        return 1, "", f"comando inesperado: {args}"

    def uploads(self):
        return [Path(c[3]).name for c in self.commands if c[1] == "upload"]


class ReleaseTest(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        folder = Path(self._tmp.name)
        self.files = []
        for name, size in (("sabia-base.sqlite.zst", 300), ("sabia-DF.sqlite.zst", 200), ("sabia-GO.sqlite.zst", 100)):
            (folder / name).write_bytes(b"x" * size)
            self.files.append(folder / name)
        self.gh = FakeGh()

    def tearDown(self):
        self._tmp.cleanup()

    def publish(self):
        publishing.publish_release(self.gh, "2026-09-30-cb859dc3", self.files, "Sabiá", "notas")

    def test_publishes_from_scratch_as_draft_then_publishes(self):
        self.publish()
        rel = self.gh.releases["2026-09-30-cb859dc3"]
        self.assertFalse(rel["draft"])
        self.assertEqual({p.name: p.stat().st_size for p in self.files}, rel["assets"])
        actions = [c[1] for c in self.gh.commands]
        self.assertEqual("create", actions[1])
        self.assertIn("--draft", self.gh.commands[1])
        self.assertEqual("edit", actions[-1])  # publicar é a última coisa

    def test_interrupted_upload_is_resumed(self):
        self.gh.fail_upload_of.add("sabia-DF.sqlite.zst")
        with self.assertRaises(publishing.GhError):
            self.publish()
        rel = self.gh.releases["2026-09-30-cb859dc3"]
        self.assertTrue(rel["draft"])  # nada foi publicado pela metade
        self.gh.commands.clear()
        self.publish()  # rodar de novo retoma em vez de recusar
        self.assertFalse(rel["draft"])
        self.assertEqual(3, len(rel["assets"]))
        self.assertNotIn("sabia-base.sqlite.zst", self.gh.uploads())  # o que já tinha subido não sobe de novo

    def test_asset_with_wrong_size_is_reuploaded(self):
        self.gh.releases["2026-09-30-cb859dc3"] = {"draft": True, "assets": {"sabia-base.sqlite.zst": 7}}
        self.publish()
        self.assertEqual(300, self.gh.releases["2026-09-30-cb859dc3"]["assets"]["sabia-base.sqlite.zst"])
        reupload = [c for c in self.gh.commands if c[1] == "upload" and c[3].endswith("sabia-base.sqlite.zst")]
        self.assertIn("--clobber", reupload[0])

    def test_already_published_release_is_blocked(self):
        self.gh.releases["2026-09-30-cb859dc3"] = {"draft": False, "assets": {}}
        with self.assertRaises(publishing.ReleaseAlreadyPublished):
            self.publish()
        self.assertEqual(["view"], [c[1] for c in self.gh.commands])

    def test_gh_error_shows_command_and_stderr(self):
        self.gh.fixed_error = (1, "HTTP 401: Bad credentials")
        with self.assertRaises(publishing.GhError) as ctx:
            self.publish()
        message = str(ctx.exception)
        self.assertIn("Bad credentials", message)
        self.assertIn("release view", message)

    def test_no_login_is_not_mistaken_for_missing_release(self):
        self.gh.fixed_error = (1, "HTTP 401: Bad credentials")
        with self.assertRaises(publishing.GhError):
            publishing.release_state(self.gh, "2026-09-30-cb859dc3")
        self.assertEqual(1, len(self.gh.commands))  # não tentou criar nada


class RulesTest(unittest.TestCase):
    def test_anonymous_identity(self):
        self.assertIsNone(publishing.identity_problem("14956419+Murkiriel@users.noreply.github.com"))
        self.assertIsNotNone(publishing.identity_problem("alguem@exemplo.com"))
        self.assertIsNotNone(publishing.identity_problem(""))

    def test_older_generation_is_blocked(self):
        published = {"build_id": "2026-10-01-aaaaaaaa", "osm": {"timestamp": "2026-10-01T00:59:51Z"}}
        older = {"build_id": "2026-09-30-bbbbbbbb", "osm": {"timestamp": "2026-09-29T00:59:51Z"}}
        updated = {"build_id": "2026-10-05-cccccccc", "osm": {"timestamp": "2026-10-04T00:59:51Z"}}
        self.assertEqual(1, len(publishing.older_generation(published, older)))
        self.assertEqual([], publishing.older_generation(published, updated))
        self.assertEqual([], publishing.older_generation(None, older))

    def test_inconsistent_flags(self):
        self.assertIsNone(publishing.flags_problem(release=False, commit=False, push=False))
        self.assertIsNone(publishing.flags_problem(release=True, commit=True, push=True))
        self.assertIsNotNone(publishing.flags_problem(release=False, commit=True, push=False))
        self.assertIsNotNone(publishing.flags_problem(release=True, commit=False, push=True))


if __name__ == "__main__":
    unittest.main()
