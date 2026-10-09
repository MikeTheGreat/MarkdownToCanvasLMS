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

[relative_due_dates.tables.default]
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
    return CliRunner().invoke(main, ["generate-due-dates", str(root), "--term", str(term), *args], **kwargs)


def _entries(root: Path) -> dict[str, dict]:
    data = tomllib.loads(_settings_text(root))
    return {e["name"]: e for e in data["due_dates"]}


# --- planning -----------------------------------------------------------------


def test_plan_lists_added_changed_and_leaves_others(tmp_path):
    root = _repo(tmp_path)
    plan = gd.plan_generation(root, _term(tmp_path))
    by_name = {c.name: c for c in plan.changes}

    assert plan.table_name == "default"
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
        _settings_text(root).replace("format_version = 14", "format_version = 1"),
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
    assert (
        "Week 1 Problem Set:\n"
        "\tdue_at: 2000-01-01T00:00:00-08:00\n"
        "\t     -> 2026-10-05T23:59:00-07:00\n"
        "\tlock_at: KEEP -> 2026-10-12T23:59:00-07:00\n"
    ) in result.output
    assert (
        "Week 1 Discussion (discussion) (new entry):\n"
        "\tdue_at: 2026-10-07T23:59:00-07:00\n"
        "\tlock_at: 2026-10-14T23:59:00-07:00\n"
        "\tunlock_at: NONE\n"
    ) in result.output
    assert "--noop" in result.output
    assert _settings_text(root) == before


def test_diff_lines_for_changes_are_yellow(tmp_path):
    root = _repo(tmp_path)
    result = _run(root, _term(tmp_path), "--noop", color=True)
    assert "\x1b[33mWeek 1 Problem Set:" in result.output
    assert "\x1b[33m\tdue_at: 2000-01-01T00:00:00-08:00" in result.output
    assert "\x1b[33m\t     -> 2026-10-05T23:59:00-07:00" in result.output
    assert "\x1b[33mWeek 1 Discussion (discussion) (new entry):" in result.output
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
    assert "Week 1 Problem Set:\n\tdue_at:" in result.output  # the diff is still shown
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
    assert "\tdue_at: 2026-10-06T12:00:00-07:00\n\t     -> 2026-10-05T23:59:00-07:00" in result.output


def test_bad_term_file_and_bad_table_are_reported_without_a_traceback(tmp_path):
    root = _repo(tmp_path)
    bad = tmp_path / "bad.toml"
    bad.write_text('first_day = 2026-09-30\n')
    result = _run(root, bad)
    assert result.exit_code == 1 and "last_day" in result.output
    result = _run(root, _term(tmp_path), "--table", "summer8")
    assert result.exit_code == 1 and "summer8" in result.output and "default" in result.output


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


def test_second_table_chosen_by_option(tmp_path):
    settings = SETTINGS + (
        '\n[relative_due_dates.tables.summer8]\ndays_of_week = ["Mon", "Tue", "Wed", "Thu"]\n'
        'items = [ { name = "Week 1 Problem Set", relative_to = { type = "START_OF_QUARTER" }, offsets = ["+1 CLASS_DAY"] } ]\n'
    )
    root = _repo(tmp_path, settings)
    term = _term(tmp_path)

    unchosen = _run(root, term, "--noop")
    assert unchosen.exit_code == 0, unchosen.output
    assert "Relative table: default" in unchosen.output  # `default` wins when no --table

    by_option = _run(root, term, "--noop", "--table", "summer8")
    assert by_option.exit_code == 0, by_option.output
    assert "Relative table: summer8" in by_option.output
    assert "2026-10-01T23:59:00-07:00" in by_option.output  # Thursday 10-01 is the next class day


def test_no_default_table_needs_the_table_option(tmp_path):
    root = _repo(tmp_path, SETTINGS.replace("tables.default]", "tables.quarter11]"))
    term = _term(tmp_path)
    unchosen = _run(root, term, "--noop")
    assert unchosen.exit_code == 1
    assert "quarter11" in unchosen.output and "--table" in unchosen.output
    assert "Traceback" not in unchosen.output
    assert _run(root, term, "--noop", "--table", "quarter11").exit_code == 0


def test_term_file_with_relative_table_is_rejected_by_the_command(tmp_path):
    root = _repo(tmp_path)
    old = tmp_path / "old.toml"
    old.write_text(TERM + 'relative_table = "default"\n')
    result = _run(root, old, "--noop")
    assert result.exit_code == 1
    assert "relative_table" in result.output and "--table" in result.output
    assert "Traceback" not in result.output


# --- due dates outside the term -------------------------------------------------


