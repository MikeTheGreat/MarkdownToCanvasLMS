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
    path = _settings(tmp_path, f"format_version = {FORMAT_VERSION}\n" + NESTED)
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
    assert data["format_version"] == FORMAT_VERSION
    assert data["upgraded_by"] == [
        f"{rf.tool_version()} on 2026-09-20: 0 -> {FORMAT_VERSION}"
    ]
    assert "created_by" not in data
    assert "# keep me\ntitle = 'x'\n" in text
    assert text.startswith(f"format_version = {FORMAT_VERSION}\nupgraded_by")
    assert tomllib.loads(manifest.read_text())["_repo_format"] == {
        "format_version": FORMAT_VERSION
    }
    assert tomllib.loads(manifest.read_text())["a.md"] == {"canvas_id": 1}
    assert rf.check_repo_format(tmp_path) is None
    out = capsys.readouterr().out
    assert "Migration 0 -> 1" in out and "Migration 1 -> 2" in out


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
    assert data["format_version"] == FORMAT_VERSION
    assert len(data["upgraded_by"]) == 1
    assert data["relative_due_dates"] == {"tables": {"default": {"items": []}}}


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
    path = _settings(tmp_path, f"format_version = {FORMAT_VERSION}\nx = 1\n")
    manifest = _manifest(tmp_path)
    before = path.read_bytes()
    rf.run_upgrade(tmp_path)
    assert path.read_bytes() == before
    assert tomllib.loads(manifest.read_text())["_repo_format"] == {
        "format_version": FORMAT_VERSION
    }


