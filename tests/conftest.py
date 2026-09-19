import pytest
from unittest.mock import MagicMock


@pytest.fixture(autouse=True)
def _block_outbound_http(monkeypatch):
    """Prevent any real HTTP requests from leaking out of tests."""
    mock_response = MagicMock()
    mock_response.status_code = 200
    monkeypatch.setattr("requests.put", MagicMock(return_value=mock_response))


def make_current(repo):
    """Give ``repo`` a course_settings.toml at the tool's current format version.

    Creates the file when missing; otherwise prepends ``format_version`` to it
    (unless it already has one). Every library entry point that reads a repo
    refuses a repo below the current version, so tests that build repos in
    tmp_path call this first.
    """
    from pathlib import Path
    from markdown_to_canvas.repo_format import FORMAT_VERSION

    path = Path(repo) / "course_settings" / "course_settings.toml"
    line = f"format_version = {FORMAT_VERSION}\n"
    if not path.exists():
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(line, encoding="utf-8")
        return path
    text = path.read_text(encoding="utf-8")
    if not any(ln.strip().startswith("format_version") for ln in text.splitlines()):
        path.write_text(line + text, encoding="utf-8")
    return path
