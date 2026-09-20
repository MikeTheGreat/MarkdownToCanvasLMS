"""Tests for the generate-due-dates command: plan, diff, confirmation, writing, warnings."""
from __future__ import annotations

import tomllib
from pathlib import Path
from unittest.mock import MagicMock

import pytest
from click.testing import CliRunner

from markdown_to_canvas import generate_due_dates as gd
from markdown_to_canvas import relative_dates as rd
from markdown_to_canvas.cli import main
from markdown_to_canvas.config import Config
from markdown_to_canvas.repo_format import RepoFormatError
from markdown_to_canvas.sync import run_sync
from tests.conftest import make_current

TERM = """\
first_day = 2026-09-30
last_day = 2026-12-18
time_zone = "America/Los_Angeles"
default_due_time = "23:59"
noninstructional_days = [
  { title = "Non-Instructional Day", date = 2026-10-21 },
]
"""

SETTINGS = """\
# course settings
title = "Course"

due_dates = [
    { name = "Week 1 Problem Set", due_at = "2000-01-01T00:00:00-08:00", unlock_at = "KEEP", lock_at = "KEEP", only_if = "in_person" },
    { name = "Old Item", due_at = "NONE", unlock_at = "KEEP", lock_at = "KEEP" },
]

[course_flags]
in_person = true

[relative_due_dates]
days_of_week = ["Mon", "Wed"]
lock_relative_default = "+7 CALENDAR_DAY"

[relative_due_dates.tables.quarter11]
items = [
    { name = "Week 1 Problem Set", relative_to = { type = "START_OF_QUARTER" }, offsets = ["+1 CLASS_DAY"] },
    { name = "Week 1 Discussion", type = "discussion", relative_to = { type = "START_OF_QUARTER" }, offsets = ["+2 CLASS_DAY"], unlock_offset = "NONE" },
    { name = "Midterm Quiz", type = "quiz", relative_to = { type = "NO_DUE_DATE" } },
]
"""


def _write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def _repo(tmp_path: Path, settings: str = SETTINGS, content: bool = True) -> Path:
    root = tmp_path / "course"
    _write(root / "course_settings" / "course_settings.toml", settings)
    make_current(root)
    if content:
        _write(root / "assignments" / "w1.md", "---\ntitle: Week 1 Problem Set\n---\n\nHi\n")
        _write(root / "discussions" / "w1.md", "---\ntitle: Week 1 Discussion\n---\n\nHi\n")
        _write(root / "quizzes" / "midterm" / "midterm.md", "---\ntitle: Midterm Quiz\n---\n")
    return root


def _term(tmp_path: Path) -> Path:
    path = tmp_path / "term.toml"
    path.write_text(TERM)
    return path


def _settings_text(root: Path) -> str:
    return (root / "course_settings" / "course_settings.toml").read_text()


def _run(root, term, *args, **kwargs):
    return CliRunner().invoke(main, ["generate-due-dates", str(term), str(root), *args], **kwargs)


def _entries(root: Path) -> dict[str, dict]:
    data = tomllib.loads(_settings_text(root))
    return {e["name"]: e for e in data["due_dates"]}


# --- planning -----------------------------------------------------------------


def test_plan_lists_added_changed_and_leaves_others(tmp_path):
    root = _repo(tmp_path)
    plan = gd.plan_generation(root, _term(tmp_path))
    by_name = {c.name: c for c in plan.changes}

    assert plan.table_name == "quarter11"
    assert by_name["Week 1 Problem Set"].kind == "changed"
    assert set(by_name["Week 1 Problem Set"].fields) == {"due_at", "unlock_at", "lock_at"} - {"unlock_at"}
    assert by_name["Week 1 Discussion"].kind == "added"
    assert by_name["Midterm Quiz"].kind == "added"
    assert by_name["Midterm Quiz"].type == "quiz"
    assert "Old Item" not in by_name


