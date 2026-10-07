"""A etapa build do generate.py de ponta a ponta, com um extrato e arquivos do IBGE de mentira: os bancos, os
pacotes .sqlite.zst e o pacotes.json com as contagens."""
import json
import sqlite3
from contextlib import closing
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from shapely.geometry import mapping

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from sabia import config, database, sqlite_old  # noqa: E402
from tests.osm_builder import MUNICIPALITIES, OsmBuilder  # noqa: E402
from tests.test_cli import load_script  # noqa: E402
from tests.test_localities import write_zip  # noqa: E402
from tests import test_anac, test_cnes, test_geonames, test_overture, test_snv  # noqa: E402
from tests.test_prf import unit, write_prf  # noqa: E402


def write_ibge(raw: Path):
    raw.mkdir(parents=True, exist_ok=True)
    features = [{"type": "Feature", "properties": {"codarea": m.code}, "geometry": mapping(m.geometry)}
                for m in MUNICIPALITIES]
    mesh = {"type": "FeatureCollection", "features": features}
    (raw / "ibge_malha_municipios.json").write_text(json.dumps(mesh), encoding="utf-8")
    names = [{"municipio-id": int(m.code), "municipio-nome": m.name, "UF-sigla": m.uf} for m in MUNICIPALITIES]
    (raw / "ibge_municipios.json").write_text(json.dumps(names, ensure_ascii=False), encoding="utf-8")
    # HS1: um povoado em Goiânia, a sede de Goiânia (já é o município) e um povoado de SP (estado não pedido)
    write_zip(raw / "ibge_localidades.zip", [("GO", "5208707", "Povoado", None, "Povoado do Teste", -16.6, -49.4),
                                             ("GO", "5208707", "Cidade", "Sede Municipal", "Goiânia", -16.68, -49.26),
                                             ("SP", "3550308", "Povoado", None, "Longe Daqui", -23.5, -46.6)])
    # HS2: um posto da PRF em Goiânia (entra) e um em Anápolis que já está no extrato (ver StageFixture: não repete)
    write_prf(raw / "antt_postos_prf.json", [unit(road="BR-153", km="500", lat="-16.6", lng="-49.3"),
                                             unit(road="BR-060", km="86", lat="-16.3", lng="-48.9")])
    # HS3: um hospital 24 horas em Goiânia (entra), o Posto Cerrado do extrato não é saúde, e uma UPA em Anápolis com
    # o ponto em Goiânia (coordenada errada: não entra)
    test_cnes.write_zip(raw / "cnes_estabelecimentos.zip",
                        [test_cnes.unit(name="HOSPITAL DO TESTE", lat="-16.6", lng="-49.1"),
                         test_cnes.unit(name="UPA ANAPOLIS", kind="73", ibge="520110", lat="-16.6", lng="-49.4")])
    # HS4: uma loja da Overture em Goiânia (entra), o Posto Cerrado do extrato de novo (não repete) e uma de
    # confiança baixa (não entra)
    test_overture.write_extract(raw / "overture_lugares.parquet", [
        test_overture.place("Loja do Teste", -16.62, -49.15, category="clothing_store"),
        test_overture.place("Posto Cerrado", -16.6805, -49.2502, category="gas_station"),
        test_overture.place("Duvidosa", -16.63, -49.15, confidence=0.3)])
    # HS6: um trecho da BR-153 de 2 km em Goiânia (do km 500 ao 502) e um acesso (não entra)
    test_snv.write_snv(raw / "dnit_snv.json", [test_snv.segment(br="153", start=500.0, end=502.0),
                                               test_snv.segment(br="153", start=0.0, end=3.0, kind="A")])
    # HS8: um aeródromo público em Goiânia (entra), um interditado (não) e um privado (entra)
    test_anac.write_list(raw / "anac_aerodromos_publicos.json",
                         [test_anac.aerodrome("Aeroporto do Teste", "SBTT", lat="-16.55", lng="-49.45"),
                          test_anac.aerodrome("Fechado", "SBFF", lat="-16.56", lng="-49.45", situation="Interditado")])
    test_anac.write_list(raw / "anac_aerodromos_privados.json",
                         [test_anac.aerodrome("FAZENDA DO TESTE", "SWTT", lat="-16.52", lng="-49.05")])
    # HS9: Goiânia ganha o nome antigo "Campinas" (GeoNames), uma cachoeira do GeoNames e um mirante do Wikidata entram
    test_geonames.write_zip(raw / "geonames_lugares.zip",
                            [test_geonames.feature(1, "Goiânia", -16.69, -49.26),
                             test_geonames.feature(2, "Cachoeira do Teste", -16.58, -49.1, "H", "FLLS")])
    test_geonames.write_zip(raw / "geonames_nomes.zip", [test_geonames.alt(1, "Campinas", "", historic="1")])
    test_geonames.write_wd(raw / "wikidata_turismo.json",
                           [test_geonames.wd_row("Q9", "Mirante do Teste", "-16.57", "-49.12", "Q6017969")])


