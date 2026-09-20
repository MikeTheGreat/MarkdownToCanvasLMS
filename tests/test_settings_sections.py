"""Tests for course_settings.toml section-level change detection.

Editing one section (or [course_flags], or due_dates) must re-run only the
affected actions — not re-send course metadata, re-upload the dashboard image,
or fire the dates-only pass over every dated item.
"""
from __future__ import annotations

import os
import time
import tomllib
from pathlib import Path
from unittest.mock import MagicMock

import tomli_w

from markdown_to_canvas.config import Config
from markdown_to_canvas.mv import run_mv
from markdown_to_canvas.sync import compute_settings_section_hashes, run_sync
from tests.conftest import make_current


# ---------------------------------------------------------------------------
# Unit tests: compute_settings_section_hashes
# ---------------------------------------------------------------------------


class TestComputeSettingsSectionHashes:
    def test_stable_under_key_order(self) -> None:
        a = compute_settings_section_hashes({"title": "X", "course_code": "C1"})
        b = compute_settings_section_hashes({"course_code": "C1", "title": "X"})
        assert a == b

    def test_course_flags_and_due_dates_affect_no_section(self) -> None:
        base = {"title": "X", "late_policy": {"late_submission_deduction": 10}}
        varied = dict(
            base,
            course_flags={"online": True},
            due_dates=[{"name": "HW1", "due_at": "2099-01-01T00:00:00"}],
        )
        assert compute_settings_section_hashes(base) == compute_settings_section_hashes(varied)

    def test_relative_due_dates_affect_no_section(self) -> None:
        base = {"title": "X", "late_policy": {"late_submission_deduction": 10}}
        varied = dict(
            base,
            relative_due_dates={
                "days_of_week": ["Mon", "Wed"],
                "tables": {"default": {"items": [{"name": "HW1", "offsets": ["+1 CLASS_DAY"]}]}},
            },
        )
        assert compute_settings_section_hashes(base) == compute_settings_section_hashes(varied)

    def test_unknown_top_level_key_counts_as_metadata(self) -> None:
        a = compute_settings_section_hashes({"title": "X"})
        b = compute_settings_section_hashes({"title": "X", "mystery_key": 42})
        assert a["metadata"] != b["metadata"]
        assert {k: v for k, v in a.items() if k != "metadata"} == {
            k: v for k, v in b.items() if k != "metadata"
        }

    def test_version_keys_are_not_metadata(self) -> None:
        base = {"title": "X"}
        varied = dict(
            base,
            format_version=1,
            created_by="0.2.0",
            upgraded_by=["0.2.1 on 2026-09-20: 0 -> 1"],
        )
        assert compute_settings_section_hashes(base) == compute_settings_section_hashes(varied)

    def test_section_change_touches_only_that_section(self) -> None:
        a = compute_settings_section_hashes({"title": "X", "late_policy": {"x": 1}})
        b = compute_settings_section_hashes({"title": "X", "late_policy": {"x": 2}})
        assert a["late_policy"] != b["late_policy"]
        assert {k: v for k, v in a.items() if k != "late_policy"} == {
            k: v for k, v in b.items() if k != "late_policy"
        }

    def test_absent_section_hashes_differently_from_present(self) -> None:
        a = compute_settings_section_hashes({"title": "X"})
        b = compute_settings_section_hashes({"title": "X", "front_page": "pages/home.md"})
        assert a["front_page"] != b["front_page"]

    def test_all_sections_always_present(self) -> None:
        hashes = compute_settings_section_hashes({})
        assert set(hashes) == {
            "metadata",
            "grading_standards",
            "dashboard_image",
            "assignment_groups",
            "late_policy",
            "default_post_policy",
            "tab_configuration",
            "front_page",
        }


# ---------------------------------------------------------------------------
# Integration: selective section re-runs via run_sync
# ---------------------------------------------------------------------------


