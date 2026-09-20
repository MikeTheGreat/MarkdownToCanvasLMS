"""The per-user course registry, term names, .env fallback and completion helpers.

Every test points HOME at a temporary directory, so the real
~/.config/markdown-to-canvas is never read or written.
"""
from pathlib import Path

import pytest

from markdown_to_canvas import course_registry as reg


@pytest.fixture
def home(tmp_path, monkeypatch) -> Path:
    fake = tmp_path / "home"
    fake.mkdir()
    monkeypatch.setenv("HOME", str(fake))
    return fake


def write_registry(home: Path, text: str) -> Path:
    path = home / ".config" / "markdown-to-canvas" / "course_registry.toml"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    return path


def make_course(tmp_path: Path, name: str = "it143") -> Path:
    course = tmp_path / name
    (course / "course_settings").mkdir(parents=True)
    (course / "course_settings" / "course_settings.toml").write_text("")
    return course


# ---------------------------------------------------------------------------
# Reading entries
# ---------------------------------------------------------------------------


def test_string_entry_resolves_from_another_directory(home, tmp_path, monkeypatch):
    course = make_course(tmp_path)
    write_registry(home, f'[courses]\n142 = "{course}"\n')
    elsewhere = tmp_path / "elsewhere"
    elsewhere.mkdir()
    monkeypatch.chdir(elsewhere)
    got = reg.resolve_course("142")
    assert got.path == course.resolve()
    assert got.key == "142"
    assert got.config is None


def test_entry_with_config_joins_it_to_the_course_dir(home, tmp_path):
    course = make_course(tmp_path)
    write_registry(
        home,
        f'[courses]\n142a = {{ path = "{course}", config = "course_settings/canvas-sec-a.toml" }}\n',
    )
    got = reg.resolve_course("142a")
    assert got.path == course.resolve()
    assert got.config == course.resolve() / "course_settings" / "canvas-sec-a.toml"


def test_tilde_in_path_is_expanded(home, tmp_path):
    (home / "courses" / "x").mkdir(parents=True)
    write_registry(home, '[courses]\nx = "~/courses/x"\n')
    assert reg.resolve_course("x").path == (home / "courses" / "x").resolve()


def test_unknown_entry_key_names_key_entry_and_allowed_keys(home, tmp_path):
    write_registry(home, f'[courses]\nbad = {{ path = "{tmp_path}", cfg = "y" }}\n')
    with pytest.raises(reg.RegistryError) as e:
        reg.resolve_course("bad")
    msg = str(e.value)
    assert "cfg" in msg and "'bad'" in msg and "path, config" in msg


def test_relative_registered_path_is_an_error(home):
    write_registry(home, '[courses]\nrel = "courses/it143"\n')
    with pytest.raises(reg.RegistryError, match="absolute or start with ~"):
        reg.resolve_course("rel")


def test_non_string_config_is_an_error(home, tmp_path):
    write_registry(home, f'[courses]\nbad = {{ path = "{tmp_path}", config = 3 }}\n')
    with pytest.raises(reg.RegistryError, match="config must be a string"):
        reg.resolve_course("bad")


def test_a_bad_entry_does_not_break_another_key(home, tmp_path):
    good = make_course(tmp_path)
    write_registry(home, f'[courses]\nbad = {{ nope = 1 }}\ngood = "{good}"\n')
    assert reg.resolve_course("good").path == good.resolve()


# ---------------------------------------------------------------------------
# Path first, then key
# ---------------------------------------------------------------------------


def test_a_directory_named_like_a_key_wins(home, tmp_path, monkeypatch):
    registered = make_course(tmp_path, "registered")
    write_registry(home, f'[courses]\n142 = "{registered}"\n')
    work = tmp_path / "work"
    (work / "142").mkdir(parents=True)
    monkeypatch.chdir(work)
    got = reg.resolve_course("142")
    assert got.path == (work / "142").resolve()
    assert got.key is None


