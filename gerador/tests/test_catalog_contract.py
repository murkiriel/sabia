"""O bloco `contract` do catalogo.json: o contrato de catálogo comum v1 (docs/CATALOGO.md).

Confere o formato contra o esquema (docs/catalogo-v1.schema.json), as regras que o esquema não expressa, as URLs
absolutas, os sha256 iguais aos das chaves antigas, a ordem do bbox e o bloco do SQLite amarrado ao config.
"""
import copy
import json
import re
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

GENERATOR_DIR = Path(__file__).resolve().parent.parent
REPO = GENERATOR_DIR.parent
sys.path.insert(0, str(GENERATOR_DIR))
from sabia import catalog, config, conformance, database, validation  # noqa: E402
from sabia.util import file_hash  # noqa: E402
from tests import contract_check  # noqa: E402
from tests.osm_builder import MUNICIPALITIES  # noqa: E402
from tests.test_catalog import OSM, packages  # noqa: E402

DOCS = REPO / "docs"
FULL = "0123456789abcdef0123456789abcdef01234567"


class ContractTestCase(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.dist = Path(self._tmp.name)
        self._patch = mock.patch.object(config, "DIST", self.dist)
        self._patch.start()
        self.cat = self.built()
        self.block = self.cat["contract"]
        self.files = {f["id"]: f for f in self.block["files"]}

    def built(self, **kwargs):
        kwargs.setdefault("generator_commit", FULL[:7])
        kwargs.setdefault("generator_commit_full", FULL)
        return catalog.build_catalog(packages(self.dist), MUNICIPALITIES, **kwargs)

    def tearDown(self):
        self._patch.stop()
        self._tmp.cleanup()

    def legacy(self, file_id):
        return self.cat["base"] if file_id == "base" else self.cat["states"][file_id]


class ContractShapeTest(ContractTestCase):
    def test_valid_against_the_schema_and_the_rules(self):
        self.assertEqual([], contract_check.problems(self.cat, DOCS))

    def test_the_checker_catches_a_broken_block(self):
        broken = copy.deepcopy(self.cat)
        broken["contract"]["files"][0]["bbox"] = [5.28, -74.0, -33.76, -29.29]  # latitude máxima no lugar da mínima
        self.assertTrue(contract_check.problems(broken, DOCS))

    def test_identity_and_versions(self):
        b = self.block
        self.assertEqual(("catalogo-comum", 1, 1, "sabia"), (b["name"], b["version"], b["min_reader_version"],
                                                             b["dataset"]))
        self.assertEqual((self.cat["build_id"], self.cat["built_at"], self.cat["release_url"]),
                         (b["build_id"], b["built_at"], b["release_url"]))
        self.assertEqual({"crs": "EPSG:4326", "bbox_order": "lat_min,lon_min,lat_max,lon_max"}, b["coordinates"])

    def test_generator_full_commit_and_licences(self):
        self.assertEqual({"repository": config.REPOSITORY_URL, "commit": FULL}, self.block["generator"])
        self.assertEqual(FULL[:7], self.cat["generator_commit"])
        self.assertEqual({"data": "ODbL-1.0", "code": "MIT", "attribution": config.ATTRIBUTION}, self.block["license"])
        self.assertIn("Open Database License", (REPO / "LICENSE").read_text(encoding="utf-8"))
        self.assertTrue((GENERATOR_DIR / "LICENSE").read_text(encoding="utf-8").startswith("MIT License"))

    def test_a_commit_that_is_not_the_catalog_one_is_refused(self):
        with self.assertRaises(ValueError):
            self.built(generator_commit="abc1234", generator_commit_full=FULL)

    def test_full_commit_from_the_checkout(self):
        sha = catalog.git_commit_full()
        self.assertTrue(sha is None or re.fullmatch(r"[0-9a-f]{40}", sha), sha)

    def test_sources_with_dates_and_checksums(self):
        sources = {s["id"]: s for s in self.block["sources"]}
        self.assertEqual({"md5": OSM["md5"]}, sources["openstreetmap"]["checksums"])
        self.assertEqual({"date": OSM["timestamp"], "md5": OSM["md5"]}, self.block["osm_snapshot"])
        expected = {"ibge-malha-municipios": config.IBGE_MESH_COPY_SHA256,
                    "ibge-municipios": config.IBGE_NAMES_COPY_SHA256, "dnit-snv-marcos": config.SNV_COPY_SHA256,
                    "anac-aerodromos-publicos": config.ANAC_PUBLIC_COPY_SHA256,
                    "anac-aerodromos-privados": config.ANAC_PRIVATE_COPY_SHA256,
                    "antt-postos-prf": config.PRF_COPY_SHA256}
        for source_id, sha in expected.items():
            self.assertEqual({"sha256": sha}, sources[source_id]["checksums"], source_id)
        self.assertEqual(config.IBGE_COPIES_DATE, sources["ibge-malha-municipios"]["date"])
        self.assertEqual(config.ANAC_PUBLIC_URL, sources["anac-aerodromos-publicos"]["url"])


class ContractFilesTest(ContractTestCase):
    def test_one_file_per_package(self):
        self.assertEqual({"base", *self.cat["states"]}, set(self.files))

    def test_absolute_urls_are_release_url_plus_file(self):
        for file_id, f in self.files.items():
            self.assertTrue(f["url"].startswith("https://"), f["url"])
            self.assertEqual(self.cat["release_url"] + self.legacy(file_id)["file"], f["url"])

    def test_sha256_and_sizes_are_the_legacy_ones(self):
        for file_id, f in self.files.items():
            old = self.legacy(file_id)
            self.assertEqual((old["sha256"], old["bytes"], old["bytes_db"]), (f["sha256"], f["bytes"], f["bytes_unpacked"]))

    def test_bbox_is_the_legacy_one_latitude_first(self):
        for file_id, f in self.files.items():
            lat_min, lon_min, lat_max, lon_max = f["bbox"]
            self.assertEqual(self.legacy(file_id)["bbox"], f["bbox"])
            self.assertTrue(-35 <= lat_min < lat_max <= 7 and -77 <= lon_min < lon_max <= -28, f["bbox"])

    def test_states_stand_alone_and_the_base_links(self):
        self.assertEqual(("base", "BR", "BASE_HIGHWAYS_ONLY", []),
                         tuple(self.files["base"][k] for k in ("kind", "region", "coverage_level", "requires")))
        self.assertEqual(("uf", "GO", "DETAILED", []),
                         tuple(self.files["GO"][k] for k in ("kind", "region", "coverage_level", "requires")))

    def test_format_and_unpacking(self):
        for f in self.files.values():
            self.assertEqual(("sqlite", "application/zstd", ["zstd"]), (f["format"], f["media_type"], f["unpack"]))
            self.assertTrue(f["url"].endswith(".sqlite.zst"))


class SqliteCompatibilityTest(ContractTestCase):
    def test_block_equals_the_config_and_the_database_format(self):
        compat = self.block["compatibility"]
        sabia = compat["sabia"]
        self.assertTrue(compat["mix_generations"])
        self.assertEqual({"name": "sabia-sqlite", "version": str(database.FORMAT_VERSION)}, compat["data_format"])
        self.assertEqual(database.FORMAT_VERSION, sabia["format_version"])
        self.assertEqual(self.cat["format_version"], sabia["format_version"])
        self.assertEqual(("3.22.0", ["fts4"], ["fts5", "rtree"]),
                         (sabia["sqlite_min_version"], sabia["sqlite_modules"], sabia["sqlite_not_used"]))

    def test_the_sqlite_floor_is_the_one_the_gate_installs(self):
        script = (GENERATOR_DIR / "scripts" / "install_sqlite.py").read_text(encoding="utf-8")
        major, minor, patch = (int(x) for x in config.SQLITE_MIN_VERSION.split("."))
        self.assertIn(f"sqlite-amalgamation-{major}{minor:02d}{patch:02d}00.zip", script)
        self.assertIn("-DSQLITE_ENABLE_FTS4", script)
        self.assertNotIn("FTS5", script.split("CFLAGS", 1)[1].splitlines()[0])

    def test_the_databases_use_none_of_what_the_floor_lacks(self):
        for module in config.SQLITE_NOT_USED:
            self.assertIn(module, validation.NEWER_FEATURES)
        schema = "\n".join(value for name, value in vars(database).items()
                           if name.isupper() and isinstance(value, str)).lower()
        self.assertIn("using fts4", schema)
        for module in config.SQLITE_NOT_USED:
            self.assertNotIn(f"using {module}", schema)

    def test_spec_links_are_pinned_to_the_commit_and_exist(self):
        sabia = self.block["compatibility"]["sabia"]
        for key, path in (("format_spec", catalog.FORMAT_SPEC), ("search_spec", catalog.SEARCH_SPEC),
                          ("search_reference", catalog.SEARCH_REFERENCE)):
            self.assertEqual(f"{config.REPOSITORY_URL}/blob/{FULL}/{path}", sabia[key])
            self.assertTrue((REPO / path.split("#")[0]).exists(), path)
        self.assertIn("\n## Buscar\n", (REPO / "docs" / "CONSUMO.md").read_text(encoding="utf-8"))


class ConformanceFileTest(ContractTestCase):
    """O conjunto de conformidade da busca (docs/CONFORMIDADE.md) na chave `conformance` e em `files`."""

    def write_set(self, build_id="2026-10-05-93a54bc6", format_version=database.FORMAT_VERSION):
        doc = {"conformance_version": conformance.CONFORMANCE_VERSION, "build_id": build_id,
               "format_version": format_version, "unit": [{"fn": "fold"}, {"fn": "fold"}],
               "search": [{"type": "nome", "db": "GO"}], "which_street": [{"db": "GO"}]}
        conformance.save(doc, self.dist / conformance.FILE)

    def test_without_the_set_nothing_changes(self):
        self.assertNotIn("conformance", self.cat)
        self.assertNotIn("conformidade", self.files)
        self.assertNotIn("conformance_spec", self.block["compatibility"]["sabia"])

    def test_the_set_of_this_generation_is_listed(self):
        self.write_set()
        cat = self.built()
        path = self.dist / conformance.FILE
        self.assertEqual({"file": conformance.FILE, "bytes": path.stat().st_size, "sha256": file_hash(path),
                          "bytes_unpacked": len(conformance.dumps(conformance.load(path), pretty=False)),
                          "conformance_version": 1, "cases": {"unit": 2, "search": 1, "which_street": 1}},
                         cat["conformance"])
        f = {f["id"]: f for f in cat["contract"]["files"]}["conformidade"]
        self.assertEqual(("conformance", None, None, None, [], "sabia-search-cases", ["zstd"]),
                         (f["kind"], f["region"], f["bbox"], f["coverage_level"], f["requires"], f["format"],
                          f["unpack"]))
        self.assertEqual((cat["release_url"] + conformance.FILE, cat["conformance"]["sha256"],
                          cat["conformance"]["bytes"], 1),
                         (f["url"], f["sha256"], f["bytes"], f["conformance_version"]))
        sabia = cat["contract"]["compatibility"]["sabia"]
        self.assertEqual(1, sabia["conformance_version"])
        self.assertEqual(f"{config.REPOSITORY_URL}/blob/{FULL}/{catalog.CONFORMANCE_SPEC}", sabia["conformance_spec"])
        self.assertTrue((REPO / catalog.CONFORMANCE_SPEC).exists())
        self.assertEqual([], contract_check.problems(cat, DOCS))

    def test_a_set_of_another_generation_or_format_stays_out(self):
        for kwargs in ({"build_id": "2026-09-01-00000000"}, {"format_version": database.FORMAT_VERSION + 1}):
            self.write_set(**kwargs)
            cat = self.built()
            self.assertNotIn("conformance", cat)
            self.assertNotIn("conformidade", {f["id"] for f in cat["contract"]["files"]})

    def test_the_set_is_one_of_the_release_files(self):
        from sabia import publishing
        self.assertIn(conformance.FILE, publishing.release_files(self.cat))


class OnlyAddsTest(ContractTestCase):
    def test_the_old_keys_are_untouched(self):
        self.assertEqual({"schema", "format_version", "build_id", "built_at", "generator_commit", "osm", "release_url",
                          "attribution", "base", "states", "contract"}, set(self.cat))
        self.assertEqual(1, self.cat["schema"])


class SharedDocumentsTest(unittest.TestCase):
    def test_spec_and_schema_are_the_shared_ones(self):
        self.assertEqual({}, contract_check.doc_mismatches(DOCS))

    def test_the_readme_points_to_the_spec(self):
        self.assertIn("docs/CATALOGO.md", (REPO / "README.md").read_text(encoding="utf-8"))


class RecatalogTest(unittest.TestCase):
    """scripts/recatalog.py sobre o catálogo publicado na raiz: só acrescenta `contract`."""

    def setUp(self):
        sys.path.insert(0, str(GENERATOR_DIR / "scripts"))

    def test_rebuilds_the_published_catalog(self):
        published = json.loads((REPO / "catalogo.json").read_text(encoding="utf-8"))
        if catalog.git_commit_full(published["generator_commit"]) is None:
            self.skipTest("o commit da geração publicada não está neste checkout (clone raso)")
        import recatalog  # noqa: E402
        out = recatalog.rebuild(published)
        self.assertEqual({k: v for k, v in published.items() if k != "contract"},
                         {k: v for k, v in out.items() if k != "contract"})
        self.assertEqual([], contract_check.problems(out, DOCS))
        self.assertEqual(len(published["states"]) + 1, len(out["contract"]["files"]))

    def test_constants_are_read_without_running_the_file(self):
        import recatalog  # noqa: E402
        head = subprocess.run(["git", "-C", str(REPO), "rev-parse", "HEAD"], capture_output=True, text=True)
        if head.returncode != 0:
            self.skipTest("sem git")
        found = recatalog.constants_at(head.stdout.strip(), ["GITHUB_REPO", "ANAC_PUBLIC_URL", "NAO_EXISTE"])
        self.assertEqual({"ANAC_PUBLIC_URL"}, set(found))  # GITHUB_REPO vem do ambiente: não é literal
        self.assertEqual(config.ANAC_PUBLIC_URL, found["ANAC_PUBLIC_URL"])


if __name__ == "__main__":
    unittest.main()
