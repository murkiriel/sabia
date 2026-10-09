"""O número das casas pelo CNEFE do Censo 2022 do IBGE (SE1; medição e formato em docs/ENDERECOS.md).

- **Fonte.** O Cadastro Nacional de Endereços para Fins Estatísticos, um zip por UF no site do IBGE (GO 121 MB, SP
  1,08 GB), CSV com `;`: município, logradouro (tipo, título, nome), número e a coordenada com o nível
  (`NV_GEO_COORD` 1 e 2: a do próprio endereço; 3 a 6, estimada: não entra). Retrato do Censo: não muda.
- **A escada.** Por rua e lado (par, ímpar), um degrau a cada STEP números e o último; entre dois degraus quem consome
  interpola. A mesma "Rua 1" existe em vários bairros: a escada se quebra em pedaços onde dois números seguidos ficam a
  mais de GAP_M. Medido em Goiás: erro da interpolação de 12 m na mediana e 92 m no p90, ~5 MB brutos.
- **Leitura em baldes.** O arquivo não vem agrupado por município: uma passada separa os endereços em baldes no disco
  pelo código do município, e cada balde vira escada; só os degraus ficam na memória (o de SP tem 3,7 GB descompactado).
- **Casamento.** Cada pedaço vai para a rua do pacote de mesmo nome no município (nome dobrado, abreviações expandidas,
  sem o tipo do logradouro: "R. 9" e "Rua 9", "Av. Dep. Jamel" e "Avenida Deputado Jamel") mais perto dele, a até
  MATCH_M; sem ela, a rua do CNEFE vira registro novo (`kind` "cnefe", `source` "cnefe").
"""
from __future__ import annotations

import csv
import io
import tempfile
import zipfile
from pathlib import Path
from typing import Dict, Iterator, List, Sequence, Tuple

from . import geo
from .records import Item
from .search_rules import ABBREVIATIONS
from .text import fold, title_pt

STEP = 20
GAP_M = 300.0
MATCH_M = 2_000.0
BUCKETS = 64
KIND = "cnefe"
SOURCE = "cnefe"

Rung = Tuple[int, int, int, float, float]   # (lado 0 par / 1 ímpar, pedaço, número, lat, lng)
_TYPES = {"rua", "avenida", "alameda", "travessa", "rodovia", "estrada", "praca", "largo", "viela", "via", "beco",
          "viaduto", "ponte"}


def core(name: str) -> str:
    """O nome para casar: dobrado, abreviações expandidas, sem o tipo do logradouro no começo."""
    words = [ABBREVIATIONS.get(w, w) for w in fold(name).split()]
    while words and words[0] in _TYPES:
        words = words[1:]
    return " ".join(words)


def ladder(addrs: Sequence[Tuple[int, float, float]]) -> List[Rung]:
    """Os degraus de uma rua: por lado, os números em ordem, quebrados em pedaços a GAP_M; em cada pedaço o primeiro, um
    a cada STEP números e o último. Os pedaços são numerados em cada lado."""
    out: List[Rung] = []
    for side in (0, 1):
        seg = 0
        pts = sorted({n: (n, la, lo) for n, la, lo in addrs if n % 2 == side}.values())
        if not pts:
            continue
        pieces: List[List[Tuple[int, float, float]]] = [[pts[0]]]
        for p in pts[1:]:
            last = pieces[-1][-1]
            if geo.dist_m(last[1], last[2], p[1], p[2]) > GAP_M:
                pieces.append([p])
            else:
                pieces[-1].append(p)
        for piece in pieces:
            kept = [piece[0]]
            for p in piece[1:]:
                if p[0] - kept[-1][0] >= STEP:
                    kept.append(p)
            if kept[-1] is not piece[-1]:
                kept.append(piece[-1])
            out += [(side, seg, n, la, lo) for n, la, lo in kept]
            seg += 1
    return out


