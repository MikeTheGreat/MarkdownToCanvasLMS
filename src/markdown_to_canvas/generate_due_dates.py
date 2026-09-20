"""``generate-due-dates``: write dates computed from relative offsets into ``due_dates``.

plan_generation() reads the repo (course_settings.toml, the term file, the content
files' titles) and returns a GenerationPlan without changing anything: the
per-entry diff and the warnings. apply_plan() writes the plan's changes into the
``due_dates`` array with tomlkit so everything else in the file keeps its
comments and layout. The command itself (cli.py) prints the plan, confirms, and
calls apply_plan().

The command never applies ``only_if`` or contacts Canvas; `update` sends the dates
to Canvas as it does for hand-written entries.
"""
from __future__ import annotations

import tomllib
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any

import tomlkit
from tomlkit.items import AoT, Array, Table

from . import relative_dates as rd
from . import repo_format, toml_write
from .convert import parse_frontmatter
from .ignore import load_ignore_matcher
from .relative_dates import RelativeDueDatesError

#: Order in which a new entry's date keys are written (as `import` writes them).
DATE_KEYS = ("unlock_at", "due_at", "lock_at")


@dataclass
class EntryChange:
    """What generating does to one ``due_dates`` entry."""

    name: str
    type: str | None
    kind: str  # "added", "changed" or "unchanged"
    #: field -> (old value or None if absent, new value); only fields that change
    fields: dict[str, tuple[str | None, str]] = field(default_factory=dict)
    #: index of the existing entry in ``due_dates`` (None for an added one)
    index: int | None = None
    #: every computed value, for adding a new entry
    values: dict[str, str] = field(default_factory=dict)


@dataclass
class GenerationPlan:
    table_name: str
    changes: list[EntryChange]
    warnings: list[str]
    notices: list[str]
    settings_path: Path
    #: the text of course_settings.toml the plan was made from
    source_text: str

    @property
    def has_changes(self) -> bool:
        return any(c.kind != "unchanged" for c in self.changes)


# ---------------------------------------------------------------------------
# Planning
# ---------------------------------------------------------------------------


def _same_value(old: Any, new: str) -> bool:
    """True when ``old`` (from due_dates) already says what ``new`` says."""
    if not isinstance(old, str):
        return False
    if old.strip().casefold() == new.casefold():
        return True
    try:
        a, b = datetime.fromisoformat(old.strip()), datetime.fromisoformat(new)
    except ValueError:
        return False
    return a.tzinfo is not None and b.tzinfo is not None and a == b


def _is_datetime(value: Any) -> bool:
    if not isinstance(value, str):
        return False
    try:
        datetime.fromisoformat(value.strip())
    except ValueError:
        return False
    return True


def _matches_entry(entry: dict[str, Any], name: str, item_type: str | None) -> bool:
    if entry.get("name") != name:
        return False
    entry_type = entry.get("type")
    return not (entry_type and item_type and entry_type != item_type)


def _find_entry(due_dates: list[Any], name: str, item_type: str | None) -> int | None:
    for i, entry in enumerate(due_dates):
        if isinstance(entry, dict) and _matches_entry(entry, name, item_type):
            return i
    return None


def _content_titles(repo: Path) -> list[tuple[str, str]]:
    """``(title, canvas_type)`` of every assignment, discussion and quiz in the repo."""
    from .sync import iter_gradeable_content  # sync imports a lot; keep it lazy

    titles: list[tuple[str, str]] = []
    for _key, md_path, ctype in iter_gradeable_content(repo, load_ignore_matcher(repo)):
        try:
            frontmatter, _ = parse_frontmatter(md_path.read_text(encoding="utf-8"))
        except Exception:
            frontmatter = {}
        titles.append((str(frontmatter.get("title", md_path.stem)), ctype))
    return titles


def title_warnings(
    table: rd.RelativeTable,
    due_dates: list[Any],
    content: list[tuple[str, str]],
) -> tuple[list[str], list[str]]:
    """(warnings, notices) about titles that do not line up.

    Each title is reported once and the message names the table(s) responsible:
    the relative table, ``due_dates``, or both.
    """
    ignore = set(table.ignore)
    warnings: list[str] = []
    label = f"relative table {table.name!r}"

    def has_content(name: str, item_type: str | None) -> bool:
        return any(t == name and (not item_type or c == item_type) for t, c in content)

    def in_table(title: str, ctype: str) -> bool:
        return any(i.name == title and (not i.type or i.type == ctype) for i in table.items)

    def in_due_dates(title: str, ctype: str) -> bool:
        return any(
            isinstance(e, dict) and e.get("name") == title
            and (not e.get("type") or e.get("type") == ctype)
            for e in due_dates
        )

    for item in table.items:
        if has_content(item.name, item.type):
            continue
        entry_index = _find_entry(due_dates, item.name, item.type)
        where = f"{label} and due_dates" if entry_index is not None else label
        kind = f" (type={item.type})" if item.type else ""
        warnings.append(
            f"WARNING: {item.name!r}{kind} is in {where} but matches no "
            f"assignment, discussion or quiz"
        )

    reported: set[tuple[str, str]] = set()
    for title, ctype in content:
        if (title, ctype) in reported or title in ignore or in_table(title, ctype):
            continue
        reported.add((title, ctype))
        if in_due_dates(title, ctype):
            warnings.append(
                f"WARNING: {ctype} {title!r} has a due_dates entry but no item in {label}; "
                f"its entry is left as it is"
            )
        else:
            warnings.append(
                f"WARNING: {ctype} {title!r} is in neither {label} nor due_dates"
            )

    leftovers = [
        str(e.get("name"))
        for e in due_dates
        if isinstance(e, dict)
        and e.get("name") not in ignore
        and not any(i.name == e.get("name") and (not i.type or not e.get("type") or i.type == e.get("type"))
                    for i in table.items)
    ]
    notices: list[str] = []
    if leftovers:
        notices.append(
            f"due_dates entries not produced by {label} (left unchanged): "
            + ", ".join(repr(n) for n in leftovers)
        )
    return warnings, notices


