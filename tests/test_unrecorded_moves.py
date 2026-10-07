"""Unrecorded-move check: files moved without `mv` must not become duplicate
Canvas items (unrecorded_moves.py, and its use in run_sync/run_targeted_sync)."""
from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock, call

import pytest
from canvasapi.exceptions import Forbidden, ResourceDoesNotExist
from click.testing import CliRunner

from tests.conftest import make_current
from markdown_to_canvas import canvas_api as capi
from markdown_to_canvas import manifest as manifest_lib
from markdown_to_canvas.canvas_api import OrphanItem
from markdown_to_canvas.config import Config
from markdown_to_canvas.pair_manifest import LocalItem
from markdown_to_canvas.sync import run_sync, run_targeted_sync
from markdown_to_canvas.unrecorded_moves import (
    SAME_NAME,
    SAME_TITLE,
    Commands,
    Orphan,
    check_unrecorded_moves,
    find_orphans,
    load_orphans,
    match_orphans,
)

COURSE_ID = 999
FUTURE = "2999-12-31T00:00:00+00:00"
OLD = "assignments/advising.md"
NEW = "assignments/educational-plan/advising.md"
TITLE = "Make An Appointment With Advising"


def _config() -> Config:
    return Config(base_url="https://school.instructure.com", course_id=COURSE_ID, api_token="tok")


def _write(root: Path, key: str, title: str | None = None, body: str = "Body\n") -> Path:
    path = root / key
    path.parent.mkdir(parents=True, exist_ok=True)
    fm = f"---\ntitle: \"{title}\"\n---\n" if title is not None else ""
    path.write_text(fm + body)
    return path


def _repo(tmp_path: Path) -> Path:
    root = tmp_path / "course"
    root.mkdir()
    make_current(root)
    return root


def _manifest_path(root: Path) -> Path:
    return manifest_lib.manifest_path_for(root, None)


def _save(root: Path, manifest: dict) -> Path:
    path = _manifest_path(root)
    manifest_lib.flush(path, manifest)
    return path


def _fetch(items: dict[int, OrphanItem]):
    calls: list[int] = []

    def fetch(canvas_type, entry):
        calls.append(entry["canvas_id"])
        return items.get(entry["canvas_id"], OrphanItem(True, None))

    fetch.calls = calls
    return fetch


# ---------------------------------------------------------------------------
# find_orphans / load_orphans
# ---------------------------------------------------------------------------


def test_find_orphans_skips_reserved_and_external_modules(tmp_path) -> None:
    root = _repo(tmp_path)
    _write(root, "pages/kept.md", "Kept")
    manifest = {
        manifest_lib.COURSE_KEY: {"canvas_type": manifest_lib.COURSE_TYPE, "course_id": 1},
        manifest_lib.FORMAT_KEY: {"format_version": 1},
        "canvas_modules/College Module": {"canvas_type": "external_module", "canvas_id": 5},
        "pages/kept.md": {"canvas_type": "page", "canvas_id": 1},
        "pages/gone.md": {"canvas_type": "page", "canvas_id": 2},
    }
    assert [k for k, _ in find_orphans(manifest, root)] == ["pages/gone.md"]


def test_load_orphans_drops_gone_items_and_unchecked_types(tmp_path) -> None:
    root = _repo(tmp_path)
    manifest = {
        "pages/a.md": {"canvas_type": "page", "canvas_id": 1, "canvas_url": "a"},
        "pages/b.md": {"canvas_type": "page", "canvas_id": 2, "canvas_url": "b"},
        "question_banks/q.md": {"canvas_type": "question_bank", "canvas_id": 3},
    }
    fetch = _fetch({1: OrphanItem(True, "A"), 2: OrphanItem(False, None)})
    orphans = load_orphans(manifest, root, fetch)
    assert orphans == [Orphan("pages/a.md", "page", 1, "A")]
    assert fetch.calls == [1, 2]


def test_load_orphans_makes_no_call_without_orphans(tmp_path) -> None:
    root = _repo(tmp_path)
    _write(root, "pages/a.md", "A")
    fetch = _fetch({})
    assert load_orphans({"pages/a.md": {"canvas_type": "page", "canvas_id": 1}}, root, fetch) == []
    assert fetch.calls == []


