"""As travas de uma geração (G7). Nada é publicado se alguma falhar.

(a) Buscas de verdade (`buscas.json`): cada caso diz a busca, o estado e o que tem de aparecer até a posição `top`:
    nome (`name`, igual depois de dobrado, ou `name_contains`), município, bairro e/ou um ponto com raio. A busca é a
    de referência (search.py), a mesma regra que quem consome aplica.
(b) Cobertura: todos os municípios do IBGE do estado estão no banco do estado, com o registro do município; na base,
    só pode faltar ponto para um município de estado não gerado.
(c) Queda de registros em relação à geração publicada (`drops`, aplicada na publicação, com --accept-drop).
(d) Ruas locais juntadas com mais de 3 km: não travam, vão para o relatório (`relatorio.json`), para conferir as
    que mudarem.
(e) O banco abre e responde igual no SQLite 3.22 (o do Android 10): esquema sem nada mais novo (FTS5, R-Tree, STRICT,
    WITHOUT ROWID, coluna gerada) e as buscas do estado, rodadas no 3.22, dão os mesmos resultados.
"""
from __future__ import annotations

import json
import sqlite3
from collections import Counter
from contextlib import closing
from pathlib import Path
from typing import Dict, List, Optional, Sequence, Tuple

from . import geo, search, sqlite_old
from .sources import Municipality
from .text import fold

# Queda máxima de registros de um estado em relação à geração publicada (no total, e em cada classe com pelo menos
# DROP_MIN_CLASS registros). Uma fonte quebrada (extrato truncado, malha errada) aparece assim; o OpenStreetMap de um
# mês para o outro varia bem menos.
MAX_DROP = 0.05
DROP_MIN_CLASS = 1000
CLASSES = ("place", "street", "road", "poi")


def load_cases(path: Path, states: Sequence[str]) -> List[dict]:
    """Os casos de busca dos estados pedidos, com `top` 1 quando o caso não diz."""
    cases = json.loads(path.read_text(encoding="utf-8"))
    return [dict({"top": 1}, **c) for c in cases if c["uf"] in states]


def _matches(case: dict, r: search.Result) -> bool:
    if "name" in case and fold(case["name"]) != fold(r.name):
        return False
    if "name_contains" in case and fold(case["name_contains"]) not in fold(r.name):
        return False
    if "municipality" in case and case["municipality"] != r.municipality:
        return False
    if "district" in case and case["district"] != r.district:
        return False
    if "lat" in case and geo.dist_m(case["lat"], case["lng"], r.lat, r.lng) > case["radius_m"]:
        return False
    return True


def search_gate(db, cases: Sequence[dict]) -> Tuple[List[str], List[dict]]:
    """(problemas, uma linha por caso com a posição achada e o primeiro resultado)."""
    problems, rows = [], []
    for case in cases:
        found = search.search(db, case["query"], limit=max(case.get("top", 1), 5))
        rank = next((n for n, r in enumerate(found, 1) if _matches(case, r)), None)
        first = found[0].label if found else None
        rows.append({"uf": case["uf"], "query": case["query"], "rank": rank, "top": case.get("top", 1),
                     "first": first})
        if rank is None or rank > case.get("top", 1):
            expected = case.get("name") or case.get("name_contains") or f"({case.get('lat')}, {case.get('lng')})"
            problems.append(f"{case['uf']}: busca '{case['query']}' não traz {expected} até a posição "
                            f"{case.get('top', 1)} (achou {rank or 'nada'}; primeiro: {first})")
    return problems, rows


def coverage_gate(db_path: Path, municipalities: Sequence[Municipality], uf: str) -> List[str]:
    """Todo município do IBGE do estado com polígono está no banco (tabela municipality e registro do município)."""
    with closing(sqlite3.connect(db_path)) as db:
        in_table = {r[0] for r in db.execute("SELECT id FROM municipality")}
        as_item = {r[0] for r in db.execute("SELECT municipality FROM item WHERE kind = 'municipality'")}
    problems = []
    for m in municipalities:
        if m.uf != uf or m.geometry is None:
            continue
        if int(m.code) not in in_table or int(m.code) not in as_item:
            problems.append(f"{uf}: falta o município {m.code} ({m.name})")
    return problems


