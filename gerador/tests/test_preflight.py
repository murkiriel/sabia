"""A sonda de pré-voo (sabia/preflight.py, scripts/preflight.py), contra um servidor HTTP local: NENHUM teste aqui
acessa a internet."""
import ast
import contextlib
import importlib.util
import io
import sys
import unittest
from pathlib import Path
from unittest import mock

GENERATOR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(GENERATOR))
from sabia import config, preflight  # noqa: E402
from tests.fake_server import FakeServer  # noqa: E402


class ProbeTest(unittest.TestCase):
    def setUp(self):
        self.server = FakeServer()
        self.server.__enter__()
        self.addCleanup(self.server.__exit__, None, None, None)

    def probe(self, path, **kwargs):
        return preflight.probe(self.server.url(path), timeout=5, pause=0, **{"attempts": 3, **kwargs})

    def test_answer_ok_asks_for_one_byte_only(self):
        self.server.files["/a"] = b"x" * 100_000
        ok, what = self.probe("/a")
        self.assertTrue(ok, what)
        self.assertIn("HTTP 206", what)
        self.assertEqual([("/a", "bytes=0-0")], self.server.requests)

    def test_site_that_ignores_the_range_still_answers(self):
        self.server.files["/a"] = b"x" * 100_000
        self.server.no_range.add("/a")
        ok, what = self.probe("/a")
        self.assertTrue(ok, what)
        self.assertIn("HTTP 200", what)

    def test_error_status_is_retried_and_reported(self):
        self.server.code["/a"] = 403
        ok, what = self.probe("/a")
        self.assertFalse(ok)
        self.assertEqual("HTTP 403 (3 tentativas)", what)
        self.assertEqual(3, len(self.server.requests))

    def test_a_passing_5xx_does_not_fail_the_probe(self):
        """Um 502 solto (o openstreetmap.fr deu um em 2026-11-23) não é fonte fora do ar."""
        self.server.files["/a"] = b"x"
        self.server.codes["/a"] = [502]
        ok, what = self.probe("/a")
        self.assertTrue(ok, what)
        self.assertEqual(2, len(self.server.requests))

    def test_nothing_listening_is_reported(self):
        with FakeServer() as dead:
            url = dead.url("/a")
        ok, what = preflight.probe(url, timeout=2, attempts=2, pause=0)
        self.assertFalse(ok)
        self.assertIn("2 tentativas", what)
        self.assertIn("URLError", what)

    def test_timeout_is_reported(self):
        def slow(req, timeout):
            raise TimeoutError("timed out")
        ok, what = preflight.probe("http://exemplo/a", attempts=2, pause=0, opener=slow)
        self.assertFalse(ok)
        self.assertEqual("TimeoutError: timed out (2 tentativas)", what)

    def test_waits_longer_after_each_failure(self):
        with mock.patch.object(preflight.time, "sleep") as sleep:
            preflight.probe(self.server.url("/nada"), timeout=5, attempts=3, pause=4)
        self.assertEqual([mock.call(4), mock.call(8)], sleep.call_args_list)


class CheckTest(unittest.TestCase):
    def test_lists_every_source_and_only_the_failures(self):
        with FakeServer() as server:
            server.files["/bom"] = b"x"
            found = [preflight.Source("Bom", server.url("/bom")), preflight.Source("Ruim", server.url("/ruim"))]
            lines, failed = preflight.check(found, timeout=5, attempts=1, pause=0)
        self.assertEqual(2, len(lines))
        self.assertTrue(lines[0].startswith("ok   Bom: HTTP 206"))
        self.assertTrue(lines[1].startswith("FALHA Ruim: HTTP 404"))
        self.assertEqual(["Ruim (HTTP 404 (1 tentativas))"], failed)

    def test_all_fine_has_no_failures(self):
        with FakeServer() as server:
            server.files["/bom"] = b"x"
            lines, failed = preflight.check([preflight.Source("Bom", server.url("/bom"))], timeout=5, attempts=1)
        self.assertEqual([], failed)
        self.assertEqual(1, len(lines))


