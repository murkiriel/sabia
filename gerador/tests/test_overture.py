"""Os lugares da Overture Maps (HS4): a versão mais nova, o recorte do Brasil, o arquivo conferido, a leitura com o
corte de confiança e os registros que entram, sem repetir o que o OpenStreetMap já tem."""
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

import pyarrow as pa
import pyarrow.fs as pafs
import pyarrow.parquet as pq

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from sabia import config, merge, overture, sources  # noqa: E402
from sabia.municipalities import MunicipalityIndex  # noqa: E402
from sabia.records import Item  # noqa: E402
from tests.fake_server import FakeServer  # noqa: E402
from tests.osm_builder import MUNICIPALITIES, east  # noqa: E402

SOURCE = pa.struct([("property", pa.string()), ("dataset", pa.string()), ("license", pa.string())])
SCHEMA = pa.schema([
    ("id", pa.string()),
    ("names", pa.struct([("primary", pa.string())])),
    ("confidence", pa.float64()),
    ("basic_category", pa.string()),
    ("taxonomy", pa.struct([("primary", pa.string()), ("hierarchy", pa.list_(pa.string()))])),
    ("bbox", pa.struct([("xmin", pa.float64()), ("xmax", pa.float64()), ("ymin", pa.float64()),
                        ("ymax", pa.float64())])),
    ("sources", pa.list_(SOURCE)),
])


def place(name="Mercado Bom Preço", lat=-16.7, lng=-49.2, confidence=0.9, category="grocery_store",
          basic="food_and_beverage_store", datasets=("meta",), pid=None, group="shopping"):
    """Um lugar no formato da Overture (só as colunas lidas)."""
    hierarchy = [group, category] if group else None
    return {"id": pid or name, "names": {"primary": name}, "confidence": confidence, "basic_category": basic,
            "taxonomy": {"primary": category, "hierarchy": hierarchy},
            "bbox": {"xmin": lng, "xmax": lng, "ymin": lat, "ymax": lat},
            "sources": [{"property": "", "dataset": d, "license": "CDLA-Permissive-2.0"} for d in datasets]}


def write_release(folder: Path, *parts):
    """A pasta theme=places/type=place de uma versão de mentira, um arquivo por lista de lugares."""
    folder.mkdir(parents=True, exist_ok=True)
    for i, rows in enumerate(parts):
        pq.write_table(pa.Table.from_pylist(list(rows), schema=SCHEMA), folder / f"part-{i:05d}.parquet")


def write_extract(path: Path, rows, copies=1):
    """O recorte do Brasil já extraído (o arquivo de data/raw/), a partir de lugares no formato da Overture."""
    with tempfile.TemporaryDirectory() as tmp:
        write_release(Path(tmp), list(rows) * copies)
        overture.extract(str(Path(tmp)), pafs.LocalFileSystem(), path)


LISTING = b"""<?xml version="1.0" encoding="UTF-8"?>
<ListBucketResult xmlns="http://s3.amazonaws.com/doc/2006-03-01/"><Name>overturemaps-us-west-2</Name>
<CommonPrefixes><Prefix>release/2026-08-19.0/</Prefix></CommonPrefixes>
<CommonPrefixes><Prefix>release/2026-09-23.0/</Prefix></CommonPrefixes>
<CommonPrefixes><Prefix>release/2026-09-23.1/</Prefix></CommonPrefixes>
<CommonPrefixes><Prefix>release/leia-me/</Prefix></CommonPrefixes>
</ListBucketResult>"""


class ReleaseTest(unittest.TestCase):
    def test_the_newest_release_of_the_listing(self):
        self.assertEqual("2026-09-23.1", overture.latest_release(LISTING.decode()))

    def test_a_listing_without_releases_is_an_error(self):
        with self.assertRaises(ValueError):
            overture.latest_release("<ListBucketResult></ListBucketResult>")


class ExtractTest(unittest.TestCase):
    def test_only_brazil_and_the_columns_read(self):
        with tempfile.TemporaryDirectory() as tmp:
            src = Path(tmp) / "rel"
            write_release(src, [place("Dentro", -16.7, -49.2, datasets=("meta", "Foursquare"))],
                          [place("Lisboa", 38.7, -9.1), place("Lima", -12.05, -77.04),
                           place("Sem taxonomia", -10.0, -50.0, category=None, group=None)])
            dest = Path(tmp) / "x.parquet"
            overture.extract(str(src), pafs.LocalFileSystem(), dest)
            rows = sorted(pq.read_table(dest).to_pylist(), key=lambda r: r["name"])
        self.assertEqual([("Dentro", -16.7, -49.2, 0.9, "grocery_store", "shopping", True),
                          ("Sem taxonomia", -10.0, -50.0, 0.9, "food_and_beverage_store", None, False)],
                         [(r["name"], r["lat"], r["lng"], r["confidence"], r["category"], r.get("group"),
                           r["foursquare"]) for r in rows])


