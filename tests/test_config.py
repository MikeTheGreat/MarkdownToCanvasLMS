"""Unit tests: canvas.toml config loading."""
from __future__ import annotations

from pathlib import Path

import pytest

from markdown_to_canvas.cli import _resolve_course
from markdown_to_canvas.config import load


def _write_toml(path: Path, content: str) -> Path:
    path.write_text(content)
    return path


def test_load_basic(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("CANVAS_API_TOKEN", "tok123")
    cfg_path = _write_toml(
        tmp_path / "canvas.toml",
        'base_url = "https://school.instructure.com"\ncourse_id = 42\n',
    )
    cfg = load(cfg_path)
    assert cfg.base_url == "https://school.instructure.com"
    assert cfg.course_id == 42
    assert cfg.api_token == "tok123"


def test_trailing_slash_stripped(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("CANVAS_API_TOKEN", "tok")
    cfg_path = _write_toml(
        tmp_path / "canvas.toml",
        'base_url = "https://school.instructure.com/"\ncourse_id = 1\n',
    )
    cfg = load(cfg_path)
    assert cfg.base_url == "https://school.instructure.com"


def test_token_from_toml_fallback(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("CANVAS_API_TOKEN", raising=False)
    cfg_path = _write_toml(
        tmp_path / "canvas.toml",
        'base_url = "https://school.instructure.com"\ncourse_id = 1\n[auth]\napi_token = "toml_tok"\n',
    )
    cfg = load(cfg_path)
    assert cfg.api_token == "toml_tok"


def test_env_var_takes_precedence_over_toml(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("CANVAS_API_TOKEN", "env_tok")
    cfg_path = _write_toml(
        tmp_path / "canvas.toml",
        'base_url = "https://school.instructure.com"\ncourse_id = 1\n[auth]\napi_token = "toml_tok"\n',
    )
    cfg = load(cfg_path)
    assert cfg.api_token == "env_tok"


def test_missing_token_raises(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("CANVAS_API_TOKEN", raising=False)
    cfg_path = _write_toml(
        tmp_path / "canvas.toml",
        'base_url = "https://school.instructure.com"\ncourse_id = 1\n',
    )
    with pytest.raises(ValueError, match="API token"):
        load(cfg_path)


def test_missing_file_raises(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("CANVAS_API_TOKEN", "tok")
    with pytest.raises(FileNotFoundError):
        load(tmp_path / "nonexistent.toml")


def test_missing_base_url_raises(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("CANVAS_API_TOKEN", "tok")
    cfg_path = _write_toml(tmp_path / "canvas.toml", "course_id = 1\n")
    with pytest.raises(KeyError):
        load(cfg_path)


def test_missing_course_id_raises(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("CANVAS_API_TOKEN", "tok")
    cfg_path = _write_toml(
        tmp_path / "canvas.toml",
        'base_url = "https://school.instructure.com"\n',
    )
    with pytest.raises(KeyError):
        load(cfg_path)


def test_course_id_coerced_to_int(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("CANVAS_API_TOKEN", "tok")
    cfg_path = _write_toml(
        tmp_path / "canvas.toml",
        'base_url = "https://school.instructure.com"\ncourse_id = 99\n',
    )
    cfg = load(cfg_path)
    assert isinstance(cfg.course_id, int)
    assert cfg.course_id == 99


def test_config_is_frozen(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("CANVAS_API_TOKEN", "tok")
    cfg_path = _write_toml(
        tmp_path / "canvas.toml",
        'base_url = "https://school.instructure.com"\ncourse_id = 1\n',
    )
    cfg = load(cfg_path)
    with pytest.raises(Exception):
        cfg.course_id = 999  # type: ignore[misc]


# ---------------------------------------------------------------------------
# [course_flags] in canvas.toml (per-config flag overrides)
# ---------------------------------------------------------------------------


def test_config_path_recorded(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("CANVAS_API_TOKEN", "tok")
    cfg_path = _write_toml(
        tmp_path / "canvas-sec-a.toml",
        'base_url = "https://school.instructure.com"\ncourse_id = 1\n',
    )
    assert load(cfg_path).config_path == cfg_path


def test_no_course_flags_table(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("CANVAS_API_TOKEN", "tok")
    cfg_path = _write_toml(
        tmp_path / "canvas.toml",
        'base_url = "https://school.instructure.com"\ncourse_id = 1\n',
    )
    assert load(cfg_path).course_flags == {}


def test_course_flags_read(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("CANVAS_API_TOKEN", "tok")
    cfg_path = _write_toml(
        tmp_path / "canvas.toml",
        'base_url = "https://school.instructure.com"\ncourse_id = 1\n'
        "[course_flags]\nnight_section = true\nin_person_class = false\n",
    )
    assert load(cfg_path).course_flags == {
        "night_section": True,
        "in_person_class": False,
    }


def test_course_flags_non_boolean_raises(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("CANVAS_API_TOKEN", "tok")
    cfg_path = _write_toml(
        tmp_path / "canvas.toml",
        'base_url = "https://school.instructure.com"\ncourse_id = 1\n'
        '[course_flags]\nquarter = "fall"\n',
    )
    with pytest.raises(ValueError, match="must be a TOML boolean"):
        load(cfg_path)


def test_course_flags_invalid_name_raises(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("CANVAS_API_TOKEN", "tok")
    cfg_path = _write_toml(
        tmp_path / "canvas.toml",
        'base_url = "https://school.instructure.com"\ncourse_id = 1\n'
        '[course_flags]\n"2cool" = true\n',
    )
    with pytest.raises(ValueError, match="invalid course flag name"):
        load(cfg_path)


def test_require_course_false_tolerates_missing_fields(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """publish/list-titles read canvas.toml only for its flags."""
    monkeypatch.delenv("CANVAS_API_TOKEN", raising=False)
    cfg_path = _write_toml(
        tmp_path / "canvas.toml", "[course_flags]\nnight_section = true\n"
    )
    cfg = load(cfg_path, require_token=False, require_course=False)
    assert cfg.course_flags == {"night_section": True}
    assert cfg.base_url == ""
    assert cfg.course_id == 0


# ---------------------------------------------------------------------------
# _resolve_course: optional COURSE_DIR argument (path, registry key, or walk-up)
# ---------------------------------------------------------------------------


def _make_course_repo(tmp_path: Path) -> Path:
    repo = tmp_path / "repo"
    (repo / "course_settings").mkdir(parents=True)
    (repo / "course_settings" / "course_settings.toml").write_text("")
    return repo


class TestResolveCourse:
    def test_explicit_path_is_used_verbatim(self, tmp_path: Path) -> None:
        """An explicit path never walks up, so a wrong path still reports its own
        missing config rather than silently acting on the parent repo."""
        repo = _make_course_repo(tmp_path)
        subdir = repo / "pages" / "worksheets"
        subdir.mkdir(parents=True)
        path, config = _resolve_course(str(subdir))
        assert path == subdir.resolve()
        assert config is None

    def test_omitted_walks_up_from_cwd(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        repo = _make_course_repo(tmp_path)
        subdir = repo / "pages" / "worksheets"
        subdir.mkdir(parents=True)
        monkeypatch.chdir(subdir)
        assert _resolve_course(None)[0] == repo.resolve()

    def test_omitted_at_repo_root(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        repo = _make_course_repo(tmp_path)
        monkeypatch.chdir(repo)
        assert _resolve_course(None)[0] == repo.resolve()

    def test_omitted_outside_any_repo_exits(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.chdir(tmp_path)
        with pytest.raises(SystemExit):
            _resolve_course(None)
