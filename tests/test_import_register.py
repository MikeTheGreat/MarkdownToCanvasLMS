"""`import --register KEY`: the new course is added to the registry, or nothing is."""
from __future__ import annotations

from pathlib import Path

import pytest
from click.testing import CliRunner

from markdown_to_canvas import course_registry as reg
from markdown_to_canvas.cli import main

FIXTURE_DIR = Path(__file__).parent / "fixtures" / "imscc"


@pytest.fixture
def home(tmp_path, monkeypatch) -> Path:
    fake = tmp_path / "home"
    fake.mkdir()
    monkeypatch.setenv("HOME", str(fake))
    return fake


def run(*args: str):
    return CliRunner().invoke(main, ["import", *args])


def write_registry(home: Path, text: str) -> Path:
    path = home / ".config" / "markdown-to-canvas" / "course_registry.toml"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    return path


def test_register_adds_the_new_course(home, tmp_path):
    out = tmp_path / "it143"
    result = run(str(FIXTURE_DIR), str(out), "--register", "143")
    assert result.exit_code == 0, result.output
    assert reg.resolve_course("143").path == out.resolve()
    assert f"Registered course 143: {out.resolve()}" in result.output


def test_a_taken_key_fails_before_anything_is_written(home, tmp_path):
    registry = write_registry(home, f'[courses]\n143 = "{tmp_path}"\n')
    before = registry.read_text()
    out = tmp_path / "it143"
    result = run(str(FIXTURE_DIR), str(out), "--register", "143")
    assert result.exit_code == 1
    assert "already registered" in result.output and "'143'" in result.output
    assert not out.exists()
    assert registry.read_text() == before


def test_a_failing_import_does_not_register(home, tmp_path):
    out = tmp_path / "it143"
    out.mkdir()
    (out / "existing.txt").write_text("hi")  # import refuses a non-empty directory
    result = run(str(FIXTURE_DIR), str(out), "--register", "143")
    assert result.exit_code == 1
    assert not (home / ".config" / "markdown-to-canvas" / "course_registry.toml").exists()


def test_registry_comments_and_other_entries_survive(home, tmp_path):
    other = tmp_path / "other"
    other.mkdir()
    registry = write_registry(home, f'# hand-written\n[courses]\n# the first one\n142 = "{other}"\n')
    out = tmp_path / "it143"
    result = run(str(FIXTURE_DIR), str(out), "--register", "143")
    assert result.exit_code == 0, result.output
    text = registry.read_text()
    assert "# hand-written" in text and "# the first one" in text
    assert f'142 = "{other}"' in text
    assert reg.resolve_course("143").path == out.resolve()


def test_import_without_register_leaves_the_registry_alone(home, tmp_path):
    result = run(str(FIXTURE_DIR), str(tmp_path / "it143"))
    assert result.exit_code == 0, result.output
    assert not (home / ".config").exists()


def test_an_empty_key_is_refused(home, tmp_path):
    out = tmp_path / "it143"
    result = run(str(FIXTURE_DIR), str(out), "--register", " ")
    assert result.exit_code == 1
    assert not out.exists()
