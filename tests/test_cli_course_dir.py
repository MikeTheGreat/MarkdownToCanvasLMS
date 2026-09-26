"""COURSE_DIR resolution through the CLI: path, registry key, walk-up, config, output.

HOME is a temporary directory in every test, so the real registry is never read.
Canvas is never contacted: `update --check-all` is offline and `prune
--manifest-only` never calls Canvas.
"""
from __future__ import annotations

from pathlib import Path

import click
import pytest
from click.testing import CliRunner

from markdown_to_canvas import manifest as manifest_lib
from markdown_to_canvas.cli import main
from tests.conftest import make_current


@pytest.fixture
def home(tmp_path, monkeypatch) -> Path:
    fake = tmp_path / "home"
    fake.mkdir()
    monkeypatch.setenv("HOME", str(fake))
    return fake


@pytest.fixture
def unrelated(tmp_path, monkeypatch) -> Path:
    """A working directory that is not inside any course."""
    work = tmp_path / "work"
    work.mkdir()
    monkeypatch.chdir(work)
    return work


def register(home: Path, text: str) -> None:
    path = home / ".config" / "markdown-to-canvas" / "course_registry.toml"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def make_course(tmp_path: Path, name: str = "course", course_id: int = 111) -> Path:
    root = tmp_path / name
    (root / "pages").mkdir(parents=True)
    make_current(root)
    (root / "course_settings" / "canvas.toml").write_text(
        f'base_url = "https://school.instructure.com"\ncourse_id = {course_id}\n'
    )
    return root


def run(*args: str):
    return CliRunner().invoke(main, list(args))


def first_line(result) -> str:
    return result.output.splitlines()[0]


# ---------------------------------------------------------------------------
# Resolution and the printed directory
# ---------------------------------------------------------------------------


def test_update_by_key_from_an_unrelated_directory(home, tmp_path, unrelated):
    course = make_course(tmp_path)
    register(home, f'[courses]\n142 = "{course}"\n')
    result = run("update", "142", "--check-all")
    assert result.exit_code == 0, result.output
    assert first_line(result) == f"Course dir: {course.resolve()}  (course 142)"
    assert "Course ID: 111" in result.output


def test_update_by_path_prints_the_absolute_path_without_a_key(home, tmp_path, unrelated):
    course = make_course(tmp_path)
    result = run("update", str(course), "--check-all")
    assert result.exit_code == 0, result.output
    assert first_line(result) == f"Course dir: {course.resolve()}"


def test_update_walks_up_from_a_subdirectory(home, tmp_path, monkeypatch):
    course = make_course(tmp_path)
    monkeypatch.chdir(course / "pages")
    result = run("update", "--check-all")
    assert result.exit_code == 0, result.output
    assert first_line(result) == f"Course dir: {course.resolve()}"


def test_a_directory_named_like_a_key_wins(home, tmp_path, unrelated):
    registered = make_course(tmp_path, "registered", course_id=111)
    register(home, f'[courses]\n142 = "{registered}"\n')
    local = make_course(unrelated, "142", course_id=222)
    result = run("update", "142", "--check-all")
    assert result.exit_code == 0, result.output
    assert first_line(result) == f"Course dir: {local.resolve()}"
    assert "Course ID: 222" in result.output


def test_unknown_course_lists_keys_and_changes_nothing(home, tmp_path, unrelated):
    course = make_course(tmp_path)
    register(home, f'[courses]\n142 = "{course}"\n143 = "{course}"\n')
    result = run("update", "999", "--check-all")
    assert result.exit_code == 1
    assert "'999'" in result.output and "142, 143" in result.output
    assert "Course dir:" not in result.output


def test_registered_directory_missing_names_the_key(home, tmp_path, unrelated):
    register(home, f'[courses]\n142 = "{tmp_path / "gone"}"\n')
    result = run("update", "142", "--check-all")
    assert result.exit_code == 1
    assert "'142'" in result.output and "gone" in result.output


def test_omitted_argument_outside_a_course_asks_for_it(home, unrelated):
    result = run("find-local-orphans")
    assert result.exit_code == 1
    assert "COURSE_DIR" in result.output


# The commands that used to default to "." now walk up like the others.
@pytest.mark.parametrize(
    "command", ["find-local-orphans", "list-titles", "upgrade", "fix-markdown"]
)
def test_walk_up_commands_work_from_a_subdirectory(command, home, tmp_path, monkeypatch):
    course = make_course(tmp_path)
    monkeypatch.chdir(course / "pages")
    result = run(command)
    assert result.exit_code == 0, result.output
    assert first_line(result) == f"Course dir: {course.resolve()}"


