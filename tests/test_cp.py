"""Tests for the `cp` subcommand: copying content between two course repos."""
from __future__ import annotations

import os
import subprocess
import textwrap
import time
import tomllib
from pathlib import Path

import pytest
from click.testing import CliRunner

from markdown_to_canvas import repo_format
from markdown_to_canvas.cli import main
from markdown_to_canvas.cp import (
    CONFLICT,
    IDENTICAL,
    NEW,
    SNIPPET_KEPT,
    CpError,
    build_copy_plan,
    run_cp,
    split_rubric_blocks,
)
from markdown_to_canvas.repo_format import RepoFormatError
from tests.conftest import make_current


def _write(root: Path, rel: str, text: str = "") -> Path:
    path = root / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(textwrap.dedent(text).lstrip("\n"))
    return path


def _snapshot(root: Path) -> dict[str, bytes]:
    return {
        p.relative_to(root).as_posix(): p.read_bytes()
        for p in sorted(root.rglob("*"))
        if p.is_file()
    }


RUBRICS = """
# Rubrics for the source course
[[rubrics]]
title = "Essay Rubric"
reusable = true
# identifier = "g123"

[[rubrics.criteria]]
description = "Thesis"
points = 5
ratings = [{ description = "Good", points = 5 }, { description = "Bad", points = 0 }]

[[rubrics]]
title = "Lab Rubric"

[[rubrics.criteria]]
description = "Works"
points = 10
ratings = [{ description = "Yes", points = 10 }, { description = "No", points = 0 }]
"""


@pytest.fixture
def src(tmp_path: Path) -> Path:
    """A source course with one of everything cp handles."""
    root = tmp_path / "src"
    _write(root, "course_settings/course_settings.toml", """
        name = "Source"
        due_dates = [{ name = "HW 1", due_at = "2026-01-01T23:59:00-08:00" }]

        [course_flags]
        online = false

        [[assignment_groups]]
        title = "Labs"
    """)
    make_current(root)
    _write(root, "course_settings/canvas.toml", 'base_url = "https://x"\ncourse_id = 555\n')
    _write(root, "course_settings/rubrics.toml", RUBRICS)
    _write(root, "assets/img/diagram.png", "PNG-diagram")
    _write(root, "assets/img/snippet-pic.png", "PNG-snippet")
    _write(root, "assets/img/online.png", "PNG-online")
    _write(root, "assets/worksheet.pdf", "PDF")
    _write(root, "assets/quiz-pic.png", "PNG-quiz")
    _write(root, "assets/bank-pic.png", "PNG-bank")
    _write(root, "snippets/late-policy.md", "Late work loses 10%. ![](../assets/img/snippet-pic.png)\n")
    _write(root, "snippets/inline/CANVAS_COURSE_ID.md", "555\n")
    _write(root, "snippets/quiz-note.md", "Show your work.\n")
    _write(root, "pages/intro.md", "---\ntitle: Intro\n---\nHello.\n")
    _write(root, "pages/syllabus.md", "---\ntitle: Syllabus\n---\nSyllabus.\n")
    _write(root, "assignments/hw1.md", """
        ---
        title: HW 1
        rubric: "Essay Rubric"
        assignment_group_id: "Labs"
        annotatable_attachment: assets/worksheet.pdf
        ---
        ![Diagram](../assets/img/diagram.png)

        [Policy](../snippets/late-policy.md)

        See the [syllabus](../pages/syllabus.md).

        Course id $../snippets/inline/CANVAS_COURSE_ID.md$.
    """)
    _write(root, "discussions/d1.md", """
        ---
        title: D 1
        rubric: "Lab Rubric"
        ---
        Discuss.
    """)
    _write(root, "quizzes/week-1-quiz/week-1-quiz.md", """
        ---
        title: Week 1 Quiz
        ---
        ![](../../assets/quiz-pic.png)

        1. [Q1](questions/q1.md)
    """)
    _write(root, "quizzes/week-1-quiz/questions/q1.md", """
        ---
        type: essay_question
        ---
        Explain. [p](../../../snippets/quiz-note.md)
    """)
    _write(root, "question_banks/bank1/bank1.toml", 'title = "Bank 1"\n')
    _write(root, "question_banks/bank1/questions/b1.md", """
        ---
        type: essay_question
        ---
        ![](../../../assets/bank-pic.png)
    """)
    _write(root, "modules/week-1.md", """
        ---
        title: Week 1
        ---
        ## Readings

        - [Intro](../pages/intro.md)
        - [HW 1](../assignments/hw1.md)
        - [Quiz](../quizzes/week-1-quiz/week-1-quiz.md)
        - [Site](https://example.com)
    """)
    return root


