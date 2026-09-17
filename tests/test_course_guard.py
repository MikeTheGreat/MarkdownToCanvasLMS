"""Unit + CLI tests: the stored course guard (manifest belongs to one course)."""
from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import pytest
from click.testing import CliRunner

from markdown_to_canvas import manifest as manifest_lib
from markdown_to_canvas.config import Config
from markdown_to_canvas.course_guard import CourseGuardError, check_course
from markdown_to_canvas.mv import compute_manifest_updates

BASE = "https://school.instructure.com"


def _config(course_id: int = 200, config_path: Path | None = None) -> Config:
    return Config(base_url=BASE, course_id=course_id, api_token="tok", config_path=config_path)


def _write(path: Path, manifest: dict) -> None:
    manifest_lib.flush(path, manifest)


def _page_entry() -> dict:
    return {"canvas_type": "page", "canvas_id": 1, "canvas_url": "a", "last_synced": "2026-01-01T00:00:00+00:00"}


def test_first_sync_asks_before_recording(tmp_path, capsys) -> None:
    """The course being uploaded to is printed by the caller; the prompt is the
    chance to notice it is the wrong one."""
    path = tmp_path / ".manifest-canvas.toml"
    prompts: list[str] = []
    check_course(path, _config(), "Fall", confirm=lambda p: prompts.append(p) or True,
                 interactive=lambda: True)
    stored = manifest_lib.get_course_identity(manifest_lib.load(path))
    assert stored["course_id"] == 200 and stored["course_name"] == "Fall"
    assert len(prompts) == 1 and "200" in prompts[0]
    assert "first sync" in capsys.readouterr().out


def test_first_sync_declined_records_nothing(tmp_path) -> None:
    path = tmp_path / ".manifest-canvas.toml"
    with pytest.raises(CourseGuardError):
        check_course(path, _config(), "Fall", confirm=lambda _: False,
                     interactive=lambda: True)
    assert not path.exists()


def test_same_course_passes_silently(tmp_path) -> None:
    path = tmp_path / ".manifest-canvas.toml"
    manifest = {"pages/a.md": _page_entry()}
    manifest_lib.set_course_identity(manifest, path, BASE + "/", 200, "Fall")
    check_course(path, _config(), "Fall", confirm=lambda _: pytest.fail("asked"))


def test_course_change_declined_changes_nothing(tmp_path, capsys) -> None:
    path = tmp_path / ".manifest-canvas.toml"
    manifest = {"pages/a.md": _page_entry()}
    manifest_lib.set_course_identity(manifest, path, BASE, 100, "Spring")
    before = path.read_bytes()
    with pytest.raises(CourseGuardError):
        check_course(path, _config(200), "Fall", confirm=lambda _: False,
                     interactive=lambda: True)
    assert path.read_bytes() == before
    out = capsys.readouterr().out
    assert "Recorded:" in out and "Requested:" in out and "duplicates" in out


def test_course_change_accepted_clears_every_canvas_id(tmp_path) -> None:
    """No object in the new course can hold an id recorded against the old one,
    so the whole manifest goes and the next update re-creates the content."""
    path = tmp_path / ".manifest-canvas.toml"
    manifest = {
        "pages/a.md": _page_entry(),
        "assets/x.png": {"canvas_type": "file", "canvas_id": 9, "last_synced": "2026-01-01T00:00:00+00:00"},
        "course_settings/course_settings.toml": {"canvas_type": "course_settings", "canvas_id": 0},
    }
    manifest_lib.set_course_identity(manifest, path, BASE, 100, "Spring")

    check_course(path, _config(200), "Fall", confirm=lambda _: True, interactive=lambda: True)

    loaded = manifest_lib.load(path)
    assert list(loaded) == [manifest_lib.COURSE_KEY]
    stored = manifest_lib.get_course_identity(loaded)
    assert stored["course_id"] == 200 and stored["course_name"] == "Fall"


def test_course_change_without_terminal_needs_yes(tmp_path) -> None:
    path = tmp_path / ".manifest-canvas.toml"
    manifest = {"pages/a.md": _page_entry()}
    manifest_lib.set_course_identity(manifest, path, BASE, 100, "Spring")
    before = path.read_bytes()
    with pytest.raises(CourseGuardError, match="--yes"):
        check_course(path, _config(200), "Fall", interactive=lambda: False)
    assert path.read_bytes() == before
    check_course(path, _config(200), "Fall", assume_yes=True, interactive=lambda: False)
    assert list(manifest_lib.load(path)) == [manifest_lib.COURSE_KEY]


def test_unrecorded_manifest_with_entries_asks(tmp_path) -> None:
    path = tmp_path / ".manifest-canvas.toml"
    _write(path, {"pages/a.md": _page_entry()})
    prompts: list[str] = []
    check_course(path, _config(), "Fall", confirm=lambda p: prompts.append(p) or True,
                 interactive=lambda: True)
    assert len(prompts) == 1
    loaded = manifest_lib.load(path)
    assert manifest_lib.get_course_identity(loaded)["course_id"] == 200
    assert "pages/a.md" in loaded