_BASE_SETTINGS = (
    'title = "Test Course"\n'
    'due_dates = [\n'
    '    {name = "HW1", due_at = "2099-12-31T23:59:00", unlock_at = "NONE", lock_at = "KEEP"},\n'
    ']\n'
    '\n'
    '[course_flags]\n'
    'online = true\n'
)


def _cfg() -> Config:
    return Config(
        base_url="https://school.instructure.com", course_id=999, api_token="tok"
    )


def _make_repo(tmp_path: Path, settings: str = _BASE_SETTINGS) -> Path:
    root = tmp_path / "course"
    (root / "course_settings").mkdir(parents=True)
    (root / "course_settings" / "course_settings.toml").write_text(settings)
    (root / "assignments").mkdir()
    (root / "assignments" / "hw1.md").write_text(
        "---\ntitle: HW1\npublished: true\n---\n\nHomework.\n"
    )
    return root


def _mock_assignment(canvas_id: int) -> MagicMock:
    a = MagicMock()
    a.id = canvas_id
    a.html_url = f"https://school.instructure.com/courses/1/assignments/{canvas_id}"
    a.edit.return_value = a
    return a


def _mock_canvas_course(mocker) -> MagicMock:
    mock_canvas_cls = mocker.patch("markdown_to_canvas.canvas_api.Canvas")
    course = MagicMock()
    mock_canvas_cls.return_value.get_course.return_value = course
    course.create_assignment.return_value = _mock_assignment(101)
    return course


def test_flag_flip_triggers_no_settings_or_dates_calls(tmp_path, mocker, capsys) -> None:
    """Flipping a [course_flags] value re-runs no settings section and makes no
    dates-only API calls (the headline behavior of the whole feature)."""
    root = _make_repo(tmp_path)
    course = _mock_canvas_course(mocker)

    make_current(root)
    run_sync(_cfg(), root)
    course.reset_mock()
    capsys.readouterr()

    settings_path = root / "course_settings" / "course_settings.toml"
    settings_path.write_text(_BASE_SETTINGS.replace("online = true", "online = false"))

    make_current(root)
    run_sync(_cfg(), root)

    out = capsys.readouterr().out
    course.update.assert_not_called()
    course.get_assignment.assert_not_called()
    course.create_assignment.assert_not_called()
    assert "Syncing course settings..." not in out


def test_comment_only_edit_runs_no_sections(tmp_path, mocker, capsys) -> None:
    """An edit that changes no section values (added comment) re-runs nothing."""
    root = _make_repo(tmp_path)
    course = _mock_canvas_course(mocker)

    make_current(root)
    run_sync(_cfg(), root)
    course.reset_mock()
    capsys.readouterr()

    settings_path = root / "course_settings" / "course_settings.toml"
    settings_path.write_text("# just a comment\n" + _BASE_SETTINGS)

    make_current(root)
    run_sync(_cfg(), root)

    course.update.assert_not_called()
    assert "Syncing course settings..." not in capsys.readouterr().out


def test_title_edit_reruns_metadata_only(tmp_path, mocker) -> None:
    """Editing the course title re-sends metadata but not dates or other sections."""
    root = _make_repo(tmp_path)
    course = _mock_canvas_course(mocker)
    upload_image = mocker.patch("markdown_to_canvas.canvas_api.upload_course_image")

    make_current(root)
    run_sync(_cfg(), root)
    course.reset_mock()
    upload_image.reset_mock()

    settings_path = root / "course_settings" / "course_settings.toml"
    settings_path.write_text(_BASE_SETTINGS.replace('"Test Course"', '"New Title"'))

    make_current(root)
    run_sync(_cfg(), root)

    course.update.assert_called_once()
    course.get_assignment.assert_not_called()
    upload_image.assert_not_called()