@pytest.fixture
def dest(tmp_path: Path) -> Path:
    root = tmp_path / "dest"
    _write(root, "course_settings/course_settings.toml", 'name = "Dest"\n')
    make_current(root)
    return root


def _statuses(plan) -> dict[str, str]:
    return {f.rel: f.status for f in plan.files}


def _cp(srcs, dest, **kw) -> bool:
    return run_cp([Path(s) for s in srcs], dest, **kw)


# ---------------------------------------------------------------------------
# Fixtures sanity
# ---------------------------------------------------------------------------


def test_fixture_repos_are_current(src, dest):
    repo_format.check_repo_format(src)
    repo_format.check_repo_format(dest)


# ---------------------------------------------------------------------------
# Arguments and errors (2.1)
# ---------------------------------------------------------------------------


class TestErrors:
    def test_same_repo_suggests_mv(self, src):
        before = _snapshot(src)
        with pytest.raises(CpError, match="mv"):
            _cp([src / "pages/intro.md"], src)
        assert _snapshot(src) == before

    def test_sources_from_two_repos(self, src, dest, tmp_path):
        other = tmp_path / "other"
        make_current(other)
        _write(other, "pages/x.md", "x\n")
        with pytest.raises(CpError, match="same course repo"):
            _cp([src / "pages/intro.md", other / "pages/x.md"], dest)
        assert not (dest / "pages").exists()

    def test_source_outside_any_course(self, dest, tmp_path):
        loose = _write(tmp_path / "loose", "a.md", "a\n")
        with pytest.raises(CpError, match="not inside a course repo"):
            _cp([loose], dest)

    def test_missing_source(self, src, dest):
        with pytest.raises(CpError, match="No such file"):
            _cp([src / "pages/nope.md"], dest)

    def test_course_settings_refused(self, src, dest):
        before = _snapshot(dest)
        with pytest.raises(CpError, match="course settings cannot be copied"):
            _cp([src / "course_settings/rubrics.toml"], dest)
        assert _snapshot(dest) == before

    def test_old_destination_refused(self, src, dest):
        settings = dest / "course_settings/course_settings.toml"
        settings.write_text('name = "Dest"\n')  # no format_version: version 0
        src_before, dest_before = _snapshot(src), _snapshot(dest)
        with pytest.raises(RepoFormatError) as exc:
            _cp([src / "pages/intro.md"], dest)
        assert str(dest.resolve()) in str(exc.value)
        assert "upgrade" in str(exc.value)
        assert _snapshot(src) == src_before
        assert _snapshot(dest) == dest_before


# ---------------------------------------------------------------------------
# Expansion of SRC arguments (2.2)
# ---------------------------------------------------------------------------


