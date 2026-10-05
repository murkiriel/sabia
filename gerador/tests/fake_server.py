"""Imitação local de um site HTTP para os testes de download: serve arquivos em memória, com Range, quedas e
respostas de erro programadas. Guarda cada requisição (caminho e cabeçalho Range) para os testes conferirem o que o
cliente pediu."""
from __future__ import annotations

import gzip
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Callable, Dict, List, Optional, Tuple, Union

Content = Union[bytes, Callable[[], bytes]]


class FakeServer:
    """`files`: {caminho: bytes ou função que devolve os bytes do momento}. `cut_after[caminho] = n`: nas próximas
    respostas desse caminho, manda o Content-Length inteiro mas fecha a conexão depois de n bytes (uma vez por item
    da lista). `no_range`: caminhos em que a resposta ignora o Range e sempre manda 200. `code[caminho]`: status fixo.
    `gzip_always`: caminhos que vão sempre comprimidos (Content-Encoding: gzip, 200, sem Range), mesmo sem o cliente
    pedir, como o IBGE faz com o urllib nos executores do GitHub Actions."""

    def __init__(self) -> None:
        self.files: Dict[str, Content] = {}
        self.cut_after: Dict[str, List[int]] = {}
        self.no_range: set = set()
        self.code: Dict[str, int] = {}
        self.gzip_always: set = set()
        self.requests: List[Tuple[str, Optional[str]]] = []
        server = self

        class Handler(BaseHTTPRequestHandler):
            def log_message(self, *args):  # silencioso
                pass

            def do_GET(self):
                server.requests.append((self.path, self.headers.get("Range")))
                if self.path in server.code:
                    self.send_response(server.code[self.path])
                    self.send_header("Content-Length", "0")
                    self.end_headers()
                    return
                content = server.files.get(self.path)
                if content is None:
                    self.send_response(404)
                    self.send_header("Content-Length", "0")
                    self.end_headers()
                    return
                data = content() if callable(content) else content
                if self.path in server.gzip_always:
                    body = gzip.compress(data)
                    self.send_response(200)
                    self.send_header("Content-Encoding", "gzip")
                    self.send_header("Content-Length", str(len(body)))
                    self.end_headers()
                    self.wfile.write(body)
                    return
                start = 0
                range_header = self.headers.get("Range")
                if range_header and self.path not in server.no_range:
                    start = int(range_header.split("=")[1].split("-")[0])
                    if start >= len(data):
                        self.send_response(416)
                        self.send_header("Content-Range", f"bytes */{len(data)}")
                        self.send_header("Content-Length", "0")
                        self.end_headers()
                        return
                    self.send_response(206)
                    self.send_header("Content-Range", f"bytes {start}-{len(data) - 1}/{len(data)}")
                else:
                    self.send_response(200)
                body = data[start:]
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                cuts = server.cut_after.get(self.path)
                if cuts:
                    n = cuts.pop(0)
                    self.wfile.write(body[:n])
                    self.wfile.flush()
                    self.close_connection = True
                    return
                self.wfile.write(body)

        self._http = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self.base = f"http://127.0.0.1:{self._http.server_address[1]}"
        self._thread = threading.Thread(target=self._http.serve_forever, daemon=True)

    def __enter__(self) -> "FakeServer":
        self._thread.start()
        return self

    def __exit__(self, *exc) -> None:
        self._http.shutdown()
        self._http.server_close()

    def url(self, path: str) -> str:
        return self.base + path