@pytest.mark.parametrize("flag", ["--yes", "--noop"])
def test_due_date_outside_the_term_stops_the_run_and_writes_nothing(tmp_path, flag):
    stale = SETTINGS.replace(
        '    { name = "Midterm Quiz"',
        '    { name = "Week 1 Discussion Reply", relative_to = { type = "ABSOLUTE_DATE", date = "2026-05-04" } },\n'
        '    { name = "Midterm Quiz"',
    )
    root = _repo(tmp_path, stale)
    before = _settings_text(root)
    result = _run(root, _term(tmp_path), flag)
    assert result.exit_code == 1
    assert "1 item is due outside the term (2026-09-30 to 2026-12-18)" in result.output
    assert "Its relative_to is ABSOLUTE_DATE 2026-05-04." in result.output
    assert "Relative table:" not in result.output  # stopped before the plan was shown
    assert _settings_text(root) == before


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
    assert "relative table 'default'" in hits[0] and "due_dates" not in hits[0]


def test_item_matching_nothing_that_is_also_in_due_dates_names_both(tmp_path):
    settings = SETTINGS.replace(
        '    { name = "Midterm Quiz", type = "quiz"',
        '    { name = "Old Item", relative_to = { type = "NO_DUE_DATE" } },\n'
        '    { name = "Midterm Quiz", type = "quiz"',
    )
    root = _repo(tmp_path, settings)
    hits = [w for w in _warnings(root, tmp_path) if "'Old Item'" in w and "matches no" in w]
    assert len(hits) == 1
    assert "relative table 'default' and due_dates" in hits[0]


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


def test_field_lines_are_alphabetical_and_datetimes_line_up():
    plan = gd.GenerationPlan(
        table_name="t", warnings=[], notices=[], settings_path=Path("x"), source_text="",
        changes=[
            gd.EntryChange(
                "Space Needle", None, "changed",
                fields={
                    "unlock_at": ("CREATE_NONE_THEN_KEEP", "KEEP"),
                    "due_at": ("2026-04-18T06:59:00", "2026-10-21T23:59:00-07:00"),
                    "lock_at": ("CREATE_NONE_THEN_KEEP", "KEEP"),
                },
            )
        ],
    )
    lines = [text for text, _ in gd.render_plan(plan)]
    assert lines[0].startswith("Not rescheduling dates: no cutoff")
    assert lines[2:] == [
        "Space Needle:",
        "\tdue_at: 2026-04-18T06:59:00",
        "\t     -> 2026-10-21T23:59:00-07:00",
        "\tlock_at: CREATE_NONE_THEN_KEEP -> KEEP",
        "\tunlock_at: CREATE_NONE_THEN_KEEP -> KEEP",
    ]
    # the two date values start in the same column
    assert lines[3].index("2026") == lines[4].index("2026")


# --- dont_reschedule_dates_before ---------------------------------------------

PS = "Week 1 Problem Set"  # computed: unlock KEEP, due 2026-10-05, lock 2026-10-12 (23:59)
DISC = "Week 1 Discussion"  # computed: unlock NONE, due 2026-10-07, lock 2026-10-14


def _at(day: str) -> str:
    """23:59 Pacific on ``day`` (MM-DD in 2026), as generate-due-dates writes it."""
    return f"2026-{day}T23:59:00-07:00"


def _cutoff_settings(cutoff: str | None, rows: list[str], extra_items: str = "") -> str:
    cutoff_line = f'dont_reschedule_dates_before = "{cutoff}"\n' if cutoff is not None else ""
    return (
        '# course settings\ntitle = "Course"\n\ndue_dates = [\n'
        + "".join(f"    {r},\n" for r in rows)
        + "]\n\n[relative_due_dates]\n"
        + cutoff_line
        + 'days_of_week = ["Mon", "Wed"]\nlock_relative_default = "+7 CALENDAR_DAY"\n\n'
        + "[relative_due_dates.tables.default]\nitems = [\n"
        + f'    {{ name = "{PS}", relative_to = {{ type = "START_OF_QUARTER" }}, offsets = ["+1 CLASS_DAY"] }},\n'
        + f'    {{ name = "{DISC}", type = "discussion", relative_to = {{ type = "START_OF_QUARTER" }}, offsets = ["+2 CLASS_DAY"], unlock_offset = "NONE" }},\n'
        + extra_items
        + "]\n"
    )


def _row(name, unlock, due, lock, kind=None):
    type_part = f', type = "{kind}"' if kind else ""
    return f'{{ name = "{name}"{type_part}, unlock_at = "{unlock}", due_at = "{due}", lock_at = "{lock}" }}'


def _cutoff_plan(tmp_path, cutoff, rows, extra_items=""):
    root = _repo(tmp_path, _cutoff_settings(cutoff, rows, extra_items))
    return root, gd.plan_generation(root, _term(tmp_path))


def _change(plan, name):
    return next(c for c in plan.changes if c.name == name)


def test_past_item_is_untouched(tmp_path):
    root, plan = _cutoff_plan(
        tmp_path, "2026-10-01", [_row(PS, _at("09-24"), _at("09-30"), _at("10-01"))]
    )
    change = _change(plan, PS)
    assert change.kind == "unchanged" and change.fields == {}
    assert list(change.kept) == ["unlock_at", "due_at", "lock_at"]
    assert plan.not_rescheduled == [change]


