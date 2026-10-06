"""O catalogo.json (G8): o índice que quem usa os pacotes lê para saber o que baixar, de onde e como conferir."""
import hashlib
import json
import re
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from sabia import catalog, config, database  # noqa: E402
from tests.osm_builder import MUNICIPALITIES  # noqa: E402

OSM = {"path": "x", "url": "https://download.openstreetmap.fr/extracts/south-america/brazil-latest.osm.pbf",
       "timestamp": "2026-10-05T00:58:57Z", "md5": "93a54bc6b85f5f39abfb43fdc046b1e7", "size": 1}


def packages(folder: Path):
    out: dict = {"build_id": "2026-10-05-93a54bc6", "osm": OSM, "states": {}}
    for name in ("sabia-GO", "sabia-DF", "sabia-base"):
        (folder / f"{name}.sqlite.zst").write_bytes(name.encode() * 100)
    counts = {"items": 10, "place": 2, "street": 5, "road": 1, "poi": 2, "district": 3, "street_line": 7,
              "municipality": 2}
    for uf in ("GO", "DF"):
        out["states"][uf] = {"file": f"sabia-{uf}.sqlite.zst", "bytes": 900, "bytes_db": 5000, "counts": counts}
    out["base"] = {"file": "sabia-base.sqlite.zst", "bytes": 1000, "bytes_db": 4000,
                   "counts": {"municipality": 3, "road": 2, "without_point": []}}
    return out


class CatalogTest(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.dist = Path(self._tmp.name)
        self._patch = mock.patch.object(config, "DIST", self.dist)
        self._patch.start()
        self.cat = catalog.build_catalog(packages(self.dist), MUNICIPALITIES, generator_commit="abc1234")

    def tearDown(self):
        self._patch.stop()
        self._tmp.cleanup()

    def test_header(self):
        c = self.cat
        self.assertEqual(1, c["schema"])
        self.assertEqual(database.FORMAT_VERSION, c["format_version"])
        self.assertEqual("2026-10-05-93a54bc6", c["build_id"])
        self.assertRegex(c["built_at"], r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z$")
        self.assertEqual("abc1234", c["generator_commit"])
        self.assertEqual({"timestamp": OSM["timestamp"], "md5": OSM["md5"], "url": OSM["url"]}, c["osm"])
        self.assertEqual(config.RELEASE_URL.format(tag="2026-10-05-93a54bc6"), c["release_url"])
        self.assertIn("OpenStreetMap", c["attribution"])

    def test_states_with_sha256_bbox_and_counts(self):
        go = self.cat["states"]["GO"]
        self.assertEqual("Goiás", go["name"])
        self.assertEqual("sabia-GO.sqlite.zst", go["file"])
        data = (self.dist / "sabia-GO.sqlite.zst").read_bytes()
        self.assertEqual(len(data), go["bytes"])  # o tamanho é o do arquivo, não o do pacotes.json
        self.assertEqual(hashlib.sha256(data).hexdigest(), go["sha256"])
        self.assertEqual(5000, go["bytes_db"])
        self.assertEqual(5, go["counts"]["street"])
        # Goiânia e Anápolis (as caixas dos testes), arredondado para fora: [lat mín, lng mín, lat máx, lng máx]
        self.assertEqual([-16.9, -49.5, -16.2, -48.8], go["bbox"])
        self.assertEqual(["DF", "GO"], list(self.cat["states"]))

    def test_base(self):
        base = self.cat["base"]
        self.assertEqual("sabia-base.sqlite.zst", base["file"])
        self.assertEqual({"municipality": 3, "road": 2}, base["counts"])
        self.assertEqual([-16.9, -49.5, -15.5, -47.3], base["bbox"])

    def test_bbox_rounds_outward(self):
        self.assertEqual([-16.69, -49.27, -16.6, -49.2], catalog.bbox_of([(-16.681, -49.261, -16.601, -49.201)]))

    def test_saved_as_utf8_with_newline(self):
        dest = self.dist / "catalogo.json"
        catalog.save(self.cat, dest)
        text = dest.read_text(encoding="utf-8")
        self.assertTrue(text.endswith("}\n"))
        self.assertIn("Goiás", text)
        self.assertEqual(self.cat, json.loads(text))
        self.assertIsNone(re.search(r"\\u00", text))


if __name__ == "__main__":
    unittest.main()
