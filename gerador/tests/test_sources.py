"""As fontes: o extrato do OpenStreetMap (baixado ou local) e os municípios do IBGE (malha e nomes)."""
import contextlib
import gzip
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


def mesh_download() -> Path:
    """O download conferido de um arquivo do IBGE (o mesmo das outras fontes), pela URL da malha: a malha e a lista de
    municípios vêm das cópias versionadas desde 2026-11-10, mas a conferência do download segue valendo para trocar
    as cópias e para as outras fontes."""
    return sources._checked_download(config.IBGE_MESH_URL, sources.MESH_FILE, sources.mesh_problem,
                                     "a malha municipal")


def names_download() -> Path:
    return sources._checked_download(config.IBGE_NAMES_URL, sources.NAMES_FILE, sources.names_problem,
                                     "a lista de municípios")


def write_copy(path: Path, body: bytes) -> str:
    """Grava `body` como cópia versionada (gzip) e devolve o sha256 do conteúdo."""
    path.write_bytes(gzip.compress(body, mtime=0))
    return hashlib.sha256(body).hexdigest()


class VersionedIbgeTest(unittest.TestCase):
    """A malha municipal e a lista de municípios vêm das cópias versionadas no repositório (gzip), conferidas pelo
    sha256 do conteúdo e pelo país inteiro, sem nenhum acesso à rede.

    De 2026-11-04 a 2026-11-09 todas as gerações agendadas caíram no download da malha: a API do IBGE não respondia
    aos executores do GitHub Actions (timeout nas 5 tentativas). Da mesma URL, numa conexão no Brasil, ~1,6 s."""

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        tmp = Path(self._tmp.name)
        self.raw = tmp / "raw"
        self.mesh_copy = tmp / "ibge_malha_municipios.json.gz"
        self.names_copy = tmp / "ibge_municipios.json.gz"
        self.mesh_body, self.names_body = fake_mesh(), fake_names()
        self._patches = [mock.patch.object(config, "RAW", self.raw),
                         mock.patch.object(config, "IBGE_MESH_COPY", self.mesh_copy),
                         mock.patch.object(config, "IBGE_MESH_COPY_SHA256", write_copy(self.mesh_copy, self.mesh_body)),
                         mock.patch.object(config, "IBGE_NAMES_COPY", self.names_copy),
                         mock.patch.object(config, "IBGE_NAMES_COPY_SHA256",
                                           write_copy(self.names_copy, self.names_body)),
                         mock.patch.object(config, "MIN_MUNICIPALITIES", 27),
                         mock.patch.object(sources.net, "download", side_effect=AssertionError("foi à rede"))]
        for p in self._patches:
            p.start()

    def tearDown(self):
        for p in self._patches:
            p.stop()
        self._tmp.cleanup()

    def test_the_copies_are_used_without_the_network(self):
        mesh, names = sources.municipal_mesh(), sources.municipality_names()
        self.assertEqual((self.raw / sources.MESH_FILE, self.raw / sources.NAMES_FILE), (mesh, names))
        self.assertEqual(self.mesh_body, mesh.read_bytes())
        self.assertEqual(self.names_body, names.read_bytes())

    def test_a_changed_copy_is_refused(self):
        """Uma malha nova muda o município de muitos registros: trocar a cópia é feito à mão, com o sha256 novo."""
        write_copy(self.mesh_copy, fake_mesh(extra=("5101837",)))
        with self.assertRaises(RuntimeError) as ctx:
            sources.municipal_mesh()
        self.assertIn("IBGE_MESH_COPY_SHA256", str(ctx.exception))
        self.assertFalse((self.raw / sources.MESH_FILE).exists())

    def test_a_copy_without_the_whole_country_is_refused(self):
        body = fake_names(exclude=("52",))
        with mock.patch.object(config, "IBGE_NAMES_COPY_SHA256", write_copy(self.names_copy, body)):
            with self.assertRaises(RuntimeError) as ctx:
                sources.municipality_names()
        self.assertIn("GO", str(ctx.exception))
        self.assertFalse((self.raw / sources.NAMES_FILE).exists())

    def test_a_stale_file_in_raw_is_replaced_by_the_copy(self):
        """data/raw/ pode ter uma malha de outra geração (cache, geração local): vale sempre a cópia versionada."""
        self.raw.mkdir(parents=True)
        (self.raw / sources.MESH_FILE).write_bytes(fake_mesh(extra=("5101837",)))
        self.assertEqual(self.mesh_body, sources.municipal_mesh().read_bytes())

    def test_the_record_has_the_date_of_the_copy(self):
        sources.municipal_mesh()
        sources.municipality_names()
        mesh, names = sources.source_record(sources.MESH_FILE), sources.source_record(sources.NAMES_FILE)
        self.assertEqual((config.IBGE_MESH_URL, config.IBGE_COPIES_DATE), (mesh["url"], mesh["date"]))
        self.assertEqual((config.IBGE_NAMES_URL, config.IBGE_COPIES_DATE), (names["url"], names["date"]))
        self.assertEqual(self.mesh_copy.name, mesh["copy"])


