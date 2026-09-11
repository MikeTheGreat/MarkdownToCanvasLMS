"""Load and validate canvas.toml configuration."""
from __future__ import annotations

import os
import re
import tomllib
from dataclasses import dataclass, field
from pathlib import Path


def find_repo_root(start_path: Path) -> Path | None:
    """Walk up from start_path looking for course_settings/course_settings.toml."""
    current = start_path if start_path.is_dir() else start_path.parent
    while True:
        if (current / "course_settings" / "course_settings.toml").exists():
            return current
        parent = current.parent
        if parent == current:
            return None
        current = parent


_FLAG_NAME_RE = re.compile(r"[A-Za-z_][A-Za-z0-9_]*\Z")


def validate_course_flags(table: object, source: str) -> dict[str, bool]:
    """Validate a ``[course_flags]`` table read from ``source``.

    Shared by ``course_settings.toml`` and ``canvas.toml`` so both files
    enforce the same rules and report problems the same way. An invalid flag
    name or a non-boolean value is a whole-run config error: raises
    ValueError, which the CLI reports via die().
    """
    if not isinstance(table, dict):
        raise ValueError(
            f"[course_flags] in {source} must be a table of "
            f"flag_name = true/false entries"
        )
    for name, value in table.items():
        if not _FLAG_NAME_RE.match(name):
            raise ValueError(
                f"invalid course flag name {name!r} in [course_flags] in "
                f"{source} — names must match [A-Za-z_][A-Za-z0-9_]* (letters, "
                f"digits, underscores; not starting with a digit)"
            )
        if not isinstance(value, bool):
            raise ValueError(
                f"course flag '{name}' in [course_flags] in {source} must be a "
                f"TOML boolean (true/false), got {value!r}"
            )
    return dict(table)


@dataclass(frozen=True)
class Config:
    base_url: str
    course_id: int
    api_token: str
    #: The canvas.toml this was loaded from; names the manifest file (see
    #: manifest.manifest_name_for). None means "the default canvas.toml".
    config_path: Path | None = None
    #: Optional [course_flags] table from this canvas.toml. Overrides the
    #: same-named flags in course_settings.toml (see sync.load_course_flags),
    #: which is what lets one repo drive several sections that differ.
    course_flags: dict[str, bool] = field(default_factory=dict)


def load(
    path: Path, require_token: bool = True, require_course: bool = True
) -> Config:
    """require_token=False is for commands that never contact Canvas
    (e.g. `update --check-all`) but still need base_url/course_id.

    require_course=False additionally tolerates a canvas.toml with no
    base_url/course_id, for commands that read the file only for its
    [course_flags] table (`publish`, `list-titles`) — a repo that never syncs
    can leave those unset, and neither command would use them anyway.
    """
    with open(path, "rb") as f:
        data = tomllib.load(f)

    api_token = os.environ.get("CANVAS_API_TOKEN") or data.get("auth", {}).get("api_token", "")
    if not api_token and require_token:
        raise ValueError("Canvas API token not set. Use CANVAS_API_TOKEN env var or canvas.toml [auth] api_token.")

    if require_course:
        base_url = data["base_url"].rstrip("/")
        course_id = int(data["course_id"])
    else:
        base_url = str(data.get("base_url", "")).rstrip("/")
        course_id = int(data.get("course_id", 0))

    return Config(
        base_url=base_url,
        course_id=course_id,
        api_token=api_token,
        config_path=path,
        course_flags=validate_course_flags(data.get("course_flags", {}), str(path)),
    )
