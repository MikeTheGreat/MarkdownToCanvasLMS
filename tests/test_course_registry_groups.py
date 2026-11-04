"""Registry groups: an entry that is an array of keys, paths and tables.

HOME is a temporary directory in every test, so the real registry is never read.
Canvas is never contacted: `update --check-as-new-course` is offline and `prune
--manifest-only` never calls Canvas.
"""
from __future__ import annotations

from pathlib import Path

import click
import pytest
from click.testing import CliRunner

from markdown_to_canvas import course_registry as reg
from markdown_to_canvas.cli import _for_each_course, _resolve_course, main
from tests.conftest import make_current


@pytest.fixture
def home(tmp_path, monkeypatch) -> Path:
    fake = tmp_path / "home"
    fake.mkdir()
    monkeypatch.setenv("HOME", str(fake))
    return fake


@pytest.fixture
def unrelated(tmp_path, monkeypatch) -> Path:
    work = tmp_path / "work"
    work.mkdir()
    monkeypatch.chdir(work)
    return work


def write_registry(home: Path, text: str) -> None:
    path = home / ".config" / "markdown-to-canvas" / "course_registry.toml"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def make_course(tmp_path: Path, name: str = "course", course_id: int = 111) -> Path:
    root = tmp_path / name
    (root / "pages").mkdir(parents=True)
    make_current(root)
    settings = root / "course_settings"
    for config, cid in (("canvas.toml", course_id), ("canvas-b.toml", course_id + 1)):
        (settings / config).write_text(
            f'base_url = "https://school.instructure.com"\ncourse_id = {cid}\n'
        )
    return root


def run(*args: str, input: str | None = None):
    return CliRunner().invoke(main, list(args), input=input)


def two_section_registry(home: Path, course: Path, extra: str = "") -> None:
    write_registry(
        home,
        "[courses]\n"
        f'13 = {{ path = "{course}", config = "course_settings/canvas.toml" }}\n'
        f'14 = {{ path = "{course}", config = "course_settings/canvas-b.toml" }}\n'
        '101 = ["13", "14"]\n' + extra,
    )


# ---------------------------------------------------------------------------
# Registry parsing
# ---------------------------------------------------------------------------


def test_group_of_keys_gives_members_in_order_with_their_configs(home, tmp_path):
    course = make_course(tmp_path)
    two_section_registry(home, course)
    members = reg.resolve_courses("101")
    assert [m.key for m in members] == ["13", "14"]
    assert [m.config.name for m in members] == ["canvas.toml", "canvas-b.toml"]
    assert all(m.path == course.resolve() for m in members)


def test_group_of_mixed_elements(home, tmp_path):
    a = make_course(tmp_path, "a")
    b = make_course(tmp_path, "b")
    c = make_course(tmp_path, "c")
    write_registry(
        home,
        f'[courses]\n13 = "{a}"\n'
        f'all = ["13", "{b}", {{ path = "{c}", config = "course_settings/canvas-b.toml" }}]\n',
    )
    m13, mb, mc = reg.resolve_courses("all")
    assert (m13.key, m13.path, m13.config) == ("13", a.resolve(), None)
    assert (mb.key, mb.path, mb.config) == (None, b.resolve(), None)
    assert mc.key is None and mc.config == c.resolve() / "course_settings/canvas-b.toml"


def test_tilde_path_element(home, tmp_path):
    (home / "courses" / "it142").mkdir(parents=True)
    write_registry(home, '[courses]\ng = ["~/courses/it142"]\n')
    [member] = reg.resolve_courses("g")
    assert member.path == (home / "courses" / "it142").resolve()


def test_string_element_is_not_resolved_against_the_current_directory(
    home, tmp_path, monkeypatch
):
    (tmp_path / "work" / "142").mkdir(parents=True)
    monkeypatch.chdir(tmp_path / "work")
    write_registry(home, '[courses]\ng = ["142"]\n')
    with pytest.raises(reg.RegistryError, match="neither a registered course key nor a path"):
        reg.resolve_courses("g")