def test_due_exactly_at_the_cutoff_is_kept(tmp_path):
    root, plan = _cutoff_plan(
        tmp_path, "2026-10-01 23:59", [_row(PS, "KEEP", _at("10-01"), "KEEP")]
    )
    change = _change(plan, PS)
    assert "due_at" in change.kept and "due_at" not in change.fields
    assert set(change.fields) == {"lock_at"}


def test_open_item_keeps_only_its_past_unlock(tmp_path):
    root, plan = _cutoff_plan(
        tmp_path, "2026-10-01", [_row(PS, _at("09-28"), _at("10-06"), _at("10-13"))]
    )
    change = _change(plan, PS)
    assert change.kind == "changed" and list(change.kept) == ["unlock_at"]
    gd.apply_plan(plan)
    entry = _entries(root)[PS]
    assert (entry["unlock_at"], entry["due_at"], entry["lock_at"]) == (
        _at("09-28"), _at("10-05"), _at("10-12"),
    )


def test_future_date_moved_into_the_past_and_sentinels_are_written(tmp_path):
    root, plan = _cutoff_plan(tmp_path, "2026-10-13", [_row(PS, "KEEP", _at("10-14"), "KEEP")])
    gd.apply_plan(plan)
    entry = _entries(root)[PS]
    # due 10-14 was after the cutoff, so it moves to 10-05 (before it); KEEP is not a date
    assert (entry["due_at"], entry["lock_at"]) == (_at("10-05"), _at("10-12"))
    assert plan.not_rescheduled == []


def test_naive_current_date_is_read_in_the_term_zone(tmp_path):
    # Read in Pacific time this is after the cutoff; read as UTC it would be
    # 2026-10-01 22:00 Pacific, before the cutoff, and would be kept.
    root, plan = _cutoff_plan(
        tmp_path, "2026-10-01", [_row(PS, "KEEP", "2026-10-02T05:00:00", "KEEP")]
    )
    assert "due_at" not in _change(plan, PS).kept


def test_new_entry_is_written_in_full_even_before_the_cutoff(tmp_path):
    root, plan = _cutoff_plan(tmp_path, "2026-10-15", [_row(PS, "KEEP", _at("10-05"), _at("10-12"))])
    assert _change(plan, DISC).kind == "added"
    gd.apply_plan(plan)
    assert _entries(root)[DISC]["due_at"] == _at("10-07")


def test_kept_field_with_no_difference_is_not_counted(tmp_path):
    root, plan = _cutoff_plan(tmp_path, "2026-10-06", [_row(PS, "KEEP", _at("10-05"), _at("10-12"))])
    assert _change(plan, PS).kept == {}
    assert plan.not_rescheduled == []


EARLY = '    { name = "Early Lab", relative_to = { type = "ABSOLUTE_DATE", date = "2026-09-30" }, lock_offset = "+1 CALENDAR_DAY" },\n'


def _inconsistent_plan(tmp_path, cutoff="2026-10-01"):
    # unlock 2026-10-01 is kept; due moves from 10-06 to 09-30, before the kept unlock
    rows = [
        _row(PS, "KEEP", _at("10-20"), _at("10-27")),
        _row("Early Lab", _at("10-01"), _at("10-06"), _at("10-13")),
    ]
    return _cutoff_plan(tmp_path, cutoff, rows, EARLY)


def test_inconsistent_entry_is_skipped_with_an_error(tmp_path):
    root, plan = _inconsistent_plan(tmp_path)
    change = _change(plan, "Early Lab")
    assert change.kind == "skipped" and change.fields == {}
    (error,) = plan.errors
    assert "Early Lab" in error
    assert error.startswith(
        "ERROR: Early Lab: keeping the dates on or before 2026-10-01 puts "
        f"unlock_at (kept, {_at('10-01')}) after due_at (computed, {_at('09-30')}). "
    )
    before = _entries(root)["Early Lab"]
    gd.apply_plan(plan)
    entries = _entries(root)
    assert entries["Early Lab"] == before
    assert entries[PS]["due_at"] == _at("10-05")  # the others are still written
    text = _settings_text(root)
    assert "\n# course settings\n" in text
    assert text.count("dont_reschedule_dates_before") == 1


def test_entry_without_kept_fields_is_not_checked(tmp_path):
    root, plan = _inconsistent_plan(tmp_path, cutoff="2026-09-30 12:00")
    assert _change(plan, "Early Lab").kind == "changed" and plan.errors == []


