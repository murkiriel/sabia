"""Limpeza das releases antigas, com um `gh` falso em memória: NENHUM teste aqui chama o GitHub nem o programa gh."""
import json
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from sabia import publishing  # noqa: E402

G1, G2, G3, G4, G5 = ("2026-06-05-aaaaaaaa", "2026-07-04-bbbbbbbb", "2026-08-02-cccccccc", "2026-08-31-dddddddd",
                      "2026-09-29-eeeeeeee")


def release(tag, draft=False, published_at=None):
    return {"tagName": tag, "isDraft": draft, "publishedAt": published_at or f"{tag[:10]}T06:40:00Z"}


class ReleasesToDeleteTest(unittest.TestCase):
    def test_keeps_the_three_most_recent(self):
        releases = [release(t) for t in (G3, G5, G1, G4, G2)]
        self.assertEqual([G1, G2], publishing.releases_to_delete(releases, G5, keep=3))

    def test_nothing_to_delete_up_to_the_limit(self):
        self.assertEqual([], publishing.releases_to_delete([release(t) for t in (G3, G4, G5)], G5, keep=3))
        self.assertEqual([], publishing.releases_to_delete([release(G5)], G5, keep=3))

    def test_published_catalog_release_is_never_deleted(self):
        """Mesmo sendo a mais antiga (geração republicada com --accept-older), a do catálogo fica."""
        releases = [release(t) for t in (G1, G2, G3, G4, G5)]
        self.assertEqual([G2, G3], publishing.releases_to_delete(releases, G1, keep=3))

    def test_keep_one_leaves_only_the_catalog_release(self):
        releases = [release(t) for t in (G3, G4, G5)]
        self.assertEqual([G3, G4], publishing.releases_to_delete(releases, G5, keep=1))

    def test_zero_turns_the_cleanup_off(self):
        releases = [release(t) for t in (G1, G2, G3, G4, G5)] + [release("2026-09-01-ffffffff", draft=True)]
        self.assertEqual([], publishing.releases_to_delete(releases, G5, keep=0))

    def test_other_tags_are_never_touched(self):
        others = [release("v1.0", published_at="2020-01-01T00:00:00Z"),
                  release("build-0.6.3", published_at="2020-01-01T00:00:00Z"),
                  release("2026-01-01", published_at="2026-01-01T00:00:00Z"),
                  release("2026-01-01-XYZ12345", published_at="2026-01-01T00:00:00Z")]
        releases = others + [release(t) for t in (G1, G2, G3, G4, G5)]
        self.assertEqual([G1, G2], publishing.releases_to_delete(releases, G5, keep=3))

    def test_orphan_draft_is_deleted(self):
        """Uma subida que caiu deixa um rascunho; a geração seguinte tem outro build_id e nunca o retoma."""
        orphan = "2026-09-28-99999999"
        releases = [release(G4), release(orphan, draft=True), release(G5)]
        self.assertEqual([orphan], publishing.releases_to_delete(releases, G5, keep=3))

    def test_drafts_do_not_count_as_kept_generations(self):
        orphan = "2026-09-28-99999999"
        releases = [release(t) for t in (G2, G3, G4, G5)] + [release(orphan, draft=True)]
        self.assertEqual([G2, orphan], publishing.releases_to_delete(releases, G5, keep=3))

    def test_same_day_generations_are_ordered_by_publication(self):
        early = release("2026-09-29-11111111", published_at="2026-09-29T06:40:00Z")
        late = release("2026-09-29-00000000", published_at="2026-09-29T19:00:00Z")
        releases = [release(G4), early, late, release("2026-09-30-22222222")]
        self.assertEqual([G4, "2026-09-29-11111111"],
                         publishing.releases_to_delete(releases, "2026-09-30-22222222", keep=2))


class FakeGh:
    """Imita `gh release list` e `gh release delete`. `fail`: ação que devolve erro."""

    def __init__(self, releases):
        self.releases = list(releases)
        self.commands = []
        self.fail = None

    def __call__(self, args):
        self.commands.append(list(args))
        action = args[1]
        if action == self.fail:
            return 1, "", "HTTP 403: Resource not accessible by integration"
        if action == "list":
            return 0, json.dumps(self.releases), ""
        if action == "delete":
            self.releases = [r for r in self.releases if r["tagName"] != args[2]]
            return 0, "", ""
        return 1, "", f"comando inesperado: {args}"

    def deletes(self):
        return [c for c in self.commands if c[1] == "delete"]

    def tags(self):
        return [r["tagName"] for r in self.releases]


