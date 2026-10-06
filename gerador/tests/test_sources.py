"""As fontes: o extrato do OpenStreetMap (baixado ou local) e os municípios do IBGE (malha e nomes)."""
import contextlib
import hashlib
import io
import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

import osmium

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from sabia import config, sources  # noqa: E402
from tests.fake_server import FakeServer  # noqa: E402

ERROR_PAGE = b"<html><body>Servico indisponivel</body></html>"
A = b"extrato versao A " * 5000
B = b"extrato versao B, mais nova " * 5000


def md5(b: bytes) -> str:
    return hashlib.md5(b).hexdigest()


class ExtractTest(unittest.TestCase):
    """sources.osm_extract contra uma imitação local do openstreetmap.fr (state.txt, .md5 e o .pbf)."""

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.raw = Path(self._tmp.name)
        self.current = [A]  # o arquivo publicado agora
        self.server = FakeServer().__enter__()
        s = self.server
        s.files["/state.txt"] = lambda: b"sequenceNumber=1\ntimestamp=2026-09-29T00\\:59\\:51Z\n"
        s.files["/x.md5"] = lambda: f"{md5(self.current[0])}  brazil.osm.pbf\n".encode()
        s.files["/x.pbf"] = lambda: self.current[0]
        self._patches = [mock.patch.object(config, "RAW", self.raw),
                         mock.patch.object(config, "OSM_STATE_URL", s.url("/state.txt")),
                         mock.patch.object(config, "OSM_MD5_URL", s.url("/x.md5")),
                         mock.patch.object(config, "OSM_PBF_URL", s.url("/x.pbf")),
                         mock.patch.object(sources, "RETRY_DELAY", 0)]
        for p in self._patches:
            p.start()

    def tearDown(self):
        for p in self._patches:
            p.stop()
        self.server.__exit__(None, None, None)
        self._tmp.cleanup()

    def downloads(self):
        return sum(1 for path, _ in self.server.requests if path == "/x.pbf")

    def test_downloads_and_saves_meta_with_size(self):
        meta = sources.osm_extract()
        self.assertEqual(A, (self.raw / "brazil-latest.osm.pbf").read_bytes())
        self.assertEqual(md5(A), meta["md5"])
        self.assertEqual("2026-09-29T00:59:51Z", meta["timestamp"])
        self.assertEqual(self.server.url("/x.pbf"), meta["url"])
        self.assertEqual(len(A), json.loads((self.raw / "brazil-latest.meta.json").read_text())["size"])

    def test_does_not_download_again_when_up_to_date(self):
        sources.osm_extract()
        sources.osm_extract()
        self.assertEqual(1, self.downloads())

    def test_extract_updated_during_download(self):
        def switch_and_serve():
            self.current[0] = B
            return B
        self.server.files["/x.pbf"] = switch_and_serve
        meta = sources.osm_extract()
        self.assertEqual(md5(B), meta["md5"])
        self.assertEqual(B, (self.raw / "brazil-latest.osm.pbf").read_bytes())

    def test_corrupted_file_fails_and_is_removed(self):
        self.server.files["/x.pbf"] = lambda: A[:-10] + b"corrompido"
        with self.assertRaises(RuntimeError):
            sources.osm_extract()
        self.assertFalse((self.raw / "brazil-latest.osm.pbf").exists())

    def test_truncated_local_extract_is_downloaded_again(self):
        sources.osm_extract()
        pbf = self.raw / "brazil-latest.osm.pbf"
        pbf.write_bytes(A[:1000])  # o meta diz que está tudo certo, mas o arquivo encolheu
        sources.osm_extract()
        self.assertEqual(A, pbf.read_bytes())
        self.assertEqual(2, self.downloads())


def write_pbf(path: Path, timestamp=None):
    header = osmium.io.Header()
    if timestamp:
        header.set("osmosis_replication_timestamp", timestamp)
    w = osmium.SimpleWriter(str(path), header=header, overwrite=True)
    w.add_node(osmium.osm.mutable.Node(id=1, location=(-47.9, -15.8), tags={"place": "city", "name": "Brasília"}))
    w.close()


