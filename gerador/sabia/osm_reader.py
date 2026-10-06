"""Uma passada pelo extrato do OpenStreetMap, guardando só o que vira registro: lugares, vias com nome ou `ref`,
pontos de interesse (pontos, vias e relações) e as áreas de lugar.

O pyosmium guarda a coordenada de cada nó (config.NODE_STORAGE) e monta as áreas das relações multipolygon. Um filtro
de chaves no C++ descarta antes do Python o que não interessa (prédios sem nome, endereços, árvores, postes).
"""
from __future__ import annotations

from array import array
from dataclasses import dataclass, field
from typing import List, Optional, Tuple

import osmium
import shapely.wkb
from shapely.geometry.base import BaseGeometry

from . import config, kinds

BBox = Tuple[float, float, float, float]  # lat mín, lng mín, lat máx, lng máx

# Só objetos com uma destas chaves chegam ao Python. Tudo o que entra sem nome é posto, pedágio e parecidos
# (amenity, shop, barrier) ou rodovia (ref).
KEYS = ("name", "amenity", "shop", "barrier", "ref")


@dataclass
class Place:
    name: str
    kind: str          # o valor de place= ("suburb")
    lat: float
    lng: float
    from_area: bool = False


@dataclass
class Poi:
    name: str
    kind: str          # "amenity=fuel"
    lat: float
    lng: float


@dataclass
class Way:
    """Uma via com nome (rua) ou com `ref` (rodovia), com os nós e as coordenadas."""
    name: str
    highway: str
    ref: str
    nodes: array       # ids dos nós ('q')
    lats: array        # ('d')
    lngs: array


@dataclass
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


def _named(tags) -> str:
    return (tags.get("name") or "").strip()


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
            self.data.places.append(Place(name, place, lat, lng))
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
        self.data.pois.append(Poi(name, kind, lat, lng))

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
        lat, lng = lats[len(lats) // 2], lngs[len(lngs) // 2]
        if not _inside(self.bbox, lat, lng):
            return
        if poi:
            self._poi(tags, name, sum(lats) / len(lats), sum(lngs) / len(lngs))
        elif len(lats) >= 2:
            self.data.ways.append(Way(name, highway, ref, ids, lats, lngs))

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
            self.data.places.append(Place(name, place, lat, lng, from_area=True))
        elif is_poi:
            self._poi(tags, name, lat, lng)


def read(path, bbox: Optional[BBox] = None) -> OsmData:
    """Lê o extrato. Com `bbox`, guarda só o que cai dentro (o meio da via, o centro da área)."""
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
