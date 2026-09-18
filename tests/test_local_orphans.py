"""Unit tests for local (repo-side) orphan detection."""
from __future__ import annotations

import subprocess
import textwrap
from pathlib import Path

import pytest

from markdown_to_canvas.ignore import load_ignore_matcher
from markdown_to_canvas.local_orphans import (
    collect_candidates,
    collect_local_refs,
    collect_settings_refs,
    find_local_orphans,
    print_report,
)


def _write(root: Path, rel: str, text: str = "") -> Path:
    path = root / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(textwrap.dedent(text).lstrip("\n"))
    return path


@pytest.fixture
def repo(tmp_path: Path) -> Path:
    """A minimal course repo; individual tests add whatever they need."""
    root = tmp_path / "course"
    _write(root, "course_settings/course_settings.toml", 'name = "Test"\n')
    return root


def _refs(repo: Path, rel: str) -> set[str]:
    return collect_local_refs(repo / rel, repo, repo / "snippets")


# ---------------------------------------------------------------------------
# collect_local_refs — one source type at a time
# ---------------------------------------------------------------------------


class TestCollectLocalRefs:
    def test_content_body_link(self, repo):
        _write(repo, "assets/pic.png", "x")
        _write(repo, "pages/a.md", "See ![pic](../assets/pic.png)\n")
        assert _refs(repo, "pages/a.md") == {"assets/pic.png"}

    def test_content_link_to_another_page_in_subfolder(self, repo):
        _write(repo, "pages/week1/b.md", "b\n")
        _write(repo, "pages/a.md", "See [b](week1/b.md)\n")
        assert _refs(repo, "pages/a.md") == {"pages/week1/b.md"}

    def test_external_and_anchor_links_are_not_refs(self, repo):
        _write(repo, "pages/a.md", "[x](https://example.com) and [y](#here)\n")
        assert _refs(repo, "pages/a.md") == set()

    def test_annotatable_attachment_frontmatter(self, repo):
        _write(repo, "assets/form.pdf", "x")
        _write(
            repo,
            "assignments/hw.md",
            """
            ---
            title: HW
            annotatable_attachment: assets/form.pdf
            ---

            body
            """,
        )
        assert _refs(repo, "assignments/hw.md") == {"assets/form.pdf"}

    def test_link_inside_a_snippet_counts_for_the_including_file(self, repo):
        _write(repo, "assets/handbook.pdf", "x")
        _write(repo, "snippets/policy.md", "Read the [handbook](../assets/handbook.pdf)\n")
        _write(repo, "pages/a.md", "[policy](../snippets/policy.md)\n")
        assert "assets/handbook.pdf" in _refs(repo, "pages/a.md")

    def test_malformed_frontmatter_still_yields_body_refs(self, repo):
        _write(repo, "assets/pic.png", "x")
        _write(repo, "pages/a.md", "---\n: : bad yaml\n---\n\n![p](../assets/pic.png)\n")
        assert "assets/pic.png" in _refs(repo, "pages/a.md")

    def test_module_items(self, repo):
        _write(repo, "pages/home.md", "home\n")
        _write(repo, "assets/slides.pdf", "x")
        _write(
            repo,
            "modules/week1.md",
            """
            - [Home](../pages/home.md)
            - [Slides](../assets/slides.pdf)
            """,
        )
        assert _refs(repo, "modules/week1.md") == {
            "pages/home.md",
            "assets/slides.pdf",
        }

    def test_module_external_url_item_is_not_a_local_ref(self, repo):
        _write(repo, "modules/week1.md", "- [Canvas](https://example.com)\n")
        assert _refs(repo, "modules/week1.md") == set()

    def test_quiz_question_links(self, repo):
        _write(repo, "assets/diagram.png", "x")
        _write(repo, "quizzes/q1/q1.md", "Intro\n\n1. [Q1](question-1.md)\n")
        _write(repo, "quizzes/q1/question-1.md", "![d](../../assets/diagram.png)\n")
        assert _refs(repo, "quizzes/q1/q1.md") == {"assets/diagram.png"}

    def test_quiz_description_links(self, repo):
        _write(repo, "pages/review.md", "review\n")
        _write(repo, "quizzes/q1/q1.md", "Study [review](../../pages/review.md) first.\n")
        assert _refs(repo, "quizzes/q1/q1.md") == {"pages/review.md"}

    def test_question_bank_question_links(self, repo):
        _write(repo, "assets/bank.png", "x")
        _write(repo, "question_banks/b1/b1.toml", 'bank_title = "B1"\n')
        _write(
            repo,
            "question_banks/b1/questions/q1.md",
            "![b](../../../assets/bank.png)\n",
        )
        assert _refs(repo, "question_banks/b1/b1.toml") == {"assets/bank.png"}

    def test_assets_reference_nothing(self, repo):
        _write(repo, "assets/pic.png", "x")
        assert _refs(repo, "assets/pic.png") == set()

    def test_conditionals_are_not_applied(self, repo):
        """A link in a false #if branch still counts — conservative by design."""
        _write(repo, "assets/pic.png", "x")
        _write(
            repo,
            "pages/a.md",
            """
            <!-- #if online_class -->
            ![p](../assets/pic.png)
            <!-- #endif -->
            """,
        )
        assert _refs(repo, "pages/a.md") == {"assets/pic.png"}


