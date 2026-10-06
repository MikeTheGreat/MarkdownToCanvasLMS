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

import re
import tomllib
from collections.abc import Callable
from datetime import date
from importlib import metadata
from pathlib import Path
from typing import Any

import tomli_w
import tomlkit
import yaml
from tomlkit.items import AoT, Array, InlineTable, Table

from . import manifest as manifest_lib
from . import toml_write
from .relative_dates import CUTOFF_HELP, CUTOFF_KEY, DEFAULT_TIMES, DEFAULT_TIMES_HELP

#: The format version this tool reads and writes. Increase it (and add a
#: migration to MIGRATIONS) whenever a change makes the tool read an existing
#: repo file differently. See CLAUDE.md.
FORMAT_VERSION = 10

SETTINGS_RELPATH = Path("course_settings") / "course_settings.toml"

#: The example term file `import` writes (see migration 2 -> 3).
TERM_RELPATH = Path("course_settings") / "term_dates.toml"

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

_insert_key = toml_write.insert_key


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
    toml_write.insert_top_level_key(doc, TAB_CONFIGURATION_KEY, value)
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
        #: The in-repo term file, when there is one, and whether a step changed it.
        self.term_path = repo / TERM_RELPATH
        self.term_doc: tomlkit.TOMLDocument | None = (
            tomlkit.parse(self.term_path.read_text(encoding="utf-8"))
            if self.term_path.exists()
            else None
        )
        self.term_changed = False
        #: Other repo files to write when the step is written: path -> new text.
        self.pending_writes: dict[Path, str] = {}


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


#: Section of course_settings.toml holding the relative due dates.
RELATIVE_DUE_DATES_KEY = "relative_due_dates"


def _migrate_1_to_2(state: UpgradeState) -> list[str]:
    """Add the empty relative-due-dates section; stamp the manifests."""
    lines: list[str] = []
    if not settings_path(state.repo).exists() or read_repo_version(state.repo) >= 2:
        pass  # nothing to edit, or the settings file is already at version 2
    elif RELATIVE_DUE_DATES_KEY in state.settings_doc:
        lines.append(f"{RELATIVE_DUE_DATES_KEY} is already present; left as it is")
    else:
        # A table header at the end of the file cannot capture existing keys.
        section = tomlkit.parse(
            f"[{RELATIVE_DUE_DATES_KEY}.tables.default]\nitems = []\n"
        )
        doc = state.settings_doc
        if doc.body:
            doc.add(tomlkit.nl())
        doc.add(RELATIVE_DUE_DATES_KEY, section[RELATIVE_DUE_DATES_KEY])
        lines.append(
            f"Add an empty [{RELATIVE_DUE_DATES_KEY}.tables.default] table to "
            f"{SETTINGS_RELPATH.name}"
        )
    for path in state.manifests:
        lines.append(f"Record format version 2 in {path.name}")
    return lines


#: Name of the table `generate-due-dates` uses when --table is not given.
DEFAULT_TABLE = "default"
_TABLES_PATH = f"{RELATIVE_DUE_DATES_KEY}.tables"


def _rename_table_headers(text: str, old: str, new: str) -> str:
    """Rewrite ``[relative_due_dates.tables.<old>...]`` and ``[[...]]`` headers to ``<new>``.

    Only header lines are touched, so comments, key order and the layout of the
    table's items (inline or ``[[...items]]``) stay as they are.
    """
    pattern = re.compile(
        r"^(\s*\[\[?\s*" + re.escape(RELATIVE_DUE_DATES_KEY) + r"\s*\.\s*tables\s*\.\s*)"
        r"(?:\"" + re.escape(old) + r"\"|'" + re.escape(old) + r"'|" + re.escape(old) + r")"
        r"(?=\s*[.\]])",
        re.MULTILINE,
    )
    return pattern.sub(lambda m: m.group(1) + new, text)


_HEADER_LINE = re.compile(r"^\s*\[")


