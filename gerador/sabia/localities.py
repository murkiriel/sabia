"""Localidades do IBGE (HS1 do plano geral 4; Parte 9 da pesquisa): povoados, vilas, lugarejos, aldeias indígenas,
localidades quilombolas, agrovilas, núcleos urbanos e rurais. São os nomes da beira de estrada que o OpenStreetMap
muitas vezes não tem.

- **Fonte.** A Base de Localidades do IBGE (2022, 96 mil localidades), um GeoPackage dentro de um zip, com o código do
  município, a categoria e o ponto de cada uma. Baixado e conferido como a malha (sources._checked_download).
- **O que entra.** Cada localidade vira um registro `place` com `kind` `ibge=<categoria>` no município do código do
  IBGE. As sedes ("Cidade") ficam de fora: já são os municípios. Uma categoria que o IBGE criar depois entra como
  `ibge=localidade`.
- **Sem repetir.** Fica de fora a localidade com o mesmo nome (sem acento nem caixa) de um lugar já registrado no
  mesmo município, a até 3 km; e uma segunda localidade igual a até 3 km de outra.
"""
from __future__ import annotations

import sqlite3
import tempfile
import zipfile
from collections import defaultdict
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, List, Optional, Sequence, Tuple

from . import config, geo
from .records import Item, order_key
from .text import fold

# Menos que isto no arquivo é resposta quebrada, não o Brasil (o de 2022 tem 96.163).
MIN_LOCALITIES = 90_000
# Mesmo nome a até esta distância, no mesmo município: o mesmo lugar.
DUPLICATE_M = 3000.0

# Categoria do IBGE -> `kind`. "Cidade" (sedes municipais e capitais) não entra.
KINDS = {
    "Povoado": "ibge=povoado",
    "Vila": "ibge=vila",
    "Lugarejo": "ibge=lugarejo",
    "Núcleo Urbano": "ibge=nucleo_urbano",
    "Núcleo Rural": "ibge=nucleo_rural",
    "Agrovila do PA": "ibge=agrovila",
    "Localidade Indígena": "ibge=indigena",
    "Localidade Quilombola": "ibge=quilombola",
    "Outras Localidades": "ibge=localidade",
    "Regiões Administrativas do Distrito Federal": "ibge=regiao_administrativa",
    "Distrito Estadual de Fernando de Noronha": "ibge=distrito_estadual",
}
SEATS = "Cidade"
OTHER = "ibge=localidade"

_COLUMNS = "SIGLA_UF, CD_MUN, CT_LOCALIDADE, NM_LOCALIDADE, LAT_LOCALIDADE, LONG_LOCALIDADE"


@dataclass
class Locality:
    name: str
    category: str
    municipality: str   # código do IBGE, 7 dígitos
    lat: float
    lng: float


def _rows(path: Path) -> List[Tuple[str, str, str, str, float, float]]:
    """As linhas da tabela de localidades do GeoPackage dentro do zip. Erros de zip ou de banco sobem."""
    with zipfile.ZipFile(path) as z, tempfile.TemporaryDirectory() as tmp:
        names = [n for n in z.namelist() if n.lower().endswith(".gpkg")]
        if not names:
            raise ValueError("o zip não tem um .gpkg")
        gpkg = Path(z.extract(names[0], tmp))
        db = sqlite3.connect(gpkg)
        try:
            tables = [r[0] for r in db.execute("SELECT table_name FROM gpkg_contents WHERE data_type = 'features'")]
            if not tables:
                raise ValueError("o .gpkg não tem tabela de localidades")
            return list(db.execute(f'SELECT {_COLUMNS} FROM "{tables[0]}"'))
        finally:
            db.close()


def problem(path: Path) -> Optional[str]:
    """O que há de errado com o zip das localidades, ou None se ele tem o país inteiro."""
    if not zipfile.is_zipfile(path):
        return "não é um zip"
    try:
        rows = _rows(path)
    except (OSError, ValueError, sqlite3.Error, zipfile.BadZipFile) as e:
        return f"não deu para ler ({e.__class__.__name__}: {e})"
    present = {str(r[0]) for r in rows}
    missing = sorted(uf for uf in config.STATES if uf not in present)
    if missing:
        return f"faltam as UFs {', '.join(missing)}"
    if len(rows) < MIN_LOCALITIES:
        return f"só {len(rows)} localidades (mínimo {MIN_LOCALITIES})"
    return None


def load(path: Path) -> List[Locality]:
    """As localidades do arquivo, na ordem dele."""
    return [Locality(str(name), str(category), str(mun), float(lat), float(lng))
            for _uf, mun, category, name, lat, lng in _rows(path)]


def kind_of(category: str) -> Optional[str]:
    """O `kind` da categoria; None para as sedes, que já são os municípios."""
    if category == SEATS:
        return None
    return KINDS.get(category, OTHER)


def add(items: Dict[str, List[Item]], found: Sequence[Locality], states: Sequence[str]) -> int:
    """Junta as localidades dos estados pedidos aos registros (em `items`, por UF), sem repetir lugares; devolve
    quantas entraram. Os registros de cada UF ficam na ordem da geração (records.order_key)."""
    wanted = set(states)
    known: Dict[Tuple[str, str], List[Tuple[float, float]]] = defaultdict(list)
    for uf in wanted:
        for it in items.get(uf, []):
            if it.cls == "place":
                known[(it.municipality, fold(it.name))].append((it.lat, it.lng))
    added = 0
    touched = set()
    for loc in found:
        kind = kind_of(loc.category)
        state = config.IBGE_STATE_CODES.get(loc.municipality[:2])
        if kind is None or state is None or state not in wanted or not loc.name.strip():
            continue
        key = (loc.municipality, fold(loc.name))
        if any(geo.dist_m(lat, lng, loc.lat, loc.lng) <= DUPLICATE_M for lat, lng in known[key]):
            continue
        items.setdefault(state, []).append(Item("place", kind, loc.name.strip(), loc.municipality, loc.lat, loc.lng))
        known[key].append((loc.lat, loc.lng))
        touched.add(state)
        added += 1
    for state in touched:
        items[state].sort(key=order_key)
    return added