def test_upgrade_appends_second_entry(tmp_path):
    v = FORMAT_VERSION
    fake = {v: lambda state: ["step"]}
    _settings(tmp_path, f"format_version = {v}\n")
    rf.run_upgrade(tmp_path, today=date(2026, 1, 1))  # already current: no entry
    rf.run_upgrade(
        tmp_path, migrations={**rf.MIGRATIONS, **fake}, target_version=v + 1,
        today=date(2026, 2, 2),
    )
    _settings_text = (tmp_path / "course_settings/course_settings.toml").read_text()
    data = tomllib.loads(_settings_text)
    assert data["format_version"] == v + 1
    assert data["upgraded_by"] == [f"{rf.tool_version()} on 2026-02-02: {v} -> {v + 1}"]
    rf.run_upgrade(
        tmp_path, migrations={**rf.MIGRATIONS, v + 1: lambda s: []}, target_version=v + 2,
        today=date(2026, 3, 3),
    )
    data = tomllib.loads((tmp_path / "course_settings/course_settings.toml").read_text())
    assert data["format_version"] == v + 2
    assert data["upgraded_by"] == [
        f"{rf.tool_version()} on 2026-02-02: {v} -> {v + 1}",
        f"{rf.tool_version()} on 2026-03-03: {v + 1} -> {v + 2}",
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
    assert data["_repo_format"] == {"format_version": FORMAT_VERSION}


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
        assert data["_repo_format"] == {"format_version": FORMAT_VERSION}
        assert list(k for k in data if k != "_repo_format") == [key]


# --- migration 1 -> 2 ------------------------------------------------------

def _v1_repo(tmp_path, body):
    return _settings(tmp_path, "format_version = 1\n" + body)


def test_migration_1_to_2_adds_empty_default_table(tmp_path):
    body = '# c\ntitle = "x"\ndue_dates = [\n  { name = "A", due_at = "NONE" },\n]\n\n[late_policy]\nz = 1  # t\n'
    path = _v1_repo(tmp_path, body)
    manifest = _manifest(tmp_path, version=1, extra={"a.md": {"canvas_id": 1}})
    rf.run_upgrade(tmp_path, today=date(2026, 9, 20), target_version=2)  # this step only
    text = path.read_text()
    data = tomllib.loads(text)
    assert data["format_version"] == 2
    assert data["relative_due_dates"] == {"tables": {"default": {"items": []}}}
    assert body in text  # everything already there is untouched
    assert text.index("[relative_due_dates") > text.index("[late_policy]")
    assert data["upgraded_by"] == [f"{rf.tool_version()} on 2026-09-20: 1 -> 2"]
    assert tomllib.loads(manifest.read_text())["_repo_format"] == {"format_version": 2}
    rf.run_upgrade(tmp_path)  # the rest of the way to the current version
    assert rf.check_repo_format(tmp_path) is None


def test_migration_1_to_2_leaves_existing_section(tmp_path, capsys):
    body = '[relative_due_dates]\ndays_of_week = ["Mon"]\n'
    path = _v1_repo(tmp_path, body)
    rf.run_upgrade(tmp_path, target_version=2)  # this step only
    data = tomllib.loads(path.read_text())
    assert data["relative_due_dates"] == {"days_of_week": ["Mon"]}
    assert data["format_version"] == 2
    assert "already present" in capsys.readouterr().out


def test_migration_1_to_2_noop_writes_nothing(tmp_path):
    path = _v1_repo(tmp_path, "x = 1\n")
    before = path.read_bytes()
    rf.run_upgrade(tmp_path, noop=True)
    assert path.read_bytes() == before


def test_current_repo_is_not_given_the_section(tmp_path, capsys):
    path = _settings(tmp_path, f"format_version = {FORMAT_VERSION}\nx = 1\n")
    before = path.read_bytes()
    rf.run_upgrade(tmp_path)
    assert path.read_bytes() == before
    assert "already current" in capsys.readouterr().out


def test_manifest_lagging_does_not_add_section_to_current_settings(tmp_path):
    path = _settings(tmp_path, f"format_version = {FORMAT_VERSION}\n" + NESTED)
    _manifest(tmp_path, version=1)
    rf.run_upgrade(tmp_path)  # the tab_configuration fix rewrites the file
    assert "relative_due_dates" not in tomllib.loads(path.read_text())


# --- migration 2 -> 3 ------------------------------------------------------
#
# The term file no longer names a table, and the table `generate-due-dates` uses
# is `default` unless --table says otherwise. The migration renames a lone table,
# drops the empty `default` that migration 1 -> 2 leaves beside a used table, and
# removes `relative_table` from the in-repo term file.

TOP = '# my course\nformat_version = 2\ntitle = "x"  # keep\ndue_dates = [\n  { name = "A", due_at = "NONE" },\n]\n\n'
LATE = '[late_policy]\nz = 1  # t\n\n'
QUARTER = (
    "# the schedule\n"
    "[relative_due_dates.tables.quarter11]\n"
    'days_of_week = ["Mon", "Wed"]  # class days\n'
    "\n"
    "[[relative_due_dates.tables.quarter11.items]]\n"
    'name = "Week 1"\n'
    'relative_to = { type = "START_OF_QUARTER" }\n'
    'offsets = ["+1 CLASS_DAY"]\n'
)
EMPTY_DEFAULT = "[relative_due_dates.tables.default]\nitems = []\n\n"
TERM = 'first_day = 2026-09-30\n# a comment\nrelative_table = "quarter11"\ntime_zone = "America/Los_Angeles"\n'


def _v2_repo(tmp_path, body, term=None):
    path = _settings(tmp_path, TOP + LATE + body)
    if term is not None:
        (tmp_path / "course_settings" / "term_dates.toml").write_text(term)
    return path


def _tables(path):
    return tomllib.loads(path.read_text())["relative_due_dates"]["tables"]


def test_migration_2_to_3_renames_a_lone_table(tmp_path, capsys):
    path = _v2_repo(tmp_path, QUARTER)
    rf.run_upgrade(tmp_path)
    text = path.read_text()
    assert list(_tables(path)) == ["default"]
    assert _tables(path)["default"]["items"][0]["name"] == "Week 1"
    assert "[relative_due_dates.tables.default]" in text
    assert "[[relative_due_dates.tables.default.items]]" in text
    assert "quarter11" not in text
    assert "# the schedule" in text and "# class days" in text
    out = capsys.readouterr().out
    assert "Rename [relative_due_dates.tables.quarter11] -> [relative_due_dates.tables.default]" in out


def test_migration_2_to_3_drops_the_empty_default_beside_a_used_table(tmp_path, capsys):
    path = _v2_repo(tmp_path, EMPTY_DEFAULT + QUARTER)
    rf.run_upgrade(tmp_path)
    text = path.read_text()
    assert list(_tables(path)) == ["default"]
    assert _tables(path)["default"]["items"][0]["name"] == "Week 1"
    assert text.count("[relative_due_dates.tables.default]") == 1
    assert "items = []" not in text
    out = capsys.readouterr().out
    assert "Remove the empty [relative_due_dates.tables.default] table" in out
    assert "Rename [relative_due_dates.tables.quarter11]" in out


def test_migration_2_to_3_drops_an_empty_default_that_comes_last(tmp_path):
    path = _v2_repo(tmp_path, QUARTER + "\n" + EMPTY_DEFAULT.rstrip("\n") + "\n")
    rf.run_upgrade(tmp_path)
    assert list(_tables(path)) == ["default"]
    assert _tables(path)["default"]["items"][0]["name"] == "Week 1"


def test_migration_2_to_3_keeps_everything_else_byte_for_byte(tmp_path):
    path = _v2_repo(tmp_path, EMPTY_DEFAULT + QUARTER)
    rf.run_upgrade(tmp_path, target_version=3)
    text = path.read_text()
    head = "format_version = 3\n"
    # upgraded_by is added after format_version by every upgrade; strip that line.
    lines = [ln for ln in text.splitlines(keepends=True) if not ln.startswith("upgraded_by")]
    expected = (TOP + LATE + QUARTER).replace("format_version = 2\n", head).replace(
        "quarter11", "default"
    )
    assert "".join(lines) == expected


def test_migration_2_to_3_handles_inline_items(tmp_path):
    body = (
        "[relative_due_dates.tables.quarter11]\n"
        'items = [ { name = "Week 1", relative_to = { type = "START_OF_QUARTER" }, offsets = ["+1 CLASS_DAY"] } ]\n'
    )
    path = _v2_repo(tmp_path, body)
    rf.run_upgrade(tmp_path)
    assert list(_tables(path)) == ["default"]
    assert _tables(path)["default"]["items"][0]["name"] == "Week 1"


def test_migration_2_to_3_leaves_several_real_tables_and_says_so(tmp_path, capsys):
    body = QUARTER + "\n" + QUARTER.replace("quarter11", "summer8")
    path = _v2_repo(tmp_path, body)
    rf.run_upgrade(tmp_path)
    assert sorted(_tables(path)) == ["quarter11", "summer8"]
    assert "--table NAME" in capsys.readouterr().out


def test_migration_2_to_3_default_plus_two_used_tables_says_so(tmp_path, capsys):
    body = EMPTY_DEFAULT + QUARTER + "\n" + QUARTER.replace("quarter11", "summer8")
    path = _v2_repo(tmp_path, body)
    rf.run_upgrade(tmp_path)
    assert sorted(_tables(path)) == ["default", "quarter11", "summer8"]
    assert "--table NAME" in capsys.readouterr().out


def test_migration_2_to_3_only_default_needs_nothing(tmp_path, capsys):
    path = _v2_repo(tmp_path, EMPTY_DEFAULT.rstrip("\n") + "\n")
    rf.run_upgrade(tmp_path)
    assert _tables(path) == {"default": {"items": []}}
    out = capsys.readouterr().out
    assert "NOTICE" not in out and "Rename" not in out


def test_migration_2_to_3_gives_up_on_a_layout_it_cannot_rewrite(tmp_path, capsys):
    # Dotted keys instead of a table header: the header rewrite cannot reach it.
    body = 'relative_due_dates.tables.quarter11.days_of_week = ["Mon"]\n'
    path = _settings(tmp_path, "format_version = 2\n" + body)
    rf.run_upgrade(tmp_path)
    assert list(_tables(path)) == ["quarter11"]
    out = capsys.readouterr().out
    assert "could not rename" in out and "--table quarter11" in out


def test_migration_2_to_3_removes_relative_table_from_the_in_repo_term_file(tmp_path, capsys):
    _v2_repo(tmp_path, QUARTER, term=TERM)
    rf.run_upgrade(tmp_path)
    term = (tmp_path / "course_settings" / "term_dates.toml").read_text()
    assert term == TERM.replace('relative_table = "quarter11"\n', "")
    assert "Remove relative_table from course_settings/term_dates.toml" in capsys.readouterr().out


def test_migration_2_to_3_leaves_a_commented_relative_table_alone(tmp_path):
    term = 'first_day = 2026-09-30\n# relative_table = "default"\n'
    _v2_repo(tmp_path, QUARTER, term=term)
    term_path = tmp_path / "course_settings" / "term_dates.toml"
    before = term_path.read_bytes()
    rf.run_upgrade(tmp_path)
    assert term_path.read_bytes() == before


def test_migration_2_to_3_does_not_create_a_term_file(tmp_path):
    _v2_repo(tmp_path, QUARTER)
    rf.run_upgrade(tmp_path)
    assert not (tmp_path / "course_settings" / "term_dates.toml").exists()


def test_migration_2_to_3_noop_writes_neither_file(tmp_path, capsys):
    path = _v2_repo(tmp_path, EMPTY_DEFAULT + QUARTER, term=TERM)
    term_path = tmp_path / "course_settings" / "term_dates.toml"
    manifest = _manifest(tmp_path, version=2, extra={"a.md": {"canvas_id": 1}})
    before = (path.read_bytes(), term_path.read_bytes(), manifest.read_bytes())
    rf.run_upgrade(tmp_path, noop=True)
    assert (path.read_bytes(), term_path.read_bytes(), manifest.read_bytes()) == before
    out = capsys.readouterr().out
    assert "Rename [relative_due_dates.tables.quarter11]" in out
    assert "Remove relative_table from" in out


def test_migration_2_to_3_stamps_manifests_and_the_version(tmp_path):
    path = _v2_repo(tmp_path, QUARTER)
    manifest = _manifest(tmp_path, version=2, extra={"a.md": {"canvas_id": 1}})
    rf.run_upgrade(tmp_path, target_version=3, today=date(2026, 9, 20))
    data = tomllib.loads(path.read_text())
    assert data["format_version"] == 3
    assert data["upgraded_by"] == [f"{rf.tool_version()} on 2026-09-20: 2 -> 3"]
    assert tomllib.loads(manifest.read_text())["_repo_format"] == {"format_version": 3}


def test_migration_2_to_3_skips_a_settings_file_already_at_3(tmp_path):
    # A current settings file with a manifest that lags: only the manifest is stamped.
    path = _settings(tmp_path, "format_version = 3\n" + QUARTER)
    manifest = _manifest(tmp_path, version=2, extra={"a.md": {"canvas_id": 1}})
    before = path.read_bytes()
    rf.run_upgrade(tmp_path, target_version=3)
    assert path.read_bytes() == before
    assert tomllib.loads(manifest.read_text())["_repo_format"] == {"format_version": 3}


def test_migration_1_through_3_in_one_run_collapses_the_two_tables(tmp_path):
    # A v1 repo gets an empty `default` from 1 -> 2 only when it has no section;
    # one that already has a lone named table just has it renamed.
    path = _settings(tmp_path, "format_version = 1\n" + QUARTER)
    rf.run_upgrade(tmp_path, target_version=3)
    assert list(_tables(path)) == ["default"]
    assert tomllib.loads(path.read_text())["format_version"] == 3


@pytest.mark.parametrize(
    "table",
    [
        QUARTER,
        "[relative_due_dates.tables.quarter11]\n"
        "# inline layout\n"
        'items = [ { name = "Week 1", relative_to = { type = "START_OF_QUARTER" }, offsets = ["+1 CLASS_DAY"] } ]\n',
    ],
    ids=["array-of-tables items", "inline items"],
)
def test_migration_2_to_3_lone_table_rename_changes_only_the_names(tmp_path, table):
    path = _v2_repo(tmp_path, table)
    rf.run_upgrade(tmp_path, target_version=3)
    lines = [ln for ln in path.read_text().splitlines(keepends=True) if not ln.startswith("upgraded_by")]
    expected = (TOP + LATE + table).replace("format_version = 2\n", "format_version = 3\n")
    assert "".join(lines) == expected.replace("quarter11", "default")


# --- pending_writes --------------------------------------------------------


def _write_file_step(state):
    state.pending_writes[state.repo / "notes.md"] = "new\n"
    return ["write notes.md"]


def test_pending_writes_are_written(tmp_path):
    _settings(tmp_path, "x = 1\n")
    (tmp_path / "notes.md").write_text("old\n")
    rf.run_upgrade(tmp_path, migrations={0: _write_file_step}, target_version=1)
    assert (tmp_path / "notes.md").read_text() == "new\n"


def test_pending_writes_skipped_with_noop(tmp_path, capsys):
    _settings(tmp_path, "x = 1\n")
    (tmp_path / "notes.md").write_text("old\n")
    rf.run_upgrade(tmp_path, migrations={0: _write_file_step}, target_version=1, noop=True)
    assert (tmp_path / "notes.md").read_text() == "old\n"
    assert "write notes.md" in capsys.readouterr().out


# --- migration 3 -> 4: snippet links become snippet-relative ---------------


def _v3_repo(tmp_path, files):
    _settings(tmp_path, "format_version = 3\n")
    for rel, text in files.items():
        path = tmp_path / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text)
    return tmp_path