def _drop_table_block(text: str, name: str) -> str:
    """Delete the ``[relative_due_dates.tables.<name>]`` header and the lines under it."""
    lines = text.splitlines(keepends=True)
    header = re.compile(
        r"^\s*\[\s*" + re.escape(RELATIVE_DUE_DATES_KEY) + r"\s*\.\s*tables\s*\.\s*"
        r"(?:\"" + re.escape(name) + r"\"|'" + re.escape(name) + r"'|" + re.escape(name) + r")"
        r"\s*\]"
    )
    start = next((i for i, line in enumerate(lines) if header.match(line)), None)
    if start is None:
        return text
    end = start + 1
    while end < len(lines) and not _HEADER_LINE.match(lines[end]):
        end += 1
    if end == len(lines):
        # The last block: take the blank line that separated it from what precedes it.
        while start > 0 and not lines[start - 1].strip():
            start -= 1
    else:
        # Comment lines right above the next header belong to that header, not to this block.
        while end - 1 > start and lines[end - 1].lstrip().startswith("#"):
            end -= 1
    return "".join(lines[:start] + lines[end:])


def _migrate_relative_tables(state: UpgradeState) -> list[str]:
    """Make the relative-due-dates table selectable as ``default`` (migration 2 -> 3, part 2)."""
    text = tomlkit.dumps(state.settings_doc)
    data = tomllib.loads(text)
    section = data.get(RELATIVE_DUE_DATES_KEY)
    tables = section.get("tables") if isinstance(section, dict) else None
    if not isinstance(tables, dict) or not tables:
        return []
    names = sorted(tables)
    if names == [DEFAULT_TABLE]:
        return []

    def is_empty(table: Any) -> bool:
        return isinstance(table, dict) and not table.get("items") and set(table) <= {"items"}

    drop_empty_default = False
    if len(names) == 1:
        target = names[0]
    elif len(names) == 2 and DEFAULT_TABLE in names and is_empty(tables[DEFAULT_TABLE]):
        target = next(n for n in names if n != DEFAULT_TABLE)
        drop_empty_default = True
    else:
        return [
            f"NOTICE: {_TABLES_PATH} has tables {', '.join(names)}; `generate-due-dates` now "
            f"uses the table named {DEFAULT_TABLE!r} unless --table NAME is given"
        ]

    new_text = text
    if drop_empty_default:
        new_text = _drop_table_block(new_text, DEFAULT_TABLE)
    new_text = _rename_table_headers(new_text, target, DEFAULT_TABLE)

    expected = {DEFAULT_TABLE: tables[target]}  # the only table left, renamed
    try:
        renamed = tomllib.loads(new_text)[RELATIVE_DUE_DATES_KEY].get("tables")
    except (tomllib.TOMLDecodeError, KeyError):
        renamed = None
    if renamed != expected:
        return [
            f"NOTICE: could not rename [{_TABLES_PATH}.{target}] to {DEFAULT_TABLE!r} "
            f"automatically (unusual layout); left unchanged. Use --table {target}, or rename it by hand"
        ]

    state.settings_doc = tomlkit.parse(new_text)
    lines = []
    if drop_empty_default:
        lines.append(f"Remove the empty [{_TABLES_PATH}.{DEFAULT_TABLE}] table")
    lines.append(f"Rename [{_TABLES_PATH}.{target}] -> [{_TABLES_PATH}.{DEFAULT_TABLE}]")
    return lines


def _migrate_2_to_3(state: UpgradeState) -> list[str]:
    """The term file no longer names a table; the table used is ``default`` unless --table.

    Removes an uncommented ``relative_table`` from the in-repo term file and renames
    a lone (or the only non-empty) table to ``default``. Term files outside the repo
    are not reachable from here. Stamps the manifests.
    """
    lines: list[str] = []
    if settings_path(state.repo).exists() and read_repo_version(state.repo) < 3:
        lines.extend(_migrate_relative_tables(state))
        if state.term_doc is not None and "relative_table" in state.term_doc:
            del state.term_doc["relative_table"]
            state.term_changed = True
            lines.append(f"Remove relative_table from {TERM_RELPATH.as_posix()}")
    for path in state.manifests:
        lines.append(f"Record format version 3 in {path.name}")
    return lines


def _migrate_3_to_4(state: UpgradeState) -> list[str]:
    """Links inside block snippets become relative to the snippet file.

    Rewrites a snippet link when every file that includes the snippet resolved
    it to the same existing file; reports the links it cannot convert. See
    snippet_migration. Stamps the manifests.
    """
    from .snippet_migration import migrate_snippet_links

    lines: list[str] = []
    if read_repo_version(state.repo) < 4:
        writes, lines = migrate_snippet_links(state.repo)
        state.pending_writes.update(writes)
    for path in state.manifests:
        lines.append(f"Record format version 4 in {path.name}")
    return lines