class TestSrcExpansion:
    def test_single_page(self, src, dest):
        assert _cp([src / "pages/intro.md"], dest)
        assert (dest / "pages/intro.md").read_bytes() == (src / "pages/intro.md").read_bytes()

    def test_directory_src(self, src, dest):
        plan = build_copy_plan([src / "pages"], dest)
        assert {"pages/intro.md", "pages/syllabus.md"} <= set(_statuses(plan))

    def test_question_file_expands_to_quiz_folder(self, src, dest):
        plan = build_copy_plan([src / "quizzes/week-1-quiz/questions/q1.md"], dest)
        files = set(_statuses(plan))
        assert "quizzes/week-1-quiz/week-1-quiz.md" in files
        assert "quizzes/week-1-quiz/questions/q1.md" in files
        assert "assets/quiz-pic.png" in files
        assert "snippets/quiz-note.md" in files

    def test_ignored_src_skipped(self, src, dest):
        _write(src, ".canvasignore", "pages/intro.md\n")
        plan = build_copy_plan([src / "pages/intro.md"], dest)
        assert plan.files == []
        assert plan.ignored == ["pages/intro.md"]


# ---------------------------------------------------------------------------
# Dependency walk (2.3)
# ---------------------------------------------------------------------------


class TestDependencies:
    def test_assignment_brings_assets_and_snippets(self, src, dest):
        files = set(_statuses(build_copy_plan([src / "assignments/hw1.md"], dest)))
        assert files >= {
            "assignments/hw1.md",
            "assets/img/diagram.png",
            "assets/worksheet.pdf",  # annotatable_attachment
            "snippets/late-policy.md",
            "snippets/inline/CANVAS_COURSE_ID.md",
            "assets/img/snippet-pic.png",  # referenced only inside the snippet
        }

    def test_false_conditional_branch_still_copied(self, src, dest):
        _write(src, "pages/cond.md", """
            <!-- #if online -->
            ![](../assets/img/online.png)
            <!-- #endif -->
            Text.
        """)
        files = set(_statuses(build_copy_plan([src / "pages/cond.md"], dest)))
        assert "assets/img/online.png" in files

    def test_module_brings_its_items(self, src, dest):
        files = set(_statuses(build_copy_plan([src / "modules/week-1.md"], dest)))
        assert files >= {
            "modules/week-1.md",
            "pages/intro.md",
            "assignments/hw1.md",
            "assets/img/diagram.png",
            "quizzes/week-1-quiz/week-1-quiz.md",
            "quizzes/week-1-quiz/questions/q1.md",
            "assets/quiz-pic.png",
        }

    def test_module_asset_item(self, src, dest):
        _write(src, "modules/files.md", "- [Worksheet](../assets/worksheet.pdf)\n")
        files = set(_statuses(build_copy_plan([src / "modules/files.md"], dest)))
        assert "assets/worksheet.pdf" in files

    def test_question_bank(self, src, dest):
        files = set(_statuses(build_copy_plan([src / "question_banks/bank1"], dest)))
        assert files == {
            "question_banks/bank1/bank1.toml",
            "question_banks/bank1/questions/b1.md",
            "assets/bank-pic.png",
        }

    def test_link_to_uncopied_page_is_listed_not_copied(self, src, dest, capsys):
        plan = build_copy_plan([src / "assignments/hw1.md"], dest)
        assert "pages/syllabus.md" not in _statuses(plan)
        assert ("assignments/hw1.md", "pages/syllabus.md", False) in plan.links_not_followed
        assert _cp([src / "assignments/hw1.md"], dest)
        out = capsys.readouterr().out
        assert "assignments/hw1.md -> pages/syllabus.md  (MISSING in destination)" in out
        assert (dest / "assignments/hw1.md").read_bytes() == (
            src / "assignments/hw1.md"
        ).read_bytes()

    def test_link_target_present_in_destination(self, src, dest):
        _write(dest, "pages/syllabus.md", "theirs\n")
        plan = build_copy_plan([src / "assignments/hw1.md"], dest)
        assert ("assignments/hw1.md", "pages/syllabus.md", True) in plan.links_not_followed

    def test_link_to_page_also_copied_is_not_listed(self, src, dest):
        plan = build_copy_plan([src / "assignments/hw1.md", src / "pages/syllabus.md"], dest)
        assert plan.links_not_followed == []

    def test_ignored_dependency_skipped(self, src, dest, capsys):
        _write(src, ".canvasignore", "assets/img/diagram.png\n")
        plan = build_copy_plan([src / "assignments/hw1.md"], dest)
        assert "assets/img/diagram.png" not in _statuses(plan)
        assert "assets/img/diagram.png" in plan.ignored
        _cp([src / "assignments/hw1.md"], dest, noop=True)
        assert "Skipped (matched by the source's .canvasignore): assets/img/diagram.png" in (
            capsys.readouterr().out
        )

    def test_missing_asset_warns(self, src, dest):
        _write(src, "pages/broken.md", "![](../assets/nope.png)\n")
        plan = build_copy_plan([src / "pages/broken.md"], dest)
        assert any("assets/nope.png" in w for w in plan.warnings)


