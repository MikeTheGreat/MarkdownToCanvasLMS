"""Every library entry point that reads a course repo refuses a repo whose
format version differs from the tool's, before reading, writing or contacting
Canvas; the CLI reports it without a traceback; upgrade fixes it."""
from __future__ import annotations

import tomllib
from pathlib import Path
from types import SimpleNamespace

import pytest
from click.testing import CliRunner

from markdown_to_canvas import manifest as manifest_lib
from markdown_to_canvas import repo_format
from markdown_to_canvas.clean_manifest import (
    check_entries,
    load_manifest,
    plan_invalidate_all,
)
from markdown_to_canvas.cli import main
from markdown_to_canvas.config import Config
from markdown_to_canvas.course_guard import check_course
from markdown_to_canvas.cp import run_cp
from markdown_to_canvas.generate_due_dates import plan_generation
from markdown_to_canvas.local_orphans import find_local_orphans
from markdown_to_canvas.mv import run_mv
from markdown_to_canvas.publish import run_publish
from markdown_to_canvas.repo_format import FORMAT_VERSION, RepoFormatError
from markdown_to_canvas.sync import (
    collect_title_items,
    run_prune,
    run_sync,
    run_targeted_sync,
)
from tests.conftest import make_current

BASE = "https://school.instructure.com"
IMSCC = Path(__file__).parent / "fixtures" / "imscc"


def _cfg(root: Path | None = None) -> Config:
    return Config(base_url=BASE, course_id=1, api_token="tok")


def _build(tmp_path: Path, state: str) -> Path:
    """A small repo in one of two out-of-date states."""
    root = tmp_path / "course"
    (root / "course_settings").mkdir(parents=True)
    (root / "pages").mkdir()
    (root / "pages" / "a.md").write_text("---\ntitle: A\n---\n\nHello.\n")
    (root / "course_settings" / "canvas.toml").write_text(
        f'base_url = "{BASE}"\ncourse_id = 1\n'
    )
    settings = root / "course_settings" / "course_settings.toml"
    settings.write_text('title = "Old"\n')
    if state == "stale_manifest":
        make_current(root)
        (root / ".manifest-canvas.toml").write_bytes(
            b'["pages/a.md"]\ncanvas_id = 1\ncanvas_type = "page"\n'
        )
    return root


def _current_dest(root: Path) -> Path:
    """A separate, current-format course repo for `cp` to copy into."""
    dest = root.parent / "cp-dest"
    make_current(dest)
    return dest


def _snapshot(root: Path) -> dict[str, bytes]:
    return {
        str(p.relative_to(root)): p.read_bytes()
        for p in sorted(root.rglob("*"))
        if p.is_file()
    }


ENTRY_POINTS = {
    "run_sync": lambda r: run_sync(_cfg(), r),
    "run_sync_check_all": lambda r: run_sync(_cfg(), r, check_all=True),
    "run_targeted_sync": lambda r: run_targeted_sync(_cfg(), r, ["pages/a.md"], []),
    "run_prune": lambda r: run_prune(_cfg(), r, "manifest"),
    "check_course": lambda r: check_course(
        r / ".manifest-canvas.toml", _cfg(), "Course", assume_yes=True
    ),
    "run_mv": lambda r: run_mv(r / "pages" / "a.md", r / "pages" / "b.md"),
    "run_cp": lambda r: run_cp([r / "pages" / "a.md"], _current_dest(r)),
    "run_publish": lambda r: run_publish(r, r / "site"),
    "find_local_orphans": lambda r: find_local_orphans(r),
    "load_manifest": lambda r: load_manifest(r, _cfg()),
    "collect_title_items": lambda r: collect_title_items(r),
    # the check comes before the term file is read, so a missing one is fine
    "plan_generation": lambda r: plan_generation(r, r.parent / "no-such-term.toml"),
}


@pytest.mark.parametrize("state", ["v0", "stale_manifest"])
@pytest.mark.parametrize("name", sorted(ENTRY_POINTS))
def test_entry_point_refuses_out_of_date_repo(name, state, tmp_path, mocker) -> None:
    canvas = mocker.patch("markdown_to_canvas.canvas_api.Canvas")
    root = _build(tmp_path, state)
    before = _snapshot(root)

    with pytest.raises(RepoFormatError) as exc:
        ENTRY_POINTS[name](root)

    assert "upgrade" in str(exc.value)
    if state == "stale_manifest":
        assert ".manifest-canvas.toml" in str(exc.value)
    canvas.assert_not_called()
    assert _snapshot(root) == before  # nothing written, nothing created


NESTED_SETTINGS = (
    'format_version = 4\n\n[late_policy]\nx = 1\ntab_configuration = [{ id = "modules" }]\n'
)


def test_commands_do_not_move_tab_configuration(tmp_path, mocker) -> None:
    """Only `upgrade` corrects placement; a current repo is taken as correct."""
    mocker.patch("markdown_to_canvas.canvas_api.Canvas")
    root = _build(tmp_path, "v0")
    settings = root / "course_settings" / "course_settings.toml"
    settings.write_text(NESTED_SETTINGS)
    before = settings.read_bytes()

    run_sync(_cfg(), root, check_all=True)
    run_mv(root / "pages" / "a.md", root / "pages" / "b.md")

    assert settings.read_bytes() == before