#: The checkbox question type before format 5 (the IMS Common Cartridge name)
#: and from format 5 (Canvas's name, sent to the API unchanged).
OLD_MULTIPLE_ANSWERS_TYPE = "multiple_response_question"
NEW_MULTIPLE_ANSWERS_TYPE = "multiple_answers_question"

_QUESTION_TYPE_LINE = re.compile(
    r"^(\s*question_type\s*:\s*)([\"']?)" + OLD_MULTIPLE_ANSWERS_TYPE + r"\2(?=\s*(?:#.*)?$)",
    re.MULTILINE,
)


def _yaml_question_type(text: str) -> Any:
    try:
        data = yaml.safe_load(text)
    except yaml.YAMLError:
        return None
    return data.get("question_type") if isinstance(data, dict) else None


def _rename_question_type(text: str, in_snippets: bool) -> tuple[str, bool]:
    """(new text, whether the old type is still set) for one .md file.

    Only the YAML the tool reads is touched: a leading frontmatter block,
    split the same way ``convert.parse_frontmatter`` splits it, or, for a file
    under snippets/ without one, the whole file (a frontmatter snippet).
    """
    if text.startswith("---\n") and (end := text.find("\n---\n", 4)) != -1:
        start = 4
    elif in_snippets:
        start, end = 0, len(text)
    else:
        return text, False
    yaml_text = _QUESTION_TYPE_LINE.sub(
        lambda m: m.group(1) + m.group(2) + NEW_MULTIPLE_ANSWERS_TYPE + m.group(2),
        text[start:end],
    )
    still_old = _yaml_question_type(yaml_text) == OLD_MULTIPLE_ANSWERS_TYPE
    return text[:start] + yaml_text + text[end:], still_old


def _migrate_4_to_5(state: UpgradeState) -> list[str]:
    """``question_type: multiple_response_question`` becomes ``multiple_answers_question``.

    Rewrites the value in every visible .md file's frontmatter and in
    frontmatter snippets; reports any it cannot rewrite. Stamps the manifests.
    """
    lines: list[str] = []
    if read_repo_version(state.repo) < 5:
        snippets = state.repo / "snippets"
        for path in sorted(state.repo.rglob("*.md")):
            rel = path.relative_to(state.repo)
            if not path.is_file() or any(part.startswith(".") for part in rel.parts):
                continue
            try:
                text = path.read_text(encoding="utf-8")
            except (OSError, UnicodeDecodeError):
                continue
            if OLD_MULTIPLE_ANSWERS_TYPE not in text:
                continue
            new_text, still_old = _rename_question_type(text, path.is_relative_to(snippets))
            if new_text != text:
                state.pending_writes[path] = new_text
                lines.append(
                    f"Change question_type {OLD_MULTIPLE_ANSWERS_TYPE} -> "
                    f"{NEW_MULTIPLE_ANSWERS_TYPE} in {rel.as_posix()}"
                )
            if still_old:
                lines.append(
                    f"NOTICE: {rel.as_posix()} still sets question_type "
                    f"{OLD_MULTIPLE_ANSWERS_TYPE} in a form upgrade cannot rewrite; "
                    f"change it to {NEW_MULTIPLE_ANSWERS_TYPE} by hand"
                )
    for path in state.manifests:
        lines.append(f"Record format version 5 in {path.name}")
    return lines


def _migrate_5_to_6(state: UpgradeState) -> list[str]:
    """Question-file sections become H1 and feedback subsections H2.

    See question_migration. Stamps the manifests.
    """
    from .question_migration import migrate_question_sections

    lines: list[str] = []
    if read_repo_version(state.repo) < 6:
        writes, lines = migrate_question_sections(state.repo)
        state.pending_writes.update(writes)
    for path in state.manifests:
        lines.append(f"Record format version 6 in {path.name}")
    return lines


#: Top-level course_settings.toml key listing the course's group sets/group
#: categories by name (format 7).
GROUP_CATEGORIES_KEY = "group_categories"


