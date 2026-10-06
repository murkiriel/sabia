"""Quando gerar de novo: a geração publicada tem uma data (`built_at` do catalogo.json), e o agendamento só segue
para o build quando ela completa o intervalo, ou no dia marcado para uma geração extra. A linha de comando fica em
scripts/due.py."""
from __future__ import annotations

import json
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Optional, Tuple


def catalog_built_at(catalog: Path) -> Optional[str]:
    """O `built_at` do catálogo publicado; None se o catálogo não existe, não é JSON ou não tem a data."""
    try:
        built_at = json.loads(catalog.read_text(encoding="utf-8")).get("built_at")
    except (OSError, ValueError, AttributeError):
        return None
    return built_at if isinstance(built_at, str) else None


def generation_due(built_at: Optional[str], now: datetime, interval_days: int,
                   manual: bool = False, generate_from: Optional[date] = None) -> Tuple[bool, str]:
    """(gera?, motivo). Os dias são arredondados, para o horário do build não empurrar a geração para o dia
    seguinte: uma geração que terminou às 07:10 conta 29 dias no agendamento das 06:17 do 29º dia.

    `generate_from` marca uma geração extra, fora do intervalo: a partir desse dia (UTC), gera se a publicada for
    de antes dele, e tenta de novo nos dias seguintes se falhar. Depois de publicar, não tem mais efeito, e o
    intervalo passa a contar da geração extra."""
    if manual:
        return True, "disparado à mão: gera"
    try:
        built = datetime.strptime(built_at or "", "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc)
    except ValueError:
        return True, "sem a data da geração publicada: gera"
    if generate_from and now.date() >= generate_from and built.date() < generate_from:
        return True, f"geração extra marcada para {generate_from} (publicada em {built_at}): gera"
    days = (now - built + timedelta(hours=12)) // timedelta(days=1)
    if days >= interval_days:
        return True, f"geração publicada em {built_at} ({days} dias): gera"
    return False, f"geração publicada em {built_at} ({days} dias): ainda não, gera ao completar {interval_days} dias"