# ---------------------------------------------------------------------------
# Reserved manifest key: no command may treat it as content
# ---------------------------------------------------------------------------


def _current_repo_with_manifest(tmp_path: Path, entries: dict) -> tuple[Path, Path]:
    root = tmp_path / "course"
    (root / "pages").mkdir(parents=True)
    make_current(root)
    path = root / ".manifest-canvas.toml"
    manifest_lib.flush(path, {**entries})
    return root, path


def test_prune_never_reports_or_removes_the_stamp(tmp_path, capsys) -> None:
    root, path = _current_repo_with_manifest(tmp_path, {})
    assert run_prune(_cfg(), root, "manifest") is False
    assert "No orphaned manifest entries" in capsys.readouterr().out
    assert manifest_lib.load(path)[manifest_lib.FORMAT_KEY] == {"format_version": FORMAT_VERSION}


def test_prune_removes_orphans_but_keeps_the_stamp(tmp_path) -> None:
    root, path = _current_repo_with_manifest(
        tmp_path, {"pages/gone.md": {"canvas_id": 1, "canvas_type": "page"}}
    )
    run_prune(_cfg(), root, "manifest")
    loaded = manifest_lib.load(path)
    assert "pages/gone.md" not in loaded
    assert loaded[manifest_lib.FORMAT_KEY] == {"format_version": FORMAT_VERSION}


def test_mv_keeps_the_stamp_and_does_not_rewrite_it(tmp_path) -> None:
    root, path = _current_repo_with_manifest(
        tmp_path, {"pages/a.md": {"canvas_id": 1, "canvas_type": "page"}}
    )
    (root / "pages" / "a.md").write_text("---\ntitle: A\n---\n")
    run_mv(root / "pages" / "a.md", root / "pages" / "b.md")
    loaded = manifest_lib.load(path)
    assert loaded[manifest_lib.FORMAT_KEY] == {"format_version": FORMAT_VERSION}
    assert "pages/b.md" in loaded and "pages/a.md" not in loaded


def test_clean_manifest_plans_skip_the_stamp() -> None:
    manifest = {manifest_lib.FORMAT_KEY: {"format_version": FORMAT_VERSION}}
    plan = plan_invalidate_all(manifest)
    assert plan.checked == 0 and not plan.removals
    plan = check_entries(manifest, {}, _cfg())
    assert plan.checked == 0 and not plan.removals


def test_course_guard_treats_a_stamp_only_manifest_as_new(tmp_path, capsys) -> None:
    root, path = _current_repo_with_manifest(tmp_path, {})
    check_course(path, _cfg(), "Course", assume_yes=True)
    out = capsys.readouterr().out
    assert "is new" in out
    assert manifest_lib.get_course_identity(manifest_lib.load(path)) is not None


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


@pytest.fixture
def cli_env(monkeypatch, mocker):
    monkeypatch.setenv("CANVAS_API_TOKEN", "tok")
    mocker.patch("markdown_to_canvas.cli._ensure_pandoc")
    mocker.patch(
        "markdown_to_canvas.cli.get_course", return_value=SimpleNamespace(name="Course")
    )


def _term_file(root: Path) -> Path:
    path = root.parent / "term.toml"
    path.write_text("first_day = 2026-09-30\n")
    return path


CLI_COMMANDS = {
    "update": lambda r: ["update", str(r)],
    "update-check-all": lambda r: ["update", str(r), "--check-all"],
    "mv": lambda r: ["mv", str(r / "pages" / "a.md"), str(r / "pages" / "b.md")],
    "cp": lambda r: ["cp", str(r / "pages" / "a.md"), str(_current_dest(r))],
    "publish": lambda r: ["publish", str(r)],
    "prune": lambda r: ["prune", str(r), "--manifest-only"],
    "fix-manifest-clean": lambda r: ["fix-manifest", str(r), "--clean"],
    "fix-manifest-pair": lambda r: ["fix-manifest", str(r), "--pair-canvas-with-local"],
    "find-local-orphans": lambda r: ["find-local-orphans", str(r)],
    "find-canvas-orphans": lambda r: ["find-canvas-orphans", str(r)],
    "list-titles": lambda r: ["list-titles", str(r)],
    "generate-due-dates": lambda r: ["generate-due-dates", str(_term_file(r)), str(r)],
}


@pytest.mark.parametrize("name", sorted(CLI_COMMANDS))
def test_cli_command_refuses_v0_repo_with_upgrade_message(name, tmp_path, cli_env, mocker) -> None:
    mocker.patch("markdown_to_canvas.canvas_api.Canvas")
    root = _build(tmp_path, "v0")

    result = CliRunner().invoke(main, CLI_COMMANDS[name](root))

    assert result.exit_code != 0, result.output
    assert "markdown-to-canvas upgrade" in result.output
    assert "Traceback" not in result.output
    assert "KeyError or ValueError" not in result.output
    assert not isinstance(result.exception, RepoFormatError)  # turned into die()