def _snippet(tmp_path, rel="snippets/policy.md"):
    return (tmp_path / rel).read_text()


def test_migration_3_to_4_rewrites_link_written_for_deeper_includers(tmp_path, capsys):
    _v3_repo(tmp_path, {
        "snippets/policy.md": "Intro.\n\n![](../../assets/logo.png)\n\nEnd.\n",
        "pages/week1/a.md": "[x](../../snippets/policy.md)\n",
        "pages/week2/b.md": "---\ntitle: B\n---\n\n[x](../../snippets/policy.md)\n",
        "assets/logo.png": "x",
    })
    manifest = _manifest(tmp_path, version=3, extra={"a.md": {"canvas_id": 1}})
    rf.run_upgrade(tmp_path)
    assert _snippet(tmp_path) == "Intro.\n\n![](../assets/logo.png)\n\nEnd.\n"
    assert tomllib.loads(
        (tmp_path / "course_settings/course_settings.toml").read_text()
    )["format_version"] == 4
    assert tomllib.loads(manifest.read_text())["_repo_format"] == {"format_version": 4}
    out = capsys.readouterr().out
    assert "Migration 3 -> 4" in out
    assert "Rewrite link in snippets/policy.md: ../../assets/logo.png -> ../assets/logo.png" in out


def test_migration_3_to_4_leaves_same_depth_snippet_alone(tmp_path, capsys):
    text = "[s](../pages/syllabus.md) ![](../assets/a.png)\n"
    _v3_repo(tmp_path, {
        "snippets/policy.md": text,
        "pages/a.md": "[x](../snippets/policy.md)\n",
        "assignments/hw.md": "[x](../snippets/policy.md)\n",
        "pages/syllabus.md": "s",
        "assets/a.png": "x",
    })
    rf.run_upgrade(tmp_path)
    assert _snippet(tmp_path) == text
    assert "snippets/policy.md" not in capsys.readouterr().out