class RealIbgeCopiesTest(unittest.TestCase):
    """As cópias do repositório: o sha256 do config e o país inteiro (5.570 polígonos, 5.571 municípios)."""

    def test_the_versioned_copies_pass(self):
        with tempfile.TemporaryDirectory() as tmp, mock.patch.object(config, "RAW", Path(tmp)):
            mesh, names = sources.municipal_mesh(), sources.municipality_names()
            municipalities = sources.load_municipalities(mesh, names)
        self.assertGreaterEqual(len(municipalities), config.MIN_MUNICIPALITIES)
        self.assertGreaterEqual(sum(1 for m in municipalities if m.geometry is not None), 5570)


class IbgeTest(unittest.TestCase):
    """O download conferido dos arquivos do IBGE: só grava (e só aceita do cache) um arquivo com o país inteiro.
    Exercitado pelas URLs da malha e dos nomes (até 2026-11-10 eram baixados assim; hoje, as outras fontes)."""

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
        mesh = mesh_download()
        names = names_download()
        self.assertEqual(27, len(json.loads(mesh.read_text(encoding="utf-8"))["features"]))
        self.assertEqual(27, len(json.loads(names.read_text(encoding="utf-8"))))

    def test_error_page_with_200_is_not_saved(self):
        """Nunca com o nome final; o corpo de cada tentativa fica em <nome>.<tentativa>.invalido, para o artefato."""
        self.server.files["/malha"] = ERROR_PAGE
        with self.assertRaises(RuntimeError):
            mesh_download()
        self.assertFalse((self.raw / sources.MESH_FILE).exists())
        self.assertEqual([f"{sources.MESH_FILE}.{i}.invalido" for i in (1, 2, 3)],
                         sorted(p.name for p in self.raw.iterdir()))
        self.assertEqual(ERROR_PAGE, (self.raw / f"{sources.MESH_FILE}.1.invalido").read_bytes())

    def test_invalid_content_is_retried_until_valid(self):
        answers = [ERROR_PAGE, fake_mesh()]
        self.server.files["/malha"] = lambda: answers.pop(0) if len(answers) > 1 else answers[0]
        mesh = mesh_download()
        self.assertEqual(2, self.downloads("/malha"))
        self.assertIsNone(sources.mesh_problem(mesh))
        self.assertEqual(ERROR_PAGE, (self.raw / f"{sources.MESH_FILE}.1.invalido").read_bytes())

    def test_gives_up_after_three_attempts(self):
        self.server.files["/nomes"] = b""
        with self.assertRaises(RuntimeError) as ctx:
            names_download()
        self.assertEqual(3, self.downloads("/nomes"))
        self.assertIn("3 tentativas", str(ctx.exception))

    def test_invalid_content_is_logged_with_status_type_and_body_start(self):
        self.server.files["/malha"] = ERROR_PAGE
        self.server.content_type["/malha"] = "text/html; charset=utf-8"
        out = io.StringIO()
        with contextlib.redirect_stdout(out), self.assertRaises(RuntimeError):
            mesh_download()
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
                mesh_download()
        self.assertEqual([mock.call(7), mock.call(14)], sleep.call_args_list)

    def test_bad_status_is_retried_and_logged(self):
        """Um 403 (o IBGE recusando o executor, por exemplo) também é tentado de novo, e o log diz o status."""
        self.server.codes["/malha"] = [403]
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            mesh = mesh_download()
        self.assertIsNone(sources.mesh_problem(mesh))
        self.assertEqual(2, self.downloads("/malha"))
        self.assertIn("HTTP 403", out.getvalue())

    def test_mesh_missing_a_state_is_rejected(self):
        self.server.files["/malha"] = fake_mesh(exclude=("53",))
        with self.assertRaises(RuntimeError) as ctx:
            mesh_download()
        self.assertIn("DF", str(ctx.exception))

    def test_too_few_municipalities_is_rejected(self):
        with mock.patch.object(config, "MIN_MUNICIPALITIES", 5570):
            with self.assertRaises(RuntimeError) as ctx:
                names_download()
        self.assertIn("5570", str(ctx.exception))

    def test_names_missing_a_state_is_rejected(self):
        self.server.files["/nomes"] = fake_names(exclude=("52",))
        with self.assertRaises(RuntimeError) as ctx:
            names_download()
        self.assertIn("GO", str(ctx.exception))

    def test_valid_cache_does_not_download_and_invalid_is_replaced(self):
        mesh_download()
        mesh_download()
        self.assertEqual(1, self.downloads("/malha"))
        (self.raw / "ibge_malha_municipios.json").write_text("<html>erro</html>", encoding="utf-8")
        mesh_download()
        self.assertEqual(2, self.downloads("/malha"))
        kept = self.raw / "ibge_malha_municipios.json.guardado.invalido"
        self.assertEqual("<html>erro</html>", kept.read_text(encoding="utf-8"))

    def test_load_municipalities_joins_names_and_mesh(self):
        """O nome e a UF vêm da lista de nomes (a fonte dos municípios); o polígono, da malha. Município novo que a
        malha ainda não tem fica sem polígono, e nunca some."""
        self.server.files["/nomes"] = fake_names(extra=("5101837",))
        found = {m.code: m for m in sources.load_municipalities(mesh_download(),
                                                                 names_download())}
        self.assertEqual(28, len(found))
        go = found["5200001"]
        self.assertEqual(("Município GO", "GO"), (go.name, go.uf))
        self.assertTrue(go.geometry.is_valid and go.geometry.area > 0)
        self.assertIsNone(found["5101837"].geometry)
        self.assertEqual("MT", found["5101837"].uf)


