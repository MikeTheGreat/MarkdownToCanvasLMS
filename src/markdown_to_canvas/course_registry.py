"""Per-user registry of courses and terms, kept under ~/.config/markdown-to-canvas/.

``course_registry.toml`` maps a short key to a course directory (and, optionally,
the canvas.toml to use for it); ``terms/<name>.toml`` are term files that
``generate-due-dates`` accepts by name; ``.env`` is a fallback for the API token.

The registry is read lazily: a bad file only matters to a command that has to
look up a key, so a path argument or a walk-up keeps working when it is broken.
This module must not import anything that reads ``CANVAS_API_TOKEN`` at import
time (``config`` and everything that imports it), because ``cli`` calls
``load_env_files`` before those imports.
"""
from __future__ import annotations

import tomllib
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import tomlkit
from dotenv import find_dotenv, load_dotenv

CONFIG_DIR_NAME = "markdown-to-canvas"
REGISTRY_NAME = "course_registry.toml"
TERMS_DIR_NAME = "terms"
ENV_NAME = ".env"
COURSES_KEY = "courses"
_ENTRY_KEYS = ("path", "config")


class RegistryError(Exception):
    """A problem with the registry or a lookup in it; the message says what.

    Deliberately not a ValueError: the CLI's ValueError handler would prefix the
    message with "KeyError or ValueError:".
    """


def config_dir() -> Path:
    """The per-user directory (looked up on each call, so tests can move HOME)."""
    return Path.home() / ".config" / CONFIG_DIR_NAME


def registry_path() -> Path:
    return config_dir() / REGISTRY_NAME


def terms_dir() -> Path:
    return config_dir() / TERMS_DIR_NAME


@dataclass(frozen=True)
class ResolvedCourse:
    """A course directory, how it was named, and the config a registry entry asks for."""

    path: Path
    key: str | None = None
    #: canvas.toml chosen by the registry entry, already joined to ``path``; None
    #: for a path argument or an entry without a ``config``.
    config: Path | None = None


# ---------------------------------------------------------------------------
# Environment
# ---------------------------------------------------------------------------


def load_env_files() -> None:
    """Load the ``.env`` from the cwd (or a parent), then the fallback file.

    Precedence for a variable: the ``.env`` found from the cwd, then the shell
    environment, then ``~/.config/markdown-to-canvas/.env``. The first load
    overrides the shell (as it always has); the fallback never overrides.
    """
    load_dotenv(find_dotenv(usecwd=True), override=True, verbose=True)
    fallback = config_dir() / ENV_NAME
    if fallback.is_file():
        load_dotenv(fallback, override=False)


# ---------------------------------------------------------------------------
# Reading the registry
# ---------------------------------------------------------------------------


def _read_courses() -> dict[str, Any] | None:
    """The raw ``[courses]`` table, or None when there is no registry file."""
    path = registry_path()
    if not path.is_file():
        return None
    try:
        with open(path, "rb") as f:
            data = tomllib.load(f)
    except tomllib.TOMLDecodeError as e:
        raise RegistryError(f"{path} is not valid TOML: {e}") from None
    courses = data.get(COURSES_KEY, {})
    if not isinstance(courses, dict):
        raise RegistryError(f"{path}: {COURSES_KEY} must be a table of key = path entries")
    return courses


def list_keys() -> list[str]:
    """Registered keys, sorted. Never raises: a missing or bad file has no keys."""
    try:
        return sorted(_read_courses() or {})
    except (RegistryError, OSError):
        return []


def _parse_entry(key: str, raw: Any) -> tuple[Path, Path | None]:
    where = f"{registry_path()}: entry {key!r}"
    if isinstance(raw, str):
        raw = {"path": raw}
    if not isinstance(raw, dict):
        raise RegistryError(f"{where} must be a path string or a table with path and config")
    unknown = sorted(set(raw) - set(_ENTRY_KEYS))
    if unknown:
        raise RegistryError(
            f"{where} has unknown key {unknown[0]!r}; allowed keys: {', '.join(_ENTRY_KEYS)}"
        )
    path = raw.get("path")
    if not isinstance(path, str) or not path:
        raise RegistryError(f"{where} needs a path (a string)")
    config = raw.get("config")
    if config is not None and (not isinstance(config, str) or not config):
        raise RegistryError(f"{where}: config must be a string")
    course_dir = Path(path).expanduser()
    if not course_dir.is_absolute():
        raise RegistryError(
            f"{where}: path {path!r} must be absolute or start with ~"
        )
    return course_dir, Path(config) if config is not None else None


