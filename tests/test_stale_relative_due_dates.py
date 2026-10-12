"""The warning `update` and `publish` print when [relative_due_dates] has no
last_generated_hash, or one that no longer matches the section (mocked Canvas)."""
from __future__ import annotations

import dataclasses

from pathlib import Path

import pytest
from click.testing import CliRunner

from markdown_to_canvas import cli
from markdown_to_canvas import relative_dates as rd
from markdown_to_canvas.sync import run_sync, run_targeted_sync
from tests.conftest import make_current
from tests.test_date_placeholders_sync import (  # noqa: F401  (course is a fixture)
    _config,
    _write,
    course,
)

SECTION = """\
due_dates = [
    {name = "HW 1", due_at = "2026-10-05T23:59:00-07:00", unlock_at = "KEEP", lock_at = "KEEP"},
]

[relative_due_dates]
{hash_line}days_of_week = ["Mon"]

[relative_due_dates.tables.default]
items = [{items}]
"""
ITEM = '{name = "HW 1", relative_to = {type = "START_OF_QUARTER"}, offsets = ["+1 CLASS_DAY"]}'


def _fill(hash_line: str, items: str) -> str:
    return SECTION.replace("{hash_line}", hash_line).replace("{items}", items)


def _settings(state: str) -> str:
    """course_settings.toml with a fingerprint that is "missing", "stale", "current",
    or a section with no items ("empty")."""
    items = "" if state == "empty" else ITEM
    text = _fill("", items)
    if state in ("stale", "current"):
        import tomllib

        value = rd.fingerprint(tomllib.loads(text)["relative_due_dates"])
        if state == "stale":
            value = "0" * 16
        text = _fill(f'last_generated_hash = "{value}"\n', items)
    return text


def _repo(tmp_path: Path, state: str) -> Path:
    root = tmp_path / "course"
    _write(root / "course_settings" / "course_settings.toml", _settings(state))
    _write(root / "assignments" / "hw1.md", "---\ntitle: HW 1\npublished: true\n---\n\nDo it.\n")
    make_current(root)
    return root


def _flags_config():
    """_config() with a [course_flags] override, so the run prints a "Flags:" line."""
    return dataclasses.replace(_config(), course_flags={"night_section": True})


EXPECTED = {
    "missing": rd.NO_HASH_WARNING,
    "stale": rd.STALE_WARNING,
    "current": None,
    "empty": None,
}


@pytest.mark.parametrize("state", list(EXPECTED))
@pytest.mark.parametrize("mode", ["real", "noop", "new_course"])
def test_full_run_prints_the_warning_after_the_flags_line(
    tmp_path, course, capsys, state, mode
) -> None:
    root = _repo(tmp_path, state)
    run_sync(_flags_config(), root, mode=mode)
    out = capsys.readouterr().out
    expected = EXPECTED[state]
    if expected is None:
        assert "[relative_due_dates]" not in out
    else:
        assert out.count(expected) == 1
        assert out.index("Flags:") < out.index(expected)
        assert out.index(expected) < out.index("Checking due_dates coverage...")


def test_targeted_run_prints_the_warning_after_the_flags_line(
    tmp_path, course, capsys
) -> None:
    root = _repo(tmp_path, "stale")
    run_targeted_sync(_flags_config(), root, [], ["assignments/hw1.md"])
    out = capsys.readouterr().out
    assert out.count(rd.STALE_WARNING) == 1
    assert out.index("Flags:") < out.index(rd.STALE_WARNING)
    assert out.index(rd.STALE_WARNING) < out.index("Checking due_dates coverage...")


# --- the second warning, after update's final status line -----------------------


def _cli_repo(tmp_path: Path, state: str) -> Path:
    root = _repo(tmp_path, state)
    _write(
        root / "course_settings" / "canvas.toml",
        'base_url = "https://school.instructure.com"\ncourse_id = 1\napi_token = "tok"\n',
    )
    return root


@pytest.fixture
def quiet_update(mocker):
    """update's CLI with the run itself mocked: returns the run_sync mock."""
    mocker.patch.object(cli, "get_course")
    mocker.patch.object(cli, "_guard_course")
    mocker.patch.object(cli, "_move_check_commands")
    mocker.patch.object(cli, "run_targeted_sync", return_value=False)
    return mocker.patch.object(cli, "run_sync", return_value=False)


@pytest.mark.parametrize("args, had_errors, status, code", [
    ([], False, "Update successful", 0),
    ([], True, "Update complete; please check errors listed above.", 0),
    (["--noop"], False, "Noop complete; no problems found.", 0),
    (["--noop"], True, "Noop complete; please check the problems listed above.", 1),
    (["--check-as-new-course"], False, "Check successful", 0),
    (["--check-as-new-course"], True, "Check complete; please fix the problems", 1),
    (["-s", "assignments/hw1.md"], False, "Update successful", 0),
])
def test_update_prints_the_warning_after_the_status_line(
    tmp_path, quiet_update, mocker, args, had_errors, status, code
) -> None:
    root = _cli_repo(tmp_path, "stale")
    quiet_update.return_value = had_errors
    cli.run_targeted_sync.return_value = had_errors
    result = CliRunner().invoke(cli.main, ["update", str(root), *args])
    assert result.exit_code == code, result.output
    assert status in result.output
    assert result.output.index(status) < result.output.index(rd.STALE_WARNING)


def test_update_prints_nothing_when_the_fingerprint_is_current(tmp_path, quiet_update) -> None:
    root = _cli_repo(tmp_path, "current")
    result = CliRunner().invoke(cli.main, ["update", str(root)])
    assert result.exit_code == 0, result.output
    assert "[relative_due_dates]" not in result.output


def test_missing_settings_file_gives_no_warning(tmp_path) -> None:
    from markdown_to_canvas.sync import relative_due_dates_warning

    assert relative_due_dates_warning(tmp_path) is None
    _write(tmp_path / "course_settings" / "course_settings.toml", "not = [valid")
    assert relative_due_dates_warning(tmp_path) is None