class StageFixture(unittest.TestCase):
    """Extrato de mentira, arquivos do IBGE de mentira e data/ numa pasta temporária."""

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        root = Path(self._tmp.name)
        self.raw, self.build, self.dist = root / "raw", root / "build", root / "dist"
        write_ibge(self.raw)
        osm = OsmBuilder()
        osm.street((-16.68, -49.26), 400, "Rua 10")
        osm.node(-16.68, -49.25, amenity="fuel", name="Posto Cerrado")
        osm.node(-16.3, -48.9003, amenity="police", name="PRF")
        osm.street((-15.79, -47.88), 400, "Eixo Rodoviário", highway="trunk")
        self.pbf = osm.write(root / "x.osm.pbf")
        self.osm = {"path": str(self.pbf), "url": "local", "timestamp": "2026-09-29T00:59:51Z",
                    "md5": "0123456789abcdef", "size": 1}
        self._patches = [mock.patch.object(config, "RAW", self.raw), mock.patch.object(config, "BUILD", self.build),
                         mock.patch.object(config, "DIST", self.dist)]
        for p in self._patches:
            p.start()
        self.script = load_script()

    def tearDown(self):
        for p in self._patches:
            p.stop()
        self._tmp.cleanup()


class BuildStageTest(StageFixture):
    def test_packages_and_counts(self):
        self.dist.mkdir(parents=True)
        (self.dist / "sabia-SP.sqlite.zst").write_bytes(b"sobra de outra geracao")
        packages = self.script.build_stage(["GO"], self.osm, today="2026-09-30")
        self.assertEqual("2026-09-30-01234567", packages["build_id"])
        self.assertEqual(["GO"], list(packages["states"]))
        go = packages["states"]["GO"]
        self.assertEqual("sabia-GO.sqlite.zst", go["file"])
        self.assertEqual(1, go["counts"]["street"])
        # o posto, a PRF do extrato, a PRF da ANTT, o hospital, a loja, os 3 marcos de km, os 2 aeródromos, a
        # cachoeira e o mirante
        self.assertEqual(12, go["counts"]["poi"])
        self.assertEqual(2, go["counts"]["municipality"])
        self.assertEqual("sabia-base.sqlite.zst", packages["base"]["file"])
        self.assertFalse((self.dist / "sabia-SP.sqlite.zst").exists())  # a saída anterior é limpa
        saved = json.loads((self.dist / "pacotes.json").read_text(encoding="utf-8"))
        self.assertEqual(packages, saved)
        back = self.build / "conferido.sqlite"
        database.decompress(self.dist / "sabia-GO.sqlite.zst", back)
        self.assertEqual((self.build / "sabia-GO.sqlite").read_bytes(), back.read_bytes())
        with closing(sqlite3.connect(back)) as db:
            self.assertEqual("2026-09-30-01234567", dict(db.execute("SELECT key, value FROM meta"))["build_id"])
            # HS1: as localidades do IBGE do estado entram como lugares; a sede não repete o município
            self.assertEqual([("Povoado do Teste", "ibge=povoado")],
                             list(db.execute("SELECT name, kind FROM item WHERE kind LIKE 'ibge=%'")))
            self.assertIn("localidades: IBGE", dict(db.execute("SELECT key, value FROM meta"))["attribution"])
            # HS2: o posto da PRF novo entra como polícia; o de Anápolis, que o extrato já tem, não repete
            self.assertEqual([("PRF", 5201108), ("PRF - Polícia Rodoviária Federal, BR-153 km 500", 5208707)],
                             list(db.execute("SELECT name, municipality FROM item WHERE kind = 'amenity=police' "
                                             "ORDER BY name")))
            self.assertIn("postos da PRF: ANTT", dict(db.execute("SELECT key, value FROM meta"))["attribution"])
            # HS3: o hospital do CNES entra; a UPA com o ponto fora do município dela, não
            self.assertEqual([("Hospital do Teste", 5208707)],
                             list(db.execute("SELECT name, municipality FROM item WHERE kind = 'amenity=hospital'")))
            self.assertIn("CNES", dict(db.execute("SELECT key, value FROM meta"))["attribution"])
            # HS4: a loja da Overture entra; o posto repetido e a de confiança baixa, não
            self.assertEqual([("Loja do Teste", "overture=clothing_store")],
                             list(db.execute("SELECT name, kind FROM item WHERE kind LIKE 'overture=%' "
                                             "OR name IN ('Duvidosa', 'Posto Cerrado') AND kind <> 'amenity=fuel'")))
            self.assertEqual(1, db.execute("SELECT count(*) FROM item WHERE name = 'Posto Cerrado'").fetchone()[0])
            self.assertIn("Overture", dict(db.execute("SELECT key, value FROM meta"))["attribution"])
            # HS6: os km do eixo principal entram; o do acesso, não
            self.assertEqual(["BR-153 km 500", "BR-153 km 501", "BR-153 km 502"],
                             [r[0] for r in db.execute("SELECT name FROM item WHERE kind = 'highway=milestone' "
                                                       "ORDER BY name")])
            self.assertIn("DNIT", dict(db.execute("SELECT key, value FROM meta"))["attribution"])
            # HS8: o aeroporto público e o privado da ANAC entram; o interditado, não
            self.assertEqual([("Aeroporto do Teste (SBTT)",), ("Aeródromo Fazenda do Teste (SWTT)",)],
                             list(db.execute("SELECT name FROM item WHERE kind = 'aeroway=aerodrome' ORDER BY name")))
            self.assertIn("ANAC", dict(db.execute("SELECT key, value FROM meta"))["attribution"])
            # HS9: a cachoeira e o mirante entram; "campinas" acha Goiânia (o nome continua o do IBGE)
            self.assertEqual([("Cachoeira do Teste", "natural=waterfall"), ("Mirante do Teste", "tourism=viewpoint")],
                             list(db.execute("SELECT name, kind FROM item WHERE name LIKE '% do Teste' "
                                             "AND kind IN ('natural=waterfall', 'tourism=viewpoint') ORDER BY name")))
            self.assertEqual([("Goiânia",)], list(db.execute(
                "SELECT item.name FROM item_text JOIN item ON item.id = item_text.docid "
                "WHERE item_text MATCH 'name:campinas'")))
            self.assertIn("GeoNames", dict(db.execute("SELECT key, value FROM meta"))["attribution"])
        self.assertEqual(back.stat().st_size, go["bytes_db"])

    def test_base_has_every_municipality_even_for_a_partial_run(self):
        packages = self.script.build_stage(["DF"], self.osm, today="2026-09-30")
        self.assertEqual(3, packages["base"]["counts"]["municipality"])
        self.assertEqual(1, packages["states"]["DF"]["counts"]["street"])


