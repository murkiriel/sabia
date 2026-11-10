"""Lugares da Overture Maps (HS4; Parte 9 da pesquisa, medição M9): o comércio e os serviços que faltam no
OpenStreetMap (lojas, restaurantes, oficinas, hotéis...).

- **Fonte.** O tema `places` da versão mais nova da Overture (GeoParquet no S3 público da Overture, `us-west-2`, sem
  conta). A versão sai da listagem do balde (`latest_release`); o recorte do Brasil (`extract`) lê com o `pyarrow` só
  os grupos de linhas que cruzam o retângulo do país e grava em data/raw/ o que o gerador usa: nome, ponto,
  confiança, categoria e se veio da Foursquare. Conferido (`problem`): parquet com essas colunas e pelo menos
  MIN_PLACES lugares.
- **O que entra.** Os lugares com confiança de MIN_CONFIDENCE ou mais e com categoria (a `taxonomy.primary`, senão a
  `basic_category`), menos os lugares naturais e marcos (rio, lago, cachoeira, morro, praia, parque, praça, sítio
  histórico: ficam com o OpenStreetMap; ver NATURAL_GROUPS) e os que vêm da Foursquare: a Apache 2.0 dela pede a
  licença e o NOTICE junto, e a Foursquare OS Places fechou o acesso a quem não tem conta (HS5). Cada um vira um
  ponto de interesse com o `kind` do OpenStreetMap quando a categoria tem um que a busca usa (KINDS: posto,
  hospital, farmácia, hotel, restaurante, oficina, borracharia...), senão `overture=<categoria>`.
- **Sem repetir.** Fica de fora o lugar com um lugar ou ponto de interesse de nome parecido (merge.similar_names) a
  até DUPLICATE_M, ou sem nome e do mesmo `kind`. Medido em Goiás (M9): até 300 m, 91% dos casamentos de nome são de
  verdade; entre 300 e 500 m, 72%.

O recorte é lido estado por estado (`load` com o retângulo do estado), para a memória não passar do estado maior.
"""
from __future__ import annotations

import re
from pathlib import Path
from typing import Dict, List, Optional, Sequence, Tuple

import numpy as np
import pyarrow as pa
import pyarrow.compute as pc
import pyarrow.dataset as ds
import pyarrow.fs as pafs
import pyarrow.parquet as pq

from . import merge
from .merge import Point
from .municipalities import MunicipalityIndex
from .records import Item

# Menos que isto no recorte do Brasil é leitura quebrada (a versão de 2026-09-23 dá 6,67 milhões no retângulo).
MIN_PLACES = 1_000_000
# Corte de confiança e raio dos repetidos medidos em Goiás (M9).
MIN_CONFIDENCE = 0.8  # era 0,6 até 08/10/2026 (Goiás: 9,6 → 8,3 MB)
DUPLICATE_M = 300.0
# O retângulo do Brasil (lat mín, lng mín, lat máx, lng máx), com folga; o município de cada lugar vem depois.
BRAZIL = (-34.0, -74.5, 5.5, -28.5)
COLUMNS = ("name", "lat", "lng", "confidence", "category", "group", "foursquare")
FOURSQUARE = "Foursquare"
# Lugares naturais e marcos ficam com o OpenStreetMap: na Overture eles vêm de páginas com nome de lugar (a
# "Cachoeira dos Dragões" no Setor Marista, em Goiânia; um "Bosque dos Buritis" em Goiatuba) e passavam na frente do
# lugar de verdade na busca (travas de Goiás, 2026-10-07). O grupo é o primeiro nível da `taxonomy.hierarchy`.
NATURAL_GROUPS = {"geographic_entities"}
LANDMARKS = {"park", "public_plaza", "historic_site", "landmark_and_historical_building", "monument", "memorial_site",
             "river", "lake", "waterfall", "mountain", "beach", "island", "forest", "nature_reserve"}

_RELEASE = re.compile(r"<Prefix>release/(\d{4}-\d{2}-\d{2}\.\d+)/</Prefix>")