# ---------------------------------------------------------------------------
# match_orphans (pure)
# ---------------------------------------------------------------------------


def test_moved_to_subfolder_matches_by_file_name() -> None:
    orphans = [Orphan(OLD, "assignment", 42270446, None)]
    items = [LocalItem(NEW, "assignment", "Anything")]
    [m] = match_orphans(orphans, items, {})
    assert (m.orphan.key, m.path, m.tracked, m.reasons) == (OLD, NEW, False, (SAME_NAME,))


def test_renamed_with_same_title_matches_by_title() -> None:
    orphans = [Orphan("pages/old-name.md", "page", 7, "How to Succeed")]
    items = [LocalItem("pages/how-to-succeed.md", "page", "how  to succeed")]
    [m] = match_orphans(orphans, items, {})
    assert m.reasons == (SAME_TITLE,)


def test_title_comparison_ignores_curly_quotes_and_dashes() -> None:
    orphans = [Orphan("pages/a.md", "page", 7, "Week 1 – “Intro”")]
    items = [LocalItem("pages/b.md", "page", 'week 1 - "intro"')]
    assert len(match_orphans(orphans, items, {})) == 1


def test_both_reasons_reported() -> None:
    orphans = [Orphan(OLD, "assignment", 1, TITLE)]
    [m] = match_orphans(orphans, [LocalItem(NEW, "assignment", TITLE)], {})
    assert m.reasons == (SAME_NAME, SAME_TITLE)
    assert m.reason_text == "same file name and same title"


def test_different_type_does_not_match() -> None:
    orphans = [Orphan("pages/week-1.md", "page", 1, "Week 1")]
    items = [LocalItem("modules/week-1.md", "module", "Week 1")]
    assert match_orphans(orphans, items, {}) == []


def test_files_match_by_name_only() -> None:
    # A file's local "title" is its path below assets/, never compared.
    orphans = [Orphan("assets/img/a.png", "file", 1, "a.png")]
    items = [LocalItem("assets/other/b.png", "file", "a.png")]
    assert match_orphans(orphans, items, {}) == []
    items = [LocalItem("assets/other/a.png", "file", "other/a.png")]
    assert len(match_orphans(orphans, items, {})) == 1


def test_unknown_orphan_title_still_matches_by_name() -> None:
    orphans = [Orphan(OLD, "assignment", 1, None)]
    assert len(match_orphans(orphans, [LocalItem(NEW, "assignment", "x")], {})) == 1


def test_tracked_file_match_is_a_duplicate() -> None:
    orphans = [Orphan(OLD, "assignment", 42270446, TITLE)]
    manifest = {NEW: {"canvas_type": "assignment", "canvas_id": 42309815}}
    [m] = match_orphans(orphans, [LocalItem(NEW, "assignment", TITLE)], manifest)
    assert m.tracked and m.path_id == 42309815


def test_one_orphan_many_files_and_many_orphans_one_file() -> None:
    orphans = [Orphan("pages/overview.md", "page", 1, None)]
    items = [
        LocalItem("pages/week-1/overview.md", "page", "x"),
        LocalItem("pages/week-2/overview.md", "page", "y"),
    ]
    assert len(match_orphans(orphans, items, {})) == 2
    orphans = [Orphan("pages/a/x.md", "page", 1, None), Orphan("pages/b/x.md", "page", 2, None)]
    assert len(match_orphans(orphans, [LocalItem("pages/c/x.md", "page", "x")], {})) == 2


# ---------------------------------------------------------------------------
# check_unrecorded_moves
# ---------------------------------------------------------------------------


def _moved_repo(tmp_path: Path, tracked_new: bool = False) -> tuple[Path, dict, Path]:
    root = _repo(tmp_path)
    _write(root, NEW, TITLE)
    _write(root, "pages/other.md", "Other")
    manifest = {
        OLD: {"canvas_type": "assignment", "canvas_id": 42270446, "last_synced": FUTURE},
        "pages/other.md": {"canvas_type": "page", "canvas_id": 5, "canvas_url": "other", "last_synced": FUTURE},
    }
    if tracked_new:
        manifest[NEW] = {"canvas_type": "assignment", "canvas_id": 42309815, "last_synced": FUTURE}
    path = _save(root, manifest)
    return root, manifest_lib.load(path), path