class SourceRecordTest(unittest.TestCase):
    """A data de cada fonte conferida (HS2): gravada ao lado do arquivo no download, lida para o registro da
    geração; o Last-Modified do site, senão o dia do download."""

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.raw = Path(self._tmp.name)
        self.server = FakeServer().__enter__()
        self.server.files["/malha"] = fake_mesh()
        self._patches = [mock.patch.object(config, "RAW", self.raw),
                         mock.patch.object(config, "IBGE_MESH_URL", self.server.url("/malha")),
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

    def test_the_date_comes_from_last_modified(self):
        self.server.headers["/malha"] = {"Last-Modified": "Fri, 28 Aug 2026 18:27:01 GMT"}
        mesh_download()
        record = sources.source_record(sources.MESH_FILE)
        self.assertEqual("2026-08-28", record["date"])
        self.assertEqual(self.server.url("/malha"), record["url"])
        self.assertIn("downloaded_at", record)

    def test_without_last_modified_the_date_is_the_download_day(self):
        mesh_download()
        record = sources.source_record(sources.MESH_FILE)
        self.assertEqual(record["downloaded_at"][:10], record["date"])

    def test_a_cached_file_keeps_its_record_and_a_file_never_downloaded_has_none(self):
        self.server.headers["/malha"] = {"Last-Modified": "Fri, 28 Aug 2026 18:27:01 GMT"}
        mesh_download()
        self.server.headers["/malha"] = {"Last-Modified": "Sat, 29 Aug 2026 18:27:01 GMT"}
        mesh_download()
        self.assertEqual("2026-08-28", sources.source_record(sources.MESH_FILE)["date"])
        self.assertIsNone(sources.source_record("nao_existe.json"))

    def test_the_records_of_a_generation(self):
        self.server.headers["/malha"] = {"Last-Modified": "Fri, 28 Aug 2026 18:27:01 GMT"}
        mesh_download()
        osm = {"url": "local", "timestamp": "2026-09-29T20:22:51Z", "path": "x", "md5": "ab", "size": 1}
        found = sources.generation_sources(osm)
        self.assertEqual({"url": "local", "date": "2026-09-29T20:22:51Z"}, found["openstreetmap"])
        self.assertEqual("2026-08-28", found[sources.MESH_FILE]["date"])
        self.assertIsNone(found[sources.NAMES_FILE])
        self.assertIn(sources.PRF_FILE, found)


class PrfDownloadTest(unittest.TestCase):
    """O arquivo da ANTT com os postos da PRF, conferido como os do IBGE."""

    def setUp(self):
        from tests.test_prf import unit, write_prf

        self._tmp = tempfile.TemporaryDirectory()
        self.raw = Path(self._tmp.name)
        good = self.raw / "bom.json"
        write_prf(good, [unit()], copies=200)
        self.server = FakeServer().__enter__()
        self.server.files["/prf.json"] = good.read_bytes()
        self._patches = [mock.patch.object(config, "RAW", self.raw),
                         mock.patch.object(config, "PRF_URL", self.server.url("/prf.json")),
                         mock.patch.object(sources, "RETRY_DELAY", 0),
                         mock.patch.object(sources, "IBGE_RETRY_DELAY", 0)]
        for p in self._patches:
            p.start()

    def tearDown(self):
        for p in self._patches:
            p.stop()
        self.server.__exit__(None, None, None)
        self._tmp.cleanup()

    def test_a_good_file_is_saved(self):
        path = sources.prf_units()
        self.assertEqual(self.raw / sources.PRF_FILE, path)
        self.assertEqual(200, len(json.loads(path.read_text(encoding="utf-8"))["PRF"]))

    def test_an_error_page_is_not_saved_and_the_error_names_the_antt(self):
        self.server.files["/prf.json"] = ERROR_PAGE
        with self.assertRaises(RuntimeError) as ctx:
            sources.prf_units()
        self.assertFalse((self.raw / sources.PRF_FILE).exists())
        self.assertIn("ANTT", str(ctx.exception))


class CnesDownloadTest(unittest.TestCase):
    """O zip do CNES (HS3), conferido como os arquivos do IBGE."""

    def setUp(self):
        from sabia import cnes
        from tests.test_cnes import one_per_state, write_zip

        self._tmp = tempfile.TemporaryDirectory()
        self.raw = Path(self._tmp.name)
        good = self.raw / "bom.zip"
        write_zip(good, one_per_state())
        self.server = FakeServer().__enter__()
        self.server.files["/cnes.zip"] = good.read_bytes()
        self._patches = [mock.patch.object(config, "RAW", self.raw),
                         mock.patch.object(config, "CNES_URL", self.server.url("/cnes.zip")),
                         mock.patch.object(cnes, "MIN_ROWS", 27), mock.patch.object(cnes, "MIN_UNITS", 27),
                         mock.patch.object(sources, "RETRY_DELAY", 0),
                         mock.patch.object(sources, "IBGE_RETRY_DELAY", 0)]
        for p in self._patches:
            p.start()

    def tearDown(self):
        for p in self._patches:
            p.stop()
        self.server.__exit__(None, None, None)
        self._tmp.cleanup()

    def test_a_good_file_is_saved_with_its_date(self):
        self.server.headers["/cnes.zip"] = {"Last-Modified": "Wed, 07 Oct 2026 06:21:58 GMT"}
        path = sources.cnes_units()
        self.assertEqual(self.raw / sources.CNES_FILE, path)
        self.assertEqual("2026-10-07", sources.source_record(sources.CNES_FILE)["date"])

    def test_an_error_page_is_not_saved_and_the_error_names_the_ministry(self):
        self.server.files["/cnes.zip"] = ERROR_PAGE
        with self.assertRaises(RuntimeError) as ctx:
            sources.cnes_units()
        self.assertFalse((self.raw / sources.CNES_FILE).exists())
        self.assertIn("Ministério da Saúde", str(ctx.exception))

    def test_the_cnes_is_in_the_generation_record(self):
        self.assertIn(sources.CNES_FILE, sources.CHECKED_FILES)


class SnvCopyTest(unittest.TestCase):
    """O SNV do DNIT (HS6) vem da cópia versionada dos marcos de km (gzip), conferida pelo sha256 e pelo mínimo de
    marcos, com a versão do SNV no registro da geração; nada vai para a rede. Desde 2026-11-10: o WFS do DNIT não
    responde aos executores do GitHub Actions (timeout), e o SNV inteiro tem 128 MB (os marcos, ~1 MB)."""

    def setUp(self):
        from sabia import snv
        from tests.test_snv import one_marker_per_state

        self._tmp = tempfile.TemporaryDirectory()
        tmp = Path(self._tmp.name)
        self.raw = tmp / "raw"
        self.copy = tmp / "dnit_snv_marcos.json.gz"
        self.body = snv.markers_json(one_marker_per_state(), "202607A", "2026-07-28")
        self._patches = [mock.patch.object(config, "RAW", self.raw),
                         mock.patch.object(config, "SNV_COPY", self.copy),
                         mock.patch.object(config, "SNV_COPY_SHA256", write_copy(self.copy, self.body)),
                         mock.patch.object(snv, "MIN_MARKERS", 27),
                         mock.patch.object(sources.net, "download", side_effect=AssertionError("foi à rede"))]
        for p in self._patches:
            p.start()

    def tearDown(self):
        for p in self._patches:
            p.stop()
        self._tmp.cleanup()

    def test_the_copy_is_used_with_the_snv_version(self):
        from sabia import snv

        path = sources.snv_roads()
        self.assertEqual(self.raw / sources.SNV_FILE, path)
        self.assertEqual(self.body, path.read_bytes())
        record = sources.source_record(sources.SNV_FILE)
        self.assertEqual(("202607A", "2026-07-28"), (record["version"], record["date"]))
        self.assertEqual(self.copy.name, record["copy"])
        self.assertIn(sources.SNV_FILE, sources.CHECKED_FILES)
        self.assertEqual(27, len(snv.load_markers(path)))

    def test_a_changed_copy_is_refused(self):
        from sabia import snv

        write_copy(self.copy, snv.markers_json([], "202607A", "2026-07-28"))
        with self.assertRaises(RuntimeError) as ctx:
            sources.snv_roads()
        self.assertIn("SNV_COPY_SHA256", str(ctx.exception))

    def test_too_few_markers_is_refused(self):
        from sabia import snv

        body = snv.markers_json([], "202607A", "2026-07-28")
        with mock.patch.object(config, "SNV_COPY_SHA256", write_copy(self.copy, body)), \
                self.assertRaises(RuntimeError) as ctx:
            sources.snv_roads()
        self.assertIn("marcos", str(ctx.exception))


class AnacCopyTest(unittest.TestCase):
    """As duas listas de aeródromos da ANAC (HS8) vêm das cópias versionadas (gzip), conferidas pelo sha256 e cada
    uma pelo seu mínimo; nada vai para a rede (desde 2026-11-10: a ANAC não responde aos executores do Actions)."""

    def setUp(self):
        from sabia import anac
        from tests.test_anac import aerodrome, write_list

        self._tmp = tempfile.TemporaryDirectory()
        tmp = Path(self._tmp.name)
        self.raw = tmp / "raw"
        good = tmp / "bom.json"
        write_list(good, [aerodrome()], copies=3)
        self.body = good.read_bytes()
        self.public, self.private = tmp / "publicos.json.gz", tmp / "privados.json.gz"
        sha = write_copy(self.public, self.body)
        write_copy(self.private, self.body)
        self._patches = [mock.patch.object(config, "RAW", self.raw),
                         mock.patch.object(config, "ANAC_PUBLIC_COPY", self.public),
                         mock.patch.object(config, "ANAC_PUBLIC_COPY_SHA256", sha),
                         mock.patch.object(config, "ANAC_PRIVATE_COPY", self.private),
                         mock.patch.object(config, "ANAC_PRIVATE_COPY_SHA256", sha),
                         mock.patch.object(anac, "MIN_PUBLIC", 3), mock.patch.object(anac, "MIN_PRIVATE", 3),
                         mock.patch.object(sources.net, "download", side_effect=AssertionError("foi à rede"))]
        for p in self._patches:
            p.start()

    def tearDown(self):
        for p in self._patches:
            p.stop()
        self._tmp.cleanup()

    def test_both_lists_come_from_the_copies(self):
        paths = sources.anac_aerodromes()
        self.assertEqual([self.raw / sources.ANAC_PUBLIC_FILE, self.raw / sources.ANAC_PRIVATE_FILE], paths)
        self.assertEqual([self.body, self.body], [p.read_bytes() for p in paths])
        self.assertEqual(config.ANAC_COPIES_DATE, sources.source_record(sources.ANAC_PUBLIC_FILE)["date"])

    def test_each_list_has_its_own_minimum(self):
        from sabia import anac

        with mock.patch.object(anac, "MIN_PRIVATE", 4), self.assertRaises(RuntimeError) as ctx:
            sources.anac_aerodromes()
        self.assertTrue((self.raw / sources.ANAC_PUBLIC_FILE).exists())
        self.assertFalse((self.raw / sources.ANAC_PRIVATE_FILE).exists())
        self.assertIn("aeródromos privados", str(ctx.exception))


class RealCopiesTest(unittest.TestCase):
    """As cópias do SNV e da ANAC no repositório: o sha256 do config e o mínimo de cada uma."""

    def test_the_versioned_copies_pass(self):
        from sabia import snv

        with tempfile.TemporaryDirectory() as tmp, mock.patch.object(config, "RAW", Path(tmp)):
            markers = snv.load_markers(sources.snv_roads())
            public, private = sources.anac_aerodromes()
            self.assertTrue(public.exists() and private.exists())
        self.assertGreaterEqual(len(markers), snv.MIN_MARKERS)


class GeonamesDownloadTest(unittest.TestCase):
    """Os dois arquivos do GeoNames (HS9), conferidos como os do IBGE."""

    def setUp(self):
        from sabia import geonames
        from tests.test_geonames import alt, one_per_state, write_zip

        self._tmp = tempfile.TemporaryDirectory()
        self.raw = Path(self._tmp.name)
        write_zip(self.raw / "p.zip", one_per_state())
        write_zip(self.raw / "n.zip", [alt(1, "Um"), alt(2, "Dois")])
        self.server = FakeServer().__enter__()
        self.server.files["/BR.zip"] = (self.raw / "p.zip").read_bytes()
        self.server.files["/alt/BR.zip"] = (self.raw / "n.zip").read_bytes()
        self._patches = [mock.patch.object(config, "RAW", self.raw),
                         mock.patch.object(config, "GEONAMES_PLACES_URL", self.server.url("/BR.zip")),
                         mock.patch.object(config, "GEONAMES_NAMES_URL", self.server.url("/alt/BR.zip")),
                         mock.patch.object(geonames, "MIN_PLACES", 27), mock.patch.object(geonames, "MIN_NAMES", 2),
                         mock.patch.object(sources, "RETRY_DELAY", 0),
                         mock.patch.object(sources, "IBGE_RETRY_DELAY", 0)]
        for p in self._patches:
            p.start()

    def tearDown(self):
        for p in self._patches:
            p.stop()
        self.server.__exit__(None, None, None)
        self._tmp.cleanup()

    def test_both_files_are_saved(self):
        self.assertEqual([self.raw / sources.GEONAMES_PLACES_FILE, self.raw / sources.GEONAMES_NAMES_FILE],
                         sources.geonames_files())

    def test_a_bad_places_file_is_not_saved(self):
        self.server.files["/BR.zip"] = (self.raw / "n.zip").read_bytes()
        with self.assertRaises(RuntimeError) as ctx:
            sources.geonames_files()
        self.assertFalse((self.raw / sources.GEONAMES_PLACES_FILE).exists())
        self.assertIn("GeoNames", str(ctx.exception))


if __name__ == "__main__":
    unittest.main()