def plan_generation(repo: Path, term_path: Path, table_name: str | None = None) -> GenerationPlan:
    """Work out what ``generate-due-dates`` would do; changes nothing.

    Raises RepoFormatError (repo not at the current format version) or
    RelativeDueDatesError (bad settings or term file).
    """
    repo_format.check_repo_format(repo)
    settings_path = repo_format.settings_path(repo)
    if not settings_path.exists():
        raise RelativeDueDatesError(f"{settings_path} not found; is {repo} a course repo?")
    source_text = settings_path.read_text(encoding="utf-8")
    settings = tomllib.loads(source_text)

    term = rd.load_term(term_path)
    table = rd.select_table(rd.load_tables(settings), table_name)
    calculation = rd.calculate(table, term)

    due_dates = settings.get("due_dates", [])
    changes: list[EntryChange] = []
    for computed in calculation.dates:
        values = {"unlock_at": computed.unlock_at, "due_at": computed.due_at, "lock_at": computed.lock_at}
        index = _find_entry(due_dates, computed.name, computed.type)
        if index is None:
            changes.append(
                EntryChange(computed.name, computed.type, "added", dict(
                    (k, (None, v)) for k, v in values.items()), None, values)
            )
            continue
        existing = due_dates[index]
        differing = {
            k: (existing.get(k), v) for k, v in values.items() if not _same_value(existing.get(k), v)
        }
        changes.append(
            EntryChange(
                computed.name, computed.type, "changed" if differing else "unchanged",
                differing, index, values,
            )
        )

    warnings, notices = title_warnings(table, due_dates, _content_titles(repo))
    return GenerationPlan(
        table_name=table.name,
        changes=changes,
        warnings=[*(f"WARNING: {w}" for w in calculation.warnings), *warnings],
        notices=notices,
        settings_path=settings_path,
        source_text=source_text,
    )


# ---------------------------------------------------------------------------
# Showing the plan
# ---------------------------------------------------------------------------


def render_plan(plan: GenerationPlan) -> list[tuple[str, bool]]:
    """Lines describing the plan, each with True when it describes a real change."""
    lines: list[tuple[str, bool]] = [(f"Relative table: {plan.table_name}", False)]
    unchanged = 0
    for change in plan.changes:
        if change.kind == "unchanged":
            unchanged += 1
            continue
        label = change.name + (f" ({change.type})" if change.type else "")
        if change.kind == "added":
            lines.append((f"{label} (new entry):", True))
            for key in sorted(DATE_KEYS):
                lines.append((f"\t{key}: {change.values[key]}", True))
            continue
        lines.append((f"{label}:", True))
        for key in sorted(change.fields):
            old, new = change.fields[key]
            prefix = f"{key}: "
            if _is_datetime(old) and _is_datetime(new):
                # Two lines, values in the same columns, so the part that changed stands out.
                lines.append((f"\t{prefix}{old}", True))
                lines.append((f"\t{'-> '.rjust(len(prefix))}{new}", True))
            else:
                lines.append((f"\t{prefix}{'(absent)' if old is None else old} -> {new}", True))
    if unchanged:
        lines.append((f"{unchanged} unchanged entr{'y' if unchanged == 1 else 'ies'}", False))
    lines.extend((n, False) for n in plan.notices)
    return lines


# ---------------------------------------------------------------------------
# Writing
# ---------------------------------------------------------------------------


def _new_row(change: EntryChange) -> dict[str, str]:
    row: dict[str, str] = {"name": change.name}
    if change.type:
        row["type"] = change.type
    row.update({k: change.values[k] for k in DATE_KEYS})
    return row


def _first_table_position(doc: tomlkit.TOMLDocument) -> int:
    """Body index of the first table header (a new top-level key must go before it)."""
    for i, (_key, item) in enumerate(doc.body):
        if isinstance(item, (Table, AoT)):
            return i
    return len(doc.body)


def apply_plan(plan: GenerationPlan) -> None:
    """Write the plan's added and changed entries into ``due_dates``.

    Everything else in course_settings.toml is left as it is. Raises
    RelativeDueDatesError if the file changed since the plan was made.
    """
    path = plan.settings_path
    if path.read_text(encoding="utf-8") != plan.source_text:
        raise RelativeDueDatesError(f"{path} changed while generating; nothing was written")
    doc = tomlkit.parse(plan.source_text)
    due_dates = doc.get("due_dates")

    added = [c for c in plan.changes if c.kind == "added"]
    for change in plan.changes:
        if change.kind == "changed":
            entry = due_dates[change.index]
            for key, (_old, new) in change.fields.items():
                entry[key] = new

    if added:
        rows = [_new_row(c) for c in added]
        if due_dates is None:
            repo_format._insert_key(
                doc, _first_table_position(doc), "due_dates", toml_write.inline_table_array(rows)
            )
        elif isinstance(due_dates, AoT):
            for row in rows:
                table = tomlkit.table()
                toml_write.fill_table(table, row)
                due_dates.append(table)
        elif isinstance(due_dates, Array):
            for row in rows:
                due_dates.append(toml_write._inline_value(row))
        else:
            raise RelativeDueDatesError(f"{path}: due_dates must be an array of tables")
    path.write_text(tomlkit.dumps(doc), encoding="utf-8")