def test_cli_import_emit_workflow_and_setup_do_not_check(tmp_path, mocker, monkeypatch) -> None:
    boom = mocker.patch(
        "markdown_to_canvas.repo_format.check_repo_format",
        side_effect=AssertionError("must not be called"),
    )
    runner = CliRunner()

    out = tmp_path / "imported"
    result = runner.invoke(main, ["import", str(IMSCC), str(out)])
    assert result.exit_code == 0, result.output

    root = _build(tmp_path, "v0")
    result = runner.invoke(main, ["emit-workflow", str(root)])
    assert result.exit_code == 0, result.output

    mocker.patch("pypandoc.get_pandoc_version", return_value="3.0")
    mocker.patch("pypandoc.get_pandoc_path", return_value="/x/pandoc")
    result = runner.invoke(main, ["setup"])
    assert result.exit_code == 0, result.output
    boom.assert_not_called()


# ---------------------------------------------------------------------------
# upgrade command
# ---------------------------------------------------------------------------


def test_cli_upgrade_normal_run(tmp_path) -> None:
    root = _build(tmp_path, "v0")
    result = CliRunner().invoke(main, ["upgrade", str(root)])
    assert result.exit_code == 0, result.output
    assert "Migration 0 -> 1" in result.output
    settings = tomllib.loads((root / "course_settings" / "course_settings.toml").read_text())
    assert settings["format_version"] == FORMAT_VERSION
    assert repo_format.check_repo_format(root) is None


def test_cli_upgrade_noop_writes_nothing(tmp_path) -> None:
    root = _build(tmp_path, "stale_manifest")
    (root / ".canvas-manifest.toml").write_text("")
    before = _snapshot(root)
    result = CliRunner().invoke(main, ["upgrade", str(root), "--noop"])
    assert result.exit_code == 0, result.output
    assert "no files were written" in result.output
    assert _snapshot(root) == before


def test_cli_upgrade_refuses_newer_repo(tmp_path) -> None:
    root = _build(tmp_path, "v0")
    settings = root / "course_settings" / "course_settings.toml"
    settings.write_text(f"format_version = {FORMAT_VERSION + 1}\n")
    result = CliRunner().invoke(main, ["upgrade", str(root)])
    assert result.exit_code != 0
    assert "Update markdown-to-canvas" in result.output
    assert settings.read_text() == f"format_version = {FORMAT_VERSION + 1}\n"


def test_cli_upgrade_finds_repo_from_cwd(tmp_path, monkeypatch) -> None:
    root = _build(tmp_path, "v0")
    monkeypatch.chdir(root / "pages")
    result = CliRunner().invoke(main, ["upgrade"])
    assert result.exit_code == 0, result.output
    assert repo_format.read_repo_version(root) == FORMAT_VERSION


# ---------------------------------------------------------------------------
# End to end: an old import, upgraded, then usable
# ---------------------------------------------------------------------------


def test_upgrade_an_old_import_end_to_end(tmp_path, mocker) -> None:
    from markdown_to_canvas.imscc_import import run_import

    root = tmp_path / "old"
    run_import(IMSCC, root)
    settings = root / "course_settings" / "course_settings.toml"

    # Simulate a repo imported before versions existed: no version keys, and
    # tab_configuration nested under a section.
    lines = [
        ln for ln in settings.read_text().splitlines()
        if not ln.startswith(("format_version", "created_by"))
    ]
    text = "\n".join(lines).lstrip("\n") + "\n"
    assert "tab_configuration" not in text and "[default_post_policy]" in text
    text = text.replace(
        "[default_post_policy]\n",
        '[default_post_policy]\ntab_configuration = [{ id = "modules" }]\n',
        1,
    )
    settings.write_text(text)
    (root / ".canvas-manifest.toml").write_text(
        '["pages/a.md"]\ncanvas_id = 1\ncanvas_type = "page"\n'
    )
    with pytest.raises(RepoFormatError):
        repo_format.check_repo_format(root)

    result = CliRunner().invoke(main, ["upgrade", str(root)])

    assert result.exit_code == 0, result.output
    data = tomllib.loads(settings.read_text())
    assert data["format_version"] == FORMAT_VERSION
    assert len(data["upgraded_by"]) == 1 and data["upgraded_by"][0].endswith(f": 0 -> {FORMAT_VERSION}")
    assert "created_by" not in data
    assert data["tab_configuration"] == [{"id": "modules"}]
    assert "tab_configuration" not in data.get("default_post_policy", {})
    assert not (root / ".canvas-manifest.toml").exists()
    stamped = tomllib.loads((root / ".manifest-canvas.toml").read_text())
    assert stamped["_repo_format"] == {"format_version": FORMAT_VERSION}
    assert repo_format.check_repo_format(root) is None

    mocker.patch("markdown_to_canvas.canvas_api.Canvas")
    run_sync(_cfg(), root, check_all=True)  # no RepoFormatError