# ---------------------------------------------------------------------------
# Classification (2.4)
# ---------------------------------------------------------------------------


class TestClassification:
    def test_identical_skipped(self, src, dest):
        _write(dest, "assets/img/diagram.png", "PNG-diagram")
        plan = build_copy_plan([src / "assignments/hw1.md"], dest)
        assert _statuses(plan)["assets/img/diagram.png"] == IDENTICAL
        assert plan.conflicts == []

    def test_conflict_listed(self, src, dest):
        _write(dest, "assets/img/diagram.png", "DIFFERENT")
        plan = build_copy_plan([src / "assignments/hw1.md"], dest)
        assert plan.conflicts == ["assets/img/diagram.png"]
        assert _statuses(plan)["assignments/hw1.md"] == NEW

    def test_destination_snippet_kept(self, src, dest):
        _write(dest, "snippets/inline/CANVAS_COURSE_ID.md", "777\n")
        plan = build_copy_plan([src / "assignments/hw1.md"], dest, overwrite=True)
        assert _statuses(plan)["snippets/inline/CANVAS_COURSE_ID.md"] == SNIPPET_KEPT
        assert plan.conflicts == []
        assert _cp([src / "assignments/hw1.md"], dest, overwrite=True)
        assert (dest / "snippets/inline/CANVAS_COURSE_ID.md").read_text() == "777\n"

    def test_snippet_named_as_src_conflicts(self, src, dest):
        _write(dest, "snippets/late-policy.md", "theirs\n")
        plan = build_copy_plan([src / "snippets/late-policy.md"], dest)
        assert _statuses(plan)["snippets/late-policy.md"] == CONFLICT
        assert not _cp([src / "snippets/late-policy.md"], dest)
        assert (dest / "snippets/late-policy.md").read_text() == "theirs\n"
        assert _cp([src / "snippets/late-policy.md"], dest, overwrite=True)
        assert (dest / "snippets/late-policy.md").read_bytes() == (
            src / "snippets/late-policy.md"
        ).read_bytes()


# ---------------------------------------------------------------------------
# Rubrics (2.5)
# ---------------------------------------------------------------------------


def _dest_rubrics(dest: Path) -> dict[str, dict]:
    data = tomllib.loads((dest / "course_settings/rubrics.toml").read_text())
    return {r["title"]: r for r in data["rubrics"]}


