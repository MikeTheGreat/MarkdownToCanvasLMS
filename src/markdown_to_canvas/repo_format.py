"""Course repo format version: recording, checking and upgrading.

A course repo records the format of its files as an integer ``format_version``
at the top of ``course_settings/course_settings.toml`` (a repo without the key
is version 0). Every ``.manifest-*.toml`` records its own version in the
reserved ``_repo_format`` entry, because manifests are local and can lag behind
the committed settings file on a machine that has not run ``upgrade``.

check_repo_format() is called at the start of every library operation that
reads a repo; it only compares versions. run_upgrade() applies the migrations in MIGRATIONS in order.
"""
from __future__ import annotations

import tomllib
from collections.abc import Callable
from datetime import date
from importlib import metadata
from pathlib import Path
from typing import Any

import tomli_w
import tomlkit
from tomlkit.items import AoT, Array, InlineTable, Table, Whitespace

from . import manifest as manifest_lib

#: The format version this tool reads and writes. Increase it (and add a
#: migration to MIGRATIONS) whenever a change makes the tool read an existing
#: repo file differently. See CLAUDE.md.
FORMAT_VERSION = 1

SETTINGS_RELPATH = Path("course_settings") / "course_settings.toml"

#: Keys written first in course_settings.toml, in this order.
VERSION_KEYS = ("format_version", "created_by", "upgraded_by")

TAB_CONFIGURATION_KEY = "tab_configuration"


class RepoFormatError(Exception):
    """The repo cannot be used as it is; the message says why and what to do.

    Deliberately not a ValueError: the CLI's ValueError handler would prefix
    the message with "KeyError or ValueError:".
    """


def tool_version() -> str:
    """The installed package version, or "unknown" when not installed."""
    try:
        return metadata.version("markdown-to-canvas")
    except metadata.PackageNotFoundError:
        return "unknown"


def settings_path(repo: Path) -> Path:
    return repo / SETTINGS_RELPATH


def _validate_version(value: Any, source: Path) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise RepoFormatError(
            f"{source}: format_version must be a non-negative integer, got {value!r}"
        )
    return value


def _load_toml(path: Path) -> dict[str, Any]:
    try:
        with open(path, "rb") as f:
            return tomllib.load(f)
    except tomllib.TOMLDecodeError as exc:
        raise RepoFormatError(f"{path} is not valid TOML: {exc}") from exc


def read_repo_version(repo: Path) -> int:
    """format_version from course_settings.toml; 0 if the file or key is missing."""
    path = settings_path(repo)
    if not path.exists():
        return 0
    data = _load_toml(path)
    if "format_version" not in data:
        return 0
    return _validate_version(data["format_version"], path)


def read_manifest_versions(repo: Path) -> dict[Path, int]:
    """Each ``.manifest-*.toml`` in ``repo`` with its recorded format version."""
    versions: dict[Path, int] = {}
    for path in sorted(repo.glob(manifest_lib.MANIFEST_GLOB)):
        stamp = _load_toml(path).get(manifest_lib.FORMAT_KEY)
        if not isinstance(stamp, dict) or "format_version" not in stamp:
            versions[path] = 0
        else:
            versions[path] = _validate_version(stamp["format_version"], path)
    return versions


# ---------------------------------------------------------------------------
# tab_configuration placement
# ---------------------------------------------------------------------------

def _insert_key(doc: tomlkit.TOMLDocument, position: int, key: str, value: Any) -> None:
    """Insert ``key = value`` at body index ``position`` (``doc.add`` only appends,
    which would land after any table header and nest the key)."""
    if position >= len(doc.body):
        doc.add(key, value)  # nothing follows, so appending is the same thing
        return
    # Container._insert_at is private but the only way to insert at a position.
    doc._insert_at(position, key, value)


def _is_table(value: Any) -> bool:
    return isinstance(value, (Table, InlineTable, dict))


def _find_nested(container: Any, target: str, path: str = "") -> tuple[Any, str] | None:
    """(parent table, dotted path) of the first ``target`` key below ``container``."""
    for key, value in container.items():
        here = f"{path}.{key}" if path else str(key)
        if _is_table(value):
            if target in value:
                return value, f"{here}.{target}"
            found = _find_nested(value, target, here)
            if found:
                return found
        elif isinstance(value, (AoT, Array)):
            for i, element in enumerate(value):
                if not _is_table(element):
                    continue
                elem_path = f"{here}[{i}]"
                if target in element:
                    return element, f"{elem_path}.{target}"
                found = _find_nested(element, target, elem_path)
                if found:
                    return found
    return None


