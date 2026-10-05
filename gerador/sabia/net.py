"""Downloads que aguentam rede ruim: retomada de onde parou, retentativa só do que é passageiro.

- O arquivo vai para `<destino>.parcial` e só vira `<destino>` completo: nunca sobra um arquivo pela metade com o nome
  final. O tamanho recebido é conferido contra o Content-Length; conexão que cai antes do fim conta como falha.
- Numa nova tentativa, o `.parcial` é retomado com `Range: bytes=<tamanho>-`. Um site que ignora o Range (responde
  200) faz recomeçar do zero.
- `identity` (ex.: o md5 publicado do arquivo) fica gravada ao lado do `.parcial`: uma sobra de OUTRA versão do
  arquivo é descartada em vez de emendada com a nova.
- Corpo comprimido (Content-Encoding gzip ou deflate) é descomprimido na hora de gravar. O urllib não pede
  compressão, mas há site que manda assim mesmo (o IBGE, para os executores do GitHub Actions).
- Erro permanente (4xx, exceto 408 e 429) falha na hora, sem esperar. Os demais (5xx, conexão, tempo esgotado) são
  retentados com espera crescente.
"""
from __future__ import annotations

import http.client
import time
import urllib.error
import urllib.request
import zlib
from pathlib import Path
from typing import Optional

from . import config
from .util import CHUNK

RETRYABLE_4XX = {408, 429}


class DownloadError(RuntimeError):
    """Todas as tentativas falharam."""


class PermanentError(DownloadError):
    """O site respondeu com um erro que não passa tentando de novo (ex.: 404)."""


def _open(url: str, timeout: float, headers: Optional[dict] = None):
    req = urllib.request.Request(url, headers={"User-Agent": config.USER_AGENT, **(headers or {})})
    return urllib.request.urlopen(req, timeout=timeout)


def _decoder(url: str, r):
    """Descompressor do corpo, ou None se ele veio sem compressão."""
    encoding = (r.headers.get("Content-Encoding") or "identity").strip().lower()
    if encoding == "identity":
        return None
    if encoding in ("gzip", "x-gzip"):
        return zlib.decompressobj(16 + zlib.MAX_WBITS)
    if encoding == "deflate":
        return zlib.decompressobj()
    raise PermanentError(f"{url}: Content-Encoding {encoding} não suportado")


def _is_permanent(e: urllib.error.HTTPError) -> bool:
    return 400 <= e.code < 500 and e.code not in RETRYABLE_4XX


def _origin_path(partial: Path) -> Path:
    return partial.with_name(partial.name + ".origem")


def mark_origin(partial: Path, identity: str) -> None:
    """Grava de qual versão do arquivo o `.parcial` é (usado também pelos testes)."""
    _origin_path(partial).write_text(identity, encoding="utf-8")


def fetch_text(url: str, attempts: int = 3, delay: float = 5) -> str:
    """O corpo da resposta como texto UTF-8."""
    for attempt in range(1, attempts + 1):
        try:
            with _open(url, timeout=60) as r:
                body = r.read()
                decoder = _decoder(url, r)
            if decoder is not None:
                body = decoder.decompress(body) + decoder.flush()
            return body.decode("utf-8")
        except urllib.error.HTTPError as e:
            if _is_permanent(e):
                raise PermanentError(f"{url}: HTTP {e.code}") from e
            error: Exception = e
        except (OSError, http.client.HTTPException) as e:
            error = e
        if attempt < attempts:
            time.sleep(delay * attempt)
    raise DownloadError(f"{url}: {attempts} tentativas falharam ({error})")


def download(url: str, dest: Path, identity: Optional[str] = None, attempts: int = 5, delay: float = 10,
             timeout: float = 120) -> None:
    """Baixa `url` para `dest`, retomando de onde parou entre tentativas."""
    partial = dest.with_name(dest.name + ".parcial")
    origin = _origin_path(partial)
    if partial.exists() and (identity is None or not origin.exists()
                             or origin.read_text(encoding="utf-8") != identity):
        partial.unlink()  # sobra de outra versão (ou de origem desconhecida): não dá para emendar
    if identity is not None:
        mark_origin(partial, identity)

    error: Exception = DownloadError("nenhuma tentativa")
    for attempt in range(1, attempts + 1):
        start = partial.stat().st_size if partial.exists() else 0
        headers = {"Range": f"bytes={start}-"} if start else {}
        try:
            with _open(url, timeout, headers) as r:
                decoder = _decoder(url, r)
                if decoder is not None and r.status == 206:
                    # O Range vale sobre os bytes comprimidos; o .parcial guarda os descomprimidos. Recomeça sem Range.
                    partial.unlink()
                    raise DownloadError("resposta parcial comprimida")
                if start and r.status == 206:
                    mode, already_had = "ab", start
                else:  # 200: começa do zero (inclusive quando o site ignorou o Range)
                    mode, already_had = "wb", 0
                expected = r.headers.get("Content-Length")
                received = 0
                with open(partial, mode) as f:
                    while chunk := r.read(CHUNK):
                        f.write(decoder.decompress(chunk) if decoder is not None else chunk)
                        received += len(chunk)
                    if decoder is not None:
                        f.write(decoder.flush())
                if expected is not None and received != int(expected):
                    raise DownloadError(f"conexão caiu: {already_had + received} bytes de "
                                        f"{already_had + int(expected)}")
                if decoder is not None and not decoder.eof:
                    raise DownloadError("conexão caiu: corpo comprimido incompleto")
            partial.replace(dest)
            if origin.exists():
                origin.unlink()
            return
        except PermanentError:
            raise
        except urllib.error.HTTPError as e:
            if e.code == 416:  # o .parcial já passou do tamanho do arquivo: recomeça
                partial.unlink(missing_ok=True)
                error = e
            elif _is_permanent(e):
                raise PermanentError(f"{url}: HTTP {e.code}") from e
            else:
                error = e
        except (OSError, http.client.HTTPException, DownloadError) as e:
            error = e
        if attempt < attempts:
            time.sleep(delay * attempt)
    raise DownloadError(f"{url}: {attempts} tentativas falharam ({error})")