def _migrate_6_to_7(state: UpgradeState) -> list[str]:
    """Add an empty top-level ``group_categories`` list; stamp the manifests.

    Format 7 lets ``group_category_id`` name a group set/group category; an
    older tool would drop the name on a discussion or send it to Canvas as an
    ID on an assignment. Content files need no change: numeric IDs stay valid.
    """
    lines: list[str] = []
    if not settings_path(state.repo).exists() or read_repo_version(state.repo) >= 7:
        pass  # nothing to edit, or the settings file is already at version 7
    elif GROUP_CATEGORIES_KEY in state.settings_doc:
        lines.append(f"{GROUP_CATEGORIES_KEY} is already present; left as it is")
    else:
        toml_write.insert_top_level_key(
            state.settings_doc, GROUP_CATEGORIES_KEY, toml_write.scalar_array([])
        )
        lines.append(
            f"Add an empty {GROUP_CATEGORIES_KEY} = [] list to {SETTINGS_RELPATH.name}"
        )
    for path in state.manifests:
        lines.append(f"Record format version 7 in {path.name}")
    return lines


#: The course-reference snippet (see convert.COURSE_REFERENCE_RELPATH).
COURSE_REFERENCE_SNIPPET_RELPATH = Path("snippets") / "inline" / "CANVAS_COURSE_REFERENCE.md"

_OLD_COURSE_REFERENCE_RE = re.compile(r"(https?://\S+/courses/)(\d+)/?")
_NEW_COURSE_REFERENCE_RE = re.compile(r"https?://\S+/courses/")


def _canvas_toml_course_id(repo: Path) -> int | None:
    """course_id from course_settings/canvas.toml, or None when unavailable."""
    path = repo / "course_settings" / "canvas.toml"
    try:
        with open(path, "rb") as f:
            value = tomllib.load(f).get("course_id")
        return int(value) if value is not None else None
    except (OSError, tomllib.TOMLDecodeError, TypeError, ValueError):
        return None


def _migrate_7_to_8(state: UpgradeState) -> list[str]:
    """The course-reference snippet loses its course ID; stamp the manifests.

    Format 8 expands snippets/inline/CANVAS_COURSE_REFERENCE.md to its first
    line with the config's course_id appended, and ignores the rest of the
    file. ``https://host/courses/12345`` becomes ``https://host/courses/``
    followed by the explanatory comment `import` writes. A file already in
    the new form is left alone; any other content stops the upgrade, because
    guessing would silently change every link built on it.
    """
    from .convert import COURSE_REFERENCE_COMMENT

    lines: list[str] = []
    path = state.repo / COURSE_REFERENCE_SNIPPET_RELPATH
    rel = COURSE_REFERENCE_SNIPPET_RELPATH.as_posix()
    if path.exists() and read_repo_version(state.repo) < 8:
        text = path.read_text(encoding="utf-8")
        first, _, rest = text.strip().partition("\n")
        first = first.strip()
        old = _OLD_COURSE_REFERENCE_RE.fullmatch(first)
        if _NEW_COURSE_REFERENCE_RE.fullmatch(first):
            lines.append(f"{rel} already ends in /courses/; left as it is")
        elif old and not rest.strip():
            prefix, old_id = old.group(1), int(old.group(2))
            state.pending_writes[path] = f"{prefix}\n{COURSE_REFERENCE_COMMENT}"
            lines.append(
                f"Remove course ID {old_id} from {rel} (it is now taken from "
                f"canvas.toml or --config) and add a comment explaining the file"
            )
            config_id = _canvas_toml_course_id(state.repo)
            if config_id is not None and config_id != old_id:
                lines.append(
                    f"NOTE: {rel} named course {old_id}, but "
                    f"course_settings/canvas.toml has course_id = {config_id}; "
                    f"links built on the snippet will now point to course {config_id}"
                )
        else:
            raise RepoFormatError(
                f"{path}: format version 8 uses only the first line of this "
                f"file, the course URL without its ID (for example "
                f"https://yourschool.instructure.com/courses/), and appends the "
                f"course_id from canvas.toml. upgrade expected the file to hold "
                f"a single URL ending in /courses/<number>, but it contains:\n"
                f"{text.rstrip()}\n"
                f"Edit the file so its first line is the course URL ending in "
                f"/courses/ (anything after the first line is ignored), then run "
                f"`markdown-to-canvas upgrade` again."
            )
    for manifest_path in state.manifests:
        lines.append(f"Record format version 8 in {manifest_path.name}")
    return lines