# ---------------------------------------------------------------------------
# collect_settings_refs
# ---------------------------------------------------------------------------


class TestCollectSettingsRefs:
    def test_front_page_and_dashboard_image(self, repo):
        _write(
            repo,
            "course_settings/course_settings.toml",
            """
            front_page = "pages/home.md"
            dashboard_image = "assets/dash.png"
            """,
        )
        refs, pinned = collect_settings_refs(repo)
        assert refs == {"pages/home.md", "assets/dash.png"}
        assert pinned == []

    def test_pinned_resources_returned_separately(self, repo):
        _write(
            repo,
            "course_settings/course_settings.toml",
            'pinned_resources = ["quizzes/live", "assets/keep.pdf"]\n',
        )
        refs, pinned = collect_settings_refs(repo)
        assert refs == set()
        assert pinned == ["quizzes/live", "assets/keep.pdf"]

    def test_due_dates_contribute_nothing(self, repo):
        """due_dates match content by title, not by path."""
        _write(
            repo,
            "course_settings/course_settings.toml",
            'due_dates = [{ name = "HW 1", due_at = "2026-01-01" }]\n',
        )
        refs, _pinned = collect_settings_refs(repo)
        assert refs == set()

    def test_missing_settings_file(self, tmp_path):
        assert collect_settings_refs(tmp_path / "nope") == (set(), [])


# ---------------------------------------------------------------------------
# collect_candidates
# ---------------------------------------------------------------------------


class TestCollectCandidates:
    def test_never_reports_roots_snippets_or_banks(self, repo):
        _write(repo, "snippets/s.md", "s\n")
        _write(repo, "modules/week1.md", "m\n")
        _write(repo, "course_settings/syllabus.md", "syl\n")
        _write(repo, "question_banks/b1/b1.toml", 'bank_title = "B1"\n')
        _write(repo, "question_banks/b1/questions/q1.md", "q\n")
        assert collect_candidates(repo, load_ignore_matcher(repo)) == set()

    def test_quizzes_and_announcements_are_never_candidates(self, repo):
        _write(repo, "quizzes/q1/q1.md", "1. [Q](question-1.md)\n")
        _write(repo, "quizzes/q1/question-1.md", "q\n")
        _write(repo, "announcements/n.md", "n\n")
        assert collect_candidates(repo, load_ignore_matcher(repo)) == set()

    def test_assets_and_content_are_candidates(self, repo):
        _write(repo, "assets/sub/pic.png", "x")
        _write(repo, "pages/a.md", "a\n")
        _write(repo, "discussions/d.md", "d\n")
        assert collect_candidates(repo, load_ignore_matcher(repo)) == {
            "assets/sub/pic.png",
            "pages/a.md",
            "discussions/d.md",
        }

    def test_canvasignore_prunes_candidates(self, repo):
        _write(repo, ".canvasignore", "drafts/\n")
        _write(repo, "pages/a.md", "a\n")
        _write(repo, "pages/drafts/wip.md", "wip\n")
        assert collect_candidates(repo, load_ignore_matcher(repo)) == {"pages/a.md"}