class TestRubrics:
    def test_split_blocks_keeps_comments(self):
        blocks = split_rubric_blocks(textwrap.dedent(RUBRICS))
        assert set(blocks) == {"Essay Rubric", "Lab Rubric"}
        assert '# identifier = "g123"' in blocks["Essay Rubric"]
        assert "[[rubrics.criteria]]" in blocks["Essay Rubric"]

    def test_present_and_same(self, src, dest):
        text = "[[rubrics]]\ntitle = \"Essay Rubric\"\n\n[[rubrics.criteria]]\n" \
            'description = "Thesis"\npoints = 5\nratings = [{ description = "Good", ' \
            'points = 5 }, { description = "Bad", points = 0 }]\n'
        _write(dest, "course_settings/rubrics.toml", text)
        plan = build_copy_plan([src / "assignments/hw1.md"], dest)
        assert plan.rubric_appends == []
        assert plan.rubrics_text is None
        assert not any("rubric" in w for w in plan.warnings)

    def test_present_but_different(self, src, dest):
        text = '[[rubrics]]\ntitle = "Essay Rubric"\n\n[[rubrics.criteria]]\n' \
            'description = "Other"\npoints = 1\n'
        _write(dest, "course_settings/rubrics.toml", text)
        assert _cp([src / "assignments/hw1.md"], dest)
        assert (dest / "course_settings/rubrics.toml").read_text() == text
        plan = build_copy_plan([src / "assignments/hw1.md"], dest)
        assert any("rubric 'Essay Rubric' differs" in w for w in plan.warnings)

    def test_missing_rubric_appended_preserving_file(self, src, dest):
        existing = "# Destination rubrics\n[[rubrics]]\ntitle = \"Other\"\n"
        _write(dest, "course_settings/rubrics.toml", existing)
        assert _cp([src / "assignments/hw1.md"], dest)
        text = (dest / "course_settings/rubrics.toml").read_text()
        assert text.startswith(existing)
        assert '# identifier = "g123"' in text
        assert set(_dest_rubrics(dest)) == {"Other", "Essay Rubric"}

    def test_no_rubrics_file_created(self, src, dest):
        assert _cp([src / "assignments/hw1.md"], dest)
        assert set(_dest_rubrics(dest)) == {"Essay Rubric"}

    def test_shared_rubric_appended_once(self, src, dest):
        _write(src, "assignments/hw2.md", '---\ntitle: HW 2\nrubric: "Essay Rubric"\n---\nx\n')
        plan = build_copy_plan([src / "assignments"], dest)
        assert plan.rubric_appends == ["Essay Rubric"]
        assert plan.rubrics_text.count('title = "Essay Rubric"') == 1

    def test_numeric_rubric_warns(self, src, dest):
        _write(src, "assignments/num.md", "---\ntitle: Num\nrubric: 4567\n---\nx\n")
        plan = build_copy_plan([src / "assignments/num.md"], dest)
        assert plan.rubric_appends == []
        assert any("4567" in w and "numeric" in w for w in plan.warnings)

    def test_rubric_missing_from_source_warns(self, src, dest):
        _write(src, "assignments/ghost.md", '---\ntitle: G\nrubric: "Ghost"\n---\nx\n')
        plan = build_copy_plan([src / "assignments/ghost.md"], dest)
        assert plan.rubric_appends == []
        assert any("'Ghost'" in w for w in plan.warnings)

    def test_discussion_rubric_merged(self, src, dest):
        assert _cp([src / "discussions/d1.md"], dest)
        assert set(_dest_rubrics(dest)) == {"Lab Rubric"}


# ---------------------------------------------------------------------------
# module_order.toml (2.6)
# ---------------------------------------------------------------------------


class TestModuleOrder:
    def test_appended_with_comments_kept(self, src, dest):
        _write(dest, "course_settings/module_order.toml", """
            # Module order
            order = [
                "intro.md",  # first
            ]
        """)
        assert _cp([src / "modules/week-1.md"], dest)
        text = (dest / "course_settings/module_order.toml").read_text()
        assert "# Module order" in text and "# first" in text
        assert tomllib.loads(text)["order"] == ["intro.md", "week-1.md"]

    def test_already_listed_unchanged(self, src, dest):
        path = _write(dest, "course_settings/module_order.toml", 'order = ["week-1.md"]\n')
        before = path.read_bytes()
        assert _cp([src / "modules/week-1.md"], dest)
        assert path.read_bytes() == before

    def test_not_created(self, src, dest):
        assert _cp([src / "modules/week-1.md"], dest)
        assert not (dest / "course_settings/module_order.toml").exists()


# ---------------------------------------------------------------------------
# Warnings (2.7)
# ---------------------------------------------------------------------------


