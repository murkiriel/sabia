"""Em que município cai cada ponto, pela malha do IBGE (polígono contém o ponto), em lote."""
from __future__ import annotations

from typing import List, Optional, Sequence

import numpy as np
import shapely
from shapely.strtree import STRtree

from .sources import Municipality


class MunicipalityIndex:
    def __init__(self, municipalities: Sequence[Municipality]) -> None:
        self.items = [m for m in municipalities if m.geometry is not None]
        self.tree = STRtree([m.geometry for m in self.items])

    def bbox(self) -> Optional[tuple]:
        """(lat mín, lng mín, lat máx, lng máx) de todos os municípios do índice."""
        if not self.items:
            return None
        bounds = np.array([m.geometry.bounds for m in self.items if m.geometry is not None])
        return (bounds[:, 1].min(), bounds[:, 0].min(), bounds[:, 3].max(), bounds[:, 2].max())

    def locate(self, lats: Sequence[float], lngs: Sequence[float]) -> List[Optional[str]]:
        """O código do município de cada ponto, ou None fora de todos. No limite entre dois, vale o primeiro."""
        out: List[Optional[str]] = [None] * len(lats)
        if not len(lats) or not self.items:
            return out
        points = shapely.points(np.asarray(lngs, dtype=float), np.asarray(lats, dtype=float))
        point_idx, tree_idx = self.tree.query(points, predicate="within")
        for p, t in zip(point_idx.tolist(), tree_idx.tolist()):
            if out[p] is None:
                out[p] = self.items[t].code
        return out