def base_gate(base_counts: dict, states: Sequence[str]) -> List[str]:
    """Na base, só pode ficar sem ponto um município cujo estado não foi gerado (sem polígono e sem o lugar do
    OpenStreetMap lido)."""
    from . import config
    return [f"base: o município {code} ({config.IBGE_STATE_CODES[code[:2]]}) ficou sem ponto"
            for code in base_counts.get("without_point", []) if config.IBGE_STATE_CODES[code[:2]] in states]


def drops(previous: Dict[str, dict], current: Dict[str, dict], max_drop: float = MAX_DROP) -> List[str]:
    """Estados da geração anterior que sumiram ou perderam mais que `max_drop` dos registros (no total, ou numa
    classe com pelo menos DROP_MIN_CLASS)."""
    out = []
    for uf, old in sorted(previous.items()):
        new = current.get(uf)
        if new is None:
            out.append(f"{uf}: sumiu da geração")
            continue
        if new["items"] < old["items"] * (1 - max_drop):
            out.append(f"{uf}: {old['items']} -> {new['items']} registros")
        for cls in CLASSES:
            if old.get(cls, 0) >= DROP_MIN_CLASS and new.get(cls, 0) < old[cls] * (1 - max_drop):
                out.append(f"{uf}: {old[cls]} -> {new.get(cls, 0)} registros {cls}")
    return out


NEWER_FEATURES = {"fts5": "FTS5", "rtree": "R-Tree", "without rowid": "WITHOUT ROWID", ") strict": "STRICT",
                  "generated always": "coluna gerada"}


def schema_problems(path: Path) -> List[str]:
    """O que no esquema o SQLite 3.22 (ou o do Android, sem FTS5 nem R-Tree) não leria."""
    with closing(sqlite3.connect(path)) as db:
        rows = db.execute("SELECT name, sql FROM sqlite_master WHERE sql IS NOT NULL").fetchall()
    virtual = [name for name, sql in rows if sql.lower().startswith("create virtual table")]
    problems = []
    for name, sql in rows:
        if any(name.startswith(v + "_") for v in virtual):
            continue  # tabela interna de uma tabela virtual: o problema já é a própria tabela virtual
        text = " ".join(sql.lower().split())
        for needle, label in NEWER_FEATURES.items():
            if needle in text:
                problems.append(f"{path.name}: {name} usa {label}")
    return problems


def old_sqlite_gate(path: Path, cases: Sequence[dict], lib_path: Optional[Path] = None) -> Tuple[List[str], str]:
    """(problemas, versão): o banco abre no SQLite 3.22, passa no integrity_check e as buscas dão o mesmo que no
    SQLite do Python."""
    lib_path = lib_path or sqlite_old.library_path()
    if not lib_path.exists():
        return [f"SQLite {sqlite_old.VERSION} não instalado ({lib_path}): rode python scripts/install_sqlite.py"], ""
    lib = sqlite_old.Library(lib_path)
    problems = schema_problems(path)
    old = lib.connect(path)
    try:
        check = old.execute("PRAGMA integrity_check")
        if check != [("ok",)]:
            problems.append(f"{path.name}: integrity_check no SQLite {lib.version}: {check[:3]}")
        with closing(sqlite3.connect(path)) as new:
            for case in cases:
                a = [(r.id, r.name) for r in search.search(old, case["query"], limit=10)]
                b = [(r.id, r.name) for r in search.search(new, case["query"], limit=10)]
                if a != b:
                    problems.append(f"{path.name}: '{case['query']}' dá outro resultado no SQLite {lib.version}")
    except sqlite_old.SqliteError as e:
        problems.append(f"{path.name}: erro no SQLite {lib.version}: {e}")
    finally:
        old.close()
    return problems, lib.version


def write_report(dest: Path, suspects: Sequence[dict], searches: Sequence[dict], problems: Sequence[str],
                 oldest_sqlite: str) -> None:
    """data/dist/relatorio.json: o que conferir a cada geração."""
    passed = sum(1 for s in searches if s["rank"] is not None and s["rank"] <= s.get("top", 1))
    data = {
        "problems": list(problems),
        "searches": {"passed": passed, "total": len(searches), "cases": list(searches)},
        "long_local_streets": {"count": dict(sorted(Counter(s["uf"] for s in suspects).items())),
                               "streets": sorted(suspects, key=lambda s: (s["uf"], -s["extent_m"]))},
        "oldest_sqlite": oldest_sqlite,
    }
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_text(json.dumps(data, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