class PruneTest(unittest.TestCase):
    def setUp(self):
        self.gh = FakeGh([release(t) for t in (G1, G2, G3, G4, G5)])

    def test_deletes_old_releases_and_their_tags(self):
        self.assertEqual([G1, G2], publishing.prune_releases(self.gh, G5, keep=3))
        self.assertEqual([G3, G4, G5], self.gh.tags())
        self.assertEqual([["release", "delete", G1, "--yes", "--cleanup-tag"],
                          ["release", "delete", G2, "--yes", "--cleanup-tag"]], self.gh.deletes())

    def test_only_lists_and_deletes(self):
        publishing.prune_releases(self.gh, G5, keep=3)
        self.assertEqual({"list", "delete"}, {c[1] for c in self.gh.commands})
        self.assertIn("tagName,isDraft,publishedAt", self.gh.commands[0])

    def test_draft_is_deleted_without_touching_tags(self):
        """Um rascunho ainda não tem tag no git."""
        orphan = "2026-09-28-99999999"
        self.gh.releases.append(release(orphan, draft=True))
        publishing.prune_releases(self.gh, G5, keep=5)
        self.assertEqual([["release", "delete", orphan, "--yes"]], self.gh.deletes())

    def test_dry_run_deletes_nothing(self):
        self.assertEqual([G1, G2], publishing.prune_releases(self.gh, G5, keep=3, dry_run=True))
        self.assertEqual([], self.gh.deletes())
        self.assertEqual(5, len(self.gh.releases))

    def test_refuses_when_the_catalog_release_is_missing(self):
        with self.assertRaises(publishing.PruneRefused):
            publishing.prune_releases(self.gh, "2026-10-28-12345678", keep=3)
        self.assertEqual([], self.gh.deletes())

    def test_refuses_when_the_catalog_release_is_a_draft(self):
        self.gh.releases[-1]["isDraft"] = True
        with self.assertRaises(publishing.PruneRefused):
            publishing.prune_releases(self.gh, G5, keep=3)
        self.assertEqual([], self.gh.deletes())

    def test_cleanup_off_does_not_even_call_gh(self):
        self.assertEqual([], publishing.prune_releases(self.gh, G5, keep=0))
        self.assertEqual([], self.gh.commands)

    def test_list_error_shows_command_and_stderr(self):
        self.gh.fail = "list"
        with self.assertRaises(publishing.GhError) as ctx:
            publishing.prune_releases(self.gh, G5, keep=3)
        self.assertIn("release list", str(ctx.exception))
        self.assertIn("Resource not accessible", str(ctx.exception))

    def test_delete_error_is_raised(self):
        self.gh.fail = "delete"
        with self.assertRaises(publishing.GhError) as ctx:
            publishing.prune_releases(self.gh, G5, keep=3)
        self.assertIn(f"release delete {G1}", str(ctx.exception))


class PruneAfterPublishTest(unittest.TestCase):
    """Depois de publicar, a limpeza nunca derruba a publicação: o que der errado vira aviso."""

    def setUp(self):
        self.gh = FakeGh([release(t) for t in (G1, G2, G3, G4, G5)])

    def test_reports_what_was_deleted(self):
        self.assertEqual(([G1, G2], None), publishing.prune_after_publish(self.gh, G5, keep=3))

    def test_gh_error_becomes_a_warning(self):
        self.gh.fail = "delete"
        deleted, warning = publishing.prune_after_publish(self.gh, G5, keep=3)
        self.assertEqual([], deleted)
        self.assertIn("Resource not accessible", warning)

    def test_refusal_becomes_a_warning(self):
        deleted, warning = publishing.prune_after_publish(self.gh, "2026-10-28-12345678", keep=3)
        self.assertEqual([], deleted)
        self.assertIn("2026-10-28-12345678", warning)
        self.assertEqual([], self.gh.deletes())


class PruneFlagsTest(unittest.TestCase):
    def test_prune_alone_is_fine(self):
        self.assertIsNone(publishing.flags_problem(release=False, commit=False, push=False, prune=True))
        self.assertIsNone(publishing.flags_problem(release=False, commit=False, push=False, prune=True, dry_run=True))

    def test_prune_does_not_mix_with_publishing(self):
        self.assertIsNotNone(publishing.flags_problem(release=True, commit=False, push=False, prune=True))

    def test_dry_run_only_with_prune(self):
        self.assertIsNotNone(publishing.flags_problem(release=True, commit=False, push=False, dry_run=True))
        self.assertIsNotNone(publishing.flags_problem(release=False, commit=False, push=False, dry_run=True))


if __name__ == "__main__":
    unittest.main()
