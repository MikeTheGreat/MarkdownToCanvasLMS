"""Per-user registry of courses and terms, kept under ~/.config/markdown-to-canvas/.

``course_registry.toml`` maps a short key to a course directory (and, optionally,
the canvas.toml to use for it) or to a group: an array of keys, paths and
``{path, config}`` tables that a command runs over one after another. It may name the ``current_term`` file that
``generate-due-dates`` uses when ``--term`` is not given; ``terms/<name>.toml``
are term files that ``--term`` accepts by name; ``.env`` is a fallback for the
API token.

The registry is read lazily: a bad file only matters to a command that has to
look up a key, so a path argument or a walk-up keeps working when it is broken.
This module must not import anything that reads ``CANVAS_API_TOKEN`` at import
time (``config`` and everything that imports it), because ``cli`` calls
``load_env_files`` before those imports.
"""
from __future__ import annotations

import os
import tomllib
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import tomlkit
from dotenv import dotenv_values, find_dotenv, load_dotenv

CONFIG_DIR_NAME = "markdown-to-canvas"
REGISTRY_NAME = "course_registry.toml"
TERMS_DIR_NAME = "terms"
ENV_NAME = ".env"
TOKEN_VAR = "CANVAS_API_TOKEN"
COURSES_KEY = "courses"
CURRENT_TERM_KEY = "current_term"
_ENTRY_KEYS = ("path", "config")


def _usable_dir(path: Path) -> bool:
    """``path.is_dir()``, but False when the check itself fails.

    An argument is tried as a path before it is tried as a key or a name. The
    path is relative to the current directory, which can be unreadable (a stale
    mount gives EIO). ``Path.is_dir()`` hides only "not found" errors and raises
    the rest, so an unreadable directory would stop a key lookup that never
    needs it. Treat it as "no directory there" and let the lookup go on.
    """
    try:
        return path.is_dir()
    except OSError:
        return False


def _usable_file(path: Path) -> bool:
    """``path.is_file()``, but False when the check itself fails. See ``_usable_dir``."""
    try:
        return path.is_file()
    except OSError:
        return False


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
    global token_source, env_search_start, env_search_found
    shell_has_token = bool(os.environ.get(TOKEN_VAR))
    try:
        env_search_start = os.getcwd()
    except OSError:
        env_search_start = None
    local = find_dotenv(usecwd=True)
    env_search_found = local or None
    load_dotenv(local, override=True, verbose=True)
    fallback = config_dir() / ENV_NAME
    if fallback.is_file():
        load_dotenv(fallback, override=False)

    if local and dotenv_values(local).get(TOKEN_VAR):
        token_source = local
    elif shell_has_token:
        token_source = "the shell environment"
    elif fallback.is_file() and dotenv_values(fallback).get(TOKEN_VAR):
        token_source = str(fallback)
    else:
        token_source = None


#: Where load_env_files() got CANVAS_API_TOKEN from: a .env path, "the shell
#: environment", or None when none of them set it. Reported by the CLI when
#: Canvas rejects the token, since a stale .env in the cwd silently wins.
token_source: str | None = None

#: The directory load_env_files() started its .env search from (None when the
#: cwd could not be read), and the .env it found there or in a parent (None when
#: there was none). Used to list the searched places when no token is set.
env_search_start: str | None = None
env_search_found: str | None = None