def test_migration_3_to_4_snippet_reading_already_works(tmp_path, capsys):
    """Rule 3: the snippet target exists and no includer names another file."""
    text = "![](../assets/x.png)\n"
    _v3_repo(tmp_path, {
        "snippets/policy.md": text,
        "pages/a.md": "[x](../snippets/policy.md)\n",
        "pages/unit1/b.md": "[x](../../snippets/policy.md)\n",
        "assets/x.png": "x",
    })
    rf.run_upgrade(tmp_path)
    assert _snippet(tmp_path) == text
    assert "NOTICE" not in capsys.readouterr().out


def test_migration_3_to_4_includers_resolve_to_different_files(tmp_path, capsys):
    text = "![](img/x.png)\n"
    _v3_repo(tmp_path, {
        "snippets/policy.md": text,
        "pages/a.md": "[x](../snippets/policy.md)\n",
        "pages/unit1/b.md": "[x](../../snippets/policy.md)\n",
        "pages/img/x.png": "x",
        "pages/unit1/img/x.png": "x",
    })
    rf.run_upgrade(tmp_path)
    assert _snippet(tmp_path) == text
    out = capsys.readouterr().out
    assert "NOTICE: snippets/policy.md: link img/x.png left unchanged" in out
    assert "pages/a.md -> pages/img/x.png" in out
    assert "pages/unit1/b.md -> pages/unit1/img/x.png" in out