# ---------------------------------------------------------------------------
# find_local_orphans — end to end
# ---------------------------------------------------------------------------


class TestFindLocalOrphans:
    def test_full_repo(self, repo):
        _write(
            repo,
            "course_settings/course_settings.toml",
            """
            front_page = "pages/home.md"
            dashboard_image = "assets/dash.png"
            pinned_resources = ["quizzes/live-quiz"]
            """,
        )
        _write(
            repo,
            "course_settings/syllabus.md",
            "[policy](../snippets/policy.md) and [rules](../pages/rules.md)\n",
        )
        _write(repo, "snippets/policy.md", "[handbook](../assets/handbook.pdf)\n")
        _write(repo, "snippets/nobody-includes-me.md", "unused\n")
        _write(repo, "pages/home.md", "![u](../assets/used.png)\n")
        _write(repo, "pages/rules.md", "rules\n")
        _write(repo, "pages/lonely.md", "nobody links here\n")
        _write(repo, "assignments/hw.md", "---\nannotatable_attachment: assets/annot.pdf\n---\n\nhw\n")
        _write(repo, "modules/week1.md", "- [Home](../pages/home.md)\n- [HW](../assignments/hw.md)\n")
        _write(repo, "quizzes/live-quiz/live-quiz.md", "1. [Q](q1.md)\n")
        _write(repo, "quizzes/live-quiz/q1.md", "q\n")
        _write(repo, "quizzes/stray-quiz/stray-quiz.md", "1. [Q](q1.md)\n")
        _write(repo, "quizzes/stray-quiz/q1.md", "![q](../../assets/quiz.png)\n")
        for asset in ("used.png", "dash.png", "handbook.pdf", "annot.pdf", "quiz.png"):
            _write(repo, f"assets/{asset}", "x")
        _write(repo, "assets/orphan.png", "x")

        report = find_local_orphans(repo)

        assert report.errors == []
        assert report.orphans == [
            "assets/orphan.png",
            "pages/lonely.md",
        ]

    def test_announcement_links_still_protect_assets(self, repo):
        _write(repo, "announcements/n.md", "![x](../assets/ann.png)\n")
        _write(repo, "assets/ann.png", "x")
        _write(repo, "announcements/unlinked.md", "nobody links here\n")
        assert find_local_orphans(repo).orphans == []

    def test_pinned_folder_suppresses_everything_beneath_it(self, repo):
        _write(
            repo,
            "course_settings/course_settings.toml",
            'pinned_resources = ["assets/handouts"]\n',
        )
        _write(repo, "assets/handouts/one.pdf", "x")
        _write(repo, "assets/loose.pdf", "x")
        assert find_local_orphans(repo).orphans == ["assets/loose.pdf"]

    def test_snippets_are_never_reported_even_when_unused(self, repo):
        _write(repo, "snippets/unused.md", "nothing includes me\n")
        assert find_local_orphans(repo).orphans == []

    def test_clean_repo_reports_nothing(self, repo):
        _write(repo, "pages/home.md", "home\n")
        _write(repo, "modules/week1.md", "- [Home](../pages/home.md)\n")
        report = find_local_orphans(repo)
        assert report.orphans == []
        assert report.errors == []

    def test_module_item_outside_the_repo_errors_instead_of_crashing(self, repo):
        _write(repo, "pages/home.md", "home\n")
        _write(repo, "modules/week1.md", "- [Outside](../../elsewhere/x.md)\n")
        report = find_local_orphans(repo)
        assert report.errors == [
            (
                "modules/week1.md",
                (
                    "could not resolve every module item - an item points "
                    "outside the repo"
                ),
            )
        ]
        # The module contributed no refs, so its real items look unreferenced —
        # that is why the error exists.
        assert report.orphans == ["pages/home.md"]