@pytest.mark.parametrize(
    "entry, message",
    [
        ('["a"]', "itself a group"),  # b = ["a"] where a is a group (set below)
        ("[]", "is empty"),
        ("[7]", "not a key, a path string or a table"),
        ('[{ path = "/x", cfg = "y" }]', "unknown key 'cfg'"),
        ('[["/x"]]', "not a key, a path string or a table"),
    ],
)
def test_bad_groups_are_rejected_whole(home, tmp_path, entry, message):
    course = make_course(tmp_path)
    write_registry(
        home, f'[courses]\na = ["{course}"]\nb = {entry}\n'
    )
    with pytest.raises(reg.RegistryError, match=message):
        reg.resolve_courses("b")


def test_missing_member_directory_is_not_an_up_front_error(home, tmp_path):
    course = make_course(tmp_path)
    write_registry(home, f'[courses]\ng = ["{tmp_path}/gone", "{course}"]\n')
    members = reg.resolve_courses("g")
    assert not members[0].path.is_dir() and members[1].path.is_dir()


def test_resolve_course_refuses_a_group(home, tmp_path):
    two_section_registry(home, make_course(tmp_path))
    with pytest.raises(reg.RegistryError, match="group"):
        reg.resolve_course("101")


def test_resolve_config_refuses_a_group(home, tmp_path):
    two_section_registry(home, make_course(tmp_path))
    with pytest.raises(reg.RegistryError, match="several courses"):
        reg.resolve_config("101")


def test_is_group_and_directory_precedence(home, tmp_path, monkeypatch):
    two_section_registry(home, make_course(tmp_path))
    assert reg.is_group("101") and not reg.is_group("13") and not reg.is_group("nosuch")
    (tmp_path / "work" / "101").mkdir(parents=True)
    monkeypatch.chdir(tmp_path / "work")
    assert not reg.is_group("101")
    assert len(reg.resolve_courses("101")) == 1


def test_is_group_without_a_registry(home):
    assert reg.is_group("101") is False


# ---------------------------------------------------------------------------
# The decorator, on a fake command
# ---------------------------------------------------------------------------


def make_fake(results: dict[str, object], calls: list):
    """A command whose behavior per course key is given by `results`."""

    @click.command()
    @click.argument("course_dir", required=False)
    @click.option("--config", default=None)
    @click.option("--flag", is_flag=True)
    @_for_each_course
    def fake(course_dir, config, flag):
        repo, _ = _resolve_course(course_dir)
        calls.append((course_dir, repo, flag))
        outcome = results.get(course_dir)
        if outcome == "die":
            click.echo("boom", err=True)
            raise SystemExit(1)
        if outcome == "zero":
            raise SystemExit(0)
        if outcome == "crash":
            raise RuntimeError("unexpected")
        if outcome == "interrupt":
            raise KeyboardInterrupt()

    return fake


def invoke(cmd, *args):
    return CliRunner().invoke(cmd, list(args))


def test_decorator_runs_members_in_order_with_headings_and_summary(home, tmp_path):
    two_section_registry(home, make_course(tmp_path))
    calls: list = []
    result = invoke(make_fake({}, calls), "101", "--flag")
    assert result.exit_code == 0, result.output
    assert [c[0] for c in calls] == ["13", "14"]
    assert all(c[2] for c in calls)  # options reach every member
    lines = result.output.splitlines()
    assert lines.index("=== 101: 13 (1/2) ===") < lines.index("=== 101: 14 (2/2) ===")
    assert lines[-1] == "13: ok, 14: ok"
    assert "Course dir:" in result.output and "(course 13)" in result.output