_RELATIVE_HEADER_RE = re.compile(
    rf"^[ \t]*\[[ \t]*{RELATIVE_DUE_DATES_KEY}[ \t]*\][ \t]*(#.*)?$", re.MULTILINE
)
_ANY_HEADER_RE = re.compile(r"^[ \t]*\[", re.MULTILINE)
#: A subtable header such as [relative_due_dates.tables.default].
_RELATIVE_SUBTABLE_RE = re.compile(
    rf"^[ \t]*\[\[?[ \t]*{RELATIVE_DUE_DATES_KEY}[ \t]*\.", re.MULTILINE
)


def _with_new_settings(text: str) -> tuple[str | None, list[str], list[str]]:
    """``text`` with format 9's settings added to [relative_due_dates].

    Returns (new text or None when nothing is added, messages, keys added). The
    commented-out cutoff is added unless a line of the section mentions it, and
    each default time unless the section sets that key. A section that exists
    only through its subtables (migration 1 -> 2 wrote just
    ``[relative_due_dates.tables.default]``) gets a ``[relative_due_dates]``
    header, placed before its first subtable.
    """
    header = _RELATIVE_HEADER_RE.search(text)
    if header is None:
        subtable = _RELATIVE_SUBTABLE_RE.search(text)
        if subtable is None:
            return None, [
                f"NOTICE: {SETTINGS_RELPATH.name} has no [{RELATIVE_DUE_DATES_KEY}] section; "
                f"{CUTOFF_KEY}, {', '.join(DEFAULT_TIMES)} were not added"
            ], []
        body = ""
    else:
        next_header = _ANY_HEADER_RE.search(text, header.end())
        body = text[header.end(): next_header.start() if next_header else len(text)]
    section = tomllib.loads(text).get(RELATIVE_DUE_DATES_KEY, {})

    messages: list[str] = []
    blocks: list[str] = []
    if CUTOFF_KEY in body:
        messages.append(f"[{RELATIVE_DUE_DATES_KEY}] already mentions {CUTOFF_KEY}; left as it is")
    else:
        blocks.append(CUTOFF_HELP)
        messages.append(f"Add a commented-out {CUTOFF_KEY} line to [{RELATIVE_DUE_DATES_KEY}]")
    added: list[str] = []
    times = ""
    for key, value in DEFAULT_TIMES.items():
        if key in section:
            messages.append(f"[{RELATIVE_DUE_DATES_KEY}] already sets {key}; left as it is")
        else:
            times += f'{key} = "{value}"\n'
            added.append(key)
            messages.append(f'Add {key} = "{value}" to [{RELATIVE_DUE_DATES_KEY}]')
    if times:
        blocks.append(DEFAULT_TIMES_HELP + times)
    if not blocks:
        return None, messages, []
    insert = "\n".join(blocks) + "\n"

    if header is None:
        at = subtable.start()
        messages.insert(0, f"Add a [{RELATIVE_DUE_DATES_KEY}] header")
        return text[:at] + f"[{RELATIVE_DUE_DATES_KEY}]\n" + insert + text[at:], messages, added
    # Just after the header line (and its newline, when there is one).
    after = text[: header.end()].rstrip("\r") + "\n"
    rest = text[header.end():].removeprefix("\n")
    return after + insert + rest, messages, added


def _migrate_8_to_9(state: UpgradeState) -> list[str]:
    """Add format 9's [relative_due_dates] settings; stamp the manifests.

    Format 9 adds ``dont_reschedule_dates_before`` (written commented out) and
    ``default_unlock_time`` / ``default_lock_time`` (written as real values) to
    ``[relative_due_dates]``; an older tool would reject them as unknown keys.
    The lines go directly under the section header (text-level, so the rest of
    the file is byte-identical), and the result is re-parsed to make sure
    nothing but the two keys was added.
    """
    lines: list[str] = []
    if settings_path(state.repo).exists() and read_repo_version(state.repo) < 9:
        text = tomlkit.dumps(state.settings_doc)
        new_text, messages, added = _with_new_settings(text)
        if new_text is None:
            lines.extend(messages)
        else:
            try:
                new_data = tomllib.loads(new_text)
                for key in added:
                    del new_data[RELATIVE_DUE_DATES_KEY][key]
                same = new_data == tomllib.loads(text)
            except (tomllib.TOMLDecodeError, KeyError):
                same = False
            if same:
                state.settings_doc = tomlkit.parse(new_text)
                lines.extend(messages)
            else:
                lines.append(
                    f"NOTICE: could not add {CUTOFF_KEY} and the default unlock and lock "
                    f"times to [{RELATIVE_DUE_DATES_KEY}] (unusual layout); left unchanged"
                )
    for manifest_path in state.manifests:
        lines.append(f"Record format version 9 in {manifest_path.name}")
    return lines