def _unknown_course_message(arg: str, courses: dict[str, Any] | None) -> str:
    if courses is None:
        return (
            f"{arg!r} is not a directory, and there is no course registry "
            f"({registry_path()}) to look it up in."
        )
    keys = ", ".join(sorted(courses)) or "(none)"
    return (
        f"{arg!r} is neither a directory nor a registered course. "
        f"Registered courses ({registry_path()}): {keys}"
    )


def resolve_course(arg: str) -> ResolvedCourse:
    """Turn an explicit course argument into a directory.

    A directory that exists at the path as typed wins, with no walking up;
    otherwise the argument is looked up as a registry key.
    """
    as_path = Path(arg)
    if as_path.is_dir():
        return ResolvedCourse(as_path.resolve())
    courses = _read_courses()
    if courses is None or arg not in courses:
        raise RegistryError(_unknown_course_message(arg, courses))
    course_dir, config = _parse_entry(arg, courses[arg])
    if not course_dir.is_dir():
        raise RegistryError(
            f"Course {arg!r} is registered as {course_dir}, which is not a directory."
        )
    course_dir = course_dir.resolve()
    return ResolvedCourse(course_dir, arg, course_dir / config if config else None)


# ---------------------------------------------------------------------------
# Terms
# ---------------------------------------------------------------------------


def list_terms() -> list[str]:
    """Names of the term files in the terms directory, sorted. Never raises."""
    try:
        return sorted(p.stem for p in terms_dir().glob("*.toml") if p.is_file())
    except OSError:
        return []


def resolve_term(arg: str) -> Path:
    """A term file named by path, or by a term name in the terms directory."""
    as_path = Path(arg)
    if as_path.is_file():
        return as_path
    by_name = terms_dir() / f"{arg}.toml"
    if by_name.is_file():
        return by_name
    names = ", ".join(list_terms()) or "(none)"
    raise RegistryError(
        f"{arg!r} is neither a term file ({as_path.resolve()}) nor a term name "
        f"({by_name}). Terms found: {names}"
    )


# ---------------------------------------------------------------------------
# Writing (import --register)
# ---------------------------------------------------------------------------


def check_key_free(key: str) -> None:
    """Raise RegistryError when ``key`` is empty or already registered."""
    if not key.strip():
        raise RegistryError("--register needs a non-empty key")
    courses = _read_courses()
    if courses is not None and key in courses:
        existing = courses[key]
        shown = existing if isinstance(existing, str) else existing.get("path", existing)
        raise RegistryError(
            f"{key!r} is already registered ({registry_path()}: {shown}); "
            "pick another key or edit the registry."
        )


def add_entry(key: str, course_dir: Path) -> Path:
    """Add ``key = "<absolute course_dir>"`` to the registry; returns the registry path.

    Creates the file and its directory when missing. Existing comments and
    entries are kept. Refuses a key that is already there.
    """
    check_key_free(key)
    path = registry_path()
    doc = tomlkit.parse(path.read_text(encoding="utf-8")) if path.is_file() else tomlkit.document()
    if COURSES_KEY not in doc:
        doc.add(COURSES_KEY, tomlkit.table())
    doc[COURSES_KEY][key] = str(course_dir.resolve())
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(tomlkit.dumps(doc), encoding="utf-8")
    return path


# ---------------------------------------------------------------------------
# Shell completion
# ---------------------------------------------------------------------------


def complete_course(ctx, param, incomplete: str):
    """Registry keys that start with ``incomplete``, plus directory completion."""
    from click.shell_completion import CompletionItem

    items = [CompletionItem(k) for k in list_keys() if k.startswith(incomplete)]
    items.append(CompletionItem(incomplete, type="dir"))
    return items


def complete_term(ctx, param, incomplete: str):
    """Term names that start with ``incomplete``, plus file completion."""
    from click.shell_completion import CompletionItem

    items = [CompletionItem(t) for t in list_terms() if t.startswith(incomplete)]
    items.append(CompletionItem(incomplete, type="file"))
    return items