def test_emit_workflow_walks_up_and_by_key(home, tmp_path, monkeypatch):
    course = make_course(tmp_path)
    register(home, f'[courses]\n142 = "{course}"\n')
    monkeypatch.chdir(course / "pages")
    result = run("emit-workflow")
    assert result.exit_code == 0, result.output
    assert first_line(result) == f"Course dir: {course.resolve()}"
    assert (course / ".github" / "workflows").is_dir()


@pytest.mark.parametrize(
    "command",
    ["find-local-orphans", "list-titles", "upgrade", "fix-manifest", "fix-markdown"],
)
def test_key_works_for_more_commands(command, home, tmp_path, unrelated):
    course = make_course(tmp_path)
    register(home, f'[courses]\n142 = "{course}"\n')
    args = [command, "142"]
    if command == "fix-manifest":
        args.append("--pair-canvas-with-local")  # a mode is required; only checking the header
    result = run(*args)
    assert first_line(result) == f"Course dir: {course.resolve()}  (course 142)"


# ---------------------------------------------------------------------------
# prune keeps a required argument and shows the directory first
# ---------------------------------------------------------------------------


def test_prune_requires_an_argument_even_inside_a_course(home, tmp_path, monkeypatch):
    course = make_course(tmp_path)
    monkeypatch.chdir(course)
    result = run("prune", "--manifest-only")
    assert result.exit_code == 2
    assert "COURSE_DIR" in result.output
    assert "Course dir:" not in result.output


def test_prune_prints_the_directory_before_anything_else(home, tmp_path, unrelated):
    course = make_course(tmp_path)
    register(home, f'[courses]\n142 = "{course}"\n')
    result = run("prune", "142", "--manifest-only")
    assert result.exit_code == 0, result.output
    assert first_line(result) == f"Course dir: {course.resolve()}  (course 142)"
    assert result.output.index("Course dir:") < result.output.index("Course ID:")


def test_prune_delete_shows_the_directory_before_contacting_canvas(
    home, tmp_path, unrelated, mocker
):
    course = make_course(tmp_path)
    register(home, f'[courses]\n142 = "{course}"\n')
    order: list[str] = []
    mocker.patch(
        "markdown_to_canvas.cli.get_course",
        side_effect=lambda cfg: order.append("canvas") or (_ for _ in ()).throw(
            click.ClickException("stop here")
        ),
    )
    result = run("prune", "142", "--delete")
    assert order == ["canvas"]
    assert first_line(result).startswith("Course dir:")


# ---------------------------------------------------------------------------
# Registry config
# ---------------------------------------------------------------------------


def section_course(tmp_path: Path) -> Path:
    course = make_course(tmp_path, course_id=111)
    (course / "course_settings" / "canvas-sec-a.toml").write_text(
        'base_url = "https://school.instructure.com"\ncourse_id = 777\n'
    )
    (course / "course_settings" / "canvas-sec-b.toml").write_text(
        'base_url = "https://school.instructure.com"\ncourse_id = 888\n'
    )
    return course


def test_entry_config_is_used(home, tmp_path, unrelated):
    course = section_course(tmp_path)
    register(
        home,
        f'[courses]\n142a = {{ path = "{course}", config = "course_settings/canvas-sec-a.toml" }}\n',
    )
    result = run("update", "142a", "--check-all")
    assert result.exit_code == 0, result.output
    assert "Course ID: 777" in result.output


def test_command_line_config_beats_the_entry_config(home, tmp_path, unrelated):
    course = section_course(tmp_path)
    register(
        home,
        f'[courses]\n142a = {{ path = "{course}", config = "course_settings/canvas-sec-a.toml" }}\n',
    )
    result = run(
        "update", "142a", "--check-all", "--config", str(course / "course_settings" / "canvas-sec-b.toml")
    )
    assert "Course ID: 888" in result.output


def test_a_path_argument_ignores_the_registry_config(home, tmp_path, unrelated):
    course = section_course(tmp_path)
    register(
        home,
        f'[courses]\n142a = {{ path = "{course}", config = "course_settings/canvas-sec-a.toml" }}\n',
    )
    result = run("update", str(course), "--check-all")
    assert "Course ID: 111" in result.output


def test_the_manifest_follows_the_entry_config(home, tmp_path, unrelated):
    course = section_course(tmp_path)
    register(
        home,
        f'[courses]\n142a = {{ path = "{course}", config = "course_settings/canvas-sec-a.toml" }}\n',
    )
    entry = {"pages/gone.md": {"canvas_id": 1, "canvas_type": "page"}}
    section_manifest = course / ".manifest-canvas-sec-a.toml"
    main_manifest = course / ".manifest-canvas.toml"
    manifest_lib.flush(section_manifest, dict(entry))
    manifest_lib.flush(main_manifest, dict(entry))

    result = run("prune", "142a", "--manifest-only")

    assert result.exit_code == 0, result.output
    assert "pages/gone.md" not in manifest_lib.load(section_manifest)
    assert "pages/gone.md" in manifest_lib.load(main_manifest)