def test_computed_values(tmp_path):
    root = _repo(tmp_path)
    plan = gd.plan_generation(root, _term(tmp_path))
    by_name = {c.name: c for c in plan.changes}
    assert by_name["Week 1 Problem Set"].values == {
        "unlock_at": "KEEP",
        "due_at": "2026-10-05T23:59:00-07:00",
        "lock_at": "2026-10-12T23:59:00-07:00",
    }
    assert by_name["Week 1 Discussion"].values == {
        "unlock_at": "NONE",
        "due_at": "2026-10-07T23:59:00-07:00",
        "lock_at": "2026-10-14T23:59:00-07:00",
    }
    # no due date: due NONE, and the lock rule cannot apply -> KEEP, with a warning
    quiz = by_name["Midterm Quiz"].values
    assert (quiz["due_at"], quiz["lock_at"]) == ("NONE", "KEEP")
    assert any("'Midterm Quiz'" in w and "no due date" in w for w in plan.warnings)


def test_unchanged_when_values_match_even_if_written_differently(tmp_path):
    root = _repo(tmp_path)
    term = _term(tmp_path)
    gd.apply_plan(gd.plan_generation(root, term))
    text = _settings_text(root).replace("-07:00", "-07:00")  # same instants stay unchanged
    plan = gd.plan_generation(root, term)
    assert not plan.has_changes
    # 23:59-07:00 is the same instant as 06:59Z the next day
    _write(
        root / "course_settings" / "course_settings.toml",
        text.replace("2026-10-05T23:59:00-07:00", "2026-10-06T06:59:00+00:00"),
    )
    assert not gd.plan_generation(root, term).has_changes


def test_old_repo_is_refused(tmp_path):
    root = _repo(tmp_path)
    _write(
        root / "course_settings" / "course_settings.toml",
        _settings_text(root).replace("format_version = 2", "format_version = 1"),
    )
    with pytest.raises(RepoFormatError):
        gd.plan_generation(root, _term(tmp_path))
    result = _run(root, _term(tmp_path))
    assert result.exit_code == 1 and "upgrade" in result.output


def test_repo_without_settings_file_writes_nothing(tmp_path):
    root = tmp_path / "empty"
    (root / "course_settings").mkdir(parents=True)
    with pytest.raises(RepoFormatError):  # a missing file counts as format version 0
        gd.plan_generation(root, _term(tmp_path))
    assert list((root / "course_settings").iterdir()) == []
    result = _run(root, _term(tmp_path), "--yes")
    assert result.exit_code == 1 and not (root / "course_settings" / "course_settings.toml").exists()


# --- command: confirmation and writing ---------------------------------------


def test_noop_prints_the_diff_and_writes_nothing(tmp_path):
    root = _repo(tmp_path)
    before = _settings_text(root)
    result = _run(root, _term(tmp_path), "--noop")
    assert result.exit_code == 0, result.output
    assert "changed: Week 1 Problem Set" in result.output
    assert "added:   Week 1 Discussion (discussion)" in result.output
    assert "--noop" in result.output
    assert _settings_text(root) == before


def test_diff_lines_for_changes_are_yellow(tmp_path):
    root = _repo(tmp_path)
    result = _run(root, _term(tmp_path), "--noop", color=True)
    assert "\x1b[33m  changed: Week 1 Problem Set" in result.output
    assert "\x1b[33m  added:" in result.output
    unchanged_or_header = [l for l in result.output.splitlines() if l.startswith("Relative table")]
    assert unchanged_or_header and "\x1b[33m" not in unchanged_or_header[0]


def test_no_terminal_without_yes_fails_and_writes_nothing(tmp_path):
    root = _repo(tmp_path)
    before = _settings_text(root)
    result = _run(root, _term(tmp_path))
    assert result.exit_code == 1
    assert "--yes" in result.output
    assert _settings_text(root) == before


def test_yes_writes_without_asking(tmp_path):
    root = _repo(tmp_path)
    result = _run(root, _term(tmp_path), "--yes")
    assert result.exit_code == 0, result.output
    assert "changed: Week 1 Problem Set" in result.output  # the diff is still shown
    entries = _entries(root)
    assert entries["Week 1 Problem Set"]["due_at"] == "2026-10-05T23:59:00-07:00"
    assert entries["Week 1 Problem Set"]["lock_at"] == "2026-10-12T23:59:00-07:00"


