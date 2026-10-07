"""Tests for `update --noop`: a dry run of update against the real course.

The defining properties under test:
- the manifest on disk decides what is reported, as in a real run (only stale
  and new files appear), and it is byte-identical afterwards;
- reads go to canvas_api, and no canvas_api write function is ever called;
- the course requester refuses any non-GET request;
- the unrecorded-move check and the course guard run without writing;
- the CLI prints a summary and exits 1 on problems.

A "previous real sync" is produced by running run_sync in real mode with the
sync module's canvas_api replaced by a DryRunCanvas, which writes a manifest
with positive fake ids. The noop run then uses the real canvas_api module with
its read functions stubbed and every other public function made to fail.
"""
from __future__ import annotations

import inspect
import os
import re
import shutil
import time
from datetime import UTC, datetime
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest
from click.testing import CliRunner

from markdown_to_canvas import canvas_api, dryrun
from markdown_to_canvas import manifest as manifest_lib
from markdown_to_canvas import sync as sync_module
from markdown_to_canvas.canvas_api import OrphanItem
from markdown_to_canvas.config import Config
from markdown_to_canvas.course_guard import CourseGuardError, check_course
from markdown_to_canvas.sync import run_sync, run_targeted_sync
from tests.conftest import make_current

FIXTURES = Path(__file__).parent / "fixtures"
COURSE_ID = 999
BASE_URL = "https://school.instructure.com"

# canvas_api functions the noop pipeline may call for real (all reads).
_READS = {
    "get_course",
    "get_canvas_updated_at",
    "get_orphan_item",
    "get_assignment_group_ids",
    "get_rubric_ids",
    "get_group_category_ids",
    "get_module_ids_by_name",
}


def _config(root: Path | None = None) -> Config:
    return Config(
        base_url=BASE_URL,
        course_id=COURSE_ID,
        api_token="token",
        config_path=(root / "course_settings" / "canvas.toml") if root else None,
    )


def _fake_course():
    requester = MagicMock()
    return SimpleNamespace(name="Test Course", id=COURSE_ID, _requester=requester)


@pytest.fixture
def course_root(tmp_path: Path) -> Path:
    root = tmp_path / "course"
    shutil.copytree(FIXTURES, root, ignore=shutil.ignore_patterns(".manifest-canvas.toml"))
    make_current(root)
    return root


def _manifest_path(root: Path) -> Path:
    return manifest_lib.manifest_path_for(root, _config(root).config_path)


def _sync_for_real(root: Path, monkeypatch) -> None:
    """Run a real full sync against a simulated course, leaving a manifest
    whose entries are all up to date."""
    fake = dryrun.DryRunCanvas()
    fake.get_course = lambda config: dryrun.DryRunCourse()
    with monkeypatch.context() as m:
        m.setattr(sync_module, "capi", fake)
        assert run_sync(_config(root), root) is False
    # Make every file older than its last_synced stamp.
    past = time.time() - 3600
    for path in root.rglob("*"):
        if path.is_file() and not path.name.startswith(".manifest"):
            os.utime(path, (past, past))


def _touch(path: Path) -> None:
    future = time.time() + 3600
    os.utime(path, (future, future))


@pytest.fixture
def live(mocker):
    """Stub canvas_api's reads and make every other public function fail."""
    course = _fake_course()
    for name, func in inspect.getmembers(canvas_api, inspect.isfunction):
        if name.startswith("_") or func.__module__ != canvas_api.__name__:
            continue
        if name not in _READS:
            mocker.patch.object(
                canvas_api, name,
                side_effect=AssertionError(f"--noop called canvas_api.{name}"),
            )
    reads = SimpleNamespace(
        course=course,
        get_course=mocker.patch.object(canvas_api, "get_course", return_value=course),
        get_canvas_updated_at=mocker.patch.object(
            canvas_api, "get_canvas_updated_at", return_value=None
        ),
        get_orphan_item=mocker.patch.object(
            canvas_api, "get_orphan_item", return_value=OrphanItem(True, None)
        ),
        get_assignment_group_ids=mocker.patch.object(
            canvas_api, "get_assignment_group_ids", return_value={}
        ),
        get_rubric_ids=mocker.patch.object(canvas_api, "get_rubric_ids", return_value={}),
        get_group_category_ids=mocker.patch.object(
            canvas_api, "get_group_category_ids", return_value={}
        ),
        get_module_ids_by_name=mocker.patch.object(
            canvas_api, "get_module_ids_by_name", return_value={}
        ),
    )
    # cli.py binds get_course by name at import time.
    from markdown_to_canvas import cli

    mocker.patch.object(cli, "get_course", reads.get_course)
    return reads


