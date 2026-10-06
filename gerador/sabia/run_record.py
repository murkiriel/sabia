"""Registro de uma geração em data/dist/geracao.json: tempo de cada etapa, pico de disco e resultado.

Os números do README (tempo, disco) vêm deste arquivo, não de memória. O pico de disco é amostrado numa thread a cada
`interval` segundos, somando os arquivos de data/: pega os bancos intermediários, que podem ser apagados antes do
fim e não apareceriam numa medição só no final.
"""
from __future__ import annotations

import json
import os
import threading
import time
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterator, List

GB = 1_000_000_000


def folder_size(folder: Path) -> int:
    total = 0
    stack = [str(folder)]
    while stack:
        try:
            with os.scandir(stack.pop()) as dir_entries:
                for item in dir_entries:
                    try:
                        if item.is_dir(follow_symlinks=False):
                            stack.append(item.path)
                        else:
                            total += item.stat(follow_symlinks=False).st_size
                    except OSError:
                        pass  # arquivo apagado entre a listagem e a leitura
        except OSError:
            pass
    return total


class RunRecorder:
    def __init__(self, folder: Path, interval: float = 20.0) -> None:
        self.folder = folder
        self.stages: List[dict] = []
        self.peak = folder_size(folder)
        self.start = datetime.now(timezone.utc)
        self._stop = threading.Event()
        self._thread = threading.Thread(target=self._sample, args=(interval,), daemon=True)
        self._thread.start()

    def _sample(self, interval: float) -> None:
        while not self._stop.wait(interval):
            self.peak = max(self.peak, folder_size(self.folder))

    @contextmanager
    def stage(self, name: str) -> Iterator[None]:
        t0 = time.time()
        status = "failed"
        try:
            yield
            status = "ok"
        finally:
            self.peak = max(self.peak, folder_size(self.folder))
            self.stages.append({"stage": name, "minutes": round((time.time() - t0) / 60, 2), "status": status})

    def save(self, dest: Path, result: str) -> None:
        self._stop.set()
        self._thread.join(timeout=5)
        self.peak = max(self.peak, folder_size(self.folder))
        data = {
            "started_at": self.start.strftime("%Y-%m-%dT%H:%M:%SZ"),
            "finished_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
            "result": result,
            "stages": self.stages,
            "total_minutes": round(sum(e["minutes"] for e in self.stages), 2),
            "peak_disk_gb": round(self.peak / GB, 6),
        }
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