def test_confirming_writes_and_declining_does_not(tmp_path, mocker):
    mocker.patch("markdown_to_canvas.cli._stdin_is_terminal", return_value=True)
    root = _repo(tmp_path)
    before = _settings_text(root)
    declined = _run(root, _term(tmp_path), input="n\n")
    assert declined.exit_code == 0
    assert "nothing was changed" in declined.output
    assert _settings_text(root) == before

    accepted = _run(root, _term(tmp_path), input="y\n")
    assert accepted.exit_code == 0, accepted.output
    assert _entries(root)["Week 1 Discussion"]["due_at"] == "2026-10-07T23:59:00-07:00"


def test_nothing_to_change_does_not_prompt_or_write(tmp_path):
    root = _repo(tmp_path)
    assert _run(root, _term(tmp_path), "--yes").exit_code == 0
    before = (root / "course_settings" / "course_settings.toml").read_bytes()
    again = _run(root, _term(tmp_path))  # no --yes and no terminal: still fine
    assert again.exit_code == 0, again.output
    assert "Nothing to change" in again.output
    assert (root / "course_settings" / "course_settings.toml").read_bytes() == before


def test_hand_edited_entry_is_shown_as_overwritten(tmp_path):
    root = _repo(tmp_path)
    term = _term(tmp_path)
    assert _run(root, term, "--yes").exit_code == 0
    path = root / "course_settings" / "course_settings.toml"
    path.write_text(_settings_text(root).replace("2026-10-05T23:59:00-07:00", "2026-10-06T12:00:00-07:00"))
    result = _run(root, term, "--noop")
    assert "2026-10-06T12:00:00-07:00 -> 2026-10-05T23:59:00-07:00" in result.output


def test_bad_term_file_and_bad_table_are_reported_without_a_traceback(tmp_path):
    root = _repo(tmp_path)
    bad = tmp_path / "bad.toml"
    bad.write_text('first_day = 2026-09-30\n')
    result = _run(root, bad)
    assert result.exit_code == 1 and "last_day" in result.output
    result = _run(root, _term(tmp_path), "--table", "summer8")
    assert result.exit_code == 1 and "summer8" in result.output and "quarter11" in result.output


# --- writing preserves everything else ---------------------------------------


def test_only_the_changed_rows_differ(tmp_path):
    root = _repo(tmp_path)
    before = _settings_text(root)
    assert _run(root, _term(tmp_path), "--yes").exit_code == 0
    after = _settings_text(root)

    # everything outside the due_dates array is byte-for-byte the same
    head, _, tail = before.partition("due_dates = [")
    _, _, tail = tail.partition("]\n")
    assert after.startswith(head) and after.endswith(tail)

    entry = _entries(root)["Week 1 Problem Set"]
    assert entry["only_if"] == "in_person"  # other keys of an existing entry survive
    assert _entries(root)["Old Item"] == {
        "name": "Old Item", "due_at": "NONE", "unlock_at": "KEEP", "lock_at": "KEEP"
    }
    assert "# course settings" in after
    parsed = tomllib.loads(after)
    assert parsed["course_flags"] == {"in_person": True}
    assert parsed["relative_due_dates"] == tomllib.loads(before)["relative_due_dates"]


def test_new_entries_have_name_type_only_when_given_and_the_three_dates(tmp_path):
    root = _repo(tmp_path)
    assert _run(root, _term(tmp_path), "--yes").exit_code == 0
    entries = _entries(root)
    assert list(entries["Week 1 Discussion"]) == ["name", "type", "unlock_at", "due_at", "lock_at"]
    assert entries["Midterm Quiz"]["due_at"] == "NONE"
    assert entries["Midterm Quiz"]["type"] == "quiz"
    # entries added for items without a type have no type key
    root2 = _repo(
        tmp_path / "two",
        SETTINGS.replace('type = "discussion", ', "").replace('type = "quiz", ', ""),
    )
    assert _run(root2, _term(tmp_path), "--yes").exit_code == 0
    assert "type" not in _entries(root2)["Week 1 Discussion"]


def test_creates_due_dates_before_the_first_table_when_absent(tmp_path):
    settings = SETTINGS.split("due_dates = [")[0] + "[course_flags]\nin_person = true\n\n" + (
        "[relative_due_dates" + SETTINGS.split("[relative_due_dates", 1)[1]
    )
    root = _repo(tmp_path, settings)
    assert _run(root, _term(tmp_path), "--yes").exit_code == 0
    data = tomllib.loads(_settings_text(root))
    assert {e["name"] for e in data["due_dates"]} == {
        "Week 1 Problem Set", "Week 1 Discussion", "Midterm Quiz",
    }
    assert data["course_flags"] == {"in_person": True}  # not captured by a table header
    assert "due_dates" not in data["course_flags"]
    assert data["title"] == "Course"