def _summary(out: str) -> dict[str, int]:
    tail = out[out.index("NOOP SUMMARY"):]
    return {
        label: int(value)
        for label, value in re.findall(r"^  ([A-Za-z ()]+):\s+(\d+)$", tail, re.MULTILINE)
    }


# ---------------------------------------------------------------------------
# Pipeline
# ---------------------------------------------------------------------------


def test_noop_reports_only_stale_and_new_files(course_root, monkeypatch, live, capsys) -> None:
    _sync_for_real(course_root, monkeypatch)
    manifest_path = _manifest_path(course_root)
    before = manifest_path.read_bytes()
    _touch(course_root / "assignments" / "week1.md")
    (course_root / "pages" / "new.md").write_text("---\ntitle: New Page\n---\n\nHello.\n")
    capsys.readouterr()

    had_errors = run_sync(_config(course_root), course_root, mode="noop")

    out = capsys.readouterr().out
    assert had_errors is False, out
    assert "NOOP MODE" in out
    assert "Would upload: assignments/week1.md" in out
    assert "Would upload: pages/new.md" in out
    assert "Would upload: pages/syllabus.md" not in out
    assert "Would upload: discussions/week1-intro.md" not in out
    assert "Uploading" not in out
    assert "Link:" not in out
    assert manifest_path.read_bytes() == before
    summary = _summary(out)
    assert summary["Would create"] == 1
    # The assignment, plus week-1 module because it links to it.
    assert summary["Would update"] == 2
    assert summary["Up to date (skipped)"] > 0
    assert summary["Problems"] == 0


def test_noop_nothing_changed(course_root, monkeypatch, live, capsys) -> None:
    _sync_for_real(course_root, monkeypatch)
    capsys.readouterr()

    assert run_sync(_config(course_root), course_root, mode="noop") is False

    out = capsys.readouterr().out
    assert "Would upload" not in out
    summary = _summary(out)
    assert summary["Would create"] == 0
    assert summary["Would update"] == 0


def test_noop_force_uploads_lists_everything(course_root, monkeypatch, live, capsys) -> None:
    """Every content type goes through NoopCanvas without a missing twin, and
    the manifest is untouched."""
    _sync_for_real(course_root, monkeypatch)
    manifest_path = _manifest_path(course_root)
    before = manifest_path.read_bytes()
    capsys.readouterr()

    had_errors = run_sync(
        _config(course_root), course_root, force_uploads=True, mode="noop"
    )

    out = capsys.readouterr().out
    assert had_errors is False, out
    assert "Would upload asset: assets/images/fig.png" in out
    assert "Would upload: pages/syllabus.md" in out
    assert "Would upload: assignments/week1.md" in out
    assert "Would upload: discussions/week1-intro.md" in out
    assert "Would upload: quizzes/a-quiz/a-quiz.md" in out
    assert "Would sync module: modules/week-1.md" in out
    assert manifest_path.read_bytes() == before
    summary = _summary(out)
    assert summary["Would create"] == 0
    assert summary["Would update"] >= 6


def test_noop_newer_on_canvas_is_not_uploaded(course_root, monkeypatch, live, capsys) -> None:
    _sync_for_real(course_root, monkeypatch)
    _touch(course_root / "assignments" / "week1.md")
    later = datetime(2999, 1, 1, tzinfo=UTC)
    live.get_canvas_updated_at.side_effect = (
        lambda course, canvas_type, identifier: later if canvas_type == "assignment" else None
    )
    capsys.readouterr()

    run_sync(_config(course_root), course_root, mode="noop")

    out = capsys.readouterr().out
    assert "Would upload: assignments/week1.md" not in out
    assert "assignments/week1.md" in out[out.index("NOOP SUMMARY") - 2000:]
    assert _summary(out)["Newer on Canvas"] == 1


def test_noop_force_overwrite_skips_canvas_timestamps(
    course_root, monkeypatch, live, capsys
) -> None:
    _sync_for_real(course_root, monkeypatch)
    _touch(course_root / "assignments" / "week1.md")
    capsys.readouterr()

    run_sync(_config(course_root), course_root, force_overwrite=True, mode="noop")

    assert "Would upload: assignments/week1.md" in capsys.readouterr().out
    live.get_canvas_updated_at.assert_not_called()