# ---------------------------------------------------------------------------
# Naming
# ---------------------------------------------------------------------------

COURSE_COMMANDS = [
    "update", "publish", "prune", "fix-manifest", "fix-markdown", "upgrade", "generate-due-dates",
    "list-titles", "find-canvas-orphans", "find-local-orphans", "emit-workflow", "cp",
]


@pytest.mark.parametrize("name", COURSE_COMMANDS)
def test_help_names_the_argument_course_dir(name):
    result = run(name, "--help")
    assert result.exit_code == 0
    assert "COURSE_DIR" in result.output
    assert "REPO" not in result.output


def test_every_course_command_is_listed():
    """Guards the list above: a new command taking a course must be added to it."""
    takers = {
        name
        for name, cmd in main.commands.items()
        if any(p.name == "course_dir" for p in cmd.params)
    }
    assert takers == set(COURSE_COMMANDS)


# ---------------------------------------------------------------------------
# Commands that need more than the course to run: stop them after the header
# ---------------------------------------------------------------------------


def test_publish_by_key_prints_the_directory(home, tmp_path, unrelated, mocker):
    course = make_course(tmp_path)
    register(home, f'[courses]\n142 = "{course}"\n')
    called = mocker.patch("markdown_to_canvas.cli.run_publish")
    result = run("publish", "142")
    assert result.exit_code == 0, result.output
    assert first_line(result) == f"Course dir: {course.resolve()}  (course 142)"
    assert called.call_args.args[0] == course.resolve()


def test_publish_uses_the_entry_config_for_flags(home, tmp_path, unrelated, mocker):
    course = section_course(tmp_path)
    register(
        home,
        f'[courses]\n142a = {{ path = "{course}", config = "course_settings/canvas-sec-a.toml" }}\n',
    )
    called = mocker.patch("markdown_to_canvas.cli.run_publish")
    result = run("publish", "142a")
    assert result.exit_code == 0, result.output
    assert called.call_args.args[2].course_id == 777


def test_find_canvas_orphans_by_key_prints_the_directory(home, tmp_path, unrelated, mocker):
    course = make_course(tmp_path)
    register(home, f'[courses]\n142 = "{course}"\n')
    mocker.patch(
        "markdown_to_canvas.cli.get_course", return_value=type("C", (), {"name": "Course"})()
    )
    mocker.patch("markdown_to_canvas.cli.find_orphans", return_value=[])
    mocker.patch("markdown_to_canvas.cli.print_report")
    result = run("find-canvas-orphans", "142")
    assert result.exit_code == 0, result.output
    assert first_line(result) == f"Course dir: {course.resolve()}  (course 142)"
    assert result.output.index("Course dir:") < result.output.index("Course ID:")


# ---------------------------------------------------------------------------
# generate-due-dates: TERM_FILE by name, then COURSE_DIR by key
# ---------------------------------------------------------------------------


def _write_term(home: Path, name: str) -> None:
    from tests.test_generate_due_dates import TERM

    path = home / ".config" / "markdown-to-canvas" / "terms" / f"{name}.toml"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(TERM)


def test_generate_due_dates_takes_a_term_name_and_a_course_key(home, tmp_path, unrelated):
    from tests.test_generate_due_dates import _repo

    course = _repo(tmp_path)
    register(home, f'[courses]\n142 = "{course}"\n')
    _write_term(home, "2026Fall")

    result = run("generate-due-dates", "2026Fall", "142", "--noop")

    assert result.exit_code == 0, result.output
    assert first_line(result) == f"Course dir: {course.resolve()}  (course 142)"
    assert "Relative table: default" in result.output


def test_generate_due_dates_walks_up_when_the_course_is_omitted(home, tmp_path, monkeypatch):
    from tests.test_generate_due_dates import _repo

    course = _repo(tmp_path)
    _write_term(home, "2026Fall")
    monkeypatch.chdir(course / "assignments")

    result = run("generate-due-dates", "2026Fall", "--noop")

    assert result.exit_code == 0, result.output
    assert first_line(result) == f"Course dir: {course.resolve()}"


def test_generate_due_dates_unknown_term_lists_the_terms(home, tmp_path, unrelated):
    from tests.test_generate_due_dates import _repo

    course = _repo(tmp_path)
    _write_term(home, "2026Fall")
    result = run("generate-due-dates", "2027Spring", str(course), "--noop")
    assert result.exit_code == 1
    assert "2026Fall" in result.output and "2027Spring" in result.output
    assert "Traceback" not in result.output
