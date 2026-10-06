"""O catalogo.json: o índice que quem usa os pacotes lê para saber o que baixar, de onde e como conferir.

    {
      "schema": 1,                          a versão deste formato de catálogo
      "format_version": 1,                  a versão do formato dos bancos (meta.format_version); recuse maior
      "build_id": "2026-10-05-93a54bc6",    data + 8 primeiros do md5 do extrato; também o nome da release
      "built_at": "2026-10-05T12:00:00Z",
      "generator_commit": "2d3c2f6",
      "osm": {"timestamp", "md5", "url"},   o extrato do OpenStreetMap usado
      "release_url": "https://github.com/Murkiriel/sabia/releases/download/2026-10-05-93a54bc6/",
      "attribution": "...",
      "base": {"file", "bytes", "sha256", "bytes_db", "bbox", "counts": {"municipality", "road"}},
      "states": {"GO": {"name", "file", "bytes", "sha256", "bytes_db", "bbox",
                        "counts": {"items", "place", "street", "road", "poi", "district", "street_line",
                                   "municipality"}}, ...}
    }

`bytes` é o tamanho do .sqlite.zst (o que se baixa); `bytes_db`, o do banco descompactado (o espaço no aparelho).
`bbox` = [lat mín, lng mín, lat máx, lng máx] dos municípios do estado (na base, o Brasil), arredondado para fora.
"""
from __future__ import annotations

import json
import math
import subprocess
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, Iterable, List, Optional, Sequence, Tuple

from . import config, database
from .sources import Municipality
from .util import file_hash

SCHEMA = 1


def bbox_of(boxes: Iterable[Tuple[float, float, float, float]]) -> List[float]:
    """O retângulo que contém todos (lat mín, lng mín, lat máx, lng máx), arredondado para fora em 2 casas."""
    boxes = list(boxes)
    lat_min = min(b[0] for b in boxes)
    lng_min = min(b[1] for b in boxes)
    lat_max = max(b[2] for b in boxes)
    lng_max = max(b[3] for b in boxes)
    return [math.floor(lat_min * 100) / 100, math.floor(lng_min * 100) / 100,
            math.ceil(lat_max * 100) / 100, math.ceil(lng_max * 100) / 100]


def _bounds(municipalities: Sequence[Municipality]) -> List[Tuple[float, float, float, float]]:
    out = []
    for m in municipalities:
        if m.geometry is not None:
            x0, y0, x1, y1 = m.geometry.bounds
            out.append((y0, x0, y1, x1))
    return out


def git_commit_hash() -> str:
    """Hash curto do commit do repositório, ou 'desconhecido' fora de um checkout do git."""
    try:
        r = subprocess.run(["git", "-C", str(config.REPO), "rev-parse", "--short", "HEAD"],
                           capture_output=True, text=True, timeout=10)
    except (OSError, subprocess.SubprocessError):
        return "desconhecido"
    return r.stdout.strip() if r.returncode == 0 and r.stdout.strip() else "desconhecido"


def _entry(package: dict, boxes: List[Tuple[float, float, float, float]], counts: dict) -> dict:
    path = config.DIST / package["file"]
    return {"file": package["file"], "bytes": path.stat().st_size, "sha256": file_hash(path),
            "bytes_db": package["bytes_db"], "bbox": bbox_of(boxes), "counts": counts}


def build_catalog(packages: dict, municipalities: Sequence[Municipality],
                  generator_commit: Optional[str] = None) -> dict:
    """O catálogo a partir do pacotes.json da etapa build e dos arquivos em data/dist/."""
    gid = packages["build_id"]
    osm = packages["osm"]
    states: Dict[str, dict] = {}
    for uf in sorted(packages["states"]):
        p = packages["states"][uf]
        states[uf] = {"name": config.STATES[uf],
                      **_entry(p, _bounds([m for m in municipalities if m.uf == uf]), dict(p["counts"]))}
    base_counts = {k: v for k, v in packages["base"]["counts"].items() if k != "without_point"}
    return {
        "schema": SCHEMA,
        "format_version": database.FORMAT_VERSION,
        "build_id": gid,
        "built_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "generator_commit": generator_commit or git_commit_hash(),
        "osm": {"timestamp": osm["timestamp"], "md5": osm["md5"], "url": osm["url"]},
        "release_url": config.RELEASE_URL.format(tag=gid),
        "attribution": config.ATTRIBUTION,
        "base": _entry(packages["base"], _bounds(municipalities), base_counts),
        "states": states,
    }


def save(cat: dict, dest: Path) -> None:
    dest.write_text(json.dumps(cat, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