def test_noop_reports_problems(course_root, monkeypatch, live, capsys) -> None:
    _sync_for_real(course_root, monkeypatch)
    (course_root / "pages" / "broken.md").write_text(
        "---\ntitle: Broken\n---\n\nSee [missing](../pages/no-such-page.md).\n"
    )
    capsys.readouterr()

    assert run_sync(_config(course_root), course_root, mode="noop") is True

    out = capsys.readouterr().out
    assert "no-such-page.md" in out
    assert _summary(out)["Problems"] >= 1


def test_noop_without_previous_sync_creates_everything(course_root, live, capsys) -> None:
    """No manifest: every item would be created, links get stubs with fake ids,
    and no manifest file appears."""
    had_errors = run_sync(_config(course_root), course_root, mode="noop")

    out = capsys.readouterr().out
    assert had_errors is False, out
    assert _summary(out)["Would update"] >= 0
    assert _summary(out)["Would create"] >= 6
    assert not _manifest_path(course_root).exists()


def test_noop_only_sends_get_requests(course_root, monkeypatch, live) -> None:
    """The requester of the course the run uses lets GETs through and stops
    anything else."""
    _sync_for_real(course_root, monkeypatch)
    underlying = live.course._requester.request
    run_sync(_config(course_root), course_root, force_uploads=True, mode="noop")

    with pytest.raises(dryrun.NoopWriteError):
        live.course._requester.request("POST", "courses/999/pages")
    live.course._requester.request("GET", "courses/999")
    assert [c.args[0] for c in underlying.call_args_list] == ["GET"]


# ---------------------------------------------------------------------------
# Targeted
# ---------------------------------------------------------------------------


def test_noop_single_target(course_root, monkeypatch, live, capsys) -> None:
    _sync_for_real(course_root, monkeypatch)
    manifest_path = _manifest_path(course_root)
    before = manifest_path.read_bytes()
    _touch(course_root / "assignments" / "week1.md")
    _touch(course_root / "pages" / "syllabus.md")
    capsys.readouterr()

    had_errors = run_targeted_sync(
        _config(course_root), course_root,
        [], [str(course_root / "assignments" / "week1.md")], mode="noop",
    )

    out = capsys.readouterr().out
    assert had_errors is False, out
    assert "Would upload: assignments/week1.md" in out
    assert "Would upload: pages/syllabus.md" not in out
    assert manifest_path.read_bytes() == before
    assert _summary(out)["Would update"] == 1


def test_noop_recursive_target_follows_links(course_root, monkeypatch, live, capsys) -> None:
    """-t reaches the syllabus through the assignment's link, as a real -t does;
    the unrelated discussion is not reported."""
    _sync_for_real(course_root, monkeypatch)
    _touch(course_root / "assignments" / "week1.md")
    _touch(course_root / "pages" / "syllabus.md")
    _touch(course_root / "discussions" / "week1-intro.md")
    capsys.readouterr()

    run_targeted_sync(
        _config(course_root), course_root,
        [str(course_root / "assignments" / "week1.md")], [], mode="noop",
    )

    out = capsys.readouterr().out
    assert "Would upload: assignments/week1.md" in out
    assert "Would upload: pages/syllabus.md" in out
    assert "Would upload: discussions/week1-intro.md" not in out
    assert _summary(out)["Would update"] == 2


def test_noop_targeted_force_uploads_asset(course_root, monkeypatch, live, capsys) -> None:
    _sync_for_real(course_root, monkeypatch)
    capsys.readouterr()

    run_targeted_sync(
        _config(course_root), course_root, [],
        [str(course_root / "assets" / "images" / "fig.png")],
        force_uploads=True, mode="noop",
    )

    out = capsys.readouterr().out
    assert "Would upload asset: assets/images/fig.png" in out
    assert _summary(out)["Would update"] == 1


def test_targeted_rejects_new_course_mode(course_root) -> None:
    with pytest.raises(ValueError):
        run_targeted_sync(_config(course_root), course_root, [], [], mode="new_course")


# ---------------------------------------------------------------------------
# Unrecorded moves
# ---------------------------------------------------------------------------


def _move_without_mv(root: Path) -> None:
    (root / "pages" / "old").mkdir()
    (root / "pages" / "syllabus.md").rename(root / "pages" / "old" / "syllabus.md")


def test_noop_stops_on_unrecorded_move(course_root, monkeypatch, live, capsys) -> None:
    _sync_for_real(course_root, monkeypatch)
    _move_without_mv(course_root)
    before = _manifest_path(course_root).read_bytes()
    capsys.readouterr()

    assert run_sync(_config(course_root), course_root, mode="noop") is True

    out = capsys.readouterr().out
    assert "mv --after" in out
    assert "Would upload" not in out
    assert "NOOP SUMMARY" not in out
    assert _manifest_path(course_root).read_bytes() == before