def fix_tab_configuration(doc: tomlkit.TOMLDocument) -> str | None:
    """Move a nested ``tab_configuration`` to the top level of ``doc``.

    Returns None when there is nothing to do, or a notice naming the old
    location after moving it. A key present at both levels raises
    RepoFormatError. The key is placed before the first table so it stays a
    top-level key; the rest of the document is untouched.
    """
    found = _find_nested(doc, TAB_CONFIGURATION_KEY)
    if found is None:
        return None
    parent, dotted = found
    if TAB_CONFIGURATION_KEY in doc:
        raise RepoFormatError(
            f"course_settings.toml has {TAB_CONFIGURATION_KEY} both at the top level and "
            f"nested at {dotted}; delete one of them and re-run"
        )
    value = parent[TAB_CONFIGURATION_KEY]
    del parent[TAB_CONFIGURATION_KEY]
    position = len(doc.body)
    for i, (_key, item) in enumerate(doc.body):
        if isinstance(item, (Table, AoT)):
            position = i
            break
    # Stay above the blank line that separates the top-level keys from the table.
    while position > 0 and isinstance(doc.body[position - 1][1], Whitespace):
        position -= 1
    _insert_key(doc, position, TAB_CONFIGURATION_KEY, value)
    return (
        f"Moved {dotted} to a top-level '{TAB_CONFIGURATION_KEY}' key in "
        f"course_settings.toml (it is only read at the top level)"
    )


# ---------------------------------------------------------------------------
# The check
# ---------------------------------------------------------------------------

def check_repo_format(repo: Path) -> None:
    """Refuse a repo (or manifest) whose format version differs from this tool's.

    Raises RepoFormatError on a mismatch. A matching version means the files
    were set up correctly: `upgrade` is the only place that corrects file
    contents (such as a misplaced ``tab_configuration``), once.
    """
    repo_version = read_repo_version(repo)
    if repo_version > FORMAT_VERSION:
        raise RepoFormatError(_newer_message(f"{settings_path(repo)}", repo_version))
    if repo_version < FORMAT_VERSION:
        raise RepoFormatError(
            f"This course repo is format version {repo_version} but this tool "
            f"(markdown-to-canvas {tool_version()}) uses format version {FORMAT_VERSION}. "
            f"Run `markdown-to-canvas upgrade` first."
        )
    for path, version in read_manifest_versions(repo).items():
        if version > FORMAT_VERSION:
            raise RepoFormatError(_newer_message(path.name, version))
        if version < FORMAT_VERSION:
            raise RepoFormatError(
                f"{path.name} is format version {version} but this tool "
                f"(markdown-to-canvas {tool_version()}) uses format version "
                f"{FORMAT_VERSION}. Run `markdown-to-canvas upgrade` first "
                f"(manifests are local, so run it on every machine that has one)."
            )


def _newer_message(what: str, version: int) -> str:
    return (
        f"{what} is format version {version} but this tool "
        f"(markdown-to-canvas {tool_version()}) only understands format version "
        f"{FORMAT_VERSION}. Update markdown-to-canvas."
    )


# ---------------------------------------------------------------------------
# Migrations and upgrade
# ---------------------------------------------------------------------------

class UpgradeState:
    """What a migration step may edit: the settings document and the manifests."""

    def __init__(self, repo: Path):
        self.repo = repo
        settings = settings_path(repo)
        self.settings_doc: tomlkit.TOMLDocument = (
            tomlkit.parse(settings.read_text(encoding="utf-8"))
            if settings.exists()
            else tomlkit.document()
        )
        self.manifests: dict[Path, dict[str, Any]] = {
            path: dict(_load_toml(path))
            for path in sorted(repo.glob(manifest_lib.MANIFEST_GLOB))
        }
        #: Renames to perform when the step is written: (old, new).
        self.renames: list[tuple[Path, Path]] = []


#: A migration edits ``state`` for the step ``v -> v + 1`` and returns
#: human-readable lines describing what it changed.
Migration = Callable[[UpgradeState], list[str]]