def test_due_date_edit_makes_dates_call_but_reruns_no_sections(tmp_path, mocker) -> None:
    """Editing a due_dates entry updates that item's dates without re-running
    metadata or any other settings section."""
    root = _make_repo(tmp_path)
    course = _mock_canvas_course(mocker)
    assignment = _mock_assignment(101)
    course.get_assignment.return_value = assignment

    make_current(root)
    run_sync(_cfg(), root)
    course.reset_mock()

    settings_path = root / "course_settings" / "course_settings.toml"
    settings_path.write_text(
        _BASE_SETTINGS.replace("2099-12-31T23:59:00", "2088-06-30T23:59:00")
    )

    make_current(root)
    run_sync(_cfg(), root)

    course.update.assert_not_called()
    course.get_assignment.assert_called_once_with(101)
    assignment.edit.assert_called_once()
    assert (
        assignment.edit.call_args[1]["assignment"]["due_at"] == "2088-06-30T23:59:00"
    )


def test_dashboard_image_file_edit_reuploads_image_only(tmp_path, mocker) -> None:
    """Touching the dashboard image file re-uploads it even though the TOML is
    unchanged (and re-runs nothing else); a further no-change run is quiet."""
    # dashboard_image must be a top-level key: insert before [course_flags].
    settings = _BASE_SETTINGS.replace(
        "[course_flags]", 'dashboard_image = "assets/logo.png"\n\n[course_flags]'
    )
    root = _make_repo(tmp_path, settings)
    (root / "assets").mkdir()
    (root / "assets" / "logo.png").write_bytes(b"\x89PNG fake")
    course = _mock_canvas_course(mocker)
    course.upload.return_value = (
        True,
        {"id": 77777, "url": "https://school.instructure.com/files/77777/download"},
    )
    upload_image = mocker.patch("markdown_to_canvas.canvas_api.upload_course_image")

    make_current(root)
    run_sync(_cfg(), root)
    upload_image.assert_called_once()
    course.reset_mock()
    upload_image.reset_mock()

    # Bump the image mtime past run 1's last_synced (but not into the future,
    # which would keep it stale across run 3 as well).
    time.sleep(0.01)
    os.utime(root / "assets" / "logo.png", None)

    make_current(root)
    run_sync(_cfg(), root)
    upload_image.assert_called_once()
    course.update.assert_not_called()
    upload_image.reset_mock()

    make_current(root)
    run_sync(_cfg(), root)
    upload_image.assert_not_called()


def test_failed_section_recorded_as_error_and_retried_alone(tmp_path, mocker, capsys) -> None:
    """A failing section fails the run and is retried alone on the next run
    (already-succeeded sections are not re-sent)."""
    settings = _BASE_SETTINGS.replace(
        "[course_flags]",
        "[late_policy]\nlate_submission_deduction = 10\n\n[course_flags]",
    )
    root = _make_repo(tmp_path, settings)
    course = _mock_canvas_course(mocker)
    update_late = mocker.patch(
        "markdown_to_canvas.canvas_api.update_late_policy",
        side_effect=Exception("boom"),
    )

    make_current(root)
    had_errors = run_sync(_cfg(), root)

    assert had_errors is True
    assert "course_settings section 'late_policy' failed" in capsys.readouterr().out
    course.reset_mock()
    update_late.reset_mock()
    update_late.side_effect = None

    make_current(root)
    had_errors = run_sync(_cfg(), root)

    assert had_errors is False
    update_late.assert_called_once()
    course.update.assert_not_called()


def test_manifest_without_section_hashes_migrates(tmp_path, mocker) -> None:
    """A pre-existing manifest entry lacking section_hashes (older tool version)
    re-runs all sections once when stale, then records hashes."""
    root = _make_repo(tmp_path)
    manifest_path = root / ".manifest-canvas.toml"
    with manifest_path.open("wb") as f:
        tomli_w.dump(
            {
                "_repo_format": {"format_version": 2},
                "course_settings/course_settings.toml": {
                    "canvas_id": 0,
                    "canvas_type": "course_settings",
                    "last_synced": "1990-01-01T00:00:00+00:00",
                }
            },
            f,
        )
    course = _mock_canvas_course(mocker)

    make_current(root)
    run_sync(_cfg(), root)

    course.update.assert_called_once()
    with manifest_path.open("rb") as f:
        manifest = tomllib.load(f)
    entry = manifest["course_settings/course_settings.toml"]
    assert "section_hashes" in entry
    assert "metadata" in entry["section_hashes"]


