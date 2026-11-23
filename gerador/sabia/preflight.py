"""Sonda de pré-voo: antes do passo longo, confere em ~1 min que cada fonte baixada na hora responde ao executor.

Em 2026-11 o IBGE, o DNIT, a ANAC e a ANTT passaram a não responder ao Actions, e cada geração só descobria isso depois
de ~40 min de tentativas, 12 vezes seguidas. Aqui cada fonte ao vivo recebe um GET de 1 byte (o `Range: bytes=0-0`;
o corpo não é lido além do primeiro byte, nem num site que ignora o Range), com poucas tentativas e tempo curto, todas
ao mesmo tempo. A falha lista o que não respondeu e por quê, para a issue "Geração falhando" já mostrar a causa.

Fontes ao vivo: o extrato do OpenStreetMap, as localidades e o CNEFE do IBGE, o CNES, a Overture (a listagem das
versões), o GeoNames (lugares e nomes), o Wikidata e a ANP. A malha e a lista de municípios, o SNV, a ANAC e a PRF vêm
de cópias versionadas e não entram.

Só a stdlib e o config: roda no python3 da máquina, antes de instalar as dependências do gerador.
"""
from __future__ import annotations

import http.client
import time
import urllib.error
import urllib.parse
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from typing import Any, Callable, List, Optional, Sequence, Tuple

from . import config

TIMEOUT = 20      # segundos de cada tentativa (conexão e leitura)
ATTEMPTS = 3      # um 502 solto é comum (o openstreetmap.fr deu um em 2026-11-23): uma tentativa só seria alarme falso
PAUSE = 5         # segundos entre as tentativas, vezes o número da tentativa

# O Wikidata recebe uma consulta vazia (ASK {}), não a de turismo: a sonda não pesa no serviço deles.
WIKIDATA_PROBE = config.WIKIDATA_SPARQL_URL + "?" + urllib.parse.urlencode({"query": "ASK {}", "format": "json"})
# A API da ANP é lenta e a resposta de uma página é grande: o byte 0 basta, e a UF é a menor.
ANP_PROBE = f"{config.ANP_API_URL}?uf=AC&numeropagina=1"


@dataclass(frozen=True)
class Source:
    name: str
    url: str


def sources(states: Optional[Sequence[str]] = None, osm_local: bool = False) -> List[Source]:
    """As fontes ao vivo de uma geração. `states` escolhe o CNEFE (um zip por UF; basta um para provar o servidor, o
    primeiro pedido); `osm_local` (extrato já baixado, --osm-file) tira o OpenStreetMap."""
    first = sorted(states or config.IBGE_STATE_CODES.values())[0]
    code = next(c for c, s in config.IBGE_STATE_CODES.items() if s == first)
    found = [] if osm_local else [Source("OpenStreetMap, data do extrato", config.OSM_STATE_URL),
                                  Source("OpenStreetMap, extrato do Brasil", config.OSM_PBF_URL)]
    return found + [
        Source("IBGE, localidades", config.IBGE_LOCALITIES_URL),
        Source(f"IBGE, CNEFE ({first})", f"{config.CNEFE_UF_URL}{code}_{first}.zip"),
        Source("CNES, estabelecimentos", config.CNES_URL),
        Source("Overture, versões", config.OVERTURE_LISTING_URL),
        Source("GeoNames, lugares", config.GEONAMES_PLACES_URL),
        Source("GeoNames, nomes alternativos", config.GEONAMES_NAMES_URL),
        Source("Wikidata, SPARQL", WIKIDATA_PROBE),
        Source("ANP, revendedores", ANP_PROBE),
    ]


def probe(url: str, timeout: float = TIMEOUT, attempts: int = ATTEMPTS, pause: float = PAUSE,
          opener: Optional[Callable[..., Any]] = None) -> Tuple[bool, str]:
    """(respondeu?, o que houve): GET de 1 byte, redirecionamentos seguidos, qualquer 2xx vale. Erro de HTTP, de rede
    e tempo esgotado são retentados `attempts` vezes; a última falha é a que volta. O `opener` é só dos testes."""
    open_url = opener or urllib.request.urlopen
    failure = "nenhuma tentativa"
    for attempt in range(1, attempts + 1):
        started = time.monotonic()
        req = urllib.request.Request(url, headers={"User-Agent": config.USER_AGENT, "Range": "bytes=0-0"})
        try:
            with open_url(req, timeout=timeout) as r:
                r.read(1)
                return True, f"HTTP {r.status}, {time.monotonic() - started:.1f} s"
        except urllib.error.HTTPError as e:
            failure = f"HTTP {e.code}"
        except (OSError, http.client.HTTPException) as e:  # URLError, tempo esgotado e conexão caída
            failure = f"{e.__class__.__name__}: {getattr(e, 'reason', None) or e}"
        if attempt < attempts:
            time.sleep(pause * attempt)
    return False, f"{failure} ({attempts} tentativas)"


def check(found: Sequence[Source], **kwargs) -> Tuple[List[str], List[str]]:
    """Sonda todas ao mesmo tempo. Devolve (linhas do log, na ordem das fontes; nomes com o motivo das que não
    responderam)."""
    with ThreadPoolExecutor(max_workers=len(found) or 1) as pool:
        results = list(pool.map(lambda s: probe(s.url, **kwargs), found))
    lines = [f"{'ok  ' if ok else 'FALHA'} {s.name}: {what} <{s.url}>" for s, (ok, what) in zip(found, results)]
    failed = [f"{s.name} ({what})" for s, (ok, what) in zip(found, results) if not ok]
    return lines, failed
