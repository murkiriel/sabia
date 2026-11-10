"""A renovação das cópias versionadas (sabia/copies.py, scripts/update_copies.py): as fontes que não respondem aos
executores do GitHub Actions (IBGE malha e municípios, SNV do DNIT, aeródromos da ANAC) baixadas de uma conexão que
as alcança, conferidas e gravadas em gzip, com o sha256 para o config."""
import gzip
import hashlib
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from sabia import anac, config, copies, snv, sources  # noqa: E402
from tests.fake_server import FakeServer  # noqa: E402
from tests.test_anac import aerodrome, write_list  # noqa: E402
from tests.test_prf import unit, write_prf  # noqa: E402
from tests.test_snv import one_per_state, write_snv  # noqa: E402
from tests.test_sources import ERROR_PAGE, fake_mesh, fake_names  # noqa: E402


class WriteCopyTest(unittest.TestCase):
    def test_gzip_without_date_and_the_sha256_of_the_content(self):
        with tempfile.TemporaryDirectory() as tmp:
            a, b = Path(tmp) / "a.gz", Path(tmp) / "b.gz"
            sha = copies.write_copy(b"conteudo", a)
            copies.write_copy(b"conteudo", b)
            self.assertEqual(a.read_bytes(), b.read_bytes())  # sem data no cabeçalho: mesmos bytes
            self.assertEqual(b"\x00\x00\x00\x00", a.read_bytes()[4:8])  # o campo MTIME do gzip
            self.assertEqual(b"conteudo", gzip.decompress(a.read_bytes()))
        self.assertEqual(hashlib.sha256(b"conteudo").hexdigest(), sha)


class RefreshTest(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        tmp = Path(self._tmp.name)
        self.dest = tmp / "copias"
        snv_file, anac_file = tmp / "snv.json", tmp / "anac.json"
        write_snv(snv_file, one_per_state())
        write_list(anac_file, [aerodrome()], copies=3)
        self.server = FakeServer().__enter__()
        prf_file = tmp / "prf.json"
        write_prf(prf_file, [unit()], copies=200)
        self.server.files.update({"/malha": fake_mesh(), "/nomes": fake_names(), "/snv": snv_file.read_bytes(),
                                  "/publicos": anac_file.read_bytes(), "/privados": anac_file.read_bytes(),
                                  "/prf": prf_file.read_bytes()})
        self._patches = [mock.patch.object(config, "RAW", tmp / "raw"),
                         mock.patch.object(config, "IBGE_MESH_URL", self.server.url("/malha")),
                         mock.patch.object(config, "IBGE_NAMES_URL", self.server.url("/nomes")),
                         mock.patch.object(snv, "url", lambda day: self.server.url("/snv")),
                         mock.patch.object(config, "ANAC_PUBLIC_URL", self.server.url("/publicos")),
                         mock.patch.object(config, "ANAC_PRIVATE_URL", self.server.url("/privados")),
                         mock.patch.object(config, "PRF_URL", self.server.url("/prf")),
                         mock.patch.object(config, "MIN_MUNICIPALITIES", 27),
                         mock.patch.object(snv, "MIN_SEGMENTS", 27), mock.patch.object(snv, "MIN_MARKERS", 27),
                         mock.patch.object(anac, "MIN_PUBLIC", 3), mock.patch.object(anac, "MIN_PRIVATE", 3),
                         mock.patch.object(sources, "RETRY_DELAY", 0),
                         mock.patch.object(sources, "IBGE_RETRY_DELAY", 0)]
        for p in self._patches:
            p.start()

    def tearDown(self):
        for p in self._patches:
            p.stop()
        self.server.__exit__(None, None, None)
        self._tmp.cleanup()

    def test_every_copy_is_written_and_checked(self):
        found = copies.refresh(self.dest, "2026-11-10")
        self.assertEqual({"IBGE_MESH_COPY_SHA256", "IBGE_NAMES_COPY_SHA256", "SNV_COPY_SHA256",
                          "ANAC_PUBLIC_COPY_SHA256", "ANAC_PRIVATE_COPY_SHA256", "PRF_COPY_SHA256"}, set(found))
        for name in ("ibge_malha_municipios.json.gz", "ibge_municipios.json.gz", "dnit_snv_marcos.json.gz",
                     "anac_aerodromos_publicos.json.gz", "anac_aerodromos_privados.json.gz", "antt_postos_prf.json.gz"):
            self.assertTrue((self.dest / name).exists(), name)
        body = gzip.decompress((self.dest / "dnit_snv_marcos.json.gz").read_bytes())
        self.assertEqual(hashlib.sha256(body).hexdigest(), found["SNV_COPY_SHA256"])
        marcos = self.dest / "m.json"
        marcos.write_bytes(body)
        self.assertEqual(("202607A", "2026-07-28"), snv.markers_version(marcos))
        self.assertEqual(27 * 3, len(snv.load_markers(marcos)))  # km 10, 11 e 12 em cada UF
        self.assertEqual(fake_mesh(), gzip.decompress((self.dest / "ibge_malha_municipios.json.gz").read_bytes()))

    def test_too_few_markers_writes_nothing(self):
        with mock.patch.object(snv, "MIN_MARKERS", 82), self.assertRaises(RuntimeError) as ctx:
            copies.refresh(self.dest, "2026-11-10")
        self.assertIn("marcos", str(ctx.exception))
        self.assertFalse(list(self.dest.glob("*.gz")))

    def test_a_bad_answer_writes_nothing(self):
        self.server.files["/privados"] = ERROR_PAGE
        with self.assertRaises(RuntimeError):
            copies.refresh(self.dest, "2026-11-10")
        self.assertFalse(list(self.dest.glob("*.gz")))


class StaleTest(unittest.TestCase):
    """O aviso de cópia velha: a geração não trava, mas o relatório e o log do Actions dizem que é hora de renovar."""

    def test_fresh_copies_say_nothing(self):
        self.assertEqual([], copies.stale("2026-11-10"))

    def test_every_copy_older_than_the_limit(self):
        found = copies.stale("2027-06-01")  # 203 dias depois de 2026-11-10
        self.assertEqual(4, len(found), found)  # IBGE, SNV, ANAC e PRF
        for text in found:
            self.assertIn("2026-11-10", text)
            self.assertIn("203 dias", text)
            self.assertIn("scripts/update_copies.py", text)
        self.assertTrue(any("IBGE" in t for t in found))
        self.assertTrue(any("SNV" in t for t in found))
        self.assertTrue(any("ANAC" in t for t in found))
        self.assertTrue(any("PRF" in t for t in found))

    def test_the_limit_is_inclusive(self):
        self.assertEqual(180, copies.STALE_DAYS)
        with mock.patch.multiple(config, IBGE_COPIES_DATE="2026-01-01", SNV_COPY_DATE="2026-11-10",
                                 ANAC_COPIES_DATE="2026-11-10", PRF_COPY_DATE="2026-11-10"):
            self.assertEqual([], copies.stale("2026-06-30"))  # 180 dias
            found = copies.stale("2026-07-01")  # 181
        self.assertEqual(1, len(found))
        self.assertIn("IBGE", found[0])

    def test_config_lines_bring_the_dates(self):
        lines = copies.config_lines({"SNV_COPY_SHA256": "abc"}, "2027-01-05")
        self.assertIn('SNV_COPY_SHA256 = "abc"', lines)
        for constant in ("IBGE_COPIES_DATE", "SNV_COPY_DATE", "ANAC_COPIES_DATE", "PRF_COPY_DATE"):
            self.assertIn(f'{constant} = "2027-01-05"', lines)


if __name__ == "__main__":
    unittest.main()
