"""A regra do agendamento: gera de novo quando a geração publicada completa o intervalo (29 dias)."""
import json
import os
import subprocess
import sys
import tempfile
import unittest
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

GENERATOR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(GENERATOR))
from sabia import config, schedule  # noqa: E402

BUILT = "2026-09-30T18:21:32Z"


def utc(text: str) -> datetime:
    return datetime.strptime(text, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc)


def after(**delta) -> datetime:
    return utc(BUILT) + timedelta(**delta)


class GenerationDueTest(unittest.TestCase):
    def due(self, built_at, now, **kwargs):
        return schedule.generation_due(built_at, now, 29, **kwargs)[0]

    def test_default_interval_is_29_days(self):
        self.assertEqual(29, config.GENERATION_INTERVAL_DAYS)

    def test_28_days_is_too_early(self):
        self.assertFalse(self.due(BUILT, after(days=28)))

    def test_29_days_generates(self):
        self.assertTrue(self.due(BUILT, after(days=29)))

    def test_days_are_rounded(self):
        """28 dias e 13 h já contam como 29: o horário do build não empurra a geração para o dia seguinte."""
        self.assertTrue(self.due(BUILT, after(days=28, hours=13)))
        self.assertFalse(self.due(BUILT, after(days=28, hours=11)))

    def test_scheduled_run_after_a_scheduled_build(self):
        """Geração agendada termina por volta das 07:10 UTC; 29 dias depois, o agendamento das 06:17 já gera."""
        self.assertTrue(self.due("2026-10-30T07:10:00Z", utc("2026-11-28T06:17:00Z")))
        self.assertFalse(self.due("2026-10-30T07:10:00Z", utc("2026-11-27T06:17:00Z")))
        self.assertFalse(self.due("2026-10-30T07:10:00Z", utc("2026-11-27T12:17:00Z")))

    def test_first_scheduled_generation_after_the_manual_one(self):
        self.assertFalse(self.due(BUILT, utc("2026-10-29T06:00:00Z")))
        self.assertTrue(self.due(BUILT, utc("2026-10-30T06:00:00Z")))

    def test_no_published_date_generates(self):
        self.assertTrue(self.due(None, after(days=1)))

    def test_unreadable_date_generates(self):
        self.assertTrue(self.due("ontem", after(days=1)))

    def test_manual_always_generates(self):
        self.assertTrue(self.due(BUILT, after(hours=1), manual=True))

    def test_reason_says_the_age(self):
        due, reason = schedule.generation_due(BUILT, after(days=10), 29)
        self.assertFalse(due)
        self.assertIn("10 dias", reason)
        self.assertIn("29", reason)


class ExtraGenerationTest(unittest.TestCase):
    """Uma geração extra, fora do intervalo: a partir do dia marcado, gera se a publicada for de antes dele."""

    PUBLISHED = "2026-10-01T18:35:31Z"
    MARKED = date(2026, 10, 2)

    def due(self, built_at, now, generate_from=MARKED):
        return schedule.generation_due(built_at, utc(now), 29, generate_from=generate_from)

    def test_before_the_marked_day_it_waits(self):
        self.assertFalse(self.due(self.PUBLISHED, "2026-10-01T23:59:00Z")[0])

    def test_on_the_marked_day_it_generates(self):
        due, reason = self.due(self.PUBLISHED, "2026-10-02T06:17:00Z")
        self.assertTrue(due)
        self.assertIn("2026-10-02", reason)

    def test_keeps_trying_on_the_following_days_until_it_publishes(self):
        self.assertTrue(self.due(self.PUBLISHED, "2026-10-02T12:17:00Z")[0])
        self.assertTrue(self.due(self.PUBLISHED, "2026-10-05T06:17:00Z")[0])

    def test_once_published_it_has_no_effect(self):
        """O segundo disparo do dia, e os dos dias seguintes, só conferem a data e param."""
        self.assertFalse(self.due("2026-10-02T07:10:00Z", "2026-10-02T12:17:00Z")[0])
        self.assertFalse(self.due("2026-10-02T07:10:00Z", "2026-10-03T06:17:00Z")[0])

    def test_the_interval_goes_on_counting_from_the_extra_generation(self):
        self.assertFalse(self.due("2026-10-02T07:10:00Z", "2026-10-30T06:17:00Z")[0])
        self.assertTrue(self.due("2026-10-02T07:10:00Z", "2026-10-31T06:17:00Z")[0])

    def test_without_a_marked_day_only_the_interval_counts(self):
        self.assertFalse(self.due(self.PUBLISHED, "2026-10-02T06:17:00Z", generate_from=None)[0])

    def test_a_marked_day_does_not_hold_back_the_interval(self):
        """Um dia marcado no futuro não impede a geração que o intervalo já pede."""
        self.assertTrue(self.due("2026-09-01T07:10:00Z", "2026-10-01T06:17:00Z")[0])