_TOP_DUE_DATES_RE = re.compile(r"^due_dates[ \t]*=", re.MULTILINE)


def _with_date_format(text: str) -> tuple[str | None, str]:
    """``text`` with format 10's ``replace_date_with_format`` line added.

    Returns (new text or None when the key is already set, message). The
    commented line goes directly above the top-level ``due_dates`` key (above
    any comment lines attached to it) when that key comes before the first
    table header, else before the first header, else at the end.
    """
    from .date_placeholders import DEFAULT_FORMAT, FORMAT_COMMENT, FORMAT_KEY

    if FORMAT_KEY in tomllib.loads(text):
        return None, f"{SETTINGS_RELPATH.name} already sets {FORMAT_KEY}; left as it is"
    header = _ANY_HEADER_RE.search(text)
    limit = header.start() if header else len(text)
    due = _TOP_DUE_DATES_RE.search(text, 0, limit)
    if due is not None:
        at = due.start()
        # Step back over comment lines directly above due_dates.
        while at > 0:
            prev_start = text.rfind("\n", 0, at - 1) + 1
            if text[prev_start:at].lstrip().startswith("#"):
                at = prev_start
            else:
                break
    else:
        at = limit
    block = f'{FORMAT_COMMENT}\n{FORMAT_KEY} = "{DEFAULT_FORMAT}"\n\n'
    before = text[:at]
    if before and not before.endswith("\n"):
        before += "\n"
    message = f'Add {FORMAT_KEY} = "{DEFAULT_FORMAT}" (date placeholder format)'
    return before + block + text[at:], message


def _migrate_9_to_10(state: UpgradeState) -> list[str]:
    """Add format 10's ``replace_date_with_format`` key; stamp the manifests.

    Format 10 adds ``[text]{.replace_date_with ...}`` date placeholders in
    content bodies and the top-level default-format key. Older files need no
    rewriting; the version changes so an older tool refuses a repo whose
    bodies it would upload with the placeholder markup still in them. The
    line is inserted text-level (the rest of the file stays byte-identical)
    and the result re-parsed to make sure only the key was added.
    """
    from .date_placeholders import FORMAT_KEY

    lines: list[str] = []
    if settings_path(state.repo).exists() and read_repo_version(state.repo) < 10:
        text = tomlkit.dumps(state.settings_doc)
        new_text, message = _with_date_format(text)
        if new_text is None:
            lines.append(message)
        else:
            try:
                new_data = tomllib.loads(new_text)
                del new_data[FORMAT_KEY]
                same = new_data == tomllib.loads(text)
            except (tomllib.TOMLDecodeError, KeyError):
                same = False
            if same:
                state.settings_doc = tomlkit.parse(new_text)
                lines.append(message)
            else:
                lines.append(
                    f"NOTICE: could not add {FORMAT_KEY} to {SETTINGS_RELPATH.name} "
                    f"(unusual layout); left unchanged. Placeholders use the default "
                    f"format until you add it as a top-level key."
                )
    for manifest_path in state.manifests:
        lines.append(f"Record format version 10 in {manifest_path.name}")
    return lines


#: Ordered migrations, keyed by the version they migrate *from*.
MIGRATIONS: dict[int, Migration] = {
    0: _migrate_0_to_1,
    1: _migrate_1_to_2,
    2: _migrate_2_to_3,
    3: _migrate_3_to_4,
    4: _migrate_4_to_5,
    5: _migrate_5_to_6,
    6: _migrate_6_to_7,
    7: _migrate_7_to_8,
    8: _migrate_8_to_9,
    9: _migrate_9_to_10,
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
        state.pending_writes = {}
        for line in migration(state):
            say(f"  {line}")
        if not noop:
            for old, new in state.renames:
                old.rename(new)
            for path, data in state.manifests.items():
                _write_manifest(path, data, version + 1)
            if state.term_changed and state.term_doc is not None:
                state.term_path.write_text(tomlkit.dumps(state.term_doc), encoding="utf-8")
                state.term_changed = False
            for path, text in state.pending_writes.items():
                path.write_text(text, encoding="utf-8")
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