def test_decorator_continues_after_a_failure(home, tmp_path):
    two_section_registry(home, make_course(tmp_path))
    calls: list = []
    result = invoke(make_fake({"13": "die"}, calls), "101")
    assert [c[0] for c in calls] == ["13", "14"]
    assert result.exit_code == 1
    assert result.output.splitlines()[-1] == "13: failed, 14: ok"


def test_decorator_all_failed(home, tmp_path):
    two_section_registry(home, make_course(tmp_path))
    result = invoke(make_fake({"13": "die", "14": "die"}, []), "101")
    assert result.exit_code == 1
    assert result.output.splitlines()[-1] == "13: failed, 14: failed"


def test_unexpected_exception_fails_only_that_member(home, tmp_path):
    two_section_registry(home, make_course(tmp_path))
    calls: list = []
    result = invoke(make_fake({"13": "crash"}, calls), "101")
    assert [c[0] for c in calls] == ["13", "14"]
    assert result.exit_code == 1
    assert "RuntimeError: unexpected" in result.output
    assert result.output.splitlines()[-1] == "13: failed, 14: ok"


def test_exit_zero_counts_as_ok(home, tmp_path):
    two_section_registry(home, make_course(tmp_path))
    result = invoke(make_fake({"13": "zero"}, []), "101")
    assert result.exit_code == 0
    assert result.output.splitlines()[-1] == "13: ok, 14: ok"


def test_ctrl_c_stops_the_whole_command(home, tmp_path):
    two_section_registry(home, make_course(tmp_path))
    calls: list = []
    result = invoke(make_fake({"13": "interrupt"}, calls), "101")
    assert [c[0] for c in calls] == ["13"]
    assert result.exit_code != 0


def test_missing_member_directory_fails_that_member_only(home, tmp_path):
    course = make_course(tmp_path)
    write_registry(
        home,
        f'[courses]\n14 = "{course}"\n13 = "{tmp_path}/gone"\n101 = ["13", "14"]\n',
    )
    calls: list = []
    result = invoke(make_fake({}, calls), "101")
    assert [c[0] for c in calls] == ["14"]
    assert "not a directory" in result.output
    assert result.output.splitlines()[-1] == "13: failed, 14: ok"
    assert result.exit_code == 1


def test_path_and_table_members_are_named_by_directory(home, tmp_path):
    course = make_course(tmp_path)
    write_registry(home, f'[courses]\ng = ["{course}"]\n')
    calls: list = []
    result = invoke(make_fake({}, calls), "g")
    assert f"=== g: {course} (1/1) ===" in result.output
    assert calls[0][0] == str(course)


def test_single_key_and_path_print_no_group_output(home, tmp_path):
    course = make_course(tmp_path)
    two_section_registry(home, course)
    for arg in ("13", str(course)):
        result = invoke(make_fake({}, []), arg)
        assert result.exit_code == 0, result.output
        assert "===" not in result.output and "ok" not in result.output


def test_config_with_a_group_fails_before_any_run(home, tmp_path):
    two_section_registry(home, make_course(tmp_path))
    calls: list = []
    result = invoke(make_fake({}, calls), "101", "--config", "x.toml")
    assert calls == [] and result.exit_code == 1
    assert "cannot be used" in result.output


def test_nested_group_runs_nothing(home, tmp_path):
    two_section_registry(home, make_course(tmp_path), extra='top = ["101"]\n')
    calls: list = []
    result = invoke(make_fake({}, calls), "top")
    assert calls == [] and result.exit_code == 1
    assert "itself a group" in result.output


# ---------------------------------------------------------------------------
# Through the real commands
# ---------------------------------------------------------------------------


def test_update_group_checks_each_section_with_its_own_config(home, tmp_path, unrelated):
    two_section_registry(home, make_course(tmp_path))
    result = run("update", "101", "--check-as-new-course")
    assert result.exit_code == 0, result.output
    assert "=== 101: 13 (1/2) ===" in result.output
    assert "=== 101: 14 (2/2) ===" in result.output
    assert "Course ID: 111" in result.output and "Course ID: 112" in result.output
    assert result.output.splitlines()[-1] == "13: ok, 14: ok"