def test_bad_cutoff_stops_before_calculating(tmp_path, mocker):
    root = _repo(tmp_path, _cutoff_settings("2026-01-15", [_row(PS, "KEEP", "KEEP", "KEEP")]))
    calculate = mocker.patch.object(rd, "calculate", side_effect=AssertionError("calculated"))
    before = _settings_text(root)
    with pytest.raises(rd.RelativeDueDatesError, match="outside the term"):
        gd.plan_generation(root, _term(tmp_path))
    calculate.assert_not_called()
    result = _run(root, _term(tmp_path), "--yes")
    assert result.exit_code == 1 and "outside the term" in result.output
    assert _settings_text(root) == before


# --- dont_reschedule_dates_before: command output -----------------------------


def test_cutoff_is_shown_first(tmp_path):
    root = _repo(tmp_path, _cutoff_settings("2026-10-01", [_row(PS, "KEEP", _at("10-05"), _at("10-12"))]))
    result = _run(root, _term(tmp_path), "--noop")
    lines = result.output.splitlines()
    first = next(i for i, l in enumerate(lines) if l.startswith("Not rescheduling"))
    assert lines[first] == (
        "Not rescheduling dates on or before: Thu Oct 1, 2026 11:59 PM PDT "
        "(dont_reschedule_dates_before)"
    )
    assert lines[first + 1].startswith("Relative table")


def test_no_cutoff_is_shown(tmp_path):
    result = _run(_repo(tmp_path), _term(tmp_path), "--noop")
    assert "Not rescheduling dates: no cutoff (dont_reschedule_dates_before is not set)" in result.output


def _three_kept(tmp_path):
    rows = [
        _row(PS, _at("09-24"), _at("09-30"), _at("10-01")),
        _row(DISC, _at("09-24"), _at("09-30"), _at("10-01"), kind="discussion"),
        _row("Early Lab", "KEEP", _at("09-29"), _at("10-01")),
    ]
    return _repo(tmp_path, _cutoff_settings("2026-10-01", rows, EARLY))


def test_kept_resources_are_counted_when_nothing_else_changes(tmp_path):
    root = _three_kept(tmp_path)
    before = _settings_text(root)
    result = _run(root, _term(tmp_path))  # no terminal, no --yes: it must not ask
    assert result.exit_code == 0, result.output
    assert (
        "3 resources were not rescheduled because of dont_reschedule_dates_before "
        "date of Thu Oct 1, 2026 11:59 PM PDT"
    ) in result.output
    assert "Nothing to change" in result.output
    assert "\tWeek 1 Problem Set:" not in result.output  # no list without --verbose
    assert _settings_text(root) == before


def test_verbose_lists_kept_resources_and_their_fields(tmp_path):
    root = _three_kept(tmp_path)
    result = _run(root, _term(tmp_path), "--verbose")
    assert (
        "3 resources were not rescheduled because of dont_reschedule_dates_before "
        "date of Thu Oct 1, 2026 11:59 PM PDT\n"
        "\tWeek 1 Problem Set: unlock_at, due_at, lock_at\n"
        "\tWeek 1 Discussion (discussion): unlock_at, due_at, lock_at\n"
        "\tEarly Lab: due_at\n"
    ) in result.output
    assert "\tEarly Lab: due_at" in _run(root, _term(tmp_path), "-v").output


def test_noop_shows_kept_resources_and_writes_nothing(tmp_path):
    rows = [
        _row(PS, _at("09-24"), _at("09-30"), _at("10-01")),
        _row(DISC, _at("09-24"), _at("09-30"), _at("10-01"), kind="discussion"),
    ]
    root = _repo(tmp_path, _cutoff_settings("2026-10-01", rows, EARLY))
    before = _settings_text(root)
    result = _run(root, _term(tmp_path), "--noop")
    assert result.exit_code == 0, result.output
    assert "Not rescheduling dates on or before: Thu Oct 1, 2026" in result.output
    assert "2 resources were not rescheduled" in result.output
    assert "Early Lab (new entry):" in result.output
    assert _settings_text(root) == before


def test_error_is_shown_before_the_prompt_and_exit_is_non_zero(tmp_path, mocker):
    mocker.patch("markdown_to_canvas.cli._stdin_is_terminal", return_value=True)
    root, _ = _inconsistent_plan(tmp_path)
    before = _settings_text(root)
    result = _run(root, _term(tmp_path), input="n\n")
    assert result.exit_code == 1
    error_at = result.output.index("ERROR: Early Lab")
    assert error_at < result.output.index("Write these dates into due_dates?")
    assert "left unchanged because of the error above" in result.output
    assert _settings_text(root) == before


def test_yes_writes_the_others_and_exits_non_zero(tmp_path):
    root, _ = _inconsistent_plan(tmp_path)
    result = _run(root, _term(tmp_path), "--yes")
    assert result.exit_code == 1
    entries = _entries(root)
    assert entries[PS]["due_at"] == _at("10-05")
    assert entries["Early Lab"]["due_at"] == _at("10-06")


