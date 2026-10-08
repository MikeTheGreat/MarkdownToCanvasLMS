"""Virtual due_dates entries (`virtual = true`): validation, and how update,
list-titles and publish treat them (mocked Canvas)."""
from __future__ import annotations

import os
from pathlib import Path

import pytest

from markdown_to_canvas import publish
from markdown_to_canvas.sync import (
    check_virtual_due_dates,
    collect_title_items,
    find_due_date_override,
    run_sync,
    run_targeted_sync,
)
from tests.conftest import make_current
from tests.test_date_placeholders_sync import (  # noqa: F401  (course is a fixture)
    _bodies,
    _config,
    _manifest,
    _write,
    course,
)

WEEK3 = "2026-10-12T23:59:00-07:00"
VIRTUAL = f'{{name = "Start_of_week_3", virtual = true, due_at = "{WEEK3}"}}'


def _settings(*entries: str) -> str:
    return "due_dates = [\n" + "".join(f"    {e},\n" for e in entries) + "]\n"


def _repo(tmp_path: Path, *entries: str) -> Path:
    root = tmp_path / "course"
    _write(root / "course_settings" / "course_settings.toml", _settings(*entries))
    _write(
        root / "assignments" / "hw1.md",
        "---\ntitle: HW 1\npublished: true\n---\n\nDo it.\n",
    )
    _write(
        root / "pages" / "schedule.md",
        "---\ntitle: Schedule\npublished: true\n---\n\n"
        'Week 3 begins [x]{.replace_date_with item="Start_of_week_3" format="%A, %B %-d"}.\n',
    )
    make_current(root)
    return root


def _check(tmp_path: Path, *entries: dict) -> None:
    root = tmp_path / "repo"
    _write(root / "assignments" / "hw1.md", "---\ntitle: HW 1\n---\n\nx\n")
    check_virtual_due_dates(list(entries), root)


def _virtual(**extra) -> dict:
    return {"name": "Start_of_week_3", "virtual": True, "due_at": WEEK3, **extra}


# ---------------------------------------------------------------------------
# Validation
# ---------------------------------------------------------------------------


def test_valid_virtual_entry_passes(tmp_path) -> None:
    _check(tmp_path, _virtual(), _virtual(name="Last day to withdraw", only_if="online"))


def test_virtual_false_is_an_ordinary_entry(tmp_path) -> None:
    _check(tmp_path, {"name": "HW 1", "virtual": False, "due_at": WEEK3, "lock_at": "KEEP"})


@pytest.mark.parametrize("key", ["type", "unlock_at", "lock_at"])
def test_forbidden_keys(tmp_path, key) -> None:
    with pytest.raises(ValueError, match=f"'Start_of_week_3': a virtual entry may not have '{key}'"):
        _check(tmp_path, _virtual(**{key: "assignment" if key == "type" else WEEK3}))


@pytest.mark.parametrize("value", [None, "NONE", "keep", "", "next week"])
def test_due_at_must_be_a_date(tmp_path, value) -> None:
    entry = _virtual(due_at=value)
    if value is None:
        del entry["due_at"]
    with pytest.raises(ValueError, match="needs 'due_at' set to a date"):
        _check(tmp_path, entry)


def test_non_boolean_virtual(tmp_path) -> None:
    with pytest.raises(ValueError, match="'virtual' must be true or false, got 'yes'"):
        _check(tmp_path, _virtual(virtual="yes"))


def test_name_of_a_content_file(tmp_path) -> None:
    with pytest.raises(ValueError, match="title of assignments/hw1.md"):
        _check(tmp_path, _virtual(name="HW 1"))


def test_ignored_content_is_not_a_collision(tmp_path) -> None:
    from markdown_to_canvas.ignore import load_ignore_matcher

    root = tmp_path / "repo"
    _write(root / "assignments" / "hw1.md", "---\ntitle: HW 1\n---\n\nx\n")
    _write(root / ".canvasignore", "assignments/hw1.md\n")
    check_virtual_due_dates([_virtual(name="HW 1")], root, load_ignore_matcher(root))


def test_name_shared_with_an_ordinary_entry(tmp_path) -> None:
    with pytest.raises(ValueError, match="may not have the name of an ordinary due_dates entry"):
        _check(tmp_path, _virtual(), {"name": "Start_of_week_3", "due_at": WEEK3})


def test_two_virtual_entries_may_share_a_name(tmp_path) -> None:
    _check(tmp_path, _virtual(only_if="online"), _virtual(only_if="not online"))


def test_entry_excluded_by_only_if_is_still_checked(tmp_path) -> None:
    with pytest.raises(ValueError, match="'lock_at'"):
        _check(tmp_path, _virtual(only_if="online", lock_at=WEEK3))


