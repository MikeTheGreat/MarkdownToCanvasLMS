"""Unit + CLI tests: fix-manifest --clean."""
from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

from click.testing import CliRunner

from markdown_to_canvas import manifest as manifest_lib
from markdown_to_canvas.canvas_api import CourseListing
from markdown_to_canvas.clean_manifest import apply_clean, check_entries, plan_clean
from markdown_to_canvas.config import Config

BASE = "https://school.instructure.com"
SYNCED = "2026-01-01T00:00:00+00:00"


def _config(course_id: int = 200) -> Config:
    return Config(base_url=BASE, course_id=course_id, api_token="tok")


def _ids(**kwargs: set[int]) -> dict[str, set[int]]:
    ids: dict[str, set[int]] = {
        t: set() for t in ("page", "assignment", "discussion", "announcement", "quiz", "module", "external_module", "file")
    }
    ids.update(kwargs)
    return ids


def _listing(**kwargs: set[int]) -> CourseListing:
    return CourseListing(_ids(**kwargs), {})


def test_removes_ids_missing_from_course_and_keeps_present_ones() -> None:
    manifest = {
        "pages/here.md": {"canvas_type": "page", "canvas_id": 1, "canvas_url": "here"},
        "pages/gone.md": {"canvas_type": "page", "canvas_id": 2, "canvas_url": "gone"},
        "assets/a.pdf": {"canvas_type": "file", "canvas_id": 10},
        "assets/b.pdf": {"canvas_type": "file", "canvas_id": 11},
        "assignments/hw.md": {"canvas_type": "assignment", "canvas_id": 20},
    }
    plan = check_entries(manifest, _ids(page={1}, file={10}, assignment={20}), _config())
    assert set(plan.removals) == {"pages/gone.md", "assets/b.pdf"}
    assert plan.checked == 5
    assert not plan.foreign_evidence


def test_page_is_checked_by_id_not_slug() -> None:
    """Slugs repeat across courses (Spring and Fall both have 'lecture-01')."""
    manifest = {"pages/l.md": {"canvas_type": "page", "canvas_id": 999, "canvas_url": "lecture-01"}}
    plan = check_entries(manifest, _ids(page={1}), _config())
    assert "pages/l.md" in plan.removals


def test_wrong_type_under_modules_is_removed_even_if_id_exists() -> None:
    manifest = {"modules/lecture-01.md": {"canvas_type": "page", "canvas_id": 5, "canvas_url": "lecture-01"}}
    plan = check_entries(manifest, _ids(page={5}), _config())
    assert "modules/lecture-01.md" in plan.removals


def test_course_level_entries_kept_without_evidence_of_another_course() -> None:
    manifest = {
        "course_settings/course_settings.toml": {"canvas_type": "course_settings", "canvas_id": 0},
        "course_settings/syllabus.md": {"canvas_type": "syllabus", "canvas_id": 200},
        "question_banks/b/b.toml": {"canvas_type": "question_bank", "canvas_id": 3},
    }
    plan = check_entries(manifest, _ids(), _config(200))
    assert not plan.removals
    assert ("course_settings/course_settings.toml", "course_settings") in plan.unchecked
    assert ("question_banks/b/b.toml", "question_bank") in plan.unchecked


def test_syllabus_from_other_course_resets_course_level_entries() -> None:
    manifest = {
        "course_settings/course_settings.toml": {"canvas_type": "course_settings", "canvas_id": 0},
        "course_settings/rubrics.toml": {"canvas_type": "rubrics", "canvas_id": 0},
        "course_settings/module_order.toml": {"canvas_type": "module_order", "canvas_id": 0},
        "course_settings/syllabus.md": {"canvas_type": "syllabus", "canvas_id": 100},
    }
    plan = check_entries(manifest, _ids(), _config(200))
    assert set(plan.removals) == set(manifest)
    assert plan.foreign_evidence


def test_stored_other_course_is_evidence() -> None:
    manifest: dict = {"course_settings/module_order.toml": {"canvas_type": "module_order", "canvas_id": 0}}
    manifest_lib.set_course_identity(manifest, None, BASE, 100, "Spring")
    plan = check_entries(manifest, _ids(), _config(200))
    assert "course_settings/module_order.toml" in plan.removals


def _repo(tmp_path: Path) -> Path:
    root = tmp_path / "course"
    for d in ("pages", "assets", "modules", "course_settings", "snippets"):
        (root / d).mkdir(parents=True)
    (root / "assets" / "sheet.pdf").write_bytes(b"pdf")
    (root / "pages" / "guide.md").write_text("---\ntitle: Guide\n---\n\nSee [sheet](../assets/sheet.pdf).\n")
    (root / "pages" / "other.md").write_text("---\ntitle: Other\n---\n\nNo links.\n")
    (root / "modules" / "week-1.md").write_text("---\ntitle: Week 1\n---\n\n- [Sheet](../assets/sheet.pdf)\n")
    (root / "course_settings" / "course_settings.toml").write_text(
        'format_version = 4\ndashboard_image = "assets/sheet.pdf"\n'
    )
    return root


def _repo_manifest() -> dict:
    return {
        "assets/sheet.pdf": {"canvas_type": "file", "canvas_id": 304998786, "last_synced": SYNCED},
        "pages/guide.md": {"canvas_type": "page", "canvas_id": 1, "canvas_url": "guide", "last_synced": SYNCED},
        "pages/other.md": {"canvas_type": "page", "canvas_id": 2, "canvas_url": "other", "last_synced": SYNCED},
        "modules/week-1.md": {"canvas_type": "module", "canvas_id": 7, "last_synced": SYNCED},
        "course_settings/course_settings.toml": {
            "canvas_type": "course_settings", "canvas_id": 0, "last_synced": SYNCED,
            "section_hashes": {"dashboard_image": "abc", "metadata": "def"},
        },
    }