def token_search_report() -> list[str]:
    """One line per place a token can come from, saying what was found there.

    Covers the places ``load_env_files`` reads. The canvas.toml ``[auth]``
    line is added by ``config.load``, which knows the file.
    """
    if env_search_found:
        has = bool(dotenv_values(env_search_found).get(TOKEN_VAR))
        local = (
            f"a .env in the current directory or a parent: found "
            f"{env_search_found}, "
            + ("which sets " if has else "which does not set ")
            + TOKEN_VAR
        )
    elif env_search_start:
        local = (
            f"a .env in the current directory or a parent: none found "
            f"(searched up from {env_search_start})"
        )
    else:
        local = "a .env in the current directory or a parent: not searched (the current directory could not be read)"
    shell = (
        f"the {TOKEN_VAR} environment variable in your shell: "
        + ("set" if token_source == "the shell environment" else "not set")
    )
    fallback = config_dir() / ENV_NAME
    try:
        if not fallback.is_file():
            state = "file not found"
        elif dotenv_values(fallback).get(TOKEN_VAR):
            state = f"sets {TOKEN_VAR}"
        else:
            state = f"does not set {TOKEN_VAR}"
    except OSError as e:
        state = f"could not be read ({e.strerror})"
    return [local, shell, f"{fallback}: {state}"]


# ---------------------------------------------------------------------------
# Reading the registry
# ---------------------------------------------------------------------------


def _read_registry() -> dict[str, Any] | None:
    """The whole parsed registry, or None when there is no registry file."""
    path = registry_path()
    if not path.is_file():
        return None
    try:
        with open(path, "rb") as f:
            return tomllib.load(f)
    except tomllib.TOMLDecodeError as e:
        raise RegistryError(f"{path} is not valid TOML: {e}") from None


def _read_courses() -> dict[str, Any] | None:
    """The raw ``[courses]`` table, or None when there is no registry file."""
    data = _read_registry()
    if data is None:
        return None
    path = registry_path()
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
        raise RegistryError(
            f"{where} must be a path string, a table with path and config, or a list of those"
        )
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
    if _usable_dir(as_path):
        return ResolvedCourse(as_path.resolve())
    courses = _read_courses()
    if courses is None or arg not in courses:
        raise RegistryError(_unknown_course_message(arg, courses))
    if isinstance(courses[arg], list):
        raise RegistryError(
            f"{arg!r} is a group of courses, not a single course; "
            f"use resolve_courses() to expand it."
        )
    course_dir, config = _parse_entry(arg, courses[arg])
    if not course_dir.is_dir():
        raise RegistryError(
            f"Course {arg!r} is registered as {course_dir}, which is not a directory."
        )
    course_dir = course_dir.resolve()
    return ResolvedCourse(course_dir, arg, course_dir / config if config else None)


def is_group(arg: str) -> bool:
    """True when ``arg`` would be read as a registry key that names a group.

    A directory that exists at the path as typed wins over a key, so it is never
    a group. Never raises: a missing or bad registry is simply "not a group", and
    the lookup that follows reports the real problem.
    """
    if _usable_dir(Path(arg)):
        return False
    try:
        courses = _read_courses()
    except (RegistryError, OSError):
        return False
    return courses is not None and isinstance(courses.get(arg), list)


def _group_member(group: str, courses: dict[str, Any], element: Any) -> ResolvedCourse:
    """One element of a group, as a course. The directory is not checked to exist."""
    where = f"{registry_path()}: group {group!r}"
    if isinstance(element, str):
        if element in courses:
            raw = courses[element]
            if isinstance(raw, list):
                raise RegistryError(
                    f"{where} lists {element!r}, which is itself a group; "
                    f"a group may not contain another group."
                )
            course_dir, config = _parse_entry(element, raw)
            key: str | None = element
        else:
            if not element or not (element.startswith("~") or Path(element).is_absolute()):
                raise RegistryError(
                    f"{where} has the element {element!r}, which is neither a "
                    f"registered course key nor a path that is absolute or "
                    f"starts with ~."
                )
            course_dir, config = _parse_entry(group, element)
            key = None
    elif isinstance(element, dict):
        course_dir, config = _parse_entry(group, element)
        key = None
    else:
        raise RegistryError(
            f"{where} has an element that is not a key, a path string or a "
            f"table with path and config: {element!r}"
        )
    course_dir = course_dir.resolve()
    return ResolvedCourse(course_dir, key, course_dir / config if config else None)