def test_noop_new_forgets_in_memory_only(course_root, monkeypatch, live, capsys) -> None:
    _sync_for_real(course_root, monkeypatch)
    _move_without_mv(course_root)
    before = _manifest_path(course_root).read_bytes()
    capsys.readouterr()

    run_sync(
        _config(course_root), course_root, mode="noop",
        new_paths=["pages/old/syllabus.md"],
    )

    out = capsys.readouterr().out
    # The run went on past the move check (the moved page's relative snippet
    # link then fails, as it would in a real run).
    assert "--new pages/old/syllabus.md: forgot the manifest entry" in out
    assert "Processing: pages/old/syllabus.md" in out
    assert _manifest_path(course_root).read_bytes() == before


# ---------------------------------------------------------------------------
# NoopCanvas and block_writes
# ---------------------------------------------------------------------------


def test_noop_canvas_merges_live_and_simulated(mocker) -> None:
    mocker.patch.object(canvas_api, "get_assignment_group_ids", return_value={"Homework": 5})
    mocker.patch.object(canvas_api, "get_rubric_ids", return_value={"Essay": 7})
    mocker.patch.object(canvas_api, "get_module_ids_by_name", return_value={"week 1": [9]})
    api = dryrun.NoopCanvas()
    course = object()

    api.sync_assignment_groups(course, [{"title": "Homework"}, {"title": "Labs"}])
    groups = api.get_assignment_group_ids(course)
    assert groups["Homework"] == 5
    assert groups["Labs"] < 0

    ids, created, updated, failed = api.sync_rubrics(course, [{"title": "Essay"}, {"title": "Lab"}])
    assert (created, updated, failed) == (["Lab"], ["Essay"], [])
    assert ids["Essay"] == 7 and ids["Lab"] < 0

    module = api.create_or_update_module(course, None, "Week 2")
    assert module.id < 0
    assert api.find_module_ids_named(course, " week 2 ") == [module.id]
    assert api.find_module_ids_named(course, "Week 1") == [9]
    assert canvas_api.get_module_ids_by_name.call_count == 1


def test_noop_canvas_answers_fake_ids_locally(mocker) -> None:
    updated_at = mocker.patch.object(canvas_api, "get_canvas_updated_at")
    api = dryrun.NoopCanvas()
    stub = api.create_stub(object(), "page", "New Page")
    assert stub["canvas_id"] < 0

    assert api.get_canvas_updated_at(object(), "page", stub["canvas_url"]) is None
    assert api.get_canvas_updated_at(object(), "assignment", -4) is None
    updated_at.assert_not_called()

    api.get_canvas_updated_at(object(), "assignment", 1234)
    updated_at.assert_called_once()


def test_block_writes() -> None:
    course = _fake_course()
    underlying = course._requester.request
    dryrun.block_writes(course)

    course._requester.request("GET", "courses/1")
    for method in ("POST", "PUT", "DELETE", "patch"):
        with pytest.raises(dryrun.NoopWriteError):
            course._requester.request(method, "courses/1")
    assert underlying.call_count == 1


# ---------------------------------------------------------------------------
# Course guard
# ---------------------------------------------------------------------------


def _no_prompt(question: str) -> bool:
    raise AssertionError(f"prompted: {question}")


def test_guard_noop_same_course(course_root) -> None:
    path = course_root / ".manifest-canvas.toml"
    manifest = {}
    manifest_lib.set_course_identity(manifest, path, BASE_URL, COURSE_ID, "Test Course")
    before = path.read_bytes()

    check_course(path, _config(course_root), "Test Course", confirm=_no_prompt, noop=True)

    assert path.read_bytes() == before


def test_guard_noop_nothing_recorded(course_root, capsys) -> None:
    path = course_root / ".manifest-canvas.toml"

    check_course(path, _config(course_root), "Test Course", confirm=_no_prompt, noop=True)

    assert not path.exists()
    assert "--noop: update would ask to record" in capsys.readouterr().out


def test_guard_noop_different_course(course_root, capsys) -> None:
    path = course_root / ".manifest-canvas.toml"
    manifest = {}
    manifest_lib.set_course_identity(manifest, path, BASE_URL, 111, "Other Course")
    before = path.read_bytes()

    with pytest.raises(CourseGuardError, match="--noop stopped"):
        check_course(path, _config(course_root), "Test Course", confirm=_no_prompt, noop=True)

    assert "belongs to a different course" in capsys.readouterr().out
    assert path.read_bytes() == before


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def _write_canvas_toml(root: Path) -> None:
    (root / "course_settings" / "canvas.toml").write_text(
        f'base_url = "{BASE_URL}"\ncourse_id = {COURSE_ID}\napi_token = "token"\n'
    )


