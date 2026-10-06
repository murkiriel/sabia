"""O SQLite mais antigo que os pacotes precisam abrir (3.22, o do Android 10), carregado com ctypes para a trava G7e.

A biblioteca é instalada por scripts/install_sqlite.py em data/tools/: no Linux, compilada do código-fonte oficial
(amalgamation) com só FTS3 e FTS4, como o Android (sem FTS5, sem R-Tree e sem a sintaxe estendida do FTS); no Windows,
a DLL oficial (que traz FTS5 e R-Tree: lá a trava de esquema, `validation.schema_problems`, cobre o que ela não
recusaria). SABIA_SQLITE_OLD aponta para outro arquivo.

`connect(path).execute(sql, params)` devolve a lista de linhas, como o sqlite3 do Python, para a busca de referência
(search.py) rodar igual nos dois.
"""
from __future__ import annotations

import ctypes
import os
import sys
from pathlib import Path
from typing import List, Sequence

from . import config

VERSION = "3.22.0"
SQLITE_OK, SQLITE_ROW, SQLITE_DONE = 0, 100, 101
SQLITE_OPEN_READONLY = 0x00000001
SQLITE_INTEGER, SQLITE_FLOAT, SQLITE_TEXT, SQLITE_BLOB, SQLITE_NULL = 1, 2, 3, 4, 5
SQLITE_TRANSIENT = ctypes.c_void_p(-1)


def library_path() -> Path:
    env = os.environ.get("SABIA_SQLITE_OLD")
    if env:
        return Path(env)
    name = "sqlite3-3220000.dll" if sys.platform == "win32" else "libsqlite3-3220000.so"
    return config.DATA / "tools" / name


class SqliteError(RuntimeError):
    pass


class Library:
    def __init__(self, path: Path) -> None:
        lib = ctypes.CDLL(str(path))
        p, i, c = ctypes.c_void_p, ctypes.c_int, ctypes.c_char_p
        lib.sqlite3_libversion.restype = c
        lib.sqlite3_open_v2.argtypes = [c, ctypes.POINTER(p), i, c]
        lib.sqlite3_close.argtypes = [p]
        lib.sqlite3_errmsg.argtypes = [p]
        lib.sqlite3_errmsg.restype = c
        lib.sqlite3_prepare_v2.argtypes = [p, c, i, ctypes.POINTER(p), ctypes.POINTER(p)]
        lib.sqlite3_step.argtypes = [p]
        lib.sqlite3_finalize.argtypes = [p]
        lib.sqlite3_bind_text.argtypes = [p, i, c, i, p]
        lib.sqlite3_bind_int64.argtypes = [p, i, ctypes.c_int64]
        lib.sqlite3_bind_double.argtypes = [p, i, ctypes.c_double]
        lib.sqlite3_column_count.argtypes = [p]
        lib.sqlite3_column_type.argtypes = [p, i]
        lib.sqlite3_column_int64.argtypes = [p, i]
        lib.sqlite3_column_int64.restype = ctypes.c_int64
        lib.sqlite3_column_double.argtypes = [p, i]
        lib.sqlite3_column_double.restype = ctypes.c_double
        lib.sqlite3_column_text.argtypes = [p, i]
        lib.sqlite3_column_text.restype = ctypes.POINTER(ctypes.c_char)
        lib.sqlite3_column_blob.argtypes = [p, i]
        lib.sqlite3_column_blob.restype = p
        lib.sqlite3_column_bytes.argtypes = [p, i]
        self.lib = lib

    @property
    def version(self) -> str:
        return self.lib.sqlite3_libversion().decode()

    def connect(self, path: Path) -> "Connection":
        handle = ctypes.c_void_p()
        rc = self.lib.sqlite3_open_v2(str(path).encode(), ctypes.byref(handle), SQLITE_OPEN_READONLY, None)
        if rc != SQLITE_OK:
            raise SqliteError(f"não abriu {path} (código {rc})")
        return Connection(self.lib, handle)


class Connection:
    def __init__(self, lib, handle: ctypes.c_void_p) -> None:
        self.lib = lib
        self.handle = handle

    def _error(self, what: str) -> SqliteError:
        return SqliteError(f"{what}: {self.lib.sqlite3_errmsg(self.handle).decode(errors='replace')}")

    def execute(self, sql: str, params: Sequence = ()) -> List[tuple]:
        stmt = ctypes.c_void_p()
        if self.lib.sqlite3_prepare_v2(self.handle, sql.encode(), -1, ctypes.byref(stmt), None) != SQLITE_OK:
            raise self._error(sql)
        try:
            for n, value in enumerate(params, 1):
                if isinstance(value, int):
                    self.lib.sqlite3_bind_int64(stmt, n, value)
                elif isinstance(value, float):
                    self.lib.sqlite3_bind_double(stmt, n, value)
                else:
                    self.lib.sqlite3_bind_text(stmt, n, str(value).encode(), -1, SQLITE_TRANSIENT)
            rows: List[tuple] = []
            while True:
                rc = self.lib.sqlite3_step(stmt)
                if rc == SQLITE_DONE:
                    return rows
                if rc != SQLITE_ROW:
                    raise self._error(sql)
                rows.append(tuple(self._column(stmt, i) for i in range(self.lib.sqlite3_column_count(stmt))))
        finally:
            self.lib.sqlite3_finalize(stmt)

    def _column(self, stmt, i: int):
        kind = self.lib.sqlite3_column_type(stmt, i)
        if kind == SQLITE_INTEGER:
            return self.lib.sqlite3_column_int64(stmt, i)
        if kind == SQLITE_FLOAT:
            return self.lib.sqlite3_column_double(stmt, i)
        if kind == SQLITE_TEXT:
            n = self.lib.sqlite3_column_bytes(stmt, i)
            return ctypes.string_at(self.lib.sqlite3_column_text(stmt, i), n).decode()
        if kind == SQLITE_BLOB:
            n = self.lib.sqlite3_column_bytes(stmt, i)
            return ctypes.string_at(self.lib.sqlite3_column_blob(stmt, i), n) if n else b""
        return None

    def close(self) -> None:
        self.lib.sqlite3_close(self.handle)