class TestConversionFailure:
    def test_unconvertible_file_errors_instead_of_crashing(self, repo, monkeypatch):
        _write(repo, "assets/pic.png", "x")
        _write(repo, "pages/a.md", "![p](../assets/pic.png)\n")

        def _boom(_markdown, timeout=None):
            raise RuntimeError('Pandoc died with exitcode "64" during conversion')

        monkeypatch.setattr(
            "markdown_to_canvas.local_orphans.markdown_to_html", _boom
        )
        report = find_local_orphans(repo)

        assert len(report.errors) == 1
        key, message = report.errors[0]
        assert key == "pages/a.md"
        assert "could not convert to HTML" in message
        assert report.orphans == ["assets/pic.png", "pages/a.md"]

    def test_pandoc_timeout_is_reported_with_the_bracket_hint(self, repo, monkeypatch):
        """A nested-bracket run makes pandoc backtrack for minutes; bound it."""
        _write(repo, "assets/pic.png", "x")
        _write(repo, "pages/slow.md", "![p](../assets/pic.png)\n")

        def _hang(_markdown, timeout=None):
            raise subprocess.TimeoutExpired(cmd="pandoc", timeout=timeout or 0)

        monkeypatch.setattr(
            "markdown_to_canvas.local_orphans.markdown_to_html", _hang
        )
        report = find_local_orphans(repo)

        assert report.errors == [
            ("pages/slow.md", "timed out after 20s - check for nested []s")
        ]
        # The file's links went unfollowed, so the asset it uses looks orphaned.
        assert report.orphans == ["assets/pic.png", "pages/slow.md"]

    def test_a_real_nested_bracket_run_does_not_stall_the_report(self, repo):
        """End to end, with a real pandoc and a short timeout."""
        _write(repo, "pages/nasty.md", "[" * 14 + "text" + "]" * 14 + "\n")
        monkeypatched = 1.0
        import markdown_to_canvas.local_orphans as mod

        original = mod._PANDOC_TIMEOUT_SECONDS
        mod._PANDOC_TIMEOUT_SECONDS = monkeypatched
        try:
            report = find_local_orphans(repo)
        finally:
            mod._PANDOC_TIMEOUT_SECONDS = original

        assert report.errors == [
            ("pages/nasty.md", "timed out after 1s - check for nested []s")
        ]


class TestPrintErrors:
    def test_errors_are_printed_last(self, repo, capsys):
        _write(repo, "assets/orphan.png", "x")
        _write(repo, "modules/week1.md", "- [Outside](../../elsewhere/x.md)\n")

        print_report(find_local_orphans(repo))
        out = capsys.readouterr().out

        assert out.index("Unreferenced local files") < out.index("Errors (1)")
        assert (
            "- modules/week1.md : could not resolve every module item" in out
        )

    def test_errors_are_printed_even_with_no_orphans(self, repo, capsys):
        _write(repo, "pages/home.md", "home\n")
        _write(repo, "modules/week1.md", "- [Home](../pages/home.md)\n")
        _write(repo, "modules/week2.md", "- [Outside](../../elsewhere/x.md)\n")

        print_report(find_local_orphans(repo))
        out = capsys.readouterr().out

        assert "No unreferenced local files found." in out
        assert "Errors (1)" in out

    def test_no_error_section_when_everything_scanned(self, repo, capsys):
        _write(repo, "assets/orphan.png", "x")
        print_report(find_local_orphans(repo))
        assert "Errors" not in capsys.readouterr().out