def test_every_error_is_reported(tmp_path) -> None:
    with pytest.raises(ValueError) as exc:
        _check(tmp_path, _virtual(lock_at=WEEK3), _virtual(name="Other", due_at="NONE"))
    assert "'lock_at'" in str(exc.value) and "'Other'" in str(exc.value)


# ---------------------------------------------------------------------------
# Commands stop before doing anything
# ---------------------------------------------------------------------------


def test_update_stops_before_any_canvas_request(tmp_path, mocker) -> None:
    canvas = mocker.patch("markdown_to_canvas.canvas_api.Canvas")
    root = _repo(tmp_path, VIRTUAL.replace("}", ', lock_at = "KEEP"}'))
    with pytest.raises(ValueError, match="'lock_at'"):
        run_sync(_config(), root)
    canvas.assert_not_called()


def test_noop_and_targeted_update_stop_too(tmp_path, mocker) -> None:
    canvas = mocker.patch("markdown_to_canvas.canvas_api.Canvas")
    root = _repo(tmp_path, VIRTUAL.replace("}", ', type = "quiz"}'))
    with pytest.raises(ValueError, match="'type'"):
        run_sync(_config(), root, mode="noop")
    with pytest.raises(ValueError, match="'type'"):
        run_targeted_sync(_config(), root, [], ["pages/schedule.md"])
    canvas.assert_not_called()


def test_update_cli_stops_before_get_course(tmp_path, mocker) -> None:
    from click.testing import CliRunner

    from markdown_to_canvas import cli

    root = _repo(tmp_path, VIRTUAL.replace("Start_of_week_3", "HW 1"))
    _write(
        root / "course_settings" / "canvas.toml",
        'base_url = "https://school.instructure.com"\ncourse_id = 1\napi_token = "tok"\n',
    )
    get_course = mocker.patch.object(cli, "get_course")
    result = CliRunner().invoke(cli.main, ["update", str(root)])
    assert result.exit_code != 0
    assert "title of assignments/hw1.md" in result.output
    get_course.assert_not_called()


def test_list_titles_stops(tmp_path) -> None:
    root = _repo(tmp_path, VIRTUAL.replace(WEEK3, "NONE"))
    with pytest.raises(ValueError, match="needs 'due_at' set to a date"):
        collect_title_items(root)


def test_publish_stops_before_staging(tmp_path, monkeypatch) -> None:
    root = _repo(tmp_path, VIRTUAL.replace("Start_of_week_3", "HW 1"))
    staged = []
    monkeypatch.setattr(publish, "stage", lambda *a, **kw: staged.append(a))
    with pytest.raises(ValueError, match="title of assignments/hw1.md"):
        publish.run_publish(root, tmp_path / "site")
    assert staged == []
    assert not (tmp_path / "site").exists()


# ---------------------------------------------------------------------------
# Never sent to Canvas
# ---------------------------------------------------------------------------


def test_find_due_date_override_skips_virtual_entries() -> None:
    entries = [{"name": "HW 1", "virtual": True, "due_at": WEEK3}]
    assert find_due_date_override(entries, "HW 1", "assignment") is None


def test_list_titles_takes_no_date_from_a_virtual_entry(tmp_path) -> None:
    root = _repo(tmp_path, VIRTUAL)
    assert collect_title_items(root) == [(None, "HW 1", "assignments/hw1.md")]


def test_no_coverage_warning_and_page_quotes_the_date(tmp_path, course, capsys) -> None:
    root = _repo(tmp_path, VIRTUAL)
    assert run_sync(_config(), root) is False
    out = capsys.readouterr().out
    assert "Start_of_week_3" not in out
    assert "Week 3 begins Monday, October 12." in _bodies(course)["page"]


def _age(root: Path) -> None:
    for path in root.rglob("*"):
        if path.is_file():
            os.utime(path, (0.0, 0.0))


def _synced_and_aged(tmp_path: Path, course) -> Path:
    root = _repo(tmp_path, VIRTUAL)
    assert run_sync(_config(), root) is False
    _age(root)
    course.reset_mock()
    return root


def test_unchanged_virtual_date_reuploads_nothing(tmp_path, course) -> None:
    root = _synced_and_aged(tmp_path, course)
    assert run_sync(_config(), root) is False
    course.get_page.assert_not_called()
    course.get_assignment.assert_not_called()


def test_changed_virtual_date_reuploads_only_the_quoting_file(tmp_path, course) -> None:
    root = _synced_and_aged(tmp_path, course)
    settings = root / "course_settings" / "course_settings.toml"
    settings.write_text(settings.read_text().replace(WEEK3, "2026-10-19T23:59:00-07:00"))
    _age(root)  # only the recorded text differs now
    assert run_sync(_config(), root) is False
    course.get_page.assert_called()
    course.get_assignment.assert_not_called()
    assert _manifest(root)["pages/schedule.md"]["dates_used"][0]["text"] == "Monday, October 19"