class LocalExtractTest(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.pbf = Path(self._tmp.name) / "regiao.osm.pbf"

    def tearDown(self):
        self._tmp.cleanup()

    def test_timestamp_from_header_and_md5_of_the_file(self):
        write_pbf(self.pbf, "2026-09-29T20:22:51Z")
        meta = sources.local_extract(self.pbf)
        self.assertEqual("2026-09-29T20:22:51Z", meta["timestamp"])
        self.assertEqual(hashlib.md5(self.pbf.read_bytes()).hexdigest(), meta["md5"])
        self.assertEqual(self.pbf.stat().st_size, meta["size"])
        self.assertEqual(str(self.pbf), meta["path"])
        self.assertEqual("local", meta["url"])  # um catálogo de extrato local não aponta para lugar nenhum

    def test_extract_without_date_is_refused(self):
        write_pbf(self.pbf)
        with self.assertRaises(RuntimeError) as ctx:
            sources.local_extract(self.pbf)
        self.assertIn("data", str(ctx.exception))


def fake_mesh(exclude=(), extra=()):
    """GeoJSON no formato da API de malhas do IBGE: aqui, um município por UF (código da UF + '00001')."""
    features = [{"type": "Feature", "properties": {"codarea": code + "00001"},
                 "geometry": {"type": "Polygon", "coordinates": [[[i, 0], [i + 1, 0], [i + 1, 1], [i, 0]]]}}
                for i, code in enumerate(config.IBGE_STATE_CODES) if code not in exclude]
    features += [{"type": "Feature", "properties": {"codarea": c}, "geometry": None} for c in extra]
    return json.dumps({"type": "FeatureCollection", "features": features}).encode()


def fake_names(exclude=(), extra=()):
    """Lista no formato da API de localidades do IBGE (view=nivelado), um município por UF."""
    rows = [{"municipio-id": int(code + "00001"), "municipio-nome": f"Município {uf}", "UF-sigla": uf}
            for code, uf in config.IBGE_STATE_CODES.items() if code not in exclude]
    rows += [{"municipio-id": int(c), "municipio-nome": "Novo", "UF-sigla": config.IBGE_STATE_CODES[c[:2]]}
             for c in extra]
    return json.dumps(rows, ensure_ascii=False).encode()


class IbgeTest(unittest.TestCase):
    """Malha municipal e nomes: só grava (e só aceita do cache) um arquivo com o país inteiro."""

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.raw = Path(self._tmp.name)
        self.server = FakeServer().__enter__()
        self.server.files["/malha"] = fake_mesh()
        self.server.files["/nomes"] = fake_names()
        self._patches = [mock.patch.object(config, "RAW", self.raw),
                         mock.patch.object(config, "IBGE_MESH_URL", self.server.url("/malha")),
                         mock.patch.object(config, "IBGE_NAMES_URL", self.server.url("/nomes")),
                         mock.patch.object(config, "MIN_MUNICIPALITIES", 27),
                         mock.patch.object(sources, "RETRY_DELAY", 0),
                         mock.patch.object(sources, "IBGE_RETRY_DELAY", 0)]
        for p in self._patches:
            p.start()

    def tearDown(self):
        for p in self._patches:
            p.stop()
        self.server.__exit__(None, None, None)
        self._tmp.cleanup()

    def downloads(self, path):
        return sum(1 for p, _ in self.server.requests if p == path)

    def test_good_files_are_saved(self):
        mesh = sources.municipal_mesh()
        names = sources.municipality_names()
        self.assertEqual(27, len(json.loads(mesh.read_text(encoding="utf-8"))["features"]))
        self.assertEqual(27, len(json.loads(names.read_text(encoding="utf-8"))))

    def test_error_page_with_200_is_not_saved(self):
        """Nunca com o nome final; o corpo de cada tentativa fica em <nome>.<tentativa>.invalido, para o artefato."""
        self.server.files["/malha"] = ERROR_PAGE
        with self.assertRaises(RuntimeError):
            sources.municipal_mesh()
        self.assertFalse((self.raw / sources.MESH_FILE).exists())
        self.assertEqual([f"{sources.MESH_FILE}.{i}.invalido" for i in (1, 2, 3)],
                         sorted(p.name for p in self.raw.iterdir()))
        self.assertEqual(ERROR_PAGE, (self.raw / f"{sources.MESH_FILE}.1.invalido").read_bytes())

    def test_invalid_content_is_retried_until_valid(self):
        answers = [ERROR_PAGE, fake_mesh()]
        self.server.files["/malha"] = lambda: answers.pop(0) if len(answers) > 1 else answers[0]
        mesh = sources.municipal_mesh()
        self.assertEqual(2, self.downloads("/malha"))
        self.assertIsNone(sources.mesh_problem(mesh))
        self.assertEqual(ERROR_PAGE, (self.raw / f"{sources.MESH_FILE}.1.invalido").read_bytes())

    def test_gives_up_after_three_attempts(self):
        self.server.files["/nomes"] = b""
        with self.assertRaises(RuntimeError) as ctx:
            sources.municipality_names()
        self.assertEqual(3, self.downloads("/nomes"))
        self.assertIn("3 tentativas", str(ctx.exception))

    def test_invalid_content_is_logged_with_status_type_and_body_start(self):
        self.server.files["/malha"] = ERROR_PAGE
        self.server.content_type["/malha"] = "text/html; charset=utf-8"
        out = io.StringIO()
        with contextlib.redirect_stdout(out), self.assertRaises(RuntimeError):
            sources.municipal_mesh()
        log = out.getvalue()
        self.assertIn("HTTP 200", log)
        self.assertIn("text/html; charset=utf-8", log)
        self.assertIn(f"{len(ERROR_PAGE)} bytes", log)
        self.assertIn("Servico indisponivel", log)
        self.assertIn("tentativa 1 de 3", log)

    def test_waits_longer_after_each_invalid_attempt(self):
        self.server.files["/malha"] = ERROR_PAGE
        with mock.patch.object(sources, "IBGE_RETRY_DELAY", 7), mock.patch.object(sources.time, "sleep") as sleep:
            with self.assertRaises(RuntimeError):
                sources.municipal_mesh()
        self.assertEqual([mock.call(7), mock.call(14)], sleep.call_args_list)

    def test_bad_status_is_retried_and_logged(self):
        """Um 403 (o IBGE recusando o executor, por exemplo) também é tentado de novo, e o log diz o status."""
        self.server.codes["/malha"] = [403]
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            mesh = sources.municipal_mesh()
        self.assertIsNone(sources.mesh_problem(mesh))
        self.assertEqual(2, self.downloads("/malha"))
        self.assertIn("HTTP 403", out.getvalue())

    def test_mesh_missing_a_state_is_rejected(self):
        self.server.files["/malha"] = fake_mesh(exclude=("53",))
        with self.assertRaises(RuntimeError) as ctx:
            sources.municipal_mesh()
        self.assertIn("DF", str(ctx.exception))

    def test_too_few_municipalities_is_rejected(self):
        with mock.patch.object(config, "MIN_MUNICIPALITIES", 5570):
            with self.assertRaises(RuntimeError) as ctx:
                sources.municipality_names()
        self.assertIn("5570", str(ctx.exception))

    def test_names_missing_a_state_is_rejected(self):
        self.server.files["/nomes"] = fake_names(exclude=("52",))
        with self.assertRaises(RuntimeError) as ctx:
            sources.municipality_names()
        self.assertIn("GO", str(ctx.exception))

    def test_valid_cache_does_not_download_and_invalid_is_replaced(self):
        sources.municipal_mesh()
        sources.municipal_mesh()
        self.assertEqual(1, self.downloads("/malha"))
        (self.raw / "ibge_malha_municipios.json").write_text("<html>erro</html>", encoding="utf-8")
        sources.municipal_mesh()
        self.assertEqual(2, self.downloads("/malha"))
        kept = self.raw / "ibge_malha_municipios.json.guardado.invalido"
        self.assertEqual("<html>erro</html>", kept.read_text(encoding="utf-8"))

    def test_load_municipalities_joins_names_and_mesh(self):
        """O nome e a UF vêm da lista de nomes (a fonte dos municípios); o polígono, da malha. Município novo que a
        malha ainda não tem fica sem polígono, e nunca some."""
        self.server.files["/nomes"] = fake_names(extra=("5101837",))
        found = {m.code: m for m in sources.load_municipalities(sources.municipal_mesh(),
                                                                 sources.municipality_names())}
        self.assertEqual(28, len(found))
        go = found["5200001"]
        self.assertEqual(("Município GO", "GO"), (go.name, go.uf))
        self.assertTrue(go.geometry.is_valid and go.geometry.area > 0)
        self.assertIsNone(found["5101837"].geometry)
        self.assertEqual("MT", found["5101837"].uf)


if __name__ == "__main__":
    unittest.main()