def test_migration_3_to_4_includer_reading_wins(tmp_path):
    _v3_repo(tmp_path, {
        "snippets/policy.md": "![](../assets/x.png)\n",
        "pages/unit1/a.md": "[x](../../snippets/policy.md)\n",
        "assets/x.png": "x",
        "pages/assets/x.png": "x",
    })
    rf.run_upgrade(tmp_path)
    assert _snippet(tmp_path) == "![](../pages/assets/x.png)\n"


def test_migration_3_to_4_nothing_resolves(tmp_path, capsys):
    text = "![](../../gone.png)\n"
    _v3_repo(tmp_path, {
        "snippets/policy.md": text,
        "pages/a.md": "[x](../snippets/policy.md)\n",
    })
    rf.run_upgrade(tmp_path)
    assert _snippet(tmp_path) == text
    out = capsys.readouterr().out
    assert "NOTICE: snippets/policy.md: link ../../gone.png left unchanged" in out
    assert "pages/a.md -> (nothing)" in out


def test_migration_3_to_4_unused_snippet_with_broken_link(tmp_path, capsys):
    text = "![](../assets/gone.png) ![](../assets/here.png)\n"
    _v3_repo(tmp_path, {"snippets/old.md": text, "assets/here.png": "x"})
    rf.run_upgrade(tmp_path)
    assert _snippet(tmp_path, "snippets/old.md") == text
    out = capsys.readouterr().out
    assert "NOTICE: snippets/old.md (included by no file): link ../assets/gone.png" in out
    assert "here.png" not in out