def _migrate_0_to_1(state: UpgradeState) -> list[str]:
    lines: list[str] = []
    legacy = state.repo / manifest_lib.LEGACY_MANIFEST_NAME
    target = state.repo / manifest_lib.manifest_name_for(None)
    if legacy.exists():
        if target.exists() or target in state.manifests:
            lines.append(
                f"WARNING: both {legacy.name} and {target.name} exist; "
                f"{legacy.name} is unused and was left untouched"
            )
        else:
            state.renames.append((legacy, target))
            state.manifests[target] = dict(_load_toml(legacy))
            lines.append(f"Rename {legacy.name} -> {target.name} (one manifest per canvas.toml)")
    for path in state.manifests:
        lines.append(f"Record format version 1 in {path.name}")
    return lines


#: Ordered migrations, keyed by the version they migrate *from*.
MIGRATIONS: dict[int, Migration] = {
    0: _migrate_0_to_1,
}


def _set_version(doc: tomlkit.TOMLDocument, version: int) -> None:
    if "format_version" in doc:
        doc["format_version"] = version
    else:
        _insert_key(doc, 0, "format_version", version)


def _write_settings(path: Path, doc: tomlkit.TOMLDocument) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(tomlkit.dumps(doc), encoding="utf-8")


def _write_manifest(path: Path, data: dict[str, Any], version: int) -> None:
    data[manifest_lib.FORMAT_KEY] = {"format_version": version}
    with open(path, "wb") as f:
        tomli_w.dump(data, f)


def _append_upgraded_by(doc: tomlkit.TOMLDocument, entry: str) -> None:
    if "upgraded_by" in doc:
        doc["upgraded_by"].append(entry)
        return
    # Insert after format_version / created_by so the version keys stay first.
    position = 0
    for i, (key, _item) in enumerate(doc.body):
        if key is not None and key.key in ("format_version", "created_by"):
            position = i + 1
    _insert_key(doc, position, "upgraded_by", [entry])


def run_upgrade(
    repo: Path,
    noop: bool = False,
    migrations: dict[int, Migration] | None = None,
    target_version: int | None = None,
    today: date | None = None,
) -> list[str]:
    """Migrate ``repo`` and its manifests to the current format version.

    Prints each change and returns the printed lines. ``migrations`` and
    ``target_version`` exist so tests can use a fake registry.
    """
    migrations = MIGRATIONS if migrations is None else migrations
    target = FORMAT_VERSION if target_version is None else target_version
    out: list[str] = []

    def say(line: str) -> None:
        out.append(line)
        print(line)

    repo_version = read_repo_version(repo)
    manifest_versions = read_manifest_versions(repo)
    start = min([repo_version, *manifest_versions.values()])
    highest = max([repo_version, *manifest_versions.values()])
    if highest > target:
        raise RepoFormatError(_newer_message(str(repo), highest))

    state = UpgradeState(repo)
    settings = settings_path(repo)
    changed_settings_version = False
    version = start
    while version < target:
        migration = migrations.get(version)
        if migration is None:
            raise RepoFormatError(f"No migration from format version {version}")
        say(f"Migration {version} -> {version + 1}:")
        state.renames = []
        for line in migration(state):
            say(f"  {line}")
        if not noop:
            for old, new in state.renames:
                old.rename(new)
            for path, data in state.manifests.items():
                _write_manifest(path, data, version + 1)
            if repo_version <= version:
                _set_version(state.settings_doc, version + 1)
                _write_settings(settings, state.settings_doc)
                changed_settings_version = True
        elif repo_version <= version:
            _set_version(state.settings_doc, version + 1)
            changed_settings_version = True
        version += 1

    # Placement check (reports only with --noop).
    notice = fix_tab_configuration(state.settings_doc)
    if notice:
        say(notice if not noop else notice.replace("Moved", "Would move", 1))

    if changed_settings_version and not noop:
        stamp = (today or date.today()).isoformat()
        _append_upgraded_by(
            state.settings_doc, f"{tool_version()} on {stamp}: {repo_version} -> {target}"
        )
    if not noop and (changed_settings_version or notice or not settings.exists()):
        _write_settings(settings, state.settings_doc)

    if version == start and not notice:
        say("Repo is already current; nothing to do")
    elif noop:
        say("--noop: no files were written")
    return out