def test_key_used_when_no_such_directory(home, tmp_path, monkeypatch):
    registered = make_course(tmp_path, "registered")
    write_registry(home, f'[courses]\n142 = "{registered}"\n')
    work = tmp_path / "work"
    work.mkdir()
    monkeypatch.chdir(work)
    assert reg.resolve_course("142").path == registered.resolve()


def test_unknown_course_lists_registered_keys(home, tmp_path, monkeypatch):
    write_registry(home, f'[courses]\n142 = "{tmp_path}"\n143 = "{tmp_path}"\n')
    monkeypatch.chdir(tmp_path)
    with pytest.raises(reg.RegistryError) as e:
        reg.resolve_course("999")
    msg = str(e.value)
    assert "'999'" in msg and "142, 143" in msg


def test_unknown_course_with_no_registry_file(home, tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    with pytest.raises(reg.RegistryError, match="no course registry"):
        reg.resolve_course("142")


def test_registered_directory_missing_names_key_and_path(home, tmp_path):
    gone = tmp_path / "gone"
    write_registry(home, f'[courses]\n142 = "{gone}"\n')
    with pytest.raises(reg.RegistryError) as e:
        reg.resolve_course("142")
    assert "'142'" in str(e.value) and str(gone) in str(e.value)


def test_broken_registry_does_not_affect_a_path_argument(home, tmp_path):
    course = make_course(tmp_path)
    write_registry(home, "this is [not toml")
    assert reg.resolve_course(str(course)).path == course.resolve()


def test_broken_registry_is_reported_when_a_key_is_needed(home, tmp_path, monkeypatch):
    write_registry(home, "this is [not toml")
    monkeypatch.chdir(tmp_path)
    with pytest.raises(reg.RegistryError, match="not valid TOML"):
        reg.resolve_course("142")


# ---------------------------------------------------------------------------
# Terms
# ---------------------------------------------------------------------------


def make_term(home: Path, name: str) -> Path:
    path = home / ".config" / "markdown-to-canvas" / "terms" / f"{name}.toml"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("first_day = 2026-09-30\n")
    return path


def test_term_by_name(home, tmp_path, monkeypatch):
    term = make_term(home, "2026Fall")
    monkeypatch.chdir(tmp_path)
    assert reg.resolve_term("2026Fall") == term


def test_term_path_wins_over_a_name(home, tmp_path, monkeypatch):
    make_term(home, "2026Fall")
    monkeypatch.chdir(tmp_path)
    (tmp_path / "2026Fall").write_text("x")
    assert reg.resolve_term("2026Fall") == Path("2026Fall")


def test_unknown_term_lists_the_terms_found(home, tmp_path, monkeypatch):
    make_term(home, "2026Fall")
    make_term(home, "2027Winter")
    monkeypatch.chdir(tmp_path)
    with pytest.raises(reg.RegistryError) as e:
        reg.resolve_term("2027Spring")
    assert "2026Fall, 2027Winter" in str(e.value)
    assert "2027Spring.toml" in str(e.value)


def test_toml_suffix_is_not_looked_up_as_a_name(home, tmp_path, monkeypatch):
    make_term(home, "2026Fall")
    monkeypatch.chdir(tmp_path)
    with pytest.raises(reg.RegistryError):
        reg.resolve_term("2026Fall.toml")


# ---------------------------------------------------------------------------
# add_entry
# ---------------------------------------------------------------------------


def test_add_entry_creates_the_file_and_directory(home, tmp_path):
    course = make_course(tmp_path)
    path = reg.add_entry("143", course)
    assert path == home / ".config" / "markdown-to-canvas" / "course_registry.toml"
    assert reg.resolve_course("143").path == course.resolve()
    assert '143 = "' in path.read_text()


def test_add_entry_refuses_an_existing_key_and_leaves_the_file(home, tmp_path):
    course = make_course(tmp_path)
    path = write_registry(home, f'[courses]\n143 = "{course}"\n')
    before = path.read_text()
    with pytest.raises(reg.RegistryError, match="already registered"):
        reg.add_entry("143", make_course(tmp_path, "other"))
    assert path.read_text() == before


def test_add_entry_keeps_comments_and_other_entries(home, tmp_path):
    first = make_course(tmp_path, "first")
    second = make_course(tmp_path, "second")
    path = write_registry(
        home, f'# my courses\n[courses]\n# the big one\n142 = "{first}"\n'
    )
    reg.add_entry("143", second)
    text = path.read_text()
    assert "# my courses" in text and "# the big one" in text
    assert f'142 = "{first}"' in text
    assert reg.resolve_course("143").path == second.resolve()


def test_add_entry_rejects_an_empty_key(home, tmp_path):
    with pytest.raises(reg.RegistryError, match="non-empty"):
        reg.add_entry("  ", tmp_path)


# ---------------------------------------------------------------------------
# Token fallback
# ---------------------------------------------------------------------------

VAR = "MTC_TEST_TOKEN"


def _clean_var(monkeypatch):
    # setenv then delenv, so monkeypatch removes whatever load_dotenv adds.
    monkeypatch.setenv(VAR, "seed")
    monkeypatch.delenv(VAR)


def _write_env(directory: Path, value: str) -> None:
    directory.mkdir(parents=True, exist_ok=True)
    (directory / ".env").write_text(f"{VAR}={value}\n")


def test_token_comes_from_the_fallback(home, tmp_path, monkeypatch):
    _clean_var(monkeypatch)
    _write_env(home / ".config" / "markdown-to-canvas", "fallback")
    elsewhere = tmp_path / "elsewhere"
    elsewhere.mkdir()
    monkeypatch.chdir(elsewhere)
    reg.load_env_files()
    import os
    assert os.environ[VAR] == "fallback"


def test_shell_beats_the_fallback(home, tmp_path, monkeypatch):
    _write_env(home / ".config" / "markdown-to-canvas", "fallback")
    monkeypatch.setenv(VAR, "shell")
    monkeypatch.chdir(tmp_path)
    reg.load_env_files()
    import os
    assert os.environ[VAR] == "shell"


def test_local_env_beats_shell_and_fallback(home, tmp_path, monkeypatch):
    _write_env(home / ".config" / "markdown-to-canvas", "fallback")
    monkeypatch.setenv(VAR, "shell")
    work = tmp_path / "work"
    _write_env(work, "local")
    monkeypatch.chdir(work)
    reg.load_env_files()
    import os
    assert os.environ[VAR] == "local"


def test_missing_fallback_is_not_an_error(home, tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    reg.load_env_files()


# ---------------------------------------------------------------------------
# Completion
# ---------------------------------------------------------------------------


def values(items):
    return [(i.value, i.type) for i in items]


def test_course_completion_offers_keys_and_directories(home, tmp_path):
    write_registry(home, f'[courses]\n142 = "{tmp_path}"\n143 = "{tmp_path}"\n')
    got = values(reg.complete_course(None, None, ""))
    assert ("142", "plain") in got and ("143", "plain") in got
    assert ("", "dir") in got


def test_course_completion_filters_by_prefix(home, tmp_path):
    write_registry(home, f'[courses]\n142 = "{tmp_path}"\n201 = "{tmp_path}"\n')
    got = [v for v, t in values(reg.complete_course(None, None, "14")) if t == "plain"]
    assert got == ["142"]


def test_a_key_added_later_is_offered_without_reinstalling(home, tmp_path):
    write_registry(home, f'[courses]\n142 = "{tmp_path}"\n')
    assert "144" not in [v for v, _ in values(reg.complete_course(None, None, ""))]
    write_registry(home, f'[courses]\n142 = "{tmp_path}"\n144 = "{tmp_path}"\n')
    assert "144" in [v for v, _ in values(reg.complete_course(None, None, ""))]


def test_completion_survives_a_broken_or_missing_registry(home):
    assert values(reg.complete_course(None, None, "")) == [("", "dir")]
    write_registry(home, "not [toml")
    assert values(reg.complete_course(None, None, "")) == [("", "dir")]


def test_term_completion_offers_names_and_files(home):
    make_term(home, "2026Fall")
    got = values(reg.complete_term(None, None, "20"))
    assert ("2026Fall", "plain") in got and ("20", "file") in got


# ---------------------------------------------------------------------------
# Through a real process: token at startup, and Click's completion protocol
# ---------------------------------------------------------------------------

import os
import subprocess
import sys

_MAIN = "from markdown_to_canvas.cli import main; main(prog_name='markdown-to-canvas')"


def _env(home: Path, **extra) -> dict:
    env = {k: v for k, v in os.environ.items() if k != "CANVAS_API_TOKEN"}
    env["HOME"] = str(home)
    env.update(extra)
    return env


def test_cli_startup_picks_up_the_token_from_the_fallback_file(home, tmp_path):
    _write_env_token(home, "from-fallback")
    elsewhere = tmp_path / "elsewhere"
    elsewhere.mkdir()
    out = subprocess.run(
        [sys.executable, "-c", "import markdown_to_canvas.cli, os; print(os.environ.get('CANVAS_API_TOKEN'))"],
        cwd=elsewhere, env=_env(home), capture_output=True, text=True, check=True,
    ).stdout
    assert out.strip() == "from-fallback"


def _write_env_token(home: Path, value: str) -> None:
    directory = home / ".config" / "markdown-to-canvas"
    directory.mkdir(parents=True, exist_ok=True)
    (directory / ".env").write_text(f"CANVAS_API_TOKEN={value}\n")


def _complete(home: Path, words: str, cword: int) -> list[str]:
    """What the shell would be offered: Click's bash_complete protocol, run for real."""
    out = subprocess.run(
        [sys.executable, "-c", _MAIN],
        env=_env(home, COMP_WORDS=words, COMP_CWORD=str(cword),
                 _MARKDOWN_TO_CANVAS_COMPLETE="bash_complete"),
        capture_output=True, text=True, cwd=home,
    ).stdout
    return out.splitlines()


def test_a_real_completion_request_offers_keys_and_term_names(home, tmp_path):
    write_registry(home, f'[courses]\n142 = "{tmp_path}"\n143 = "{tmp_path}"\n')
    make_term(home, "2026Fall")

    assert "plain,142" in _complete(home, "markdown-to-canvas update 14", 2)
    assert "plain,2026Fall" in _complete(home, "markdown-to-canvas generate-due-dates 20", 2)
    # The course comes second for generate-due-dates.
    assert "plain,143" in _complete(home, "markdown-to-canvas generate-due-dates 2026Fall 14", 3)


def test_a_key_added_after_install_is_offered_without_reinstalling(home, tmp_path):
    write_registry(home, f'[courses]\n142 = "{tmp_path}"\n')
    installed = subprocess.run(
        [sys.executable, "-c", _MAIN, "install-completion", "--shell", "bash"],
        env=_env(home), capture_output=True, text=True,
    )
    assert installed.returncode == 0, installed.stderr
    script = home / ".local" / "share" / "bash-completion" / "completions" / "markdown-to-canvas"
    before = script.read_text()

    assert "plain,144" not in _complete(home, "markdown-to-canvas update 14", 2)
    write_registry(home, f'[courses]\n142 = "{tmp_path}"\n144 = "{tmp_path}"\n')
    assert "plain,144" in _complete(home, "markdown-to-canvas update 14", 2)
    assert script.read_text() == before  # the installed script never had to change


def test_completion_with_a_broken_registry_prints_no_error(home):
    write_registry(home, "not [toml")
    result = subprocess.run(
        [sys.executable, "-c", _MAIN],
        env=_env(home, COMP_WORDS="markdown-to-canvas update 1", COMP_CWORD="2",
                 _MARKDOWN_TO_CANVAS_COMPLETE="bash_complete"),
        capture_output=True, text=True, cwd=home,
    )
    assert result.returncode == 0
    assert result.stderr == ""
    assert "plain," not in result.stdout