def test_noop_with_an_error_exits_non_zero(tmp_path):
    root, _ = _inconsistent_plan(tmp_path)
    result = _run(root, _term(tmp_path), "--noop")
    assert result.exit_code == 1 and "ERROR: Early Lab" in result.output


def test_only_inconsistent_entries(tmp_path):
    rows = [
        _row(PS, "KEEP", _at("10-05"), _at("10-12")),
        _row(DISC, "NONE", _at("10-07"), _at("10-14"), kind="discussion"),
        _row("Early Lab", _at("10-01"), _at("10-06"), _at("10-13")),
    ]
    root = _repo(tmp_path, _cutoff_settings("2026-10-01", rows, EARLY))
    before = _settings_text(root)
    result = _run(root, _term(tmp_path))
    assert result.exit_code == 1
    assert "ERROR: Early Lab" in result.output and "Nothing to change" in result.output
    assert "Write these dates" not in result.output
    assert _settings_text(root) == before


def test_update_ignores_the_cutoff(tmp_path, mocker):
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
    assert course.create_assignment.call_args.kwargs["assignment"]["due_at"] == _at("10-05")

    # Setting the cutoff changes nothing update sends: no course settings, no dates.
    path = root / "course_settings" / "course_settings.toml"
    path.write_text(path.read_text().replace(
        "[relative_due_dates]\n", '[relative_due_dates]\ndont_reschedule_dates_before = "2026-10-01"\n'
    ))
    course.reset_mock()
    run_sync(cfg, root)
    course.create_assignment.assert_not_called()
    course.get_assignment.assert_not_called()
    course.update.assert_not_called()


# --- date placeholders ------------------------------------------------------


def _with_page(root: Path, body: str) -> None:
    _write(root / "pages" / "schedule.md", f"---\ntitle: Schedule\n---\n\n{body}\n")
    make_current(root)


def test_placeholder_naming_a_missing_entry_is_reported(tmp_path):
    root = _repo(tmp_path)
    _with_page(root, '[x]{.replace_date_with item="HW 9"}')
    plan = gd.plan_generation(root, _term(tmp_path))
    assert plan.errors == []
    assert len(plan.placeholder_errors) == 1
    assert "pages/schedule.md" in plan.placeholder_errors[0]
    assert "'HW 9'" in plan.placeholder_errors[0]


def test_placeholder_in_a_module_file_is_checked(tmp_path):
    root = _repo(tmp_path)
    _write(
        root / "modules" / "week-1.md",
        '---\ntitle: Week 1\n---\n## Week 1: [x]{.replace_date_with item="HW 9"}\n',
    )
    make_current(root)
    (err,) = gd.plan_generation(root, _term(tmp_path)).placeholder_errors
    assert "modules/week-1.md" in err and "'HW 9'" in err


def test_placeholder_naming_an_entry_the_plan_adds_is_fine(tmp_path):
    root = _repo(tmp_path)
    # Week 1 Discussion has no due_dates entry yet; the plan adds it.
    _with_page(root, '[x]{.replace_date_with item="Week 1 Discussion"}')
    assert gd.plan_generation(root, _term(tmp_path)).placeholder_errors == []


def test_own_entry_and_only_if_entries_count(tmp_path):
    root = _repo(tmp_path)
    # The entry has only_if = "in_person"; generate-due-dates ignores only_if.
    _write(
        root / "assignments" / "w1.md",
        "---\ntitle: Week 1 Problem Set\n---\n\nDue [x]{.replace_date_with}\n",
    )
    make_current(root)
    assert gd.plan_generation(root, _term(tmp_path)).placeholder_errors == []


def test_placeholder_quoting_an_entry_with_no_due_date(tmp_path):
    root = _repo(tmp_path)
    _with_page(root, '[x]{.replace_date_with item="Old Item"}')
    (err,) = gd.plan_generation(root, _term(tmp_path)).placeholder_errors
    assert "no date for due_at (NONE)" in err


def test_placeholders_in_code_and_snippets(tmp_path):
    root = _repo(tmp_path)
    _write(root / "snippets" / "due.md", '[x]{.replace_date_with item="Nope"}\n')
    _with_page(root, "`[x]{.replace_date_with}`\n\n[Due](../snippets/due.md)")
    (err,) = gd.plan_generation(root, _term(tmp_path)).placeholder_errors
    assert "'Nope'" in err


def test_cli_writes_dates_and_exits_non_zero_on_placeholder_errors(tmp_path):
    root = _repo(tmp_path)
    _with_page(root, '[x]{.replace_date_with item="HW 9"}')
    result = _run(root, _term(tmp_path), "--yes")
    assert result.exit_code != 0
    assert "'HW 9'" in result.output
    assert "1 date placeholder does not resolve" in result.output
    assert "Week 1 Discussion" in _settings_text(root)  # dates were still written


