"""Põe as issues fixas do workflow gerar de acordo com o resultado de uma execução agendada.

    python scripts/alert.py --interval failure --generate skipped --run-url https://github.com/.../runs/123

`--interval` e `--generate` são os resultados dos jobs (success, failure, cancelled, skipped). Duas issues: "Geração
falhando" e "Publicação parada" (a idade da geração publicada, lida de `--catalog`). A lógica fica em sabia/alert.py;
o gh precisa de GH_TOKEN com permissão de escrever issues.
"""
from __future__ import annotations

import argparse
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional, Sequence

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from sabia import alert, config, schedule  # noqa: E402


def main(argv: Optional[Sequence[str]] = None, gh: alert.Gh = alert.gh_real,
         now: Optional[datetime] = None) -> None:
    for stream in (sys.stdout, sys.stderr):  # acentos certos também com a saída redirecionada para arquivo
        try:
            stream.reconfigure(encoding="utf-8", errors="replace")  # type: ignore[union-attr]
        except (AttributeError, ValueError):
            pass
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--interval", required=True, help="resultado do job interval")
    ap.add_argument("--generate", required=True, help="resultado do job generate")
    ap.add_argument("--run-url", required=True, help="link da execução")
    ap.add_argument("--catalog", type=Path, default=config.REPO / "catalogo.json",
                    help="catálogo publicado, de onde sai a idade da geração (padrão: o da raiz do repositório)")
    args = ap.parse_args(argv)

    moment = now or datetime.now(timezone.utc)
    when = moment.strftime("%Y-%m-%d %H:%M UTC")
    stale, stale_detail = alert.stale_outcome(schedule.catalog_built_at(args.catalog), moment)
    checks = [
        (alert.GENERATION, alert.outcome(args.interval, args.generate), "",
         f"interval {args.interval}, generate {args.generate}"),
        (alert.STALE, stale, stale_detail, stale_detail),
    ]
    # Uma issue que o gh não conseguiu mexer não impede a outra: as duas rodam, e o erro derruba o job no fim.
    errors = []
    for notice, result, detail, shown in checks:
        try:
            done = alert.sync(gh, result, args.run_url, when, notice, detail)
        except alert.AlertError as e:
            errors.append(str(e))
            done = f"ERRO ({e})"
        print(f"{shown} -> {result}; issue \"{notice.title}\": {done}")
    if errors:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