# Categoria da Overture -> `kind` do OpenStreetMap, para as que a busca usa (palavras de categoria e viagem).
KINDS = {
    "gas_station": "amenity=fuel", "hospital": "amenity=hospital", "pharmacy": "amenity=pharmacy",
    "pharmacy_and_drug_store": "amenity=pharmacy", "hotel": "tourism=hotel", "motel": "tourism=motel",
    "lodging": "tourism=guest_house", "bed_and_breakfast": "tourism=guest_house", "inn": "tourism=guest_house",
    "campground": "tourism=camp_site", "restaurant": "amenity=restaurant",
    "brazilian_restaurant": "amenity=restaurant", "pizza_restaurant": "amenity=restaurant",
    "barbecue_restaurant": "amenity=restaurant", "steakhouse": "amenity=restaurant",
    "bar_and_grill_restaurant": "amenity=restaurant", "japanese_restaurant": "amenity=restaurant",
    "seafood_restaurant": "amenity=restaurant", "italian_restaurant": "amenity=restaurant",
    "fast_food_restaurant": "amenity=fast_food", "burger_restaurant": "amenity=fast_food",
    "sandwich_shop": "amenity=fast_food", "casual_eatery": "amenity=fast_food", "bakery": "shop=bakery",
    "grocery_store": "shop=supermarket", "supermarket": "shop=supermarket", "convenience_store": "shop=convenience",
    "automotive_repair": "shop=car_repair", "motorcycle_repair": "shop=motorcycle_repair",
    "tire_dealer_and_repair": "shop=tyres", "tire_shop": "shop=tyres", "auto_dealer": "shop=car",
    "motorcycle_dealer": "shop=motorcycle", "bank": "amenity=bank", "bank_or_credit_union": "amenity=bank",
    "police_station": "amenity=police", "fire_station": "amenity=fire_station",
    "christian_place_of_worship": "amenity=place_of_worship",
    "roman_catholic_place_of_worship": "amenity=place_of_worship",
    "protestant_place_of_worship": "amenity=place_of_worship",
    "pentecostal_place_of_worship": "amenity=place_of_worship",
    "baptist_place_of_worship": "amenity=place_of_worship", "school": "amenity=school",
    "elementary_school": "amenity=school", "public_school": "amenity=school", "private_school": "amenity=school",
    "high_school": "amenity=school", "college_university": "amenity=university", "park": "leisure=park",
    "shopping_mall": "shop=mall", "parking": "amenity=parking", "bus_station": "amenity=bus_station",
    "museum": "tourism=museum", "waterfall": "natural=waterfall", "stadium_arena": "leisure=stadium",
    "movie_theater": "amenity=cinema", "zoo": "tourism=zoo", "ev_charging_station": "amenity=charging_station",
}


def filesystem() -> pafs.FileSystem:
    """O S3 público da Overture, sem conta (os testes trocam por uma pasta local)."""
    return pafs.S3FileSystem(anonymous=True, region="us-west-2")


def latest_release(listing: str) -> str:
    """A versão mais nova na listagem do balde (ListObjectsV2 com delimitador): '2026-09-23.1'."""
    found = _RELEASE.findall(listing)
    if not found:
        raise ValueError("a listagem do S3 não tem nenhuma versão (release/AAAA-MM-DD.N/)")
    return max(found, key=lambda r: (r.split(".")[0], int(r.split(".")[1])))