def test_block_style_due_dates_are_supported(tmp_path):
    settings = (
        'title = "Course"\n\n'
        '[[due_dates]]\nname = "Week 1 Problem Set"\ndue_at = "NONE"\nonly_if = "x"\n\n'
        + "[relative_due_dates" + SETTINGS.split("[relative_due_dates", 1)[1]
    )
    root = _repo(tmp_path, settings)
    assert _run(root, _term(tmp_path), "--yes").exit_code == 0
    entries = _entries(root)
    assert entries["Week 1 Problem Set"]["due_at"] == "2026-10-05T23:59:00-07:00"
    assert entries["Week 1 Problem Set"]["only_if"] == "x"
    assert entries["Week 1 Discussion"]["due_at"] == "2026-10-07T23:59:00-07:00"


def test_apply_refuses_when_the_file_changed_after_planning(tmp_path):
    root = _repo(tmp_path)
    plan = gd.plan_generation(root, _term(tmp_path))
    path = root / "course_settings" / "course_settings.toml"
    path.write_text(path.read_text() + "\n# edited meanwhile\n")
    with pytest.raises(rd.RelativeDueDatesError, match="changed while generating"):
        gd.apply_plan(plan)
    assert path.read_text().endswith("# edited meanwhile\n")


# --- table selection through the command -------------------------------------


def test_second_table_chosen_by_option_or_term_file(tmp_path):
    settings = SETTINGS + (
        '\n[relative_due_dates.tables.summer8]\ndays_of_week = ["Mon", "Tue", "Wed", "Thu"]\n'
        'items = [ { name = "Week 1 Problem Set", relative_to = { type = "START_OF_QUARTER" }, offsets = ["+1 CLASS_DAY"] } ]\n'
    )
    root = _repo(tmp_path, settings)
    term = _term(tmp_path)

    unchosen = _run(root, term, "--noop")
    assert unchosen.exit_code == 1
    assert "quarter11" in unchosen.output and "summer8" in unchosen.output

    by_option = _run(root, term, "--noop", "--table", "summer8")
    assert by_option.exit_code == 0, by_option.output
    assert "Relative table: summer8" in by_option.output
    assert "2026-10-01T23:59:00-07:00" in by_option.output  # Thursday 10-01 is the next class day

    named = tmp_path / "named.toml"
    named.write_text(TERM + 'relative_table = "quarter11"\n')
    assert "Relative table: quarter11" in _run(root, named, "--noop").output
    assert "Relative table: summer8" in _run(root, named, "--noop", "--table", "summer8").output


# --- warnings ----------------------------------------------------------------


def _warnings(root, tmp_path, settings=None):
    return gd.plan_generation(root, _term(tmp_path)).warnings


def test_item_matching_nothing_is_reported_once_naming_the_table(tmp_path):
    settings = SETTINGS.replace(
        '    { name = "Midterm Quiz", type = "quiz"',
        '    { name = "Week 12 Quiz", relative_to = { type = "NO_DUE_DATE" } },\n'
        '    { name = "Midterm Quiz", type = "quiz"',
    )
    root = _repo(tmp_path, settings)
    hits = [w for w in _warnings(root, tmp_path) if "Week 12 Quiz" in w and "matches no" in w]
    assert len(hits) == 1
    assert "relative table 'quarter11'" in hits[0] and "due_dates" not in hits[0]


def test_item_matching_nothing_that_is_also_in_due_dates_names_both(tmp_path):
    settings = SETTINGS.replace(
        '    { name = "Midterm Quiz", type = "quiz"',
        '    { name = "Old Item", relative_to = { type = "NO_DUE_DATE" } },\n'
        '    { name = "Midterm Quiz", type = "quiz"',
    )
    root = _repo(tmp_path, settings)
    hits = [w for w in _warnings(root, tmp_path) if "'Old Item'" in w and "matches no" in w]
    assert len(hits) == 1
    assert "relative table 'quarter11' and due_dates" in hits[0]


