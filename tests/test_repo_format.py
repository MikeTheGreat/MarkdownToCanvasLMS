"""Tests for repo_format: version reading, the check, tab_configuration, upgrade."""
import tomllib
from datetime import date

import pytest
import tomli_w
import tomlkit

from markdown_to_canvas import manifest as manifest_lib
from markdown_to_canvas import repo_format as rf
from markdown_to_canvas.repo_format import FORMAT_VERSION, RepoFormatError
from tests.conftest import make_current


def _settings(repo, text):
    path = repo / "course_settings" / "course_settings.toml"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    return path


def _manifest(repo, name=".manifest-canvas.toml", version=None, extra=None):
    data = dict(extra or {})
    if version is not None:
        data["_repo_format"] = {"format_version": version}
    path = repo / name
    with open(path, "wb") as f:
        tomli_w.dump(data, f)
    return path


# --- make_current ---------------------------------------------------------

def test_make_current_creates_file(tmp_path):
    path = make_current(tmp_path)
    assert tomllib.loads(path.read_text()) == {"format_version": FORMAT_VERSION}


def test_make_current_prepends_to_existing(tmp_path):
    path = _settings(tmp_path, "# hi\nfoo = 1\n")
    make_current(tmp_path)
    assert path.read_text() == f"format_version = {FORMAT_VERSION}\n# hi\nfoo = 1\n"
    make_current(tmp_path)  # idempotent
    assert path.read_text().count("format_version") == 1


# --- reading ---------------------------------------------------------------

def test_tool_version_is_a_string():
    assert isinstance(rf.tool_version(), str) and rf.tool_version()


def test_read_repo_version_missing_file(tmp_path):
    assert rf.read_repo_version(tmp_path) == 0


def test_read_repo_version_missing_key(tmp_path):
    _settings(tmp_path, "foo = 1\n")
    assert rf.read_repo_version(tmp_path) == 0


def test_read_repo_version_value(tmp_path):
    _settings(tmp_path, "format_version = 1\n")
    assert rf.read_repo_version(tmp_path) == 1


@pytest.mark.parametrize("bad", ['"1"', "1.5", "-1", "True"])
def test_read_repo_version_invalid(tmp_path, bad):
    _settings(tmp_path, f"format_version = {bad.lower() if bad == 'True' else bad}\n")
    with pytest.raises(RepoFormatError) as exc:
        rf.read_repo_version(tmp_path)
    assert "course_settings.toml" in str(exc.value)
    assert bad.strip('"') in str(exc.value)


def test_read_manifest_versions(tmp_path):
    stamped = _manifest(tmp_path, ".manifest-canvas.toml", version=1)
    unstamped = _manifest(tmp_path, ".manifest-b.toml", extra={"a.md": {"canvas_id": 1}})
    assert rf.read_manifest_versions(tmp_path) == {stamped: 1, unstamped: 0}


def test_read_manifest_versions_none(tmp_path):
    assert rf.read_manifest_versions(tmp_path) == {}


def test_read_manifest_versions_ignores_legacy_name(tmp_path):
    (tmp_path / ".canvas-manifest.toml").write_text("")
    assert rf.read_manifest_versions(tmp_path) == {}


# --- tab_configuration -----------------------------------------------------

NESTED = '''\
# top comment
title = "x"

[default_post_policy]
# policy comment
post_manually = true
tab_configuration = """
[{"id": "home"}]
"""

[[other]]
name = "a"
'''


def _fix(text):
    doc = tomlkit.parse(text)
    return doc, rf.fix_tab_configuration(doc)


def test_fix_tab_configuration_none():
    doc, notice = _fix('title = "x"\n[a]\nb = 1\n')
    assert notice is None
    assert tomlkit.dumps(doc) == 'title = "x"\n[a]\nb = 1\n'


