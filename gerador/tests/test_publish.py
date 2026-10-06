"""As travas da publicação (publishing.check) e a tabela "Baixar por estado" do README."""
import json
import sys
import tempfile
import unicodedata
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from sabia import catalog, config, publishing  # noqa: E402
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