def extract(source: str, fs: pafs.FileSystem, dest: Path) -> None:
    """Grava em `dest` os lugares de `source` (a pasta theme=places/type=place de uma versão) que caem no retângulo do
    Brasil, só com as colunas que o gerador usa."""
    dataset = ds.dataset(source, filesystem=fs, format="parquet")
    lat0, lng0, lat1, lng1 = BRAZIL
    inside = ((ds.field("bbox", "xmin") >= lng0) & (ds.field("bbox", "xmin") <= lng1)
              & (ds.field("bbox", "ymin") >= lat0) & (ds.field("bbox", "ymin") <= lat1))
    columns = {"name": ds.field("names", "primary"), "lat": ds.field("bbox", "ymin"),
               "lng": ds.field("bbox", "xmin"), "confidence": ds.field("confidence"),
               "taxonomy": ds.field("taxonomy", "primary"), "hierarchy": ds.field("taxonomy", "hierarchy"),
               "basic": ds.field("basic_category"),
               "sources": ds.field("sources")}
    schema = pa.schema([("name", pa.string()), ("lat", pa.float64()), ("lng", pa.float64()),
                        ("confidence", pa.float64()), ("category", pa.string()), ("group", pa.string()),
                        ("foursquare", pa.bool_())])
    with pq.ParquetWriter(dest, schema, compression="zstd") as writer:
        for batch in dataset.scanner(columns=columns, filter=inside, batch_size=65536).to_batches():
            if batch.num_rows == 0:
                continue
            src = batch.column("sources")
            flat = pc.list_flatten(src)
            from_fsq = pc.equal(pc.struct_field(flat, "dataset"), FOURSQUARE).fill_null(False).to_numpy(
                zero_copy_only=False)
            parents = pc.list_parent_indices(src).to_numpy()
            foursquare = np.bincount(parents[from_fsq], minlength=batch.num_rows) > 0
            writer.write_table(pa.table({
                "name": batch.column("name"), "lat": batch.column("lat"), "lng": batch.column("lng"),
                "confidence": batch.column("confidence"),
                "category": pc.coalesce(batch.column("taxonomy"), batch.column("basic")),
                "group": pc.list_element(batch.column("hierarchy"), 0),
                "foursquare": pa.array(foursquare)}, schema=schema))


def problem(path: Path) -> Optional[str]:
    """O que há de errado com o recorte, ou None se ele tem as colunas e o Brasil inteiro."""
    try:
        meta = pq.ParquetFile(path).metadata
        names = set(meta.schema.names)
    except (OSError, pa.ArrowException) as e:
        return f"não é um parquet que dê para ler ({e.__class__.__name__})"
    missing = [c for c in COLUMNS if c not in names]
    if missing:
        return f"faltam as colunas {', '.join(missing)}"
    if meta.num_rows < MIN_PLACES:
        return f"só {meta.num_rows} lugares (mínimo {MIN_PLACES})"
    return None


def kind_of(category: str) -> str:
    return KINDS.get(category, f"overture={category}")


def load(path: Path, box: Tuple[float, float, float, float]) -> List[Point]:
    """Os lugares do retângulo `box` (lat mín, lng mín, lat máx, lng máx) que passam no corte, na ordem do arquivo."""
    lat0, lng0, lat1, lng1 = box
    table = pq.read_table(path, columns=list(COLUMNS), filters=[
        ("lat", ">=", lat0), ("lat", "<=", lat1), ("lng", ">=", lng0), ("lng", "<=", lng1),
        ("confidence", ">=", MIN_CONFIDENCE), ("foursquare", "=", False)])
    out = []
    for name, lat, lng, category, group in zip(*(table.column(c).to_pylist()
                                                  for c in ("name", "lat", "lng", "category", "group"))):
        if not category or not (name or "").strip() or group in NATURAL_GROUPS or category in LANDMARKS:
            continue
        out.append(Point(name.strip(), kind_of(category), lat, lng))
    return out


def is_same(item: Item, point: Point) -> bool:
    """O registro é o mesmo lugar? Lugar ou ponto de interesse de nome parecido; sem nome, do mesmo `kind`."""
    if item.cls not in ("poi", "place"):
        return False
    if not item.name.strip():
        return item.kind == point.kind
    return merge.similar_names(item.name, point.name)


def add(items: Dict[str, List[Item]], points: Sequence[Point], index: MunicipalityIndex,
        states: Sequence[str]) -> Tuple[int, int]:
    """Junta os lugares aos registros dos estados pedidos; devolve (entraram, já estavam)."""
    return merge.add(items, points, index, states, DUPLICATE_M, is_same, origin="overture")
