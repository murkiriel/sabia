"""Os avisos em issues (sabia/alert.py, scripts/alert.py), com um `gh` falso em memória: NENHUM teste aqui chama o
GitHub nem o programa gh."""
import importlib.util
import io
import json
import sys
import tempfile
import unittest
from contextlib import redirect_stdout
from datetime import datetime, timedelta, timezone
from pathlib import Path

GENERATOR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(GENERATOR))
from sabia import alert  # noqa: E402

RUN = "https://github.com/x/y/actions/runs/1"
WHEN = "2026-12-09 14:50 UTC"
BUILT = "2026-11-10T07:10:00Z"


def utc(text: str) -> datetime:
    return datetime.strptime(text, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc)


class FakeGh:
    """O `gh` com as issues numa lista: guarda cada chamada e responde como o gh responderia."""

    def __init__(self, open_titles=(), fail_on=None, label_ok=True):
        self.issues = {i + 1: t for i, t in enumerate(open_titles)}
        self.calls = []
        self.fail_on = fail_on
        self.label_ok = label_ok

    def __call__(self, args):
        args = list(args)
        self.calls.append(args)
        if self.fail_on and args[:2] == self.fail_on:
            return 1, "", "HTTP 403"
        if args[:2] == ["issue", "list"]:
            return 0, json.dumps([{"number": n, "title": t} for n, t in self.issues.items()]), ""
        if args[:2] == ["label", "create"]:
            return (0 if self.label_ok else 1), "", ""
        if args[:2] == ["issue", "create"]:
            self.issues[max(self.issues, default=0) + 1] = args[args.index("--title") + 1]
        if args[:2] == ["issue", "close"]:
            del self.issues[int(args[2])]
        return 0, "", ""

    def verbs(self):
        return [" ".join(c[:2]) for c in self.calls]


class OutcomeTest(unittest.TestCase):
    def test_generate_failure_or_interval_failure_is_a_failure(self):
        self.assertEqual("falhou", alert.outcome("success", "failure"))
        self.assertEqual("falhou", alert.outcome("failure", "skipped"))

    def test_published_generation_is_ok(self):
        self.assertEqual("ok", alert.outcome("success", "success"))

    def test_not_due_or_cancelled_says_nothing(self):
        self.assertEqual("nada", alert.outcome("success", "skipped"))
        self.assertEqual("nada", alert.outcome("success", "cancelled"))
        self.assertEqual("nada", alert.outcome("cancelled", "skipped"))


class StaleTest(unittest.TestCase):
    def test_limit_is_the_cycle_plus_six_days(self):
        self.assertEqual(35, alert.STALE_DAYS)

    def stale(self, **delta):
        return alert.stale_outcome(BUILT, utc(BUILT) + timedelta(**delta))

    def test_up_to_35_days_is_ok(self):
        self.assertEqual("ok", self.stale(days=29)[0])
        self.assertEqual("ok", self.stale(days=35)[0])

    def test_over_35_days_fails_and_says_how_old(self):
        result, detail = self.stale(days=35, hours=1)
        self.assertEqual("falhou", result)
        self.assertIn("35,0 dias", detail.replace(".", ","))
        self.assertIn("limite de 35 dias", detail)
        self.assertIn(BUILT, detail)

    def test_no_date_says_nothing(self):
        for built_at in (None, "", "ontem"):
            self.assertEqual("nada", alert.stale_outcome(built_at, utc(BUILT))[0], built_at)