class TestWarnings:
    def _warnings(self, src, dest, rel):
        plan = build_copy_plan([src / rel], dest)
        return plan.warnings

    def test_unknown_assignment_group(self, src, dest):
        ws = self._warnings(src, dest, "assignments/hw1.md")
        assert any("assignment_group_id 'Labs'" in w for w in ws)

    def test_known_assignment_group_no_warning(self, src, dest):
        with (dest / "course_settings/course_settings.toml").open("a") as fh:
            fh.write('\n[[assignment_groups]]\ntitle = "Labs"\n')
        ws = self._warnings(src, dest, "assignments/hw1.md")
        assert not any("assignment_group_id" in w for w in ws)

    def test_numeric_ids(self, src, dest):
        _write(src, "assignments/ids.md", """
            ---
            title: IDs
            assignment_group_id: 12
            group_category_id: 34
            final_grader_id: 56
            ---
            x
        """)
        ws = self._warnings(src, dest, "assignments/ids.md")
        assert any("assignment_group_id 12" in w for w in ws)
        assert any("group_category_id 34" in w for w in ws)
        assert any("final_grader_id 56" in w for w in ws)

    def test_undefined_flags(self, src, dest):
        _write(src, "pages/flags.md", """
            ---
            title: Flags
            published_if: in_person
            ---
            <!-- #if online -->
            x
            <!-- #endif -->
        """)
        ws = self._warnings(src, dest, "pages/flags.md")
        assert any("in_person" in w and "online" in w for w in ws)

    def test_flag_defined_in_destination_canvas_toml(self, src, dest):
        _write(src, "pages/flags.md", "<!-- #if online -->\nx\n<!-- #endif -->\n")
        _write(dest, "course_settings/canvas.toml", "course_id = 1\n[course_flags]\nonline = true\n")
        ws = self._warnings(src, dest, "pages/flags.md")
        assert not any("course flag" in w for w in ws)

    def test_centralized_due_date(self, src, dest):
        ws = self._warnings(src, dest, "assignments/hw1.md")
        assert any("dates for 'HW 1'" in w and "due_dates" in w for w in ws)

    def test_relative_due_date(self, src, dest):
        with (src / "course_settings/course_settings.toml").open("a") as fh:
            fh.write(
                '\n[relative_due_dates.tables.default]\nitems = [{ name = "D 1", '
                'relative_to = { type = "START_OF_QUARTER" }, offsets = ["+1d"] }]\n'
            )
        ws = self._warnings(src, dest, "discussions/d1.md")
        assert any("dates for 'D 1'" in w and "relative_due_dates" in w for w in ws)

    def test_title_collision(self, src, dest):
        _write(dest, "assignments/old-hw1.md", "---\ntitle: HW 1\n---\nold\n")
        ws = self._warnings(src, dest, "assignments/hw1.md")
        assert any("titled 'HW 1'" in w and "assignments/old-hw1.md" in w for w in ws)

    def test_source_course_url(self, src, dest):
        _write(src, "pages/url.md", "[x](https://x/courses/555/files/1)\n")
        ws = self._warnings(src, dest, "pages/url.md")
        assert any("/courses/555/" in w for w in ws)

    def test_warnings_do_not_change_file(self, src, dest):
        assert _cp([src / "assignments/hw1.md"], dest)
        assert (dest / "assignments/hw1.md").read_bytes() == (
            src / "assignments/hw1.md"
        ).read_bytes()


# ---------------------------------------------------------------------------
# Write phase (3.1)
# ---------------------------------------------------------------------------