def test_mv_preserves_resolved_dates(tmp_path) -> None:
    """mv re-keys the per-file entry wholesale; the resolved_dates cache rides along."""
    root = _make_repo(tmp_path)
    manifest_path = root / ".manifest-canvas.toml"
    with manifest_path.open("wb") as f:
        tomli_w.dump(
            {
                "_repo_format": {"format_version": 2},
                "assignments/hw1.md": {
                    "canvas_id": 101,
                    "canvas_type": "assignment",
                    "last_synced": "2025-01-01T00:00:00+00:00",
                    "resolved_dates": {
                        "due_at": "2099-12-31T23:59:00",
                        "unlock_at": "NONE",
                        "lock_at": "KEEP",
                    },
                }
            },
            f,
        )

    make_current(root)
    run_mv(root / "assignments" / "hw1.md", root / "assignments" / "renamed.md")

    with manifest_path.open("rb") as f:
        manifest = tomllib.load(f)
    assert "assignments/hw1.md" not in manifest
    assert manifest["assignments/renamed.md"]["resolved_dates"] == {
        "due_at": "2099-12-31T23:59:00",
        "unlock_at": "NONE",
        "lock_at": "KEEP",
    }


def test_relative_due_dates_edit_makes_no_course_update(tmp_path, mocker) -> None:
    """Editing only [relative_due_dates] must not send course settings to Canvas."""
    root = _make_repo(tmp_path)
    course = _mock_canvas_course(mocker)
    make_current(root)
    run_sync(_cfg(), root)
    assert course.update.call_count == 1
    course.reset_mock()

    settings_path = root / "course_settings" / "course_settings.toml"
    settings_path.write_text(
        settings_path.read_text()
        + '\n[relative_due_dates.tables.default]\nitems = [{ name = "HW1", '
        'relative_to = { type = "START_OF_QUARTER" }, offsets = ["+1 CLASS_DAY"] }]\n'
    )

    run_sync(_cfg(), root)

    course.update.assert_not_called()


def test_version_keys_change_makes_no_course_update(tmp_path, mocker) -> None:
    """upgrade only edits format_version / created_by / upgraded_by; the next
    update must not treat that as a course-metadata change."""
    root = _make_repo(tmp_path)
    course = _mock_canvas_course(mocker)
    make_current(root)
    run_sync(_cfg(), root)
    assert course.update.call_count == 1  # first sync sends the metadata
    course.reset_mock()

    settings_path = root / "course_settings" / "course_settings.toml"
    text = settings_path.read_text()
    settings_path.write_text(
        text.replace("format_version = 2\n", 'format_version = 2\ncreated_by = "0.2.0"\n'
                     'upgraded_by = ["0.2.1 on 2026-09-20: 0 -> 1"]\n', 1)
    )
    assert "upgraded_by" in settings_path.read_text()

    run_sync(_cfg(), root)

    course.update.assert_not_called()


def test_version_keys_never_reach_the_metadata_payload(tmp_path, mocker) -> None:
    root = _make_repo(
        tmp_path,
        'format_version = 2\ncreated_by = "0.2.0"\nupgraded_by = ["x"]\n'
        'title = "Test Course"\n',
    )
    course = _mock_canvas_course(mocker)

    run_sync(_cfg(), root)

    params = [c.kwargs["course"] for c in course.update.call_args_list]
    assert params and all(
        not ({"format_version", "created_by", "upgraded_by"} & set(p)) for p in params
    )