def test_update_group_with_config_option_fails(home, tmp_path, unrelated):
    two_section_registry(home, make_course(tmp_path))
    result = run("update", "101", "--check-as-new-course", "-c", "13")
    assert result.exit_code == 1
    assert "cannot be used" in result.output


def test_config_option_naming_a_group_fails(home, tmp_path, unrelated):
    course = make_course(tmp_path)
    two_section_registry(home, course)
    result = run("update", str(course), "--check-as-new-course", "-c", "101")
    assert result.exit_code != 0
    assert "several courses" in result.output


def test_update_group_one_bad_member_does_not_stop_the_other(home, tmp_path, unrelated):
    course = make_course(tmp_path)
    (course / "course_settings" / "canvas-b.toml").unlink()
    two_section_registry(home, course)
    result = run("update", "101", "--check-as-new-course")
    assert result.exit_code == 1
    assert "Course ID: 111" in result.output
    assert result.output.splitlines()[-1] == "13: ok, 14: failed"


def test_publish_group_is_expanded_like_update(home, tmp_path, unrelated, monkeypatch):
    # publish goes through the same decorator as update; the site build is stubbed.
    two_section_registry(home, make_course(tmp_path))
    seen: list = []
    monkeypatch.setattr(
        "markdown_to_canvas.cli.run_publish",
        lambda course_dir, out, cfg: seen.append((course_dir, cfg.course_id)),
    )
    result = run("publish", "101", "--output-dir", str(tmp_path / "out"))
    assert result.exit_code == 0, result.output
    assert "=== 101: 13 (1/2) ===" in result.output
    assert "=== 101: 14 (2/2) ===" in result.output
    assert [cid for _, cid in seen] == [111, 112]


def test_prune_group_asks_per_course(home, tmp_path, unrelated):
    two_section_registry(home, make_course(tmp_path))
    result = run("prune", "101", "--manifest-only", input="n\nn\n")
    assert "=== 101: 13 (1/2) ===" in result.output
    assert "=== 101: 14 (2/2) ===" in result.output
    assert result.output.count("Course dir:") == 2


@pytest.mark.parametrize(
    "cmd",
    ["list-titles", "find-local-orphans", "emit-workflow", "upgrade", "fix-markdown"],
)
def test_other_commands_reach_every_member(home, tmp_path, unrelated, cmd):
    two_section_registry(home, make_course(tmp_path))
    result = run(cmd, "101")
    assert "=== 101: 13 (1/2) ===" in result.output, result.output
    assert "=== 101: 14 (2/2) ===" in result.output, result.output
    assert result.output.count("Course dir:") == 2


def test_cp_group_copies_into_every_destination(home, tmp_path, unrelated):
    src = make_course(tmp_path, "src")
    (src / "pages" / "intro.md").write_text("---\ntitle: Intro\n---\nHello\n")
    d1 = make_course(tmp_path, "d1")
    d2 = make_course(tmp_path, "d2")
    write_registry(home, f'[courses]\ng = ["{d1}", "{d2}"]\n')
    result = run("cp", str(src / "pages" / "intro.md"), "g")
    assert result.exit_code == 0, result.output
    assert (d1 / "pages" / "intro.md").is_file()
    assert (d2 / "pages" / "intro.md").is_file()


# ---------------------------------------------------------------------------
# A canvas.toml that is not valid TOML gives a one-line error, not a traceback
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("cmd", [["list-titles"], ["publish"]])
def test_invalid_canvas_toml_is_reported_without_a_traceback(
    home, tmp_path, unrelated, cmd
):
    course = make_course(tmp_path)
    (course / "course_settings" / "canvas.toml").write_text("this is = not [valid\n")
    result = run(*cmd, str(course))
    assert result.exit_code == 1
    assert "Invalid canvas.toml" in result.output
    assert "Traceback" not in result.output