class TestWrite:
    def test_conflict_writes_nothing(self, src, dest, capsys):
        _write(dest, "assets/img/diagram.png", "DIFFERENT")
        before = _snapshot(dest)
        assert _cp([src / "assignments/hw1.md"], dest) is False
        assert _snapshot(dest) == before
        out = capsys.readouterr().out
        assert "assets/img/diagram.png" in out and "--overwrite" in out

    def test_overwrite_replaces(self, src, dest):
        _write(dest, "assets/img/diagram.png", "DIFFERENT")
        assert _cp([src / "assignments/hw1.md"], dest, overwrite=True)
        assert (dest / "assets/img/diagram.png").read_text() == "PNG-diagram"

    def test_noop_writes_nothing(self, src, dest, capsys):
        src_before, dest_before = _snapshot(src), _snapshot(dest)
        assert _cp([src / "modules/week-1.md"], dest, noop=True)
        assert _snapshot(src) == src_before
        assert _snapshot(dest) == dest_before
        assert "Would copy: modules/week-1.md" in capsys.readouterr().out

    def test_identical_summarised_unless_verbose(self, src, dest, capsys):
        _write(dest, "assets/img/diagram.png", "PNG-diagram")
        _cp([src / "assignments/hw1.md"], dest, noop=True)
        assert "1 file(s) already identical" in capsys.readouterr().out
        _cp([src / "assignments/hw1.md"], dest, noop=True, verbose=True)
        assert "Identical in destination, skipped: assets/img/diagram.png" in (
            capsys.readouterr().out
        )

    def test_fresh_mtime(self, src, dest):
        old = time.time() - 10 * 24 * 3600
        os.utime(src / "assets/img/diagram.png", (old, old))
        _write(dest, "assets/img/diagram.png", "DIFFERENT")
        last_synced = time.time() - 24 * 3600  # after the source edit, before now
        assert _cp([src / "assignments/hw1.md"], dest, overwrite=True)
        assert (dest / "assets/img/diagram.png").stat().st_mtime > last_synced

    def test_manifests_untouched(self, src, dest):
        manifest = _write(
            dest, ".manifest-canvas.toml",
            f"[_repo_format]\nformat_version = {repo_format.FORMAT_VERSION}\n",
        )
        before = manifest.read_bytes()
        assert _cp([src / "modules/week-1.md"], dest)
        assert manifest.read_bytes() == before
        assert not list(src.glob(".manifest-*.toml"))

    def test_nothing_git_added(self, src, dest):
        subprocess.run(["git", "init", "-q"], cwd=dest, check=True)
        assert _cp([src / "assignments/hw1.md"], dest)
        staged = subprocess.run(
            ["git", "diff", "--cached", "--name-only"], cwd=dest,
            capture_output=True, text=True, check=True,
        ).stdout
        assert staged == ""

    def test_ends_with_update_reminder(self, src, dest, capsys):
        assert _cp([src / "pages/intro.md"], dest)
        assert "Run `markdown-to-canvas update` on the destination" in capsys.readouterr().out


# ---------------------------------------------------------------------------
# CLI (3.2)
# ---------------------------------------------------------------------------


@pytest.fixture
def home(tmp_path, monkeypatch):
    home = tmp_path / "home"
    home.mkdir()
    monkeypatch.setenv("HOME", str(home))
    return home


class TestCli:
    def test_copy_by_registry_key(self, src, dest, home, tmp_path, monkeypatch):
        reg = home / ".config/markdown-to-canvas/course_registry.toml"
        reg.parent.mkdir(parents=True)
        reg.write_text(f'[courses]\n143 = "{dest}"\n')
        elsewhere = tmp_path / "elsewhere"
        elsewhere.mkdir()
        monkeypatch.chdir(elsewhere)
        result = CliRunner().invoke(main, ["cp", str(src / "pages/intro.md"), "143"])
        assert result.exit_code == 0, result.output
        assert f"Course dir: {dest.resolve()}  (course 143)" in result.output
        assert (dest / "pages/intro.md").exists()

    def test_missing_destination_is_usage_error(self, src):
        result = CliRunner().invoke(main, ["cp", str(src / "pages/intro.md")])
        assert result.exit_code == 2
        assert "COURSE_DIR" in result.output

    def test_help_shows_course_dir(self):
        result = CliRunner().invoke(main, ["cp", "--help"])
        assert "SRC... COURSE_DIR" in result.output

    def test_conflict_exit_code(self, src, dest):
        _write(dest, "pages/intro.md", "theirs\n")
        result = CliRunner().invoke(main, ["cp", str(src / "pages/intro.md"), str(dest)])
        assert result.exit_code == 1
        assert (dest / "pages/intro.md").read_text() == "theirs\n"

    def test_error_goes_through_die(self, src):
        result = CliRunner().invoke(main, ["cp", str(src / "pages/intro.md"), str(src)])
        assert result.exit_code == 1
        assert "Error:" in result.output and "mv" in result.output
        assert "Traceback" not in result.output