class ValidateStageTest(StageFixture):
    """A etapa validate sobre os bancos da etapa build: as travas e o relatorio.json."""

    def cases(self, *cases):
        path = self.build.parent / "buscas.json"
        path.write_text(json.dumps(list(cases), ensure_ascii=False), encoding="utf-8")
        return mock.patch.object(config, "SEARCH_CASES", path)

    def test_passing_generation(self):
        if not sqlite_old.library_path().exists():
            self.skipTest("SQLite 3.22 não instalado; rode python scripts/install_sqlite.py")
        packages = self.script.build_stage(["GO"], self.osm, today="2026-09-30")
        with self.cases({"uf": "GO", "query": "rua 10 goiania", "name": "Rua 10"},
                        {"uf": "DF", "query": "eixo rodoviario", "name": "Eixo Rodoviário"}):
            problems = self.script.validate_stage(["GO"], packages)
        self.assertEqual([], problems)
        report = json.loads((self.dist / "relatorio.json").read_text(encoding="utf-8"))
        self.assertEqual({"passed": 1, "total": 1}, {k: report["searches"][k] for k in ("passed", "total")})
        self.assertEqual("3.22.0", report["oldest_sqlite"])

    def test_failing_search_blocks(self):
        packages = self.script.build_stage(["GO"], self.osm, today="2026-09-30")
        with self.cases({"uf": "GO", "query": "rua 10 goiania", "name": "Rua 11"}):
            problems = self.script.validate_stage(["GO"], packages)
        self.assertEqual(1, len(problems))
        self.assertIn("rua 10 goiania", problems[0])
        report = json.loads((self.dist / "relatorio.json").read_text(encoding="utf-8"))
        self.assertEqual(problems, report["problems"])

    def test_without_the_old_sqlite_it_blocks(self):
        packages = self.script.build_stage(["GO"], self.osm, today="2026-09-30")
        with self.cases(), mock.patch.dict("os.environ", {"SABIA_SQLITE_OLD": str(self.build / "nao-existe.dll")}):
            problems = self.script.validate_stage(["GO"], packages)
        self.assertTrue(problems)
        self.assertTrue(all("3.22" in p for p in problems), problems)


class CatalogStageTest(StageFixture):
    def test_catalog_in_dist(self):
        packages = self.script.build_stage(["GO"], self.osm, today="2026-09-30")
        cat = self.script.catalog_stage(packages)
        saved = json.loads((self.dist / "catalogo.json").read_text(encoding="utf-8"))
        self.assertEqual(cat, saved)
        self.assertEqual(["GO"], list(saved["states"]))
        self.assertEqual("2026-09-30-01234567", saved["build_id"])
        self.assertEqual("local", saved["osm"]["url"])


if __name__ == "__main__":
    unittest.main()