class ProblemTest(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.path = Path(self._tmp.name) / "lugares.parquet"
        self._min = overture.MIN_PLACES
        overture.MIN_PLACES = 3

    def tearDown(self):
        overture.MIN_PLACES = self._min
        self._tmp.cleanup()

    def test_a_good_file_has_no_problem(self):
        write_extract(self.path, [place()], copies=3)
        self.assertIsNone(overture.problem(self.path))

    def test_not_a_parquet_file(self):
        self.path.write_text("<html>erro</html>", encoding="utf-8")
        self.assertIn("parquet", overture.problem(self.path))

    def test_a_missing_column_is_named(self):
        pq.write_table(pa.table({"name": ["a"] * 3, "lat": [1.0] * 3}), self.path)
        self.assertIn("confidence", overture.problem(self.path))

    def test_too_few_places(self):
        write_extract(self.path, [place()], copies=2)
        self.assertIn("2 lugares", overture.problem(self.path))


GO_BOX = (-17.0, -50.0, -16.0, -48.0)


class LoadTest(unittest.TestCase):
    def load(self, rows, box=GO_BOX):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "lugares.parquet"
            write_extract(path, rows)
            return overture.load(path, box)

    def test_the_confidence_cut(self):
        found = self.load([place("Alta", confidence=0.6), place("Baixa", confidence=0.59)])
        self.assertEqual(["Alta"], [p.name for p in found])

    def test_without_category_or_from_foursquare_stays_out(self):
        found = self.load([place("Sem", category=None, basic=None), place("Fsq", datasets=("Foursquare",)),
                           place("Ok")])
        self.assertEqual(["Ok"], [p.name for p in found])

    def test_natural_places_and_landmarks_stay_with_the_openstreetmap(self):
        """Rio, lago, cachoeira, morro, praia, parque, praça e sítio histórico da Overture vêm de páginas com nome de
        lugar: a "Cachoeira dos Dragões" de Goiânia passava na frente da de Pirenópolis na busca."""
        found = self.load([place("Cachoeira dos Dragões", category="waterfall", group="geographic_entities"),
                           place("Rio Meia Ponte", category="river", group="geographic_entities"),
                           place("Bosque dos Buritis", category="park", group="sports_and_recreation"),
                           place("Praça Cívica", category="public_plaza", group="travel_and_transportation"),
                           place("Casarão", category="historic_site", group="cultural_and_historic"),
                           place("Igreja Matriz", category="roman_catholic_place_of_worship",
                                 group="cultural_and_historic")])
        self.assertEqual(["Igreja Matriz"], [p.name for p in found])

    def test_only_inside_the_box(self):
        self.assertEqual(["Dentro"], [p.name for p in self.load([place("Dentro"), place("Fora", -20.0, -49.0)])])

    def test_the_kind_of_each_category(self):
        found = self.load([place("Posto", category="gas_station"), place("Loja", category="clothing_store"),
                           place("Borracharia", category="tire_dealer_and_repair"),
                           place("Só básica", category=None, basic="restaurant")])
        self.assertEqual({"Posto": "amenity=fuel", "Loja": "overture=clothing_store", "Borracharia": "shop=tyres",
                          "Só básica": "amenity=restaurant"}, {p.name: p.kind for p in found})
        self.assertEqual((-16.7, -49.2), (found[0].lat, found[0].lng))


class SimilarNamesTest(unittest.TestCase):
    def test_similar(self):
        self.assertTrue(merge.similar_names("Supermercado Bom Preço", "SUPERMERCADO BOM PRECO"))
        self.assertTrue(merge.similar_names("Bom Preço", "Supermercado Bom Preço"))
        self.assertTrue(merge.similar_names("Padaria Pão de Ouro Ltda", "Pão de Ouro Padaria e Confeitaria"))

    def test_not_similar(self):
        self.assertFalse(merge.similar_names("Bar", "Barbearia do Zé"))
        self.assertFalse(merge.similar_names("Padaria Central", "Farmácia Popular"))
        self.assertFalse(merge.similar_names("", "Farmácia"))
        # uma palavra em comum de três não basta
        self.assertFalse(merge.similar_names("Supermercado Bom Preço", "Farmácia Bom Jesus"))
        # artigo e "Ltda" não contam como palavra em comum
        self.assertFalse(merge.similar_names("A Loja", "A Casa"))
        self.assertFalse(merge.similar_names("Loja Ltda", "Casa Ltda"))


def poi(name, lat, lng, kind="shop=supermarket", cls="poi"):
    return Item(cls, kind, name, "5208707", lat, lng)


class AddTest(unittest.TestCase):
    def setUp(self):
        self.index = MunicipalityIndex(MUNICIPALITIES)
        self.new = merge.Point("Mercado Bom Preço", "shop=supermarket", -16.7, -49.2)

    def add(self, existing, points=None):
        items = {"GO": list(existing)}
        return overture.add(items, points or [self.new], self.index, ["GO"]), items

    def test_a_new_place_comes_in(self):
        counts, items = self.add([])
        self.assertEqual((1, 0), counts)
        self.assertEqual("poi", items["GO"][0].cls)

    def test_the_same_place_nearby_is_not_repeated(self):
        lat, lng = east(-16.7, -49.2, 290)
        for existing in (poi("Bom Preço", lat, lng), poi("Mercado Bom Preco", lat, lng, kind="shop=convenience"),
                         poi("", lat, lng), poi("Bom Preço", lat, lng, cls="place", kind="place=locality")):
            with self.subTest(existing=existing):
                self.assertEqual((0, 1), self.add([existing])[0])

    def test_far_away_another_name_or_an_unnamed_of_another_kind_comes_in(self):
        lat, lng = east(-16.7, -49.2, 310)
        self.assertEqual((1, 0), self.add([poi("Bom Preço", lat, lng)])[0])
        self.assertEqual((1, 0), self.add([poi("Farmácia Popular", -16.7, -49.2)])[0])
        self.assertEqual((1, 0), self.add([poi("", -16.7, -49.2, kind="amenity=fuel")])[0])
        street = poi("Bom Preço", -16.7, -49.2, cls="street", kind="highway=residential")
        self.assertEqual((1, 0), self.add([street])[0])

    def test_the_radius_measured(self):
        self.assertEqual(300.0, overture.DUPLICATE_M)
        self.assertEqual(0.6, overture.MIN_CONFIDENCE)


class DownloadTest(unittest.TestCase):
    """sources.overture_places: a versão mais nova pela listagem do S3 e o recorte do Brasil, conferido."""

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        root = Path(self._tmp.name)
        self.raw = root / "raw"
        self.bucket = root / "balde"
        write_release(self.bucket / "release/2026-09-23.1/theme=places/type=place", [place()] * 3)
        self.server = FakeServer().__enter__()
        self.server.files["/lista"] = LISTING
        self._patches = [mock.patch.object(config, "RAW", self.raw),
                         mock.patch.object(config, "OVERTURE_LISTING_URL", self.server.url("/lista")),
                         mock.patch.object(config, "OVERTURE_BUCKET", self.bucket.as_posix()),
                         mock.patch.object(overture, "filesystem", pafs.LocalFileSystem),
                         mock.patch.object(overture, "MIN_PLACES", 3),
                         mock.patch.object(sources, "RETRY_DELAY", 0)]
        for p in self._patches:
            p.start()

    def tearDown(self):
        for p in self._patches:
            p.stop()
        self.server.__exit__(None, None, None)
        self._tmp.cleanup()

    def test_the_newest_release_is_extracted_and_recorded(self):
        path = sources.overture_places()
        self.assertEqual(self.raw / "overture_lugares.parquet", path)
        self.assertEqual(3, pq.read_table(path).num_rows)
        record = sources.source_record(sources.OVERTURE_FILE)
        self.assertEqual("2026-09-23", record["date"])
        self.assertEqual("2026-09-23.1", record["release"])
        self.assertIn(sources.OVERTURE_FILE, sources.CHECKED_FILES)

    def test_a_bad_extract_is_not_saved(self):
        with mock.patch.object(overture, "MIN_PLACES", 4), self.assertRaises(RuntimeError) as ctx:
            sources.overture_places()
        self.assertFalse((self.raw / sources.OVERTURE_FILE).exists())
        self.assertIn("Overture", str(ctx.exception))

    def test_a_good_cached_extract_is_not_extracted_again(self):
        sources.overture_places()
        with mock.patch.object(overture, "extract") as extract:
            sources.overture_places()
        extract.assert_not_called()

    def test_the_credit(self):
        self.assertIn("lugares: Overture Maps Foundation (CDLA Permissive 2.0)", config.ATTRIBUTION)


if __name__ == "__main__":
    unittest.main()