def test_cli_noop_reports_placeholder_errors(tmp_path):
    root = _repo(tmp_path)
    _with_page(root, '[x]{.replace_date_with item="HW 9"}')
    before = _settings_text(root)
    result = _run(root, _term(tmp_path), "--noop")
    assert result.exit_code != 0
    assert "'HW 9'" in result.output
    assert _settings_text(root) == before


# --- virtual items ------------------------------------------------------------

VIRTUAL_ITEMS = (
    '    { name = "Start_of_week_3", virtual = true, relative_to = { type = "START_OF_QUARTER" }, offsets = ["+14 CALENDAR_DAY"] },\n'
    '    { name = "Start_of_week_2", virtual = true, relative_to = { type = "START_OF_QUARTER" }, offsets = ["+7 CALENDAR_DAY"] },\n'
    '    { name = "Lab 3", relative_to = { type = "ASSIGNMENT", assignment_name = "Start_of_week_3" }, offsets = ["-1 CALENDAR_DAY", "+2 CLASS_DAY"] },\n'
    '    { name = "Midterm Quiz", type = "quiz"'
)


def _virtual_repo(tmp_path: Path, settings: str = SETTINGS) -> Path:
    root = _repo(tmp_path, settings.replace('    { name = "Midterm Quiz", type = "quiz"', VIRTUAL_ITEMS))
    _write(root / "assignments" / "lab3.md", "---\ntitle: Lab 3\n---\n\nHi\n")
    return root


def test_virtual_name_that_is_a_content_title_is_an_error(tmp_path):
    root = _virtual_repo(tmp_path)
    _write(root / "quizzes" / "w3" / "w3.md", "---\ntitle: Start_of_week_3\n---\n")
    before = _settings_text(root)
    result = _run(root, _term(tmp_path), "--yes")
    assert result.exit_code != 0
    assert "virtual item 'Start_of_week_3' is the title of quizzes/w3/w3.md" in result.output
    assert "Traceback" not in result.output
    assert _settings_text(root) == before


def test_virtual_name_collision_counts_ignored_titles(tmp_path):
    root = _virtual_repo(tmp_path)
    _write(root / "assignments" / "w2.md", "---\ntitle: Start_of_week_2\n---\n\nHi\n")
    _write(
        root / "course_settings" / "course_settings.toml",
        _settings_text(root).replace(
            "items = [\n    { name = \"Week 1 Problem Set\"",
            'ignore = ["Start_of_week_2"]\nitems = [\n    { name = "Week 1 Problem Set"',
        ),
    )
    with pytest.raises(rd.RelativeDueDatesError, match="'Start_of_week_2' is the title of assignments/w2.md"):
        gd.plan_generation(root, _term(tmp_path))


W3 = "2026-10-14T23:59:00-07:00"  # Start_of_week_3
W2 = "2026-10-07T23:59:00-07:00"  # Start_of_week_2


def _add_entries(root: Path, *rows: str) -> None:
    _write(
        root / "course_settings" / "course_settings.toml",
        _settings_text(root).replace(
            '    { name = "Old Item"', "".join(f"    {r},\n" for r in rows) + '    { name = "Old Item"'
        ),
    )


def test_virtual_items_are_written_as_virtual_entries(tmp_path):
    root = _virtual_repo(tmp_path)
    result = _run(root, _term(tmp_path), "--yes")
    assert result.exit_code == 0, result.output
    entries = _entries(root)
    assert entries["Lab 3"]["due_at"] == "2026-10-19T23:59:00-07:00"
    assert entries["Start_of_week_3"] == {"name": "Start_of_week_3", "virtual": True, "due_at": W3}
    assert entries["Start_of_week_2"] == {"name": "Start_of_week_2", "virtual": True, "due_at": W2}
    assert 'name = "Start_of_week_3", virtual = true, due_at = "2026-10-14T23:59:00-07:00"' in (
        _settings_text(root)
    )


def test_virtual_entries_are_listed_with_the_changes(tmp_path):
    root = _virtual_repo(tmp_path)
    result = _run(root, _term(tmp_path), "--noop")
    assert result.exit_code == 0, result.output
    assert f"Start_of_week_3 (virtual) (new entry):\n\tdue_at: {W3}\n" in result.output
    assert "Virtual dates" not in result.output


def test_block_style_due_dates_get_a_virtual_table(tmp_path):
    settings = (
        'title = "Course"\n\n'
        '[[due_dates]]\nname = "Week 1 Problem Set"\ndue_at = "NONE"\n\n'
        + "[relative_due_dates" + SETTINGS.split("[relative_due_dates", 1)[1]
    )
    root = _virtual_repo(tmp_path, settings)
    assert _run(root, _term(tmp_path), "--yes").exit_code == 0
    assert '[[due_dates]]\nname = "Start_of_week_3"\nvirtual = true\ndue_at = ' in _settings_text(root)