def _rows(path: Path) -> Iterator[Tuple[str, str, int, float, float]]:
    """(município, logradouro, número, lat, lng) dos endereços numerados com a coordenada do próprio endereço."""
    with zipfile.ZipFile(path) as z:
        for info in z.infolist():
            if not info.filename.lower().endswith(".csv"):
                continue
            with z.open(info) as raw:
                text = io.TextIOWrapper(raw, encoding="utf-8", errors="replace", newline="")
                for r in csv.DictReader(text, delimiter=";"):
                    if r.get("NV_GEO_COORD") not in ("1", "2"):
                        continue
                    try:
                        number = int(r["NUM_ENDERECO"])
                        lat, lng = float(r["LATITUDE"]), float(r["LONGITUDE"])
                    except (KeyError, TypeError, ValueError):
                        continue
                    if number <= 0:
                        continue
                    parts = (r.get("NOM_TIPO_SEGLOGR"), r.get("NOM_TITULO_SEGLOGR"), r.get("NOM_SEGLOGR"))
                    name = " ".join(x.strip() for x in parts if x and x.strip())
                    yield r["COD_MUNICIPIO"], name, number, lat, lng


def read(path: Path) -> Dict[Tuple[str, str], Tuple[str, List[Rung]]]:
    """{(município, nome dobrado): (nome em caixa de título, degraus)} do arquivo de uma UF. O arquivo não vem agrupado
    por município (as linhas se intercalam): uma passada as separa em BUCKETS arquivos temporários pelo código do
    município, e cada um é agrupado na memória e vira escada; só os degraus ficam."""
    out: Dict[Tuple[str, str], Tuple[str, List[Rung]]] = {}
    with tempfile.TemporaryDirectory() as tmp:
        files = [open(Path(tmp) / f"{n}.tsv", "w", encoding="utf-8", newline="") for n in range(BUCKETS)]
        try:
            for mun, name, number, lat, lng in _rows(path):
                files[int(mun) % BUCKETS].write(f"{mun}\t{name}\t{number}\t{lat}\t{lng}\n")
        finally:
            for f in files:
                f.close()
        for n in range(BUCKETS):
            streets: Dict[Tuple[str, str], Tuple[str, List[Tuple[int, float, float]]]] = {}
            with open(Path(tmp) / f"{n}.tsv", encoding="utf-8") as f:
                for line in f:
                    m, nm, num, la, lo = line.rstrip("\n").split("\t")
                    streets.setdefault((m, fold(nm)), (nm, []))[1].append((int(num), float(la), float(lo)))
            for key, (name, addrs) in streets.items():
                out[key] = (title_pt(name), ladder(addrs))
    return out


def add(items: Dict[str, List[Item]], groups: Dict[Tuple[str, str], Tuple[str, List[Rung]]],
        uf: str) -> Tuple[int, int]:
    """Põe cada pedaço da escada na rua do pacote de mesmo nome no município mais perto dele (a até MATCH_M) ou numa rua
    nova. Devolve (pedaços postos em ruas do pacote, ruas novas)."""
    by_name: Dict[Tuple[str, str], List[Item]] = {}
    for it in items.get(uf, []):
        if it.cls == "street":
            by_name.setdefault((it.municipality, core(it.name)), []).append(it)
    matched = created = 0
    for (mun, key), (name, rungs) in sorted(groups.items()):
        candidates = by_name.get((mun, core(key)), [])
        for side, seg in sorted({(r[0], r[1]) for r in rungs}):
            piece = [r for r in rungs if (r[0], r[1]) == (side, seg)]
            mid = piece[len(piece) // 2]
            near = [(geo.dist_m(it.lat, it.lng, mid[3], mid[4]), n, it) for n, it in enumerate(candidates)]
            near = [x for x in near if x[0] <= MATCH_M]
            if near:
                min(near, key=lambda x: (x[0], x[1]))[2].numbers.extend(piece)
                matched += 1
                continue
            street = Item("street", KIND, name, mun, piece[0][3], piece[0][4], source=SOURCE, numbers=list(piece))
            items.setdefault(uf, []).append(street)
            candidates.append(street)
            by_name[(mun, core(key))] = candidates
            created += 1
    return matched, created