def _commands(root: Path) -> Commands:
    return Commands(root, "course")


def test_check_stops_on_unrecorded_move(tmp_path, capsys, monkeypatch) -> None:
    root, manifest, path = _moved_repo(tmp_path)
    monkeypatch.chdir(root)
    before = path.read_bytes()
    errors: list[str] = []
    stop = check_unrecorded_moves(
        root, manifest, path, _fetch({42270446: OrphanItem(True, TITLE)}), errors,
        commands=_commands(root),
    )
    out = capsys.readouterr().out
    assert stop is True
    assert f"{OLD} → {NEW} (same file name and same title)" in out
    assert f"markdown-to-canvas mv --after {OLD} {NEW}" in out
    assert f"markdown-to-canvas update course --new {NEW}" in out
    assert "nothing was changed in Canvas or the manifest" in out
    assert len(errors) == 1
    assert path.read_bytes() == before


def test_check_lists_every_ambiguous_pair(tmp_path, capsys) -> None:
    root = _repo(tmp_path)
    _write(root, "pages/week-1/overview.md", "Week 1")
    _write(root, "pages/week-2/overview.md", "Week 2")
    manifest = {"pages/overview.md": {"canvas_type": "page", "canvas_id": 1, "canvas_url": "o"}}
    errors: list[str] = []
    assert check_unrecorded_moves(root, manifest, None, _fetch({}), errors) is True
    out = capsys.readouterr().out
    assert "pages/overview.md → pages/week-1/overview.md" in out
    assert "pages/overview.md → pages/week-2/overview.md" in out


def test_check_ignores_orphan_gone_from_canvas(tmp_path, capsys) -> None:
    root, manifest, path = _moved_repo(tmp_path)
    errors: list[str] = []
    stop = check_unrecorded_moves(
        root, manifest, path, _fetch({42270446: OrphanItem(False, None)}), errors
    )
    assert stop is False and errors == []
    assert capsys.readouterr().out == ""


def test_check_quiet_without_orphans_and_verbose_summary(tmp_path, capsys) -> None:
    root = _repo(tmp_path)
    _write(root, "pages/a.md", "A")
    manifest = {"pages/a.md": {"canvas_type": "page", "canvas_id": 1}}
    fetch = _fetch({})
    assert check_unrecorded_moves(root, manifest, None, fetch, [], verbose=True) is False
    assert fetch.calls == [] and capsys.readouterr().out == ""

    manifest["pages/gone.md"] = {"canvas_type": "page", "canvas_id": 2, "canvas_url": "g"}
    assert check_unrecorded_moves(root, manifest, None, _fetch({2: OrphanItem(True, "Gone")}), [], verbose=True) is False
    assert "1 orphaned entries, no matches" in capsys.readouterr().out


def test_check_warns_about_existing_duplicate_and_continues(tmp_path, capsys, monkeypatch) -> None:
    root, manifest, path = _moved_repo(tmp_path, tracked_new=True)
    monkeypatch.chdir(root)
    errors: list[str] = []
    stop = check_unrecorded_moves(
        root, manifest, path, _fetch({42270446: OrphanItem(True, TITLE)}), errors,
        commands=_commands(root),
    )
    out = capsys.readouterr().out
    assert stop is False and errors == []
    assert "probable duplicate in Canvas" in out
    assert "assignment 42270446" in out and "assignment 42309815" in out
    assert f"markdown-to-canvas update course --new {NEW}" in out
    assert "markdown-to-canvas prune course" in out


def test_new_forgets_matching_orphan_and_continues(tmp_path, capsys, monkeypatch) -> None:
    root, manifest, path = _moved_repo(tmp_path)
    manifest["pages/unrelated-gone.md"] = {"canvas_type": "page", "canvas_id": 9, "canvas_url": "u"}
    monkeypatch.chdir(root)
    errors: list[str] = []
    stop = check_unrecorded_moves(
        root, manifest, path, _fetch({42270446: OrphanItem(True, TITLE)}), errors,
        new_paths=[NEW],
    )
    out = capsys.readouterr().out
    assert stop is False and errors == []
    assert f"--new {NEW}: forgot the manifest entry for {OLD} (assignment 42270446)" in out
    assert "was left in Canvas and is no longer tracked" in out
    saved = manifest_lib.load(path)
    assert OLD not in saved
    assert "pages/unrelated-gone.md" in saved  # other orphans are kept