def test_content_in_neither_table_is_reported_once(tmp_path):
    root = _repo(tmp_path)
    _write(root / "discussions" / "intro.md", "---\ntitle: Intro Post\n---\n\nHi\n")
    hits = [w for w in _warnings(root, tmp_path) if "Intro Post" in w]
    assert len(hits) == 1 and "neither" in hits[0] and "due_dates" in hits[0]


def test_content_missing_only_from_the_relative_table(tmp_path):
    root = _repo(tmp_path)
    _write(root / "assignments" / "lab.md", "---\ntitle: Lab 3\n---\n\nHi\n")
    _write(
        root / "course_settings" / "course_settings.toml",
        _settings_text(root).replace(
            '    { name = "Old Item"',
            '    { name = "Lab 3", due_at = "NONE" },\n    { name = "Old Item"',
        ),
    )
    hits = [w for w in _warnings(root, tmp_path) if "Lab 3" in w]
    assert len(hits) == 1
    assert "has a due_dates entry but no item in relative table" in hits[0]


def test_ignored_titles_are_not_reported(tmp_path):
    root = _repo(tmp_path)
    _write(root / "assignments" / "w10.md", "---\ntitle: Week 10 Problem Set\n---\n\nHi\n")
    assert any("Week 10 Problem Set" in w for w in _warnings(root, tmp_path))
    _write(
        root / "course_settings" / "course_settings.toml",
        _settings_text(root).replace(
            "items = [\n    { name = \"Week 1 Problem Set\"",
            'ignore = ["Week 10 Problem Set", "Old Item"]\nitems = [\n    { name = "Week 1 Problem Set"',
        ),
    )
    plan = gd.plan_generation(root, _term(tmp_path))
    assert not any("Week 10 Problem Set" in w for w in plan.warnings)
    assert not any("Old Item" in n for n in plan.notices)


def test_leftover_due_dates_entries_are_reported_not_changed(tmp_path):
    root = _repo(tmp_path)
    plan = gd.plan_generation(root, _term(tmp_path))
    assert any("'Old Item'" in n and "left unchanged" in n for n in plan.notices)
    assert _run(root, _term(tmp_path), "--yes").exit_code == 0
    assert _entries(root)["Old Item"]["due_at"] == "NONE"


def test_item_with_a_type_matches_only_content_of_that_type(tmp_path):
    root = _repo(tmp_path)
    settings = _settings_text(root).replace(
        'name = "Week 1 Discussion", type = "discussion"', 'name = "Week 1 Discussion", type = "quiz"'
    )
    _write(root / "course_settings" / "course_settings.toml", settings)
    warnings = _warnings(root, tmp_path)
    assert any("'Week 1 Discussion' (type=quiz) is in relative table" in w for w in warnings)


# --- end to end with update ---------------------------------------------------


def test_generated_dates_reach_canvas_through_update_and_only_if_still_applies(tmp_path, mocker):
    root = _repo(tmp_path, content=False)
    _write(root / "assignments" / "w1.md", "---\ntitle: Week 1 Problem Set\n---\n\nHi\n")
    assert _run(root, _term(tmp_path), "--yes").exit_code == 0

    canvas_cls = mocker.patch("markdown_to_canvas.canvas_api.Canvas")
    course = MagicMock()
    canvas_cls.return_value.get_course.return_value = course
    created = MagicMock(id=101, html_url="https://s.instructure.com/courses/1/assignments/101")
    course.create_assignment.return_value = created
    cfg = Config(base_url="https://s.instructure.com", course_id=1, api_token="t")

    run_sync(cfg, root)

    params = course.create_assignment.call_args.kwargs["assignment"]
    assert params["due_at"] == "2026-10-05T23:59:00-07:00"
    assert params["lock_at"] == "2026-10-12T23:59:00-07:00"

    # only_if = "in_person" is still honored by update: flip the flag off and the entry drops out
    off = _settings_text(root).replace("in_person = true", "in_person = false")
    (root / "course_settings" / "course_settings.toml").write_text(off)
    course.reset_mock()
    course.create_assignment.return_value = created
    (root / ".manifest-canvas.toml").unlink(missing_ok=True)
    run_sync(cfg, root)
    dropped = course.create_assignment.call_args.kwargs["assignment"]
    assert "due_at" not in dropped or dropped["due_at"] != "2026-10-05T23:59:00-07:00"
