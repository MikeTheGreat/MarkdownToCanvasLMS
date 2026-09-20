"""mv and publish on a repo that has [relative_due_dates] and a term file.

The relative table is read only by generate-due-dates (items are matched by
title, not path), so neither command needs to know about it; these tests pin that.
"""
from __future__ import annotations

import shutil
import sys
from pathlib import Path

import tomli_w

from markdown_to_canvas import publish
from markdown_to_canvas.mv import run_mv
from markdown_to_canvas.repo_format import FORMAT_VERSION

FIXTURES = Path(__file__).parent / "fixtures"

SETTINGS = f"""\
format_version = {FORMAT_VERSION}
title = "Course"
front_page = "pages/home.md"

due_dates = [
    {{ name = "HW1", due_at = "NONE", unlock_at = "KEEP", lock_at = "KEEP" }},
]

[relative_due_dates]
days_of_week = ["Mon", "Wed"]

[relative_due_dates.tables.default]
items = [
    {{ name = "HW1", relative_to = {{ type = "START_OF_QUARTER" }}, offsets = ["+1 CLASS_DAY"] }},
]
"""

TERM = "first_day = 2026-09-30\nlast_day = 2026-12-18\n"


def test_mv_leaves_the_relative_section_and_term_file_alone(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    (repo / "course_settings").mkdir(parents=True)
    (repo / "course_settings" / "course_settings.toml").write_text(SETTINGS)
    (repo / "course_settings" / "term_dates.toml").write_text(TERM)
    (repo / "pages").mkdir()
    (repo / "pages" / "home.md").write_text("---\ntitle: Home\n---\n\nHi\n")
    (repo / "assignments").mkdir()
    (repo / "assignments" / "hw1.md").write_text("---\ntitle: HW1\n---\n\nDo it\n")
    with (repo / ".manifest-canvas.toml").open("wb") as f:
        tomli_w.dump({"_repo_format": {"format_version": FORMAT_VERSION}}, f)

    run_mv(repo / "assignments" / "hw1.md", repo / "assignments" / "homework-1.md")
    run_mv(repo / "pages" / "home.md", repo / "pages" / "start.md")

    text = (repo / "course_settings" / "course_settings.toml").read_text()
    assert 'front_page = "pages/start.md"' in text  # mv still does its own job here
    assert text == SETTINGS.replace("pages/home.md", "pages/start.md")
    assert (repo / "course_settings" / "term_dates.toml").read_text() == TERM
    assert (repo / "assignments" / "homework-1.md").exists()


def test_publish_runs_on_a_repo_with_the_section_and_term_file(tmp_path, monkeypatch) -> None:
    repo = tmp_path / "course"
    shutil.copytree(FIXTURES, repo, ignore=shutil.ignore_patterns(".manifest-canvas.toml"))
    settings = repo / "course_settings" / "course_settings.toml"
    settings.write_text(
        settings.read_text()
        + '\n[relative_due_dates.tables.default]\nitems = []\n'
    )
    (repo / "course_settings" / "term_dates.toml").write_text(TERM)

    staging = tmp_path / "staging"
    monkeypatch.setattr(publish.tempfile, "mkdtemp", lambda prefix="": str(staging))
    monkeypatch.setattr(publish.importlib.util, "find_spec", lambda name: object())
    calls = []
    monkeypatch.setattr(publish.subprocess, "run", lambda cmd, **kw: calls.append(cmd))

    publish.run_publish(repo, tmp_path / "site")

    (cmd,) = calls
    assert cmd[:4] == [sys.executable, "-m", "mkdocs", "build"]