def test_virtual_entry_is_updated_and_keeps_only_if(tmp_path):
    root = _virtual_repo(tmp_path)
    _add_entries(root, '{ name = "Start_of_week_3", virtual = true, due_at = "2026-01-01T00:00:00-08:00", only_if = "in_person" }')
    plan = gd.plan_generation(root, _term(tmp_path))
    change = next(c for c in plan.changes if c.name == "Start_of_week_3")
    assert (change.kind, change.virtual) == ("changed", True)
    assert change.fields == {"due_at": ("2026-01-01T00:00:00-08:00", W3)}
    assert _run(root, _term(tmp_path), "--yes").exit_code == 0
    assert _entries(root)["Start_of_week_3"] == {
        "name": "Start_of_week_3", "virtual": True, "due_at": W3, "only_if": "in_person"
    }


def test_virtual_entries_produced_by_the_table_are_not_leftovers(tmp_path):
    root = _virtual_repo(tmp_path)
    assert _run(root, _term(tmp_path), "--yes").exit_code == 0
    plan = gd.plan_generation(root, _term(tmp_path))
    assert not any("Start_of_week" in w for w in plan.warnings)
    assert not any("Start_of_week" in n for n in plan.notices)


def test_only_a_virtual_entry_changed_asks_to_confirm(tmp_path):
    root = _virtual_repo(tmp_path)
    assert _run(root, _term(tmp_path), "--yes").exit_code == 0
    path = root / "course_settings" / "course_settings.toml"
    path.write_text(_settings_text(root).replace(
        f'"Start_of_week_3", virtual = true, due_at = "{W3}"',
        '"Start_of_week_3", virtual = true, due_at = "2026-10-15T23:59:00-07:00"',
    ))
    plan = gd.plan_generation(root, _term(tmp_path))
    assert plan.has_changes
    assert [c.name for c in plan.changes if c.kind == "changed"] == ["Start_of_week_3"]


def test_nothing_changed_with_virtual_entries(tmp_path):
    root = _virtual_repo(tmp_path)
    assert _run(root, _term(tmp_path), "--yes").exit_code == 0
    before = _settings_text(root)
    result = _run(root, _term(tmp_path), "-v")  # no --yes and no terminal: would fail if it asked
    assert result.exit_code == 0, result.output
    assert "Nothing to change" in result.output
    assert "Virtual dates" not in result.output
    assert _settings_text(root) == before


def test_virtual_entry_no_longer_in_the_table_is_a_leftover(tmp_path):
    root = _virtual_repo(tmp_path)
    _add_entries(root, f'{{ name = "Start_of_week_12", virtual = true, due_at = "{W3}" }}')
    plan = gd.plan_generation(root, _term(tmp_path))
    assert any("'Start_of_week_12'" in n and "left unchanged" in n for n in plan.notices)
    assert _run(root, _term(tmp_path), "--yes").exit_code == 0
    assert _entries(root)["Start_of_week_12"]["due_at"] == W3


def test_entry_left_from_before_the_item_was_virtual_is_an_error(tmp_path):
    root = _virtual_repo(tmp_path)
    _add_entries(root, f'{{ name = "Start_of_week_3", due_at = "{W3}", unlock_at = "KEEP", lock_at = "KEEP" }}')
    before = _settings_text(root)
    result = _run(root, _term(tmp_path), "--yes")
    assert result.exit_code != 0
    assert "'Start_of_week_3' is a virtual item but due_dates has an ordinary entry" in result.output
    assert _settings_text(root) == before


def test_ordinary_item_with_a_virtual_entry_name_is_an_error(tmp_path):
    root = _virtual_repo(tmp_path)
    _add_entries(root, f'{{ name = "Lab 3", virtual = true, due_at = "{W3}" }}')
    root.joinpath("assignments", "lab3.md").unlink()  # else the content-title check fires first
    with pytest.raises(rd.RelativeDueDatesError, match="'Lab 3' is an ordinary item but due_dates has a virtual entry"):
        gd.plan_generation(root, _term(tmp_path))


def test_invalid_hand_written_virtual_entry_stops_the_command(tmp_path):
    root = _virtual_repo(tmp_path)
    _add_entries(root, f'{{ name = "Last day to withdraw", virtual = true, due_at = "{W3}", lock_at = "KEEP" }}')
    before = _settings_text(root)
    result = _run(root, _term(tmp_path), "--yes")
    assert result.exit_code != 0
    assert "'Last day to withdraw': a virtual entry may not have 'lock_at'" in result.output
    assert "Traceback" not in result.output
    assert _settings_text(root) == before


def test_cutoff_keeps_a_past_virtual_date(tmp_path):
    root = _virtual_repo(tmp_path)
    _add_entries(root, '{ name = "Start_of_week_2", virtual = true, due_at = "2026-10-06T23:59:00-07:00" }')
    path = root / "course_settings" / "course_settings.toml"
    path.write_text(_settings_text(root).replace(
        "[relative_due_dates]\n", '[relative_due_dates]\ndont_reschedule_dates_before = "2026-10-06"\n', 1
    ))
    plan = gd.plan_generation(root, _term(tmp_path))
    change = next(c for c in plan.changes if c.name == "Start_of_week_2")
    assert change.kind == "unchanged"
    assert change.kept == {"due_at": ("2026-10-06T23:59:00-07:00", W2)}
    assert change in plan.not_rescheduled


