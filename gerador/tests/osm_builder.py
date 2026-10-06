"""Extratos pequenos do OpenStreetMap escritos pelos próprios testes (pyosmium), e municípios de mentira.

Coordenadas sempre em (lat, lng). Os ids são dados em ordem; `way` aceita uma lista de pontos novos ou de ids de nós já
criados (para trechos que se tocam)."""
from __future__ import annotations

import math
import sys
from pathlib import Path
from typing import Dict, List, Sequence, Tuple, Union

import osmium
from shapely.geometry import box

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from sabia.sources import Municipality  # noqa: E402

M_PER_DEG = 111_320.0

# Três municípios-caixa: dois de Goiás (lado a lado na latitude) e o DF.
GOIANIA = Municipality("5208707", "Goiânia", "GO", box(-49.5, -16.9, -49.0, -16.5))
ANAPOLIS = Municipality("5201108", "Anápolis", "GO", box(-49.1, -16.45, -48.8, -16.2))
BRASILIA = Municipality("5300108", "Brasília", "DF", box(-48.3, -16.1, -47.3, -15.5))
MUNICIPALITIES = [GOIANIA, ANAPOLIS, BRASILIA]


def east(lat: float, lng: float, meters: float) -> Tuple[float, float]:
    """O ponto `meters` a leste de (lat, lng)."""
    return lat, lng + meters / (M_PER_DEG * math.cos(math.radians(lat)))


def north(lat: float, lng: float, meters: float) -> Tuple[float, float]:
    return lat + meters / M_PER_DEG, lng


class OsmBuilder:
    def __init__(self) -> None:
        self.nodes: Dict[int, Tuple[float, float, dict]] = {}
        self.ways: List[Tuple[int, List[int], dict]] = []
        self.relations: List[Tuple[int, list, dict]] = []
        self._next_node = 1
        self._next_way = 1
        self._next_relation = 1

    def node(self, lat: float, lng: float, **tags: str) -> int:
        nid = self._next_node
        self._next_node += 1
        self.nodes[nid] = (lat, lng, tags)
        return nid

    def way(self, points: Sequence[Union[int, Tuple[float, float]]], **tags: str) -> int:
        refs = [p if isinstance(p, int) else self.node(*p) for p in points]
        wid = self._next_way
        self._next_way += 1
        self.ways.append((wid, refs, tags))
        return wid

    def street(self, start: Tuple[float, float], meters: float, name: str, highway: str = "residential",
               step: float = 50.0, **tags: str) -> int:
        """Uma via reta para leste, com um nó a cada `step` metros."""
        n = max(1, int(round(meters / step)))
        points = [east(start[0], start[1], meters * i / n) for i in range(n + 1)]
        if name:
            tags["name"] = name
        return self.way(points, highway=highway, **tags)

    def multipolygon(self, ring: Sequence[Tuple[float, float]], **tags: str) -> int:
        """Uma relação multipolygon com um anel externo (fechado aqui)."""
        refs = [self.node(*p) for p in ring]
        wid = self.way(refs + [refs[0]])
        rid = self._next_relation
        self._next_relation += 1
        self.relations.append((rid, [("w", wid, "outer")], dict(tags, type="multipolygon")))
        return rid

    def write(self, path: Path, timestamp: str = "2026-09-29T00:59:51Z") -> Path:
        header = osmium.io.Header()
        header.set("osmosis_replication_timestamp", timestamp)
        w = osmium.SimpleWriter(str(path), header=header, overwrite=True)
        try:
            for nid in sorted(self.nodes):
                lat, lng, tags = self.nodes[nid]
                w.add_node(osmium.osm.mutable.Node(id=nid, location=(lng, lat), tags=tags, version=1))
            for wid, refs, tags in self.ways:
                w.add_way(osmium.osm.mutable.Way(id=wid, nodes=refs, tags=tags, version=1))
            for rid, members, tags in self.relations:
                w.add_relation(osmium.osm.mutable.Relation(id=rid, members=members, tags=tags, version=1))
        finally:
            w.close()
        return path