def test_migration_3_to_4_ignored_includer_counts(tmp_path, capsys):
    text = "![](img/x.png)\n"
    _v3_repo(tmp_path, {
        ".canvasignore": "pages/drafts/\n",
        "snippets/policy.md": text,
        "pages/a.md": "[x](../snippets/policy.md)\n",
        "pages/drafts/d.md": "[x](../../snippets/policy.md)\n",
        "pages/img/x.png": "x",
        "pages/drafts/img/x.png": "x",
    })
    rf.run_upgrade(tmp_path)
    assert _snippet(tmp_path) == text
    assert "pages/drafts/d.md -> pages/drafts/img/x.png" in capsys.readouterr().out


def test_migration_3_to_4_hidden_folders_frontmatter_and_inline_refs_do_not_count(tmp_path):
    """Only block includes outside hidden folders count; a snippet referenced in
    any other way is treated as included by no file."""
    text = "![](../../assets/x.png)\n"
    _v3_repo(tmp_path, {
        "snippets/policy.md": text,
        ".hidden/deep/a.md": "[x](../../snippets/policy.md)\n",
        "pages/week1/b.md": "[PASTE_SNIPPET_INTO_FRONTMATTER](../../snippets/policy.md)\n"
                            "$../../snippets/policy.md$\n"
                            "```\n[x](../../snippets/policy.md)\n```\n",
        "assets/x.png": "x",
    })
    rf.run_upgrade(tmp_path)
    assert _snippet(tmp_path) == text


def test_migration_3_to_4_keeps_other_bytes_and_skips_fences_and_absolute_urls(tmp_path):
    text = (
        "# Heading\n\n"
        '<img src="../../assets/x.png" alt="A">  [site](https://example.edu/x)\n'
        "[faq](<../../pages/My FAQ.md#late> \"FAQ\") [t](#top)\n\n"
        "```\n![](../../assets/x.png)\n```\n"
        "[enc](../../assets/My%20File.pdf)\n"
    )
    _v3_repo(tmp_path, {
        "snippets/policy.md": text,
        "pages/week1/a.md": "[x](../../snippets/policy.md)\n",
        "assets/x.png": "x",
        "assets/My File.pdf": "x",
        "pages/My FAQ.md": "faq",
    })
    rf.run_upgrade(tmp_path)
    assert _snippet(tmp_path) == (
        "# Heading\n\n"
        '<img src="../assets/x.png" alt="A">  [site](https://example.edu/x)\n'
        "[faq](<../pages/My FAQ.md#late> \"FAQ\") [t](#top)\n\n"
        "```\n![](../../assets/x.png)\n```\n"
        "[enc](../assets/My%20File.pdf)\n"
    )


