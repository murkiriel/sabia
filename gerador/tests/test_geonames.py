"""GeoNames e Wikidata (HS9): os arquivos conferidos, os pontos turísticos novos e os nomes alternativos que vão para o
índice de busca dos registros que já existem."""
import json
import sqlite3
import sys
import tempfile
import unittest
import urllib.parse
import zipfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from sabia import config, database, geonames, merge, sources, wikidata  # noqa: E402
from sabia.municipalities import MunicipalityIndex  # noqa: E402
from sabia.records import Item  # noqa: E402
from tests.osm_builder import MUNICIPALITIES, east  # noqa: E402

# Os códigos de UF do GeoNames (admin1) do Brasil: 27, de 01 a 31 com buracos.
ADMIN1 = ["01", "02", "03", "04", "05", "06", "07", "08", "11", "13", "14", "15", "16", "17", "18", "20", "21", "22",
          "23", "24", "25", "26", "27", "28", "29", "30", "31"]


def feature(gid, name, lat=-16.7, lng=-49.2, fclass="P", fcode="PPL", admin1="29"):
    """Uma linha do BR.txt do GeoNames (19 colunas separadas por tabulação)."""
    return [str(gid), name, name, "", str(lat), str(lng), fclass, fcode, "BR", "", admin1, "", "", "", "0", "", "700",
            "America/Sao_Paulo", "2026-10-01"]


def alt(gid, name, lang="pt", historic=""):
    """Uma linha do BR.txt dos nomes alternativos (10 colunas)."""
    return ["9" + str(gid), str(gid), lang, name, "", "", "", historic, "", ""]


def write_zip(path: Path, rows, inner="BR.txt"):
    text = "".join("\t".join(r) + "\n" for r in rows)
    with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as z:
        z.writestr("readme.txt", "GeoNames")
        z.writestr(inner, text.encode("utf-8"))


def one_per_state():
    return [feature(i, f"Lugar {a}", admin1=a) for i, a in enumerate(ADMIN1, 1)]