def test_unrecorded_manifest_declined_changes_nothing(tmp_path) -> None:
    path = tmp_path / ".manifest-canvas.toml"
    _write(path, {"pages/a.md": _page_entry()})
    with pytest.raises(CourseGuardError):
        check_course(path, _config(), "Fall", confirm=lambda _: False, interactive=lambda: True)
    assert manifest_lib.get_course_identity(manifest_lib.load(path)) is None


def test_unrecorded_manifest_without_terminal_needs_yes(tmp_path) -> None:
    path = tmp_path / ".manifest-canvas.toml"
    _write(path, {"pages/a.md": _page_entry()})
    with pytest.raises(CourseGuardError, match="--yes"):
        check_course(path, _config(), "Fall", interactive=lambda: False)
    check_course(path, _config(), "Fall", assume_yes=True, interactive=lambda: False)
    assert manifest_lib.get_course_identity(manifest_lib.load(path)) is not None


def test_mv_keeps_course_identity() -> None:
    manifest = {
        manifest_lib.COURSE_KEY: {"canvas_type": manifest_lib.COURSE_TYPE, "base_url": BASE, "course_id": 1},
        "pages/a.md": _page_entry(),
    }
    result = compute_manifest_updates(manifest, {"pages/a.md": "pages/b.md"})
    assert result[manifest_lib.COURSE_KEY] == manifest[manifest_lib.COURSE_KEY]
    assert "pages/b.md" in result


def test_prune_manifest_only_keeps_course_identity(tmp_path) -> None:
    from markdown_to_canvas.sync import run_prune

    (tmp_path / "course_settings").mkdir()
    path = tmp_path / ".manifest-canvas.toml"
    manifest = {"pages/gone.md": _page_entry()}
    manifest_lib.set_course_identity(manifest, path, BASE, 200, "Fall")
    run_prune(_config(), tmp_path, "manifest")
    loaded = manifest_lib.load(path)
    assert "pages/gone.md" not in loaded
    assert manifest_lib.get_course_identity(loaded) is not None


def _cli_repo(tmp_path: Path, course_id: int) -> Path:
    root = tmp_path / "course"
    (root / "course_settings").mkdir(parents=True)
    (root / "course_settings" / "course_settings.toml").write_text("")
    (root / "course_settings" / "canvas.toml").write_text(
        f'base_url = "{BASE}"\ncourse_id = {course_id}\n'
    )
    return root


def test_cli_update_switches_course_then_syncs_with_yes(tmp_path, mocker, monkeypatch) -> None:
    from markdown_to_canvas.cli import main

    monkeypatch.setenv("CANVAS_API_TOKEN", "tok")
    root = _cli_repo(tmp_path, 200)
    path = root / ".manifest-canvas.toml"
    manifest = {"pages/a.md": _page_entry()}
    manifest_lib.set_course_identity(manifest, path, BASE, 100, "Spring")
    mocker.patch("markdown_to_canvas.cli._ensure_pandoc")
    mocker.patch("markdown_to_canvas.cli.get_course", return_value=SimpleNamespace(name="Fall"))
    run_sync = mocker.patch("markdown_to_canvas.cli.run_sync", return_value=False)

    result = CliRunner().invoke(main, ["update", str(root), "--yes"])

    assert result.exit_code == 0, result.output
    assert "Course ID: 200" in result.output and "Course:    Fall" in result.output
    assert list(manifest_lib.load(path)) == [manifest_lib.COURSE_KEY]
    run_sync.assert_called_once()


def test_cli_update_stops_before_sync_on_course_mismatch(tmp_path, mocker, monkeypatch) -> None:
    from markdown_to_canvas.cli import main

    monkeypatch.setenv("CANVAS_API_TOKEN", "tok")
    root = _cli_repo(tmp_path, 200)
    manifest = {"pages/a.md": _page_entry()}
    manifest_lib.set_course_identity(manifest, root / ".manifest-canvas.toml", BASE, 100, "Spring")
    mocker.patch("markdown_to_canvas.cli._ensure_pandoc")
    mocker.patch("markdown_to_canvas.cli.get_course", return_value=SimpleNamespace(name="Fall"))
    run_sync = mocker.patch("markdown_to_canvas.cli.run_sync")

    # No --yes and CliRunner's stdin is not a terminal, so it cannot ask.
    result = CliRunner().invoke(main, ["update", str(root)])

    assert result.exit_code == 1
    assert "no terminal to ask" in result.output
    assert manifest_lib.get_course_identity(manifest_lib.load(root / ".manifest-canvas.toml"))["course_id"] == 100
    run_sync.assert_not_called()


def test_cli_prune_delete_stops_on_course_mismatch(tmp_path, mocker, monkeypatch) -> None:
    from markdown_to_canvas.cli import main

    monkeypatch.setenv("CANVAS_API_TOKEN", "tok")
    root = _cli_repo(tmp_path, 200)
    manifest = {"pages/a.md": _page_entry()}
    manifest_lib.set_course_identity(manifest, root / ".manifest-canvas.toml", BASE, 100, "Spring")
    mocker.patch("markdown_to_canvas.cli.get_course", return_value=SimpleNamespace(name="Fall"))
    run_prune = mocker.patch("markdown_to_canvas.cli.run_prune")

    result = CliRunner().invoke(main, ["prune", str(root), "--delete"])

    assert result.exit_code == 1
    run_prune.assert_not_called()