# ---------------------------------------------------------------------------
# End to end: cp, then update on the destination (4.1)
# ---------------------------------------------------------------------------


class TestEndToEnd:
    def test_check_all_on_destination_only_reports_links_not_followed(self, src, dest, capsys):
        """The only problem `update` finds after a module copy is the link cp listed."""
        from markdown_to_canvas.config import Config
        from markdown_to_canvas.sync import run_sync

        assert _cp([src / "modules/week-1.md"], dest)
        listed = capsys.readouterr().out
        assert "assignments/hw1.md -> pages/syllabus.md  (MISSING in destination)" in listed

        cfg = Config(base_url="https://school.instructure.com", course_id=1, api_token="tok")
        assert run_sync(cfg, dest, check_all=True) is True
        out = capsys.readouterr().out
        errors = out.split("errors occurred during the update")[1].splitlines()[1:]
        errors = [e.strip() for e in errors if e.strip()]
        assert errors == [
            "assignments/hw1.md: local file not found, removing tag: pages/syllabus.md",
            "module week-1.md: some items could not be added",  # hw1 was skipped
        ]

    def test_update_creates_assignment_with_rubric(self, src, dest, mocker):
        from unittest.mock import MagicMock

        from markdown_to_canvas.config import Config
        from markdown_to_canvas.sync import run_sync

        _write(src, "assignments/hw3.md", """
            ---
            title: HW 3
            rubric: "Essay Rubric"
            published: true
            ---
            ![Diagram](../assets/img/diagram.png)
        """)
        assert _cp([src / "assignments/hw3.md"], dest)

        canvas = mocker.patch("markdown_to_canvas.canvas_api.Canvas")
        course = MagicMock()
        canvas.return_value.get_course.return_value = course
        mocker.patch("markdown_to_canvas.manifest.flush")
        course.get_rubrics.return_value = []
        rubric = MagicMock(id=42)
        rubric.title = "Essay Rubric"
        course.create_rubric.return_value = {"rubric": rubric}
        assignment = MagicMock(id=98765, html_url="https://x/a/98765", rubric_settings=None)
        assignment.edit.return_value = assignment
        course.create_assignment.return_value = assignment
        course.upload.return_value = (True, {"id": 7, "url": "https://x/files/7/download"})

        cfg = Config(base_url="https://school.instructure.com", course_id=1, api_token="tok")
        run_sync(cfg, dest)

        created = course.create_assignment.call_args[1]["assignment"]
        assert created["name"] == "HW 3"
        assoc = course.create_rubric_association.call_args[1]["rubric_association"]
        assert assoc["rubric_id"] == 42
        assert assoc["association_id"] == 98765


def test_cp_copies_asset_linked_from_snippet_of_deep_page(tmp_path, dest):
    src = tmp_path / "deep-src"
    _write(src, "course_settings/course_settings.toml", 'name = "Src"\n')
    _write(src, "snippets/policy.md", "![logo](../assets/logo.png)\n")
    _write(src, "pages/week1/intro.md", "[x](../../snippets/policy.md)\n")
    _write(src, "assets/logo.png", "x")
    make_current(src)
    _cp([src / "pages/week1/intro.md"], dest)
    assert (dest / "assets/logo.png").exists()
    assert (dest / "snippets/policy.md").exists()