def test_new_accepts_tracked_file_to_clear_duplicate_warning(tmp_path, capsys) -> None:
    root, manifest, path = _moved_repo(tmp_path, tracked_new=True)
    fetch = _fetch({42270446: OrphanItem(True, TITLE)})
    assert check_unrecorded_moves(root, manifest, path, fetch, [], new_paths=[str(root / NEW)]) is False
    out = capsys.readouterr().out
    assert "forgot the manifest entry" in out
    assert "probable duplicate" not in out
    saved = manifest_lib.load(path)
    assert OLD not in saved and saved[NEW]["canvas_id"] == 42309815
    # The next run has nothing to warn about.
    assert check_unrecorded_moves(root, saved, path, fetch, []) is False
    assert capsys.readouterr().out == ""


def test_new_path_resolved_from_repo_root(tmp_path, monkeypatch) -> None:
    root, manifest, path = _moved_repo(tmp_path)
    monkeypatch.chdir(tmp_path)  # outside the repo: NEW is not a cwd-relative path
    assert check_unrecorded_moves(root, manifest, path, _fetch({}), [], new_paths=[NEW]) is False
    assert OLD not in manifest_lib.load(path)


@pytest.mark.parametrize(
    "new_path, message",
    [
        ("pages/missing.md", "no such file"),
        ("course_settings/course_settings.toml", "not a file that update syncs"),
        ("pages/other.md", "matches no orphaned manifest entry"),
    ],
)
def test_bad_new_path_stops_without_changes(tmp_path, capsys, monkeypatch, new_path, message) -> None:
    root, manifest, path = _moved_repo(tmp_path, tracked_new=True)
    monkeypatch.chdir(root)
    before = path.read_bytes()
    errors: list[str] = []
    stop = check_unrecorded_moves(
        root, manifest, path, _fetch({}), errors, new_paths=[NEW, new_path]
    )
    assert stop is True
    assert message in capsys.readouterr().out
    assert path.read_bytes() == before
    assert OLD in manifest  # validation runs before anything is forgotten


def test_new_does_not_flush_when_another_move_still_stops(tmp_path, monkeypatch) -> None:
    root, manifest, path = _moved_repo(tmp_path)
    _write(root, "pages/week-2/overview.md", "Overview")
    manifest["pages/overview.md"] = {"canvas_type": "page", "canvas_id": 3, "canvas_url": "o"}
    manifest_lib.flush(path, manifest)
    before = path.read_bytes()
    monkeypatch.chdir(root)
    assert check_unrecorded_moves(root, manifest, path, _fetch({}), [], new_paths=[NEW]) is True
    assert path.read_bytes() == before


def test_commands_show_absolute_paths_outside_cwd(tmp_path, monkeypatch) -> None:
    root = _repo(tmp_path)
    elsewhere = tmp_path / "elsewhere"
    elsewhere.mkdir()
    monkeypatch.chdir(elsewhere)
    cmds = Commands(root, "142")
    assert cmds.mv_after(OLD, NEW) == f"markdown-to-canvas mv --after {root / OLD} {root / NEW}"
    monkeypatch.chdir(root / "course_settings")
    assert cmds.update_new(NEW) == f"markdown-to-canvas update 142 --new ../{NEW}"


# ---------------------------------------------------------------------------
# canvas_api.get_orphan_item
# ---------------------------------------------------------------------------


def test_get_orphan_item_reads_titles_and_404() -> None:
    course = MagicMock()
    course.get_assignment.return_value = MagicMock(name="a", workflow_state="published")
    course.get_assignment.return_value.name = TITLE
    assert capi.get_orphan_item(course, "assignment", {"canvas_id": 1}) == OrphanItem(True, TITLE)

    course.get_page.return_value = MagicMock(title="P", workflow_state="active")
    assert capi.get_orphan_item(course, "page", {"canvas_id": 2, "canvas_url": "p"}) == OrphanItem(True, "P")
    course.get_page.assert_called_once_with("p")

    course.get_file.return_value = MagicMock(display_name="a.png", workflow_state=None)
    assert capi.get_orphan_item(course, "file", {"canvas_id": 3}).title == "a.png"

    course.get_quiz.side_effect = ResourceDoesNotExist("gone")
    assert capi.get_orphan_item(course, "quiz", {"canvas_id": 4}) == OrphanItem(False, None)

    course.get_module.return_value = MagicMock(workflow_state="deleted")
    assert capi.get_orphan_item(course, "module", {"canvas_id": 5}).exists is False


