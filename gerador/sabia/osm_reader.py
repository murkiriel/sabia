"""Uma passada pelo extrato do OpenStreetMap, guardando só o que vira registro: lugares, vias com nome ou `ref`,
pontos de interesse (pontos, vias e relações) e as áreas de lugar.

O pyosmium guarda a coordenada de cada nó (config.NODE_STORAGE) e monta as áreas das relações multipolygon. Um filtro
de chaves no C++ descarta antes do Python o que não interessa (prédios sem nome, endereços, árvores, postes).

Duas passadas (`write_reduced`): a primeira grava uma cópia reduzida do extrato, só com os objetos que a leitura
usa (os com uma chave de KEYS, as relações de área) e os nós e vias que eles referenciam; a segunda lê a cópia. Sem
isso, o pyosmium guardava a coordenada de todos os nós do Brasil (~7 GB, no executor do Actions de 7,8 GB) para usar
a de poucos.
"""
from __future__ import annotations

import tempfile
from array import array
from dataclasses import dataclass, field
from pathlib import Path
from typing import List, Optional, Tuple, Union

import osmium
import shapely.wkb
from shapely.geometry.base import BaseGeometry

from . import config, kinds
from .text import fold

BBox = Tuple[float, float, float, float]  # lat mín, lng mín, lat máx, lng máx

# Só objetos com uma destas chaves chegam ao Python. Tudo o que entra sem nome é posto, pedágio e parecidos
# (amenity, shop, barrier) ou rodovia (ref).
KEYS = ("name", "amenity", "shop", "barrier", "ref")
# As relações que viram área (as do AreaManager do pyosmium); as outras (linhas de ônibus, rotas) a leitura não usa.
AREA_RELATIONS = ("multipolygon", "boundary")
# Nomes alternativos (item 9): só para o índice de busca do registro; cada tag pode trazer vários, separados por ";".
ALIAS_TAGS = ("alt_name", "short_name", "old_name", "official_name", "loc_name", "name:pt", "reg_name", "nickname")
MAX_ALIASES = 5


@dataclass(slots=True)
class Place:
    name: str
    kind: str          # o valor de place= ("suburb")
    lat: float
    lng: float
    from_area: bool = False
    population: int = 0
    aliases: Tuple[str, ...] = ()


@dataclass(slots=True)
class Poi:
    name: str
    kind: str          # "amenity=fuel"
    lat: float
    lng: float
    aliases: Tuple[str, ...] = ()


@dataclass(slots=True)
class Way:
    """Uma via com nome (rua) ou com `ref` (rodovia), com os nós e as coordenadas."""
    name: str
    highway: str
    ref: str
    nodes: array       # ids dos nós ('q')
    lats: array        # ('d')
    lngs: array
    aliases: Tuple[str, ...] = ()


@dataclass(slots=True)
class DistrictArea:
    """Um bairro desenhado como área (relação ou via fechada)."""
    name: str
    kind: str          # kinds.district_kind: "suburb", "admin_level=10"...
    geometry: BaseGeometry


@dataclass
class OsmData:
    places: List[Place] = field(default_factory=list)
    pois: List[Poi] = field(default_factory=list)
    ways: List[Way] = field(default_factory=list)
    district_areas: List[DistrictArea] = field(default_factory=list)


def _inside(bbox: Optional[BBox], lat: float, lng: float) -> bool:
    return bbox is None or (bbox[0] <= lat <= bbox[2] and bbox[1] <= lng <= bbox[3])


def _crosses(bbox: Optional[BBox], lats: array, lngs: array) -> bool:
    """A via encosta no retângulo? (o município dela sai depois, do meio do comprimento)"""
    return bbox is None or (min(lats) <= bbox[2] and max(lats) >= bbox[0] and min(lngs) <= bbox[3]
                            and max(lngs) >= bbox[1])


def _named(tags) -> str:
    return (tags.get("name") or "").strip()


def aliases(tags, name: str) -> Tuple[str, ...]:
    """Os nomes alternativos das ALIAS_TAGS que servem para buscar (escrita latina, com letra, 3 caracteres ou mais),
    sem repetir o nome nem outro alternativo (sem acento e minúsculo), até MAX_ALIASES."""
    seen = {fold(name)}
    out: List[str] = []
    for tag in ALIAS_TAGS:
        for value in (tags.get(tag) or "").split(";"):
            value = value.strip()
            if (len(value) < 3 or not any(c.isalpha() for c in value) or any(ord(c) >= 0x250 for c in value)
                    or fold(value) in seen):
                continue
            seen.add(fold(value))
            out.append(value)
    return tuple(out[:MAX_ALIASES])


def population(value: str) -> int:
    """A tag population ("1536097", "1.536.097", "12 000"); 0 quando não é um número."""
    digits = value.replace(".", "").replace(",", "").replace(" ", "").strip()
    return int(digits) if digits.isdigit() else 0