class CatalogBuiltAtTest(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())

    def test_reads_built_at(self):
        f = self.tmp / "catalogo.json"
        f.write_text(json.dumps({"built_at": BUILT}), encoding="utf-8")
        self.assertEqual(BUILT, schedule.catalog_built_at(f))

    def test_missing_catalog(self):
        self.assertIsNone(schedule.catalog_built_at(self.tmp / "catalogo.json"))

    def test_broken_catalog(self):
        f = self.tmp / "catalogo.json"
        f.write_text("<html>", encoding="utf-8")
        self.assertIsNone(schedule.catalog_built_at(f))

    def test_catalog_without_the_date(self):
        f = self.tmp / "catalogo.json"
        f.write_text(json.dumps({"schema": 1}), encoding="utf-8")
        self.assertIsNone(schedule.catalog_built_at(f))


class DueScriptTest(unittest.TestCase):
    """A linha de comando que o workflow chama: imprime o motivo e grava run=true|false em $GITHUB_OUTPUT."""

    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.output = self.tmp / "github_output"

    def run_script(self, built_at, *args):
        catalog = self.tmp / "catalogo.json"
        if built_at is not None:
            catalog.write_text(json.dumps({"built_at": built_at}), encoding="utf-8")
        env = {**os.environ, "GITHUB_OUTPUT": str(self.output)}
        r = subprocess.run([sys.executable, str(GENERATOR / "scripts" / "due.py"), "--catalog", str(catalog), *args],
                           capture_output=True, text=True, encoding="utf-8", env=env)
        self.assertEqual(0, r.returncode, r.stderr)
        return self.output.read_text(encoding="utf-8"), r.stdout

    def stamp(self, days_ago: int) -> str:
        return (datetime.now(timezone.utc) - timedelta(days=days_ago)).strftime("%Y-%m-%dT%H:%M:%SZ")

    def test_recent_generation(self):
        output, log = self.run_script(self.stamp(3))
        self.assertEqual("run=false\n", output)
        self.assertIn("3 dias", log)

    def test_old_generation(self):
        self.assertEqual("run=true\n", self.run_script(self.stamp(40))[0])

    def test_no_catalog(self):
        self.assertEqual("run=true\n", self.run_script(None)[0])

    def test_manual(self):
        self.assertEqual("run=true\n", self.run_script(self.stamp(3), "--manual")[0])

    def test_interval_from_the_command_line(self):
        self.assertEqual("run=true\n", self.run_script(self.stamp(3), "--interval-days", "2")[0])

    def test_extra_generation_from_the_command_line(self):
        today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        output, log = self.run_script(self.stamp(3), "--generate-from", today)
        self.assertEqual("run=true\n", output)
        self.assertIn(today, log)

    def test_empty_extra_generation_means_none(self):
        """O workflow passa a variável mesmo vazia: vazio é "só o intervalo"."""
        self.assertEqual("run=false\n", self.run_script(self.stamp(3), "--generate-from", "")[0])

    def test_extra_generation_that_is_not_a_date_is_refused(self):
        r = subprocess.run([sys.executable, str(GENERATOR / "scripts" / "due.py"), "--generate-from", "amanhã"],
                           capture_output=True, text=True, encoding="utf-8",
                           env={**os.environ, "GITHUB_OUTPUT": str(self.output)})
        self.assertNotEqual(0, r.returncode)
        self.assertFalse(self.output.exists(), "não pode decidir nada com uma data que não leu")


if __name__ == "__main__":
    unittest.main()