def test_fix_tab_configuration_nested_in_table():
    doc, notice = _fix(NESTED)
    assert "default_post_policy.tab_configuration" in notice
    data = tomllib.loads(tomlkit.dumps(doc))
    assert data["tab_configuration"].strip() == '[{"id": "home"}]'
    assert data["default_post_policy"] == {"post_manually": True}
    assert "# top comment" in tomlkit.dumps(doc)
    assert "# policy comment" in tomlkit.dumps(doc)
    assert data["other"] == [{"name": "a"}]


def test_fix_tab_configuration_nested_in_array_element():
    text = 'title = "x"\n\n[[sections]]\nname = "a"\ntab_configuration = "[]"\n'
    doc, notice = _fix(text)
    assert "sections[0].tab_configuration" in notice
    data = tomllib.loads(tomlkit.dumps(doc))
    assert data["tab_configuration"] == "[]"
    assert data["sections"] == [{"name": "a"}]


def test_fix_tab_configuration_conflict():
    text = 'tab_configuration = "[]"\n[a]\ntab_configuration = "[1]"\n'
    doc = tomlkit.parse(text)
    with pytest.raises(RepoFormatError) as exc:
        rf.fix_tab_configuration(doc)
    assert "top level" in str(exc.value) and "a.tab_configuration" in str(exc.value)


def test_fix_tab_configuration_correct_placement():
    doc, notice = _fix('tab_configuration = "[]"\n[a]\nb = 1\n')
    assert notice is None


def test_fix_tab_configuration_comments_survive():
    doc, _ = _fix(NESTED)
    out = tomlkit.dumps(doc)
    # Everything but the moved key is still there, byte for byte.
    assert out.startswith('# top comment\ntitle = "x"\n')
    assert "[default_post_policy]\n# policy comment\npost_manually = true\n" in out


# --- check_repo_format -----------------------------------------------------

def test_check_older_repo(tmp_path):
    _settings(tmp_path, "foo = 1\n")
    with pytest.raises(RepoFormatError) as exc:
        rf.check_repo_format(tmp_path)
    msg = str(exc.value)
    assert "markdown-to-canvas upgrade" in msg and "version 0" in msg
    assert f"version {FORMAT_VERSION}" in msg


def test_check_newer_repo(tmp_path):
    _settings(tmp_path, f"format_version = {FORMAT_VERSION + 1}\n")
    with pytest.raises(RepoFormatError) as exc:
        rf.check_repo_format(tmp_path)
    msg = str(exc.value)
    assert "Update markdown-to-canvas" in msg and str(FORMAT_VERSION + 1) in msg


def test_check_older_manifest_named(tmp_path):
    make_current(tmp_path)
    _manifest(tmp_path, ".manifest-other.toml")
    with pytest.raises(RepoFormatError) as exc:
        rf.check_repo_format(tmp_path)
    assert ".manifest-other.toml" in str(exc.value)
    assert "upgrade" in str(exc.value)


def test_check_newer_manifest_named(tmp_path):
    make_current(tmp_path)
    _manifest(tmp_path, ".manifest-other.toml", version=FORMAT_VERSION + 1)
    with pytest.raises(RepoFormatError) as exc:
        rf.check_repo_format(tmp_path)
    assert ".manifest-other.toml" in str(exc.value)
    assert "Update markdown-to-canvas" in str(exc.value)


def test_check_current_passes(tmp_path):
    make_current(tmp_path)
    _manifest(tmp_path, version=FORMAT_VERSION)
    assert rf.check_repo_format(tmp_path) is None


def test_check_only_compares_versions_and_leaves_tab_configuration(tmp_path, capsys):
    """Placement is fixed once, by `upgrade`; a current version means it was."""
    path = _settings(tmp_path, "format_version = 1\n" + NESTED)
    before = path.read_bytes()
    assert rf.check_repo_format(tmp_path) is None
    assert path.read_bytes() == before
    assert capsys.readouterr().out == ""


# --- manifest stamp --------------------------------------------------------

def test_new_manifest_is_stamped_on_flush(tmp_path):
    path = tmp_path / ".manifest-canvas.toml"
    m = manifest_lib.load(path)
    manifest_lib.flush(path, m)
    assert rf.read_manifest_versions(tmp_path) == {path: FORMAT_VERSION}