def _cli(*args: str):
    from markdown_to_canvas.cli import main

    return CliRunner().invoke(main, ["update", *args])


def _record_course(root: Path) -> None:
    path = _manifest_path(root)
    manifest = manifest_lib.load(path)
    manifest_lib.set_course_identity(manifest, path, BASE_URL, COURSE_ID, "Test Course")


def test_cli_noop_success(course_root, monkeypatch, live) -> None:
    _write_canvas_toml(course_root)
    _sync_for_real(course_root, monkeypatch)
    _record_course(course_root)
    _touch(course_root / "assignments" / "week1.md")
    before = _manifest_path(course_root).read_bytes()

    result = _cli(str(course_root), "-n")

    assert result.exit_code == 0, result.output
    assert "Would upload: assignments/week1.md" in result.output
    assert "NOOP SUMMARY" in result.output
    assert "Noop complete; no problems found. Nothing was changed." in result.output
    assert _manifest_path(course_root).read_bytes() == before


def test_cli_noop_exit_code_on_problems(course_root, monkeypatch, live) -> None:
    _write_canvas_toml(course_root)
    _sync_for_real(course_root, monkeypatch)
    _record_course(course_root)
    (course_root / "pages" / "broken.md").write_text(
        "---\ntitle: Broken\n---\n\nSee [missing](../pages/no-such-page.md).\n"
    )

    result = _cli(str(course_root), "--noop")

    assert result.exit_code == 1
    assert "Noop complete; please check the problems listed above" in result.output


def test_cli_noop_unrecorded_move_exits_nonzero(course_root, monkeypatch, live) -> None:
    _write_canvas_toml(course_root)
    _sync_for_real(course_root, monkeypatch)
    _record_course(course_root)
    _move_without_mv(course_root)

    result = _cli(str(course_root), "--noop")

    assert result.exit_code == 1
    assert "mv --after" in result.output


def test_cli_noop_different_course_stops(course_root, monkeypatch, live) -> None:
    _write_canvas_toml(course_root)
    _sync_for_real(course_root, monkeypatch)
    path = _manifest_path(course_root)
    manifest = manifest_lib.load(path)
    manifest_lib.set_course_identity(manifest, path, BASE_URL, 111, "Other Course")
    before = path.read_bytes()

    result = _cli(str(course_root), "--noop")

    assert result.exit_code != 0
    assert "--noop stopped" in result.output
    assert path.read_bytes() == before


def test_cli_noop_accepts_other_options(course_root, monkeypatch, live) -> None:
    _write_canvas_toml(course_root)
    _sync_for_real(course_root, monkeypatch)
    _record_course(course_root)

    for extra in (
        ["-t", str(course_root / "assignments" / "week1.md")],
        ["-s", str(course_root / "assignments" / "week1.md")],
        ["--force-uploads"],
        ["--force-overwrite"],
        ["--verbose", "--yes"],
    ):
        result = _cli(str(course_root), "--noop", *extra)
        assert result.exit_code == 0, (extra, result.output)
        assert "NOOP SUMMARY" in result.output


def test_cli_noop_rejects_check_as_new_course(course_root, live) -> None:
    _write_canvas_toml(course_root)

    result = _cli(str(course_root), "--noop", "--check-as-new-course")

    assert result.exit_code != 0
    assert "cannot be combined" in result.output
    live.get_course.assert_not_called()


def test_cli_noop_needs_a_token(course_root, monkeypatch, live) -> None:
    (course_root / "course_settings" / "canvas.toml").write_text(
        f'base_url = "{BASE_URL}"\ncourse_id = {COURSE_ID}\n'
    )
    monkeypatch.delenv("CANVAS_API_TOKEN", raising=False)

    result = _cli(str(course_root), "--noop")

    assert result.exit_code != 0
    live.get_course.assert_not_called()


def test_cli_check_all_is_gone(course_root, live) -> None:
    result = _cli(str(course_root), "--check-all")
    assert result.exit_code == 2
    assert "No such option" in result.output
    # -ca is no longer an option; click reads it as -c a (--config a).
    result = _cli(str(course_root), "-ca")
    assert result.exit_code != 0
    live.get_course.assert_not_called()