def test_referrers_of_removed_entry_are_marked_for_resync(tmp_path) -> None:
    root = _repo(tmp_path)
    manifest = _repo_manifest()
    plan = plan_clean(manifest, _ids(page={1, 2}, module={7}), _config(), root)

    assert set(plan.removals) == {"assets/sheet.pdf"}
    assert set(plan.resync) == {"pages/guide.md", "modules/week-1.md"}
    assert plan.settings_sections == {"dashboard_image": "assets/sheet.pdf"}

    path = root / ".manifest-canvas.toml"
    apply_clean(manifest, path, plan, _config(), "Fall")
    loaded = manifest_lib.load(path)
    assert "assets/sheet.pdf" not in loaded
    assert "last_synced" not in loaded["pages/guide.md"]
    assert "last_synced" not in loaded["modules/week-1.md"]
    assert loaded["pages/other.md"]["last_synced"] == SYNCED
    settings = loaded["course_settings/course_settings.toml"]
    assert settings["section_hashes"] == {"metadata": "def"}
    assert "last_synced" not in settings
    assert manifest_lib.get_course_identity(loaded)["course_id"] == 200


def test_cli_report_changes_nothing_and_apply_cleans(tmp_path, mocker, monkeypatch) -> None:
    from markdown_to_canvas.cli import main

    monkeypatch.setenv("CANVAS_API_TOKEN", "tok")
    root = _repo(tmp_path)
    (root / "course_settings" / "canvas.toml").write_text(f'base_url = "{BASE}"\ncourse_id = 200\n')
    path = root / ".manifest-canvas.toml"
    manifest_lib.flush(path, _repo_manifest())
    before = path.read_bytes()

    mocker.patch("markdown_to_canvas.cli.get_course", return_value=SimpleNamespace(name="Fall"))
    mocker.patch(
        "markdown_to_canvas.canvas_api.list_course_objects",
        return_value=_listing(page={1, 2}, module={7}),
    )

    result = CliRunner().invoke(main, ["fix-manifest", str(root), "--clean"])
    assert result.exit_code == 0, result.output
    assert "Would remove 1 entries" in result.output
    assert path.read_bytes() == before

    result = CliRunner().invoke(main, ["fix-manifest", str(root), "--clean", "--apply"])
    assert result.exit_code == 0, result.output
    assert "assets/sheet.pdf" not in manifest_lib.load(path)


def test_cli_apply_switching_course_needs_yes_without_terminal(tmp_path, mocker, monkeypatch) -> None:
    from markdown_to_canvas.cli import main

    monkeypatch.setenv("CANVAS_API_TOKEN", "tok")
    root = _repo(tmp_path)
    (root / "course_settings" / "canvas.toml").write_text(f'base_url = "{BASE}"\ncourse_id = 200\n')
    path = root / ".manifest-canvas.toml"
    manifest = _repo_manifest()
    manifest_lib.set_course_identity(manifest, path, BASE, 100, "Spring")
    before = path.read_bytes()
    mocker.patch("markdown_to_canvas.cli.get_course", return_value=SimpleNamespace(name="Fall"))
    mocker.patch(
        "markdown_to_canvas.canvas_api.list_course_objects",
        return_value=_listing(page={1, 2}, module={7}),
    )

    result = CliRunner().invoke(main, ["fix-manifest", str(root), "--clean", "--apply"])
    assert result.exit_code == 1
    assert path.read_bytes() == before

    result = CliRunner().invoke(main, ["fix-manifest", str(root), "--clean", "--apply", "--yes"])
    assert result.exit_code == 0, result.output
    loaded = manifest_lib.load(path)
    assert manifest_lib.get_course_identity(loaded)["course_id"] == 200
    # stored Spring course is evidence, so course-level state is reset too
    assert "course_settings/course_settings.toml" not in loaded


def test_list_failure_aborts_without_changes(tmp_path, mocker, monkeypatch) -> None:
    from markdown_to_canvas.cli import main

    monkeypatch.setenv("CANVAS_API_TOKEN", "tok")
    root = _repo(tmp_path)
    (root / "course_settings" / "canvas.toml").write_text(f'base_url = "{BASE}"\ncourse_id = 200\n')
    path = root / ".manifest-canvas.toml"
    manifest_lib.flush(path, _repo_manifest())
    before = path.read_bytes()
    course = mocker.MagicMock()
    course.name = "Fall"
    course.get_files.side_effect = RuntimeError("500 from Canvas")
    mocker.patch("markdown_to_canvas.cli.get_course", return_value=course)

    result = CliRunner().invoke(main, ["fix-manifest", str(root), "--clean", "--apply"])
    assert result.exit_code == 1
    assert "could not list the course's contents" in result.output
    assert path.read_bytes() == before


def test_cli_requires_a_mode(tmp_path, mocker, monkeypatch) -> None:
    from markdown_to_canvas.cli import main

    monkeypatch.setenv("CANVAS_API_TOKEN", "tok")
    root = _repo(tmp_path)
    get_course = mocker.patch("markdown_to_canvas.cli.get_course")

    result = CliRunner().invoke(main, ["fix-manifest", str(root), "--apply"])

    assert result.exit_code == 1
    assert "--clean, --pair-canvas-with-local, --force-pair" in result.output
    get_course.assert_not_called()


def test_old_name_and_no_canvas_check_are_gone() -> None:
    from markdown_to_canvas.cli import main

    assert "clean-manifest" not in main.commands
    result = CliRunner().invoke(main, ["fix-manifest", "--clean", "--no-canvas-check"])
    assert result.exit_code == 2