class GeonamesProblemTest(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.path = Path(self._tmp.name) / "g.zip"
        self._mins = geonames.MIN_PLACES, geonames.MIN_NAMES
        geonames.MIN_PLACES, geonames.MIN_NAMES = 27, 2

    def tearDown(self):
        geonames.MIN_PLACES, geonames.MIN_NAMES = self._mins
        self._tmp.cleanup()

    def test_a_good_places_file(self):
        write_zip(self.path, one_per_state())
        self.assertIsNone(geonames.places_problem(self.path))

    def test_not_a_zip_or_without_the_file(self):
        self.path.write_text("<html>erro</html>", encoding="utf-8")
        self.assertIn("zip", geonames.places_problem(self.path))
        write_zip(self.path, one_per_state(), inner="outro.txt")
        self.assertIn("BR.txt", geonames.places_problem(self.path))

    def test_rows_with_the_wrong_columns(self):
        write_zip(self.path, [r[:10] for r in one_per_state()])
        self.assertIn("colunas", geonames.places_problem(self.path))

    def test_too_few_places_or_states(self):
        write_zip(self.path, [r for r in one_per_state() if r[10] != "29"] * 2)
        self.assertIn("26 UFs", geonames.places_problem(self.path))
        geonames.MIN_PLACES = 30
        write_zip(self.path, one_per_state())
        self.assertIn("27 lugares", geonames.places_problem(self.path))

    def test_the_names_file(self):
        write_zip(self.path, [alt(1, "Um"), alt(2, "Dois")])
        self.assertIsNone(geonames.names_problem(self.path))
        write_zip(self.path, [alt(1, "One", "en"), alt(2, "Two", "en")])
        self.assertIn("pt", geonames.names_problem(self.path))
        write_zip(self.path, [alt(1, "Um")])
        self.assertIn("1 nomes", geonames.names_problem(self.path))
        write_zip(self.path, [r[:5] for r in [alt(1, "Um"), alt(2, "Dois")]])
        self.assertIn("colunas", geonames.names_problem(self.path))


class GeonamesLoadTest(unittest.TestCase):
    def load(self, places, names):
        with tempfile.TemporaryDirectory() as tmp:
            p, n = Path(tmp) / "p.zip", Path(tmp) / "n.zip"
            write_zip(p, places)
            write_zip(n, names)
            return geonames.load(p, n)

    def test_places_and_tourism_with_their_kinds_and_portuguese_names(self):
        found = self.load([feature(1, "Silvânia"), feature(2, "Salto do Corumbá", fclass="H", fcode="FLLS"),
                           feature(3, "Rio Meia Ponte", fclass="H", fcode="STM"),
                           feature(4, "Morro do Cabeludo", fclass="T", fcode="MT")],
                          [alt(1, "Bonfim", ""), alt(1, "Silvania", "pt"), alt(1, "Сильвания", "ru"),
                           alt(1, "Q123", "wkdt"), alt(1, "Old English", "en"), alt(1, "Bomfim", "pt"),
                           alt(2, "Cachoeira do Corumbá")])
        # sem língua (o nome antigo "Bonfim", no GeoNames) e em português entram; "Silvania" é o mesmo nome sem acento
        self.assertEqual([("Silvânia", "", ["Bonfim", "Bomfim"]),
                          ("Salto do Corumbá", "natural=waterfall", ["Cachoeira do Corumbá"]),
                          ("Morro do Cabeludo", "natural=peak", [])],
                         [(f.name, f.kind, f.aliases) for f in found])
        self.assertEqual((-16.7, -49.2), (found[0].lat, found[0].lng))


class AliasTest(unittest.TestCase):
    def test_usable_names(self):
        self.assertTrue(merge.usable_alias("Bonfim"))
        for bad in ("Сильвания", "瓦索拉斯", "BR", "123", ""):
            with self.subTest(bad=bad):
                self.assertFalse(merge.usable_alias(bad))

    def test_attach_to_the_nearest_match_without_repeating(self):
        index = MunicipalityIndex(MUNICIPALITIES)
        town = Item("place", "municipality", "Silvânia", "5208707", -16.7, -49.2)
        items = {"GO": [town]}
        point = merge.Point("Silvania", "", *east(-16.7, -49.2, 2900),
                            aliases=["Bonfim", "SILVÂNIA", "Bomfim", "Сильвания", "Vila do Bonfim", "Bonfim de Goiás",
                                     "Arraial do Bonfim", "Sexto"])
        far = merge.Point("Silvânia", "", *east(-16.7, -49.2, 3100), aliases=["Longe"])
        self.assertEqual(1, merge.attach_aliases(items, [point, far], index, ["GO"], 3000.0,
                                                 lambda it, p: merge.similar_names(it.name, p.name)))
        self.assertEqual(["Bonfim", "Bomfim", "Vila do Bonfim", "Bonfim de Goiás", "Arraial do Bonfim"], town.aliases)

    def test_only_within_the_radius_to_the_nearest_and_in_the_states_asked_for(self):
        index = MunicipalityIndex(MUNICIPALITIES)
        near = Item("place", "place=village", "Bonfim", "5208707", -16.7, -49.2)
        farther = Item("place", "place=village", "Bonfim", "5208707", *east(-16.7, -49.2, 2000))
        in_df = Item("place", "place=village", "Bonfim", "5300108", -15.8, -47.9)
        items = {"GO": [farther, near], "DF": [in_df]}

        def same(it, p):
            return merge.similar_names(it.name, p.name)

        points = [merge.Point("Bonfim", "", *east(-16.7, -49.2, 500), aliases=["Vila do Bonfim"]),
                  merge.Point("Bonfim", "", *east(-16.7, -49.2, -3200), aliases=["Longe"]),
                  merge.Point("Bonfim", "", -15.8, -47.9, aliases=["No DF"])]
        self.assertEqual(1, merge.attach_aliases(items, points, index, ["GO"], 3000.0, same))
        self.assertEqual((["Vila do Bonfim"], [], []), (near.aliases, farther.aliases, in_df.aliases))

    def test_aliases_go_to_the_search_text_and_not_to_the_name(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "x.sqlite"
            items = [Item("place", "municipality", "Silvânia", "5208707", -16.7, -49.2, aliases=["Bonfim"])]
            database.write_state(path, "GO", items, [], [], MUNICIPALITIES,
                                 {"build_id": "x", "osm_timestamp": "y"})
            db = sqlite3.connect(path)
            found = list(db.execute("SELECT item.name FROM item_text JOIN item ON item.id = item_text.docid "
                                    "WHERE item_text MATCH 'name:bonfim'"))
            db.close()
        self.assertEqual([("Silvânia",)], found)


class GeonamesAddTest(unittest.TestCase):
    def setUp(self):
        self.index = MunicipalityIndex(MUNICIPALITIES)

    def test_a_place_only_gives_names_and_tourism_comes_in_once(self):
        town = Item("place", "municipality", "Silvânia", "5208707", -16.7, -49.2)
        fall = Item("poi", "natural=waterfall", "Cachoeira do Abade", "5208707", -16.6, -49.3)
        items = {"GO": [town, fall]}
        found = [merge.Point("Silvânia", "", -16.71, -49.2, aliases=["Bonfim"]),
                 merge.Point("Vila Nova", "", -16.75, -49.25, aliases=["Vila Velha"]),
                 merge.Point("Abade", "natural=waterfall", *east(-16.6, -49.3, 1900), aliases=["Salto do Abade"]),
                 merge.Point("Salto do Corumbá", "natural=waterfall", -16.8, -49.1, aliases=["Cachoeira do Corumbá"])]
        counts = geonames.add(items, found, self.index, ["GO"])
        self.assertEqual((1, 1, 2), counts)  # entraram, já estavam, registros com nome alternativo novo
        self.assertEqual(["Bonfim"], town.aliases)
        self.assertEqual(["Abade", "Salto do Abade"], fall.aliases)
        new = [i for i in items["GO"] if i.name == "Salto do Corumbá"]
        self.assertEqual([("poi", "natural=waterfall", ["Cachoeira do Corumbá"])],
                         [(i.cls, i.kind, i.aliases) for i in new])
        self.assertFalse(any(i.name == "Vila Nova" for i in items["GO"]))

    def test_a_populated_place_gives_names_only_to_a_place_of_a_similar_name(self):
        shop = Item("poi", "amenity=fast_food", "Bonfim Lanches", "5208707", -16.7, -49.2)
        town = Item("place", "municipality", "Silvânia", "5208707", -16.69, -49.2)
        items = {"GO": [shop, town]}
        found = [merge.Point("Bonfim", "", -16.701, -49.2, aliases=["Bomfim"]),
                 merge.Point("Vila Nova", "", -16.691, -49.2, aliases=["Vila Velha"])]
        self.assertEqual((0, 0, 0), geonames.add(items, found, self.index, ["GO"]))
        self.assertEqual(([], []), (shop.aliases, town.aliases))

    def test_the_radii(self):
        self.assertEqual((3000.0, 2000.0), (geonames.ALIAS_M, geonames.DUPLICATE_M))


def wd_row(item="Q1", label="Cachoeira da Jiboia", lat="-16.7", lon="-49.2", kind="Q34038", alts=""):
    """Uma linha da resposta SPARQL em JSON."""
    row = {"item": {"type": "uri", "value": f"http://www.wikidata.org/entity/{item}"},
           "lat": {"type": "literal", "value": lat}, "lon": {"type": "literal", "value": lon},
           "type": {"type": "uri", "value": f"http://www.wikidata.org/entity/{kind}"},
           "alts": {"type": "literal", "value": alts}}
    if label is not None:
        row["label"] = {"type": "literal", "value": label, "xml:lang": "pt"}
    return row


def write_wd(path: Path, rows, copies=1):
    data = {"head": {"vars": ["item", "label", "lat", "lon", "type", "alts"]},
            "results": {"bindings": list(rows) * copies}}
    path.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")


class WikidataTest(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.path = Path(self._tmp.name) / "w.json"
        self._min = wikidata.MIN_ITEMS
        wikidata.MIN_ITEMS = 3

    def tearDown(self):
        wikidata.MIN_ITEMS = self._min
        self._tmp.cleanup()

    def test_the_query_asks_for_json_and_every_type(self):
        url = wikidata.url()
        self.assertTrue(url.startswith("https://query.wikidata.org/sparql?"))
        query = dict(urllib.parse.parse_qsl(urllib.parse.urlsplit(url).query))
        self.assertEqual("json", query["format"])
        for qid in wikidata.KINDS:
            self.assertIn(f"wd:{qid}", query["query"])
        self.assertIn("wd:Q155", query["query"])

    def test_problems(self):
        write_wd(self.path, [wd_row()], copies=3)
        self.assertIsNone(wikidata.problem(self.path))
        self.path.write_text("<html>erro</html>", encoding="utf-8")
        self.assertIn("JSON", wikidata.problem(self.path))
        self.path.write_text(json.dumps({"head": {"vars": ["item"]}, "results": {"bindings": []}}), encoding="utf-8")
        self.assertIn("label", wikidata.problem(self.path))
        write_wd(self.path, [wd_row()], copies=2)
        self.assertIn("2 itens", wikidata.problem(self.path))

    def test_load(self):
        write_wd(self.path, [wd_row(alts="Cachoeira da jibóia|Cascata da Jiboia"),
                             wd_row("Q2", "Pico dos Pireneus", kind="Q8502"), wd_row("Q3", None),
                             wd_row("Q4", "Mirante", kind="Q6017969", lat="x"),
                             wd_row("Q5", "Gruta", kind="Q35509", lat="-15.5", lon="-47.5"),
                             wd_row("Q6", "Tipo Novo", kind="Q999")])
        found = wikidata.load(self.path)
        self.assertEqual([("Cachoeira da Jiboia", "natural=waterfall", ["Cascata da Jiboia"]),
                          ("Pico dos Pireneus", "natural=peak", []), ("Gruta", "natural=cave_entrance", [])],
                         [(f.name, f.kind, f.aliases) for f in found])
        self.assertEqual((-15.5, -47.5), (found[2].lat, found[2].lng))

    def test_add_like_the_geonames(self):
        index = MunicipalityIndex(MUNICIPALITIES)
        items = {"GO": [Item("poi", "natural=waterfall", "Cachoeira da Jibóia", "5208707", -16.7, -49.2)]}
        found = [merge.Point("Cachoeira da Jiboia", "natural=waterfall", -16.705, -49.2, aliases=["Salto da Jiboia"]),
                 merge.Point("Pico Novo", "natural=peak", -16.6, -49.1)]
        self.assertEqual((1, 1, 1), wikidata.add(items, found, index, ["GO"]))
        self.assertEqual(["Salto da Jiboia"], items["GO"][0].aliases)


class DownloadTest(unittest.TestCase):
    def test_the_urls_and_files(self):
        self.assertEqual("https://download.geonames.org/export/dump/BR.zip", config.GEONAMES_PLACES_URL)
        self.assertEqual("https://download.geonames.org/export/dump/alternatenames/BR.zip", config.GEONAMES_NAMES_URL)
        self.assertEqual(("geonames_lugares.zip", "geonames_nomes.zip", "wikidata_turismo.json"),
                         (sources.GEONAMES_PLACES_FILE, sources.GEONAMES_NAMES_FILE, sources.WIKIDATA_FILE))
        for name in (sources.GEONAMES_PLACES_FILE, sources.GEONAMES_NAMES_FILE, sources.WIKIDATA_FILE):
            self.assertIn(name, sources.CHECKED_FILES)

    def test_the_credit(self):
        self.assertIn("nomes alternativos e pontos turísticos: GeoNames (CC BY 4.0) e Wikidata (CC0)",
                      config.ATTRIBUTION)


if __name__ == "__main__":
    unittest.main()