class TestReferencedMap:
    def test_referrers_are_listed_per_candidate(self, repo):
        _write(repo, "assets/pic.png", "x")
        _write(repo, "pages/welcome.md", "![p](../assets/pic.png)\n")
        _write(repo, "assignments/a1.md", "![p](../assets/pic.png)\n")

        report = find_local_orphans(repo)
        assert report.referenced["assets/pic.png"] == [
            "assignments/a1.md",
            "pages/welcome.md",
        ]

    def test_settings_keys_are_credited_to_the_settings_file(self, repo):
        _write(
            repo,
            "course_settings/course_settings.toml",
            'front_page = "pages/home.md"\n',
        )
        _write(repo, "pages/home.md", "home\n")

        report = find_local_orphans(repo)
        assert report.referenced["pages/home.md"] == [
            "course_settings/course_settings.toml"
        ]

    def test_pinned_resources_are_labelled_as_pins(self, repo):
        _write(
            repo,
            "course_settings/course_settings.toml",
            'pinned_resources = ["pages/live.md"]\n',
        )
        _write(repo, "pages/live.md", "live\n")

        report = find_local_orphans(repo)
        assert report.referenced["pages/live.md"] == [
            "course_settings/course_settings.toml (pinned_resources)"
        ]

    def test_referenced_and_orphans_partition_the_candidates(self, repo):
        _write(repo, "assets/used.png", "x")
        _write(repo, "assets/unused.png", "x")
        _write(repo, "snippets/lib.md", "shared\n")
        _write(repo, "pages/home.md", "![u](../assets/used.png)\n")
        _write(repo, "modules/week1.md", "- [Home](../pages/home.md)\n")

        report = find_local_orphans(repo)
        candidates = collect_candidates(repo, load_ignore_matcher(repo))
        assert set(report.referenced) | set(report.orphans) == candidates
        assert not set(report.referenced) & set(report.orphans)
        # Non-candidates appear in neither list.
        assert "snippets/lib.md" not in report.referenced
        assert "modules/week1.md" not in report.referenced


class TestPrintReport:
    def test_verbose_lists_referenced_before_unreferenced(self, repo, capsys):
        _write(repo, "assets/used.png", "x")
        _write(repo, "assets/orphan.png", "x")
        _write(repo, "pages/home.md", "![u](../assets/used.png)\n")
        _write(repo, "modules/week1.md", "- [Home](../pages/home.md)\n")

        print_report(find_local_orphans(repo), verbose=True)
        out = capsys.readouterr().out

        assert "assets/used.png : pages/home.md" in out
        assert out.index("Referenced local files (2):") < out.index(
            "Unreferenced local files (1):"
        )
        assert "assets/orphan.png" in out

    def test_non_verbose_omits_the_referenced_section(self, repo, capsys):
        _write(repo, "assets/used.png", "x")
        _write(repo, "assets/orphan.png", "x")
        _write(repo, "pages/home.md", "![u](../assets/used.png)\n")
        _write(repo, "modules/week1.md", "- [Home](../pages/home.md)\n")

        print_report(find_local_orphans(repo), verbose=False)
        out = capsys.readouterr().out

        assert "Referenced local files" not in out
        assert "Unreferenced local files (1):" in out

    def test_verbose_on_a_repo_with_no_orphans(self, repo, capsys):
        _write(repo, "pages/home.md", "home\n")
        _write(repo, "modules/week1.md", "- [Home](../pages/home.md)\n")

        print_report(find_local_orphans(repo), verbose=True)
        out = capsys.readouterr().out

        assert "Referenced local files (1):" in out
        assert "No unreferenced local files found." in out

    def test_scope_note_is_printed_before_the_findings(self, repo, capsys):
        _write(repo, "assets/orphan.png", "x")

        print_report(find_local_orphans(repo))
        out = capsys.readouterr().out

        assert "never" in out and "excluded by design" in out
        assert out.index("Note:") < out.index("Unreferenced local files")

    def test_scope_note_is_printed_even_when_nothing_is_found(self, repo, capsys):
        print_report(find_local_orphans(repo))
        out = capsys.readouterr().out

        assert "Note:" in out
        assert "No unreferenced local files found." in out