def test_reserved_key_helpers():
    assert manifest_lib.is_reserved_key("_repo_format", {"format_version": 1})
    assert manifest_lib.is_reserved_key("_canvas_course")
    assert not manifest_lib.is_reserved_key("pages/a.md", {"canvas_id": 1})
    assert not manifest_lib.has_content_entries({"_repo_format": {"format_version": 1}})
    assert manifest_lib.has_content_entries({"a.md": {"canvas_id": 1}})


# --- upgrade ---------------------------------------------------------------

def test_upgrade_old_repo(tmp_path, capsys):
    path = _settings(tmp_path, "# keep me\ntitle = 'x'\n")
    manifest = _manifest(tmp_path, extra={"a.md": {"canvas_id": 1}})
    rf.run_upgrade(tmp_path, today=date(2026, 9, 20))
    text = path.read_text()
    data = tomllib.loads(text)
    assert data["format_version"] == 1
    assert data["upgraded_by"] == [f"{rf.tool_version()} on 2026-09-20: 0 -> 1"]
    assert "created_by" not in data
    assert "# keep me\ntitle = 'x'\n" in text
    assert text.startswith("format_version = 1\nupgraded_by")
    assert tomllib.loads(manifest.read_text())["_repo_format"] == {"format_version": 1}
    assert tomllib.loads(manifest.read_text())["a.md"] == {"canvas_id": 1}
    assert rf.check_repo_format(tmp_path) is None
    assert "Migration 0 -> 1" in capsys.readouterr().out


def test_upgrade_second_run_is_noop(tmp_path, capsys):
    _settings(tmp_path, "x = 1\n")
    rf.run_upgrade(tmp_path)
    capsys.readouterr()
    before = (tmp_path / "course_settings/course_settings.toml").read_bytes()
    rf.run_upgrade(tmp_path)
    assert "already current" in capsys.readouterr().out
    assert (tmp_path / "course_settings/course_settings.toml").read_bytes() == before


def test_upgrade_creates_missing_settings(tmp_path):
    rf.run_upgrade(tmp_path)
    data = tomllib.loads((tmp_path / "course_settings/course_settings.toml").read_text())
    assert data["format_version"] == 1
    assert len(data["upgraded_by"]) == 1


def test_upgrade_noop_writes_nothing(tmp_path, capsys):
    path = _settings(tmp_path, "x = 1\n")
    manifest = _manifest(tmp_path)
    legacy = tmp_path / ".canvas-manifest.toml"
    legacy.write_text("")
    before = (path.read_bytes(), manifest.read_bytes())
    rf.run_upgrade(tmp_path, noop=True)
    assert (path.read_bytes(), manifest.read_bytes()) == before
    assert legacy.exists()
    assert "no files were written" in capsys.readouterr().out


def test_upgrade_refuses_newer(tmp_path):
    path = _settings(tmp_path, f"format_version = {FORMAT_VERSION + 1}\n")
    before = path.read_bytes()
    with pytest.raises(RepoFormatError):
        rf.run_upgrade(tmp_path)
    assert path.read_bytes() == before


def test_upgrade_manifest_only_adds_no_entry(tmp_path):
    path = _settings(tmp_path, "format_version = 1\nx = 1\n")
    manifest = _manifest(tmp_path)
    before = path.read_bytes()
    rf.run_upgrade(tmp_path)
    assert path.read_bytes() == before
    assert tomllib.loads(manifest.read_text())["_repo_format"] == {"format_version": 1}