def resolve_courses(arg: str) -> list[ResolvedCourse]:
    """Turn a course argument into the courses it stands for.

    Same lookup as ``resolve_course`` for a path or a non-group key (a list of
    one). A key naming a group gives its elements in order. The whole group is
    checked first, so a malformed or nested element fails before anything runs;
    a member whose directory is missing is returned anyway, for the caller to
    report at its turn.
    """
    as_path = Path(arg)
    if _usable_dir(as_path):
        return [ResolvedCourse(as_path.resolve())]
    courses = _read_courses()
    if courses is None or arg not in courses:
        raise RegistryError(_unknown_course_message(arg, courses))
    entry = courses[arg]
    if not isinstance(entry, list):
        return [resolve_course(arg)]
    if not entry:
        raise RegistryError(f"{registry_path()}: group {arg!r} is empty")
    return [_group_member(arg, courses, element) for element in entry]


def resolve_config(arg: str) -> Path:
    """Turn a --config value into a canvas.toml path.

    A file that exists at the path as typed wins. Otherwise a registered key
    names the entry's canvas.toml: its ``config`` joined to its course directory,
    or ``course_settings/canvas.toml`` there when the entry has none. A value
    that is neither is returned as a path, so the caller's own "not found"
    error applies.
    """
    as_path = Path(arg)
    if _usable_file(as_path):
        return as_path
    courses = _read_courses()
    if courses is None or arg not in courses:
        return as_path
    if isinstance(courses[arg], list):
        raise RegistryError(
            f"{arg!r} names a group of several courses, not one canvas.toml; "
            f"give a single course's key (or a file path) to --config."
        )
    course_dir, config = _parse_entry(arg, courses[arg])
    return course_dir.resolve() / (config or Path("course_settings") / "canvas.toml")


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
    if _usable_file(as_path):
        return as_path
    by_name = terms_dir() / f"{arg}.toml"
    if by_name.is_file():
        return by_name
    names = ", ".join(list_terms()) or "(none)"
    raise RegistryError(
        f"{arg!r} is neither a term file ({as_path.resolve()}) nor a term name "
        f"({by_name}). Terms found: {names}"
    )


def current_term() -> Path:
    """The term file named by the registry's top-level ``current_term`` key.

    The value may be absolute, start with ~, or be relative to the registry
    file's directory. Raises RegistryError when there is no registry, no key,
    a value that is not a string, or no file at the path. Whether the term is
    still running is the caller's check (it needs the term file's contents).
    """
    path = registry_path()
    data = _read_registry()
    if data is None:
        raise RegistryError(
            f"No --term given, and there is no course registry ({path}) with a "
            f"{CURRENT_TERM_KEY} key to fall back on."
        )
    if CURRENT_TERM_KEY not in data:
        courses = data.get(COURSES_KEY)
        if isinstance(courses, dict) and CURRENT_TERM_KEY in courses:
            raise RegistryError(
                f"No --term given, and {path} has {CURRENT_TERM_KEY} inside [{COURSES_KEY}]. "
                f"Move the {CURRENT_TERM_KEY} line above the [{COURSES_KEY}] header."
            )
        raise RegistryError(
            f"No --term given, and {path} has no {CURRENT_TERM_KEY} key. Add a line like "
            f'{CURRENT_TERM_KEY} = "terms/2026Fall.toml" above [{COURSES_KEY}], or pass --term.'
        )
    raw = data[CURRENT_TERM_KEY]
    if not isinstance(raw, str) or not raw:
        raise RegistryError(f"{path}: {CURRENT_TERM_KEY} must be a path (a string), not {raw!r}")
    term = Path(raw).expanduser()
    if not term.is_absolute():
        term = path.parent / term
    if not term.is_file():
        raise RegistryError(
            f"{path}: {CURRENT_TERM_KEY} = {raw!r}, but there is no file at {term}. "
            f"Fix the path, or pass --term."
        )
    return term


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