class SyncTest(unittest.TestCase):
    def sync(self, gh, result, notice=alert.GENERATION, detail=""):
        return alert.sync(gh, result, RUN, WHEN, notice, detail)

    def test_failure_opens_the_issue_with_the_run_link_and_the_label(self):
        gh = FakeGh()
        self.assertEqual("aberta", self.sync(gh, "falhou"))
        create = gh.calls[-1]
        self.assertEqual(["issue", "create"], create[:2])
        self.assertEqual("Geração falhando", create[create.index("--title") + 1])
        self.assertIn(RUN, create[create.index("--body") + 1])
        self.assertEqual(alert.LABEL, create[create.index("--label") + 1])
        self.assertEqual(["label create", "issue create"], [v for v in gh.verbs() if v != "issue list"])

    def test_failure_without_the_label_still_opens_the_issue(self):
        gh = FakeGh(label_ok=False)
        self.assertEqual("aberta", self.sync(gh, "falhou"))
        self.assertNotIn("--label", gh.calls[-1])

    def test_failure_with_the_issue_open_only_comments(self):
        gh = FakeGh(["Geração falhando"])
        self.assertEqual("comentada", self.sync(gh, "falhou"))
        self.assertEqual(["issue list", "issue comment"], gh.verbs())
        self.assertEqual("1", gh.calls[-1][2])
        self.assertIn(RUN, gh.calls[-1][-1])

    def test_ok_closes_the_open_issue(self):
        gh = FakeGh(["outra", "Geração falhando"])
        self.assertEqual("fechada", self.sync(gh, "ok"))
        self.assertEqual({1: "outra"}, gh.issues)
        self.assertIn(RUN, gh.calls[-1][-1])

    def test_ok_without_an_open_issue_does_nothing(self):
        gh = FakeGh(["outra"])
        self.assertEqual("nada", self.sync(gh, "ok"))
        self.assertEqual(["issue list"], gh.verbs())

    def test_nothing_to_check_never_calls_github(self):
        gh = FakeGh()
        self.assertEqual("nada", self.sync(gh, "nada"))
        self.assertEqual([], gh.calls)

    def test_title_must_match_exactly(self):
        gh = FakeGh(["Geração falhando em SP", "geração falhando"])
        self.assertEqual("aberta", self.sync(gh, "falhou"))

    def test_the_two_issues_are_independent(self):
        gh = FakeGh(["Publicação parada"])
        self.assertEqual("aberta", self.sync(gh, "falhou"))
        self.assertEqual("fechada", self.sync(gh, "ok", alert.STALE, "a geração publicada é de x (1,0 dias)"))
        self.assertEqual(["Geração falhando"], list(gh.issues.values()))

    def test_stale_text_carries_the_detail(self):
        gh = FakeGh()
        self.sync(gh, "falhou", alert.STALE, "a geração publicada é de X (40,0 dias)")
        self.assertIn("a geração publicada é de X (40,0 dias)", gh.calls[-1][gh.calls[-1].index("--body") + 1])

    def test_gh_error_names_the_command_and_what_it_said(self):
        with self.assertRaises(alert.AlertError) as cm:
            self.sync(FakeGh(fail_on=["issue", "list"]), "falhou")
        self.assertIn("gh issue list", str(cm.exception))
        self.assertIn("403", str(cm.exception))

    def test_texts_are_anonymous_and_fill_every_placeholder(self):
        for notice in (alert.GENERATION, alert.STALE):
            for text in (notice.opening, notice.again, notice.closing):
                self.assertNotIn("{", text.format(when="a", run_url="b", detail="c"))


def load_script():
    spec = importlib.util.spec_from_file_location("alert_script", GENERATOR / "scripts" / "alert.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class ScriptTest(unittest.TestCase):
    def setUp(self):
        self.script = load_script()
        self._tmp = tempfile.TemporaryDirectory()
        self.catalog = Path(self._tmp.name) / "catalogo.json"
        self.now = utc(BUILT) + timedelta(days=40)

    def tearDown(self):
        self._tmp.cleanup()

    def run_script(self, gh, interval="success", generate="skipped", built_at=BUILT):
        self.catalog.write_text(json.dumps({"built_at": built_at}), encoding="utf-8")
        argv = ["--interval", interval, "--generate", generate, "--run-url", RUN, "--catalog", str(self.catalog)]
        out = io.StringIO()
        with redirect_stdout(out):
            self.script.main(argv, gh=gh, now=self.now)
        return out.getvalue()

    def test_old_catalog_opens_the_stale_issue_even_when_the_build_was_skipped(self):
        gh = FakeGh()
        out = self.run_script(gh)
        self.assertEqual(["Publicação parada"], list(gh.issues.values()))
        self.assertIn("Publicação parada", out)

    def test_failed_generation_with_an_old_catalog_opens_both(self):
        gh = FakeGh()
        self.run_script(gh, generate="failure")
        self.assertEqual({"Geração falhando", "Publicação parada"}, set(gh.issues.values()))

    def test_published_generation_closes_both(self):
        gh = FakeGh(["Geração falhando", "Publicação parada"])
        self.run_script(gh, generate="success", built_at="2026-12-19T07:10:00Z")
        self.assertEqual({}, gh.issues)

    def test_a_gh_error_in_one_issue_does_not_stop_the_other_but_fails_the_job(self):
        gh = FakeGh(fail_on=["issue", "comment"], open_titles=["Geração falhando"])
        with self.assertRaises(SystemExit):
            self.run_script(gh, generate="failure")
        self.assertEqual({"Geração falhando", "Publicação parada"}, set(gh.issues.values()))

    def test_no_catalog_does_not_open_the_stale_issue(self):
        gh = FakeGh()
        self.run_script(gh, built_at="")
        self.assertEqual({}, gh.issues)


if __name__ == "__main__":
    unittest.main()