def test_get_orphan_item_other_errors_mean_unknown() -> None:
    course = MagicMock()
    course.get_discussion_topic.side_effect = Forbidden("no")
    assert capi.get_orphan_item(course, "discussion", {"canvas_id": 1}) == OrphanItem(True, None)


# ---------------------------------------------------------------------------
# run_sync / run_targeted_sync / CLI
# ---------------------------------------------------------------------------


@pytest.fixture
def mock_course(mocker) -> MagicMock:
    mock_canvas_cls = mocker.patch("markdown_to_canvas.canvas_api.Canvas")
    course = MagicMock()
    mock_canvas_cls.return_value.get_course.return_value = course
    advising = MagicMock(workflow_state="published")
    advising.name = TITLE
    course.get_assignment.return_value = advising
    return course


def test_run_sync_stops_before_any_canvas_change(mock_course, tmp_path) -> None:
    root, _, path = _moved_repo(tmp_path)
    before = path.read_bytes()
    assert run_sync(_config(), root) is True
    assert mock_course.method_calls == [call.get_assignment(42270446)]
    assert path.read_bytes() == before


def test_run_sync_with_new_creates_the_item(mock_course, tmp_path, monkeypatch) -> None:
    root, _, path = _moved_repo(tmp_path)
    monkeypatch.chdir(root)
    created = MagicMock(id=42309815, html_url="https://x/assignments/42309815")
    created.edit.return_value = created
    mock_course.create_assignment.return_value = created
    run_sync(_config(), root, new_paths=[NEW])
    mock_course.create_assignment.assert_called_once()
    saved = manifest_lib.load(path)
    assert OLD not in saved and saved[NEW]["canvas_id"] == 42309815


def test_run_sync_with_duplicate_warns_and_syncs(mock_course, tmp_path, capsys) -> None:
    root, _, _ = _moved_repo(tmp_path, tracked_new=True)
    run_sync(_config(), root)
    out = capsys.readouterr().out
    assert "probable duplicate in Canvas" in out
    assert "Aborting" not in out


def test_check_as_new_course_runs_no_check(mocker, tmp_path) -> None:
    root, _, _ = _moved_repo(tmp_path)
    spy = mocker.patch("markdown_to_canvas.sync.check_unrecorded_moves")
    run_sync(_config(), root, mode="new_course")
    spy.assert_not_called()


def test_targeted_run_checks_whole_repo(mock_course, tmp_path, capsys) -> None:
    root, _, path = _moved_repo(tmp_path)
    before = path.read_bytes()
    assert run_targeted_sync(_config(), root, [], [str(root / "pages/other.md")]) is True
    assert f"{OLD} → {NEW}" in capsys.readouterr().out
    assert path.read_bytes() == before
    mock_course.get_page.assert_not_called()


def test_cli_rejects_new_with_check_as_new_course(tmp_path) -> None:
    from markdown_to_canvas.cli import main

    root, _, _ = _moved_repo(tmp_path)
    (root / "course_settings" / "canvas.toml").write_text(
        f'base_url = "https://school.instructure.com"\ncourse_id = {COURSE_ID}\n'
    )
    result = CliRunner().invoke(main, ["update", str(root), "--check-as-new-course", "--new", NEW])
    assert result.exit_code != 0
    assert "--new" in result.output


def test_printed_commands_repeat_course_and_config(tmp_path, monkeypatch) -> None:
    from markdown_to_canvas.cli import _move_check_commands

    root = _repo(tmp_path)
    monkeypatch.chdir(root)
    cmds = _move_check_commands(root, "13", Path("course_settings/canvas-ol-3.toml"))
    assert cmds.update_new(NEW) == (
        f"markdown-to-canvas update 13 --config course_settings/canvas-ol-3.toml --new {NEW}"
    )
    # No course given: prune still needs one, so the repo path is printed.
    assert _move_check_commands(root, None, None).prune().startswith("markdown-to-canvas prune . ")