def test_migration_3_to_4_noop_writes_nothing(tmp_path, capsys):
    _v3_repo(tmp_path, {
        "snippets/policy.md": "![](../../assets/logo.png)\n",
        "pages/week1/a.md": "[x](../../snippets/policy.md)\n",
        "assets/logo.png": "x",
    })
    before = _snippet(tmp_path)
    rf.run_upgrade(tmp_path, noop=True)
    assert _snippet(tmp_path) == before
    assert "Rewrite link in snippets/policy.md" in capsys.readouterr().out


def test_migration_3_to_4_skips_settings_already_at_4(tmp_path):
    """A manifest lagging a current settings file: only the manifest is stamped."""
    _settings(tmp_path, "format_version = 4\n")
    (tmp_path / "snippets").mkdir()
    (tmp_path / "snippets/policy.md").write_text("![](../../assets/logo.png)\n")
    (tmp_path / "pages/week1").mkdir(parents=True)
    (tmp_path / "pages/week1/a.md").write_text("[x](../../snippets/policy.md)\n")
    (tmp_path / "assets").mkdir()
    (tmp_path / "assets/logo.png").write_text("x")
    manifest = _manifest(tmp_path, version=3)
    rf.run_upgrade(tmp_path)
    assert _snippet(tmp_path) == "![](../../assets/logo.png)\n"
    assert tomllib.loads(manifest.read_text())["_repo_format"] == {"format_version": 4}


def test_migration_3_to_4_working_includers_win_over_broken_ones(tmp_path, capsys):
    """One includer found the file, another found nothing (already broken):
    rewrite to the working reading, which fixes the broken includer too."""
    _v3_repo(tmp_path, {
        "snippets/block/front.md": "[oh](../instructor_info/office-hours.md)\n",
        "pages/landing.md": "[x](../snippets/block/front.md)\n",
        "pages/week-1/home.md": "[x](../../snippets/block/front.md)\n",
        "pages/instructor_info/office-hours.md": "oh",
    })
    rf.run_upgrade(tmp_path)
    assert _snippet(tmp_path, "snippets/block/front.md") == (
        "[oh](../../pages/instructor_info/office-hours.md)\n"
    )
    assert "NOTICE" not in capsys.readouterr().out


def test_migration_3_to_4_converts_refs_to_other_snippets(tmp_path):
    """Nested block and inline refs were never expanded before format 4; they
    were written for the includers and now resolve from the snippet."""
    _v3_repo(tmp_path, {
        "snippets/block/weekly/front.md": (
            "Hi [NAME](../../snippets/inline/name.md)! "
            "[Syllabus]($../../snippets/inline/C.md$/syllabus)\n"
        ),
        "snippets/inline/name.md": "Mike",  # block include pastes it verbatim
        "snippets/inline/C.md": "https://x.edu/courses/1\n",
        "pages/week-1/home.md": "[x](../../snippets/block/weekly/front.md)\n",
        "pages/landing.md": "[x](../snippets/block/weekly/front.md)\n",
    })
    rf.run_upgrade(tmp_path)
    migrated = _snippet(tmp_path, "snippets/block/weekly/front.md")
    assert migrated == (
        "Hi [NAME](../../inline/name.md)! "
        "[Syllabus]($../../inline/C.md$/syllabus)\n"
    )
    from markdown_to_canvas.convert import preprocess_snippets
    for includer in ("pages/week-1/home.md", "pages/landing.md"):
        path = tmp_path / includer
        assert preprocess_snippets(
            path.read_text(), path, tmp_path / "snippets"
        ).strip() == "Hi Mike! [Syllabus](https://x.edu/courses/1/syllabus)"