class _Reader:
    def __init__(self, bbox: Optional[BBox]) -> None:
        self.bbox = bbox
        self.data = OsmData()
        self.wkb = osmium.geom.WKBFactory()

    def node(self, n) -> None:
        if not n.location.valid():
            return
        lat, lng = n.location.lat, n.location.lon
        if not _inside(self.bbox, lat, lng):
            return
        tags = n.tags
        name = _named(tags)
        place = tags.get("place")
        if place in kinds.PLACE_KINDS and name:
            self.data.places.append(Place(name, place, lat, lng, population=population(tags.get("population") or ""),
                                          aliases=aliases(tags, name)))
            return
        self._poi(tags, name, lat, lng)

    def _poi(self, tags, name: str, lat: float, lng: float) -> None:
        kind = kinds.poi_kind(tags)
        if kind is None:
            return
        if not name and kinds.is_travel(kind):
            name = (tags.get("brand") or "").strip()
        elif not name:
            return
        self.data.pois.append(Poi(name, kind, lat, lng, aliases(tags, name)))

    def way(self, w) -> None:
        tags = w.tags
        highway = tags.get("highway")
        name = _named(tags)
        ref = (tags.get("ref") or "").strip()
        is_street = highway in kinds.STREET_HIGHWAYS and bool(name)
        is_road = highway in kinds.ROAD_HIGHWAYS and bool(ref)
        poi = not is_street and not is_road and kinds.poi_kind(tags) is not None
        if not (is_street or is_road or poi):
            return
        ids, lats, lngs = array("q"), array("d"), array("d")
        for n in w.nodes:
            loc = n.location
            if loc.valid():
                ids.append(n.ref)
                lats.append(loc.lat)
                lngs.append(loc.lon)
        if not lats:
            return
        if poi:
            lat, lng = sum(lats) / len(lats), sum(lngs) / len(lngs)
            if _inside(self.bbox, lat, lng):
                self._poi(tags, name, lat, lng)
        elif len(lats) >= 2 and _crosses(self.bbox, lats, lngs):
            self.data.ways.append(Way(name, highway, ref, ids, lats, lngs, aliases(tags, name) if name else ()))

    def area(self, a) -> None:
        tags = a.tags
        name = _named(tags)
        if not name:
            return
        place = tags.get("place")
        district = kinds.district_kind(tags)
        # ponto de interesse de via fechada já entrou como via; daqui só os das relações
        is_poi = not a.from_way() and kinds.poi_kind(tags) is not None
        if place not in kinds.PLACE_KINDS and not is_poi and district is None:
            return
        try:
            geometry = shapely.wkb.loads(self.wkb.create_multipolygon(a), hex=True)
        except (RuntimeError, osmium.InvalidLocationError):
            return  # anel quebrado no extrato (relação cortada na borda)
        point = geometry.representative_point() if not geometry.centroid.within(geometry) else geometry.centroid
        lat, lng = point.y, point.x
        if not _inside(self.bbox, lat, lng):
            return
        if district is not None:
            self.data.district_areas.append(DistrictArea(name, district, geometry))
        if place in kinds.PLACE_KINDS:
            self.data.places.append(Place(name, place, lat, lng, from_area=True,
                                          population=population(tags.get("population") or ""),
                                          aliases=aliases(tags, name)))
        elif is_poi:
            self._poi(tags, name, lat, lng)


def write_reduced(src: Union[str, Path], dest: Path) -> None:
    """Grava em `dest` a cópia reduzida de `src`: os objetos com uma chave de KEYS (sem as relações que não são de
    área) e, sem mudar nada, os nós, vias e membros que eles referenciam."""
    with osmium.BackReferenceWriter(str(dest), ref_src=str(src), overwrite=True, remove_tags=False) as writer:
        for obj in osmium.FileProcessor(str(src)).with_filter(osmium.filter.KeyFilter(*KEYS)):
            if isinstance(obj, osmium.osm.Relation) and obj.tags.get("type") not in AREA_RELATIONS:
                continue
            writer.add(obj)


def read(path: Union[str, Path], bbox: Optional[BBox] = None, reduce: bool = True,
         workdir: Optional[Path] = None) -> OsmData:
    """Lê o extrato. Com `bbox`, guarda só o que cai dentro (o meio da via, o centro da área). Com `reduce`, lê a cópia
    reduzida (gravada e apagada numa pasta temporária em `workdir`): o mesmo resultado, com bem menos memória."""
    if not reduce:
        return _read(path, bbox)
    with tempfile.TemporaryDirectory(dir=workdir) as tmp:
        reduced = Path(tmp) / "reduzido.osm.pbf"
        write_reduced(path, reduced)
        return _read(reduced, bbox)


def _read(path: Union[str, Path], bbox: Optional[BBox]) -> OsmData:
    reader = _Reader(bbox)
    fp = (osmium.FileProcessor(str(path))
          .with_locations(config.NODE_STORAGE)
          .with_areas(osmium.filter.KeyFilter("name"))
          .with_filter(osmium.filter.KeyFilter(*KEYS)))
    for obj in fp:
        if isinstance(obj, osmium.osm.Node):
            reader.node(obj)
        elif isinstance(obj, osmium.osm.Way):
            reader.way(obj)
        elif isinstance(obj, osmium.osm.Area):
            reader.area(obj)
    return reader.data