def test_placeholder_naming_a_virtual_item_resolves(tmp_path):
    root = _virtual_repo(tmp_path)
    _with_page(root, '[x]{.replace_date_with item="Start_of_week_3"}')
    plan = gd.plan_generation(root, _term(tmp_path))
    assert plan.placeholder_errors == []


# --- clamp_lock_at_to_last_day_of_term ------------------------------------------

END = "2026-12-18T23:59:00-08:00"
_LATE = '    { name = "Final Project", relative_to = { type = "START_OF_QUARTER" }, offsets = ["+76 CALENDAR_DAY"] },\n'
_LATE2 = '    { name = "Final Essay", relative_to = { type = "START_OF_QUARTER" }, offsets = ["+77 CALENDAR_DAY"] },\n'
_OPEN = '    { name = "Week 10 Discussion", type = "discussion", relative_to = { type = "START_OF_QUARTER" }, offsets = ["+70 CALENDAR_DAY"], lock_offset = "NONE" },\n'


def _clamp_plan(tmp_path, extra_items, rows=(), cutoff=None, clamp=True):
    text = _cutoff_settings(cutoff, list(rows), extra_items)
    if clamp:
        text = text.replace(
            '[relative_due_dates]\n', '[relative_due_dates]\nclamp_lock_at_to_last_day_of_term = true\n', 1
        )
    root = _repo(tmp_path, text)
    return root, gd.plan_generation(root, _term(tmp_path))


def _clamp_line(plan, verbose=False):
    lines = [line for line, _ in gd.render_plan(plan, verbose=verbose)]
    matching = [i for i, line in enumerate(lines) if "set to the term's last day" in line]
    return lines, matching


def test_clamp_line_counts_both_causes(tmp_path):
    _, plan = _clamp_plan(tmp_path, _LATE + _LATE2 + _OPEN)
    assert _change(plan, "Final Project").values["lock_at"] == END
    assert _change(plan, "Week 10 Discussion").values["lock_at"] == END
    lines, idx = _clamp_line(plan)
    assert [lines[i] for i in idx] == [
        "3 lock dates set to the term's last day (Fri Dec 18, 2026 11:59 PM PST): "
        "2 were later, 1 was NONE"
    ]


def test_clamp_line_with_one_cause_leaves_out_the_other(tmp_path):
    _, plan = _clamp_plan(tmp_path, _LATE)
    lines, idx = _clamp_line(plan)
    assert len(idx) == 1
    assert lines[idx[0]].endswith("): 1 was later")
    assert lines[idx[0]].startswith("1 lock date set to")


def test_clamp_verbose_lists_each_resource(tmp_path):
    _, plan = _clamp_plan(tmp_path, _LATE + _OPEN)
    lines, idx = _clamp_line(plan, verbose=True)
    assert lines[idx[0] + 1 : idx[0] + 3] == [
        "\tFinal Project: later",
        "\tWeek 10 Discussion (discussion): was NONE",
    ]
    lines, idx = _clamp_line(plan)
    assert not any(line.startswith("\t") for line in lines[idx[0] + 1 :])


def test_clamp_line_on_an_unchanged_second_run(tmp_path):
    root, plan = _clamp_plan(tmp_path, _LATE + _OPEN)
    gd.apply_plan(plan)
    plan = gd.plan_generation(root, _term(tmp_path))
    assert not plan.has_changes
    _, idx = _clamp_line(plan)
    assert len(idx) == 1

    result = _run(root, _term(tmp_path), "--noop")
    assert result.exit_code == 0, result.output
    assert "2 lock dates set to the term's last day" in result.output
    assert "Nothing to change" in result.output


def test_clamp_not_counted_when_kept_by_the_cutoff(tmp_path):
    rows = [_row("Week 10 Discussion", "KEEP", _at("12-09"), _at("10-01"), "discussion")]
    _, plan = _clamp_plan(tmp_path, _OPEN, rows=rows, cutoff="2026-10-01")
    change = _change(plan, "Week 10 Discussion")
    assert "lock_at" in change.kept
    assert plan.clamped == []
    _, idx = _clamp_line(plan)
    assert idx == []


def test_no_clamp_line_when_the_setting_is_off(tmp_path):
    _, plan = _clamp_plan(tmp_path, _LATE + _OPEN, clamp=False)
    assert _change(plan, "Final Project").values["lock_at"] == "2026-12-22T23:59:00-08:00"
    assert _change(plan, "Week 10 Discussion").values["lock_at"] == "NONE"
    _, idx = _clamp_line(plan)
    assert idx == []