class SourcesTest(unittest.TestCase):
    def urls(self, **kwargs):
        return [s.url for s in preflight.sources(**kwargs)]

    def test_the_live_sources_and_the_osm(self):
        urls = self.urls()
        self.assertEqual(10, len(urls))
        for url in (config.OSM_STATE_URL, config.OSM_PBF_URL, config.IBGE_LOCALITIES_URL, config.CNES_URL,
                    config.OVERTURE_LISTING_URL, config.GEONAMES_PLACES_URL, config.GEONAMES_NAMES_URL):
            self.assertIn(url, urls)
        self.assertTrue(any(u.startswith(config.WIKIDATA_SPARQL_URL) for u in urls))
        self.assertTrue(any(u.startswith(config.ANP_API_URL) for u in urls))
        self.assertTrue(any(u.startswith(config.CNEFE_UF_URL) for u in urls))

    def test_versioned_copies_are_not_probed(self):
        urls = self.urls()
        for url in (config.IBGE_MESH_URL, config.IBGE_NAMES_URL, config.PRF_URL, config.SNV_WFS_URL,
                    config.ANAC_PUBLIC_URL, config.ANAC_PRIVATE_URL):
            self.assertNotIn(url, urls)

    def test_local_extract_drops_the_osm(self):
        urls = self.urls(osm_local=True)
        self.assertEqual(8, len(urls))
        self.assertFalse([u for u in urls if "openstreetmap" in u])

    def test_cnefe_is_the_first_requested_state(self):
        def cnefe(**kwargs):
            return [u for u in self.urls(**kwargs) if u.startswith(config.CNEFE_UF_URL)]
        self.assertEqual([config.CNEFE_UF_URL + "53_DF.zip"], cnefe(states=["GO", "DF"]))
        self.assertEqual([config.CNEFE_UF_URL + "12_AC.zip"], cnefe())

    def test_wikidata_probe_is_a_trivial_query_not_the_tourism_one(self):
        self.assertIn("ASK", preflight.WIKIDATA_PROBE)
        self.assertNotIn("wdt", preflight.WIKIDATA_PROBE)

    def test_only_the_stdlib_and_the_config(self):
        """O passo roda no python3 da máquina, antes de instalar as dependências."""
        tree = ast.parse((GENERATOR / "sabia" / "preflight.py").read_text(encoding="utf-8"))
        modules = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                modules |= {a.name.split(".")[0] for a in node.names}
            elif isinstance(node, ast.ImportFrom) and node.level == 0:
                modules.add((node.module or "").split(".")[0])
            elif isinstance(node, ast.ImportFrom):
                self.assertEqual("config", node.names[0].name)
        self.assertLessEqual(modules, set(sys.stdlib_module_names))


class FailingDownloadTimeTest(unittest.TestCase):
    """Uma fonte que não responde custava ~40 min por geração (5 conexões de 120 s, 3 rodadas, esperas de 60 e 120 s);
    agora, ~10 (3 conexões de 45 s, 3 rodadas, esperas de 30 e 60 s)."""

    def test_worst_case_is_about_ten_minutes(self):
        from sabia import net, sources
        self.assertEqual((3, 45, 3, 30), (sources.DOWNLOAD_ATTEMPTS, sources.DOWNLOAD_TIMEOUT, sources.IBGE_ATTEMPTS,
                                          sources.IBGE_RETRY_DELAY))
        connection = sources.DOWNLOAD_ATTEMPTS * sources.DOWNLOAD_TIMEOUT + sum(
            sources.RETRY_DELAY * a for a in range(1, sources.DOWNLOAD_ATTEMPTS))
        rounds = sources.IBGE_ATTEMPTS * connection + sum(
            sources.IBGE_RETRY_DELAY * a for a in range(1, sources.IBGE_ATTEMPTS))
        self.assertLessEqual(rounds, 11 * 60)
        self.assertGreater(net.download.__defaults__[1], sources.DOWNLOAD_ATTEMPTS)  # o padrão do net não mudou

    def test_checked_download_uses_the_short_limits(self):
        import tempfile
        from sabia import net, sources
        with tempfile.TemporaryDirectory() as tmp, \
                mock.patch.object(config, "RAW", Path(tmp)), \
                mock.patch.object(sources, "IBGE_RETRY_DELAY", 0), \
                mock.patch.object(sources.net, "download", side_effect=net.DownloadError("timed out")) as download:
            with self.assertRaises(RuntimeError):
                sources._checked_download("http://exemplo/a", "a.json", lambda p: None, "a fonte")
        self.assertEqual(sources.IBGE_ATTEMPTS, download.call_count)
        for call in download.call_args_list:
            self.assertEqual((3, 45), (call.kwargs["attempts"], call.kwargs["timeout"]))


def load_script():
    spec = importlib.util.spec_from_file_location("preflight_script", GENERATOR / "scripts" / "preflight.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class ScriptTest(unittest.TestCase):
    def run_script(self, *argv, result):
        script = load_script()
        out = io.StringIO()
        with mock.patch.object(preflight, "check", return_value=result), contextlib.redirect_stdout(out):
            script.main(list(argv))
        return out.getvalue()

    def test_all_answered(self):
        out = self.run_script(result=(["ok   A"], []))
        self.assertIn("ok   A", out)
        self.assertIn("10 fontes responderam.", out)

    def test_failure_exits_listing_what_did_not_answer(self):
        with self.assertRaises(SystemExit) as cm:
            self.run_script(result=(["FALHA A", "FALHA B"], ["A (HTTP 403)", "B (timed out)"]))
        self.assertEqual("2 de 10 fontes não responderam: A (HTTP 403); B (timed out)", str(cm.exception))

    def test_unknown_state_is_refused(self):
        with self.assertRaises(SystemExit), contextlib.redirect_stderr(io.StringIO()):
            self.run_script("--states", "XX", result=([], []))


if __name__ == "__main__":
    unittest.main()
