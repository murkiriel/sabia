"""Avisos do workflow gerar, em issues fixas do repositório: "Geração falhando" e "Publicação parada".

De 2026-11-04 a 2026-11-10, 12 gerações agendadas falharam (IBGE, DNIT e ANTT não respondiam ao Actions) sem ninguém
saber: o GitHub só manda e-mail para quem editou o cron por último, e só com as notificações de Actions ligadas. Uma
issue notifica quem acompanha o repositório e fica visível na página dele.

O job `notify` do workflow gerar chama scripts/alert.py no fim de toda execução agendada. Para cada issue, o mesmo
desenho: falhou, abre a issue (ou comenta nela, se já estiver aberta) com o link da execução; deu certo, comenta e
fecha, se estiver aberta; não houve o que conferir, não faz nada, nem consulta o GitHub.
- "Geração falhando": o interval ou o generate falhou; passou quando o generate gerou e publicou.
- "Publicação parada": a geração publicada (`built_at` do catalogo.json) tem mais de `STALE_DAYS` dias. Cobre o que a
  outra não vê: o agendamento do GitHub que não dispara, o interval que diz "ainda não" por engano, uma release que não
  sobe. Confere em todo disparo agendado, mesmo quando o build é pulado.

Só a stdlib e o config: o job roda no python3 da máquina, sem instalar as dependências do gerador.
"""
from __future__ import annotations

import json
import subprocess
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Callable, Optional, Sequence, Tuple

from . import config

# A geração é de 29 dias: a próxima já devia ter saído, e mais 6 dias de folga cobrem um agendamento atrasado (7 a
# 8 horas em 2026-11), uma falha que o disparo seguinte conserta e uma fonte que volta depois de alguns dias (a
# geração de 2026-11 saiu com 6 dias de atraso e só avisaria no 7º).
STALE_DAYS = 35

# O rótulo das duas issues; criado na primeira vez que uma abre.
LABEL = "alerta-geracao"
LABEL_DESCRIPTION = "Aviso automático do workflow gerar"

Gh = Callable[[Sequence[str]], Tuple[int, str, str]]


class AlertError(RuntimeError):
    """Um comando do gh falhou; a mensagem traz o comando e o que o gh disse."""


def gh_real(args: Sequence[str]) -> Tuple[int, str, str]:
    """O `gh` de verdade, no repositório do projeto."""
    r = subprocess.run(["gh", *args, "--repo", config.GITHUB_REPO], capture_output=True, text=True)
    return r.returncode, r.stdout, r.stderr


def _run(gh: Gh, args: Sequence[str]) -> str:
    code, output, error = gh(list(args))
    if code != 0:
        raise AlertError(f"gh {' '.join(args[:2])} falhou (código {code}): {error.strip() or output.strip()}")
    return output


@dataclass(frozen=True)
class Notice:
    """Uma issue fixa: o título e os textos de abrir, comentar e fechar. `{when}`, `{run_url}` e `{detail}` entram."""
    title: str
    opening: str
    again: str
    closing: str


GENERATION = Notice(
    "Geração falhando",
    "A geração agendada de {when} falhou: {run_url}\n\n"
    "A release publicada continua valendo. O disparo seguinte tenta de novo (duas vezes por dia); cada nova falha "
    "comenta aqui, e esta issue fecha sozinha na primeira geração agendada que passar. Se a causa for uma fonte que "
    "não responde ao Actions, o log do passo \"Fontes respondem?\" diz qual.",
    "Falhou de novo em {when}: {run_url}",
    "A geração agendada de {when} passou: {run_url}")

STALE = Notice(
    "Publicação parada",
    "{detail}\n\nA geração já devia ter saído: o agendamento pode não ter disparado, o job interval pode ter dito "
    "\"ainda não\" por engano ou a release pode não ter subido. Execução que conferiu: {run_url}\n\n"
    "Cada conferência seguinte comenta aqui, e esta issue fecha sozinha quando a geração publicada voltar a ser "
    "recente.",
    "Segue parada em {when}: {detail} ({run_url})",
    "A geração publicada voltou a ser recente em {when}: {detail} ({run_url})")


def outcome(interval: str, generate: str) -> str:
    """'falhou', 'ok' ou 'nada', a partir dos resultados dos jobs (success, failure, cancelled, skipped). Pulado
    (o interval disse "ainda não") ou cancelado não diz nada: a issue fica como está."""
    if interval == "failure" or generate == "failure":
        return "falhou"
    if generate == "success":
        return "ok"
    return "nada"


def stale_outcome(built_at: Optional[str], now: datetime) -> Tuple[str, str]:
    """('falhou', 'ok' ou 'nada', detalhe) para a idade da geração publicada. Sem a data não dá para dizer: 'nada'
    (o job interval já manda gerar quando o catálogo não tem `built_at`)."""
    try:
        built = datetime.strptime(built_at or "", "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc)
    except ValueError:
        return "nada", "o catálogo publicado não tem a data da geração"
    age = now - built
    detail = f"a geração publicada é de {built_at} ({age.total_seconds() / 86400:.1f} dias)"
    if age > timedelta(days=STALE_DAYS):
        return "falhou", f"{detail}, mais velha que o limite de {STALE_DAYS} dias"
    return "ok", detail


def open_issue(gh: Gh, title: str) -> Optional[int]:
    """O número da issue aberta com o título exato, ou None. A lista, e não a busca, que demora a ver issue nova."""
    issues = json.loads(_run(gh, ["issue", "list", "--state", "open", "--limit", "200", "--json", "number,title"]))
    numbers = [i["number"] for i in issues if i.get("title") == title]
    return min(numbers) if numbers else None


def _ensure_label(gh: Gh) -> bool:
    """Cria o rótulo (ou atualiza, se já existe). False se o gh recusou: a issue abre sem rótulo, que o aviso vale
    mais que o enfeite."""
    code, _, _ = gh(["label", "create", LABEL, "--description", LABEL_DESCRIPTION, "--color", "B60205", "--force"])
    return code == 0


def sync(gh: Gh, result: str, run_url: str, when: str, notice: Notice = GENERATION, detail: str = "") -> str:
    """Põe a issue de `notice` de acordo com o resultado. Devolve o que fez: aberta, comentada, fechada ou nada."""
    if result not in ("falhou", "ok"):
        return "nada"
    text = dict(when=when, run_url=run_url, detail=detail)
    number = open_issue(gh, notice.title)
    if result == "falhou":
        if number is None:
            create = ["issue", "create", "--title", notice.title, "--body", notice.opening.format(**text)]
            if _ensure_label(gh):
                create += ["--label", LABEL]
            _run(gh, create)
            return "aberta"
        _run(gh, ["issue", "comment", str(number), "--body", notice.again.format(**text)])
        return "comentada"
    if number is None:
        return "nada"
    _run(gh, ["issue", "close", str(number), "--comment", notice.closing.format(**text)])
    return "fechada"