def test_upgrade_appends_second_entry(tmp_path):
    fake = {1: lambda state: ["step"]}
    _settings(tmp_path, "format_version = 1\n")
    rf.run_upgrade(tmp_path, today=date(2026, 1, 1))  # already current: no entry
    rf.run_upgrade(
        tmp_path, migrations={**rf.MIGRATIONS, **fake}, target_version=2,
        today=date(2026, 2, 2),
    )
    _settings_text = (tmp_path / "course_settings/course_settings.toml").read_text()
    data = tomllib.loads(_settings_text)
    assert data["format_version"] == 2
    assert data["upgraded_by"] == [f"{rf.tool_version()} on 2026-02-02: 1 -> 2"]
    rf.run_upgrade(
        tmp_path, migrations={**rf.MIGRATIONS, 2: lambda s: []}, target_version=3,
        today=date(2026, 3, 3),
    )
    data = tomllib.loads((tmp_path / "course_settings/course_settings.toml").read_text())
    assert data["format_version"] == 3
    assert data["upgraded_by"] == [
        f"{rf.tool_version()} on 2026-02-02: 1 -> 2",
        f"{rf.tool_version()} on 2026-03-03: 2 -> 3",
    ]


def test_upgrade_failing_second_step_keeps_first(tmp_path):
    def boom(state):
        raise RepoFormatError("cannot")

    path = _settings(tmp_path, "x = 1\n")
    with pytest.raises(RepoFormatError):
        rf.run_upgrade(
            tmp_path, migrations={0: lambda s: ["one"], 1: boom}, target_version=2
        )
    assert tomllib.loads(path.read_text())["format_version"] == 1


def test_upgrade_keeps_created_by_and_order(tmp_path):
    path = _settings(
        tmp_path, 'created_by = "0.1"\n\n# c\nfoo = 1\n\n[s]\nbar = 2  # trailing\n'
    )
    rf.run_upgrade(tmp_path, today=date(2026, 1, 1))
    text = path.read_text()
    data = tomllib.loads(text)
    assert data["created_by"] == "0.1"
    assert list(data)[:3] == ["format_version", "created_by", "upgraded_by"]
    assert "# c\nfoo = 1\n\n[s]\nbar = 2  # trailing\n" in text


def test_upgrade_fixes_nested_tab_configuration(tmp_path, capsys):
    path = _settings(tmp_path, "format_version = 1\n" + NESTED)
    rf.run_upgrade(tmp_path)
    data = tomllib.loads(path.read_text())
    assert "tab_configuration" in data
    assert "tab_configuration" not in data["default_post_policy"]
    assert "Moved" in capsys.readouterr().out


# --- migration 0 -> 1 ------------------------------------------------------

def test_migration_renames_legacy_manifest(tmp_path):
    _settings(tmp_path, "x = 1\n")
    legacy = tmp_path / ".canvas-manifest.toml"
    with open(legacy, "wb") as f:
        tomli_w.dump({"a.md": {"canvas_id": 1}}, f)
    rf.run_upgrade(tmp_path)
    new = tmp_path / ".manifest-canvas.toml"
    assert not legacy.exists()
    data = tomllib.loads(new.read_text())
    assert data["a.md"] == {"canvas_id": 1}
    assert data["_repo_format"] == {"format_version": 1}


def test_migration_legacy_and_current_both_present(tmp_path, capsys):
    _settings(tmp_path, "x = 1\n")
    legacy = tmp_path / ".canvas-manifest.toml"
    legacy.write_text('["a.md"]\ncanvas_id = 1\n')
    _manifest(tmp_path)
    rf.run_upgrade(tmp_path)
    assert legacy.read_text() == '["a.md"]\ncanvas_id = 1\n'
    assert "unused" in capsys.readouterr().out


def test_migration_stamps_every_manifest(tmp_path):
    _settings(tmp_path, "x = 1\n")
    _manifest(tmp_path, ".manifest-canvas.toml", extra={"a.md": {"canvas_id": 1}})
    _manifest(tmp_path, ".manifest-canvas-sec-b.toml", extra={"b.md": {"canvas_id": 2}})
    rf.run_upgrade(tmp_path)
    for name, key in ((".manifest-canvas.toml", "a.md"), (".manifest-canvas-sec-b.toml", "b.md")):
        data = tomllib.loads((tmp_path / name).read_text())
        assert data["_repo_format"] == {"format_version": 1}
        assert list(k for k in data if k != "_repo_format") == [key]
