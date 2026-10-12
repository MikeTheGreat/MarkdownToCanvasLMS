"""``generate-due-dates``: write dates computed from relative offsets into ``due_dates``.

plan_generation() reads the repo (course_settings.toml, the term file, the content
files' titles) and returns a GenerationPlan without changing anything: the
per-entry diff and the warnings. apply_plan() writes the plan's changes into the
``due_dates`` array with tomlkit so everything else in the file keeps its
comments and layout. The command itself (cli.py) prints the plan, confirms, and
calls apply_plan().

When ``[relative_due_dates]`` sets ``dont_reschedule_dates_before``, a field whose
current value is a date at or before that cutoff is kept as it is (per field, not
per entry), and an entry left inconsistent by keeping some fields and changing
others is skipped with an error (see plan_generation).

The command never applies ``only_if`` or contacts Canvas; `update` sends the dates
to Canvas as it does for hand-written entries.
"""
from __future__ import annotations

import tomllib
from dataclasses import dataclass, field
from datetime import date, datetime
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

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
    kind: str  # "added", "changed", "unchanged" or "skipped" (inconsistent; nothing written)
    #: field -> (old value or None if absent, new value); only fields that change
    fields: dict[str, tuple[str | None, str]] = field(default_factory=dict)
    #: index of the existing entry in ``due_dates`` (None for an added one)
    index: int | None = None
    #: every computed value, for adding a new entry
    values: dict[str, str] = field(default_factory=dict)
    #: field -> (current value, computed value) for fields that would have changed
    #: but were kept because the current value is at or before the cutoff
    kept: dict[str, tuple[str, str]] = field(default_factory=dict)
    #: a virtual entry (``virtual = true``): only ``due_at``, never sent to Canvas
    virtual: bool = False
    #: why clamp_lock_at_to_last_day_of_term set lock_at (rd.CLAMPED_LATER or
    #: rd.CLAMPED_NONE), or None
    lock_clamped: str | None = None

    @property
    def label(self) -> str:
        if self.virtual:
            return f"{self.name} (virtual)"
        return self.name + (f" ({self.type})" if self.type else "")


@dataclass
class GenerationPlan:
    table_name: str
    changes: list[EntryChange]
    warnings: list[str]
    notices: list[str]
    settings_path: Path
    #: the text of course_settings.toml the plan was made from
    source_text: str
    #: dont_reschedule_dates_before, or None when no cutoff is set
    cutoff: datetime | None = None
    #: one message per skipped (inconsistent) entry; the command exits non-zero
    errors: list[str] = field(default_factory=list)
    #: date placeholders that will not resolve against the generated
    #: due_dates; the dates are still written, and the command exits non-zero
    placeholder_errors: list[str] = field(default_factory=list)
    #: the term's last day at 23:59, the limit clamped lock dates are set to
    term_end: datetime | None = None
    #: the fingerprint of [relative_due_dates] as read for this plan
    fingerprint: str = ""
    #: the last_generated_hash the file had, or None when it had none
    recorded_hash: str | None = None

    @property
    def has_changes(self) -> bool:
        return any(c.kind in ("added", "changed") for c in self.changes)

    @property
    def clean(self) -> bool:
        """No skipped entries and no unresolved placeholders: writing the plan
        brings due_dates in line with the section, so the fingerprint may be
        recorded."""
        return not self.errors and not self.placeholder_errors

    @property
    def hash_current(self) -> bool:
        return self.recorded_hash == self.fingerprint

    @property
    def not_rescheduled(self) -> list[EntryChange]:
        """Entries with at least one field kept by the cutoff (skipped ones included)."""
        return [c for c in self.changes if c.kept]

    @property
    def clamped(self) -> list[EntryChange]:
        """Entries whose planned lock_at comes from clamp_lock_at_to_last_day_of_term.

        Unchanged entries count; a lock_at kept by the cutoff, and a skipped
        entry (nothing written), do not."""
        return [
            c for c in self.changes
            if c.lock_clamped and c.kind != "skipped" and "lock_at" not in c.kept
        ]


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


def _is_virtual_entry(entry: Any) -> bool:
    from .sync import is_virtual_entry  # sync imports a lot; keep it lazy

    return is_virtual_entry(entry)


def _matches_entry(
    entry: dict[str, Any], name: str, item_type: str | None, virtual: bool = False
) -> bool:
    """A virtual item matches only virtual entries, an ordinary item only ordinary ones."""
    if entry.get("name") != name or _is_virtual_entry(entry) != virtual:
        return False
    entry_type = entry.get("type")
    return not (entry_type and item_type and entry_type != item_type)


def _find_entry(
    due_dates: list[Any], name: str, item_type: str | None, virtual: bool = False
) -> int | None:
    for i, entry in enumerate(due_dates):
        if isinstance(entry, dict) and _matches_entry(entry, name, item_type, virtual):
            return i
    return None


def _kind_clashes(table: rd.RelativeTable, due_dates: list[Any]) -> None:
    """Raise when an item and a due_dates entry share a name but not their kind
    (a virtual item and an ordinary entry, or the reverse)."""
    entries = [e for e in due_dates if isinstance(e, dict)]
    clashes: list[str] = []
    for item in table.items:
        if any(e.get("name") == item.name and _is_virtual_entry(e) != item.virtual for e in entries):
            if item.virtual:
                clashes.append(
                    f"  {item.name!r} is a virtual item but due_dates has an ordinary entry "
                    f"of that name; delete the entry (or make it virtual = true with only "
                    f"name and due_at)"
                )
            else:
                clashes.append(
                    f"  {item.name!r} is an ordinary item but due_dates has a virtual entry "
                    f"of that name; rename one of them"
                )
    if clashes:
        raise RelativeDueDatesError(
            f"[{rd.SECTION_KEY}.tables.{table.name}] and due_dates disagree about which names "
            f"are virtual. Nothing was written.\n" + "\n".join(clashes)
        )


def _as_datetime(value: Any, zone: ZoneInfo) -> datetime | None:
    """``value`` as an aware datetime (naive ones read in ``zone``), or None if not a date."""
    if not isinstance(value, str):
        return None
    try:
        parsed = datetime.fromisoformat(value.strip())
    except ValueError:
        return None
    return parsed if parsed.tzinfo is not None else parsed.replace(tzinfo=zone)


#: (earlier, later) pairs Canvas requires to be in order.
_DATE_ORDER = (("unlock_at", "due_at"), ("due_at", "lock_at"), ("unlock_at", "lock_at"))


def _inconsistency(change: EntryChange, existing: dict[str, Any], zone: ZoneInfo) -> str | None:
    """What is out of order in the entry's resulting dates, or None when they are in order.

    The result is the kept fields' current values plus the changed fields' new
    values (other fields already equal their computed value).
    """
    def source(key: str) -> tuple[Any, str]:
        if key in change.kept:
            return change.kept[key][0], "kept"
        if key in change.fields:
            return change.fields[key][1], "computed"
        return existing.get(key), "current"

    for early, late in _DATE_ORDER:
        (a, a_src), (b, b_src) = source(early), source(late)
        a_dt, b_dt = _as_datetime(a, zone), _as_datetime(b, zone)
        if a_dt is not None and b_dt is not None and a_dt > b_dt:
            return f"{early} ({a_src}, {a}) after {late} ({b_src}, {b})"
    return None


def _content_titles(repo: Path) -> list[tuple[str, str, str]]:
    """``(title, canvas_type, repo-relative path)`` of every assignment, discussion and quiz."""
    from .sync import iter_gradeable_content  # sync imports a lot; keep it lazy

    titles: list[tuple[str, str, str]] = []
    for key, md_path, ctype in iter_gradeable_content(repo, load_ignore_matcher(repo)):
        try:
            frontmatter, _ = parse_frontmatter(md_path.read_text(encoding="utf-8"))
        except Exception:
            frontmatter = {}
        titles.append((str(frontmatter.get("title", md_path.stem)), ctype, key))
    return titles


def _virtual_collisions(table: rd.RelativeTable, content: list[tuple[str, str, str]]) -> None:
    """Raise when a virtual item has the title of an assignment, discussion or quiz."""
    virtual = {i.name for i in table.items if i.virtual}
    hits = [(title, path) for title, _ctype, path in content if title in virtual]
    if hits:
        raise RelativeDueDatesError(
            f"[{rd.SECTION_KEY}.tables.{table.name}]: a virtual item names a date, so its "
            f"name cannot also be the title of an assignment, discussion or quiz. "
            f"Rename the item (and the items relative to it). Nothing was written.\n"
            + "\n".join(f"  virtual item {title!r} is the title of {path}" for title, path in hits)
        )


def title_warnings(
    table: rd.RelativeTable,
    due_dates: list[Any],
    content: list[tuple[str, str, str]],
) -> tuple[list[str], list[str]]:
    """(warnings, notices) about titles that do not line up.

    Each title is reported once and the message names the table(s) responsible:
    the relative table, ``due_dates``, or both. Virtual items name no content and
    produce no entry, so they are left out of every check.
    """
    ignore = set(table.ignore)
    items = [i for i in table.items if not i.virtual]
    virtual_names = {i.name for i in table.items if i.virtual}
    warnings: list[str] = []
    label = f"relative table {table.name!r}"

    def has_content(name: str, item_type: str | None) -> bool:
        return any(t == name and (not item_type or c == item_type) for t, c, _ in content)

    def in_table(title: str, ctype: str) -> bool:
        return any(i.name == title and (not i.type or i.type == ctype) for i in items)

    def in_due_dates(title: str, ctype: str) -> bool:
        return any(
            isinstance(e, dict) and not _is_virtual_entry(e) and e.get("name") == title
            and (not e.get("type") or e.get("type") == ctype)
            for e in due_dates
        )

    def produced(entry: dict[str, Any]) -> bool:
        if _is_virtual_entry(entry):
            return entry.get("name") in virtual_names
        return any(
            i.name == entry.get("name")
            and (not i.type or not entry.get("type") or i.type == entry.get("type"))
            for i in items
        )

    for item in items:
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
    for title, ctype, _path in content:
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
        if isinstance(e, dict) and e.get("name") not in ignore and not produced(e)
    ]
    notices: list[str] = []
    if leftovers:
        notices.append(
            f"due_dates entries not produced by {label} (left unchanged): "
            + ", ".join(repr(n) for n in leftovers)
        )
    return warnings, notices


def current_date(zone: ZoneInfo) -> date:
    """Today's date in ``zone`` (a function so tests can fix the date)."""
    return datetime.now(zone).date()


def check_term_not_over(term_path: Path, source: str) -> None:
    """Raise RelativeDueDatesError when the term's last_day is before today.

    Used only for a term taken from the registry's ``current_term``, to catch a
    registry entry left over from a term that has ended. Today is taken in the
    term file's time zone; a term that has not started yet passes, because due
    dates are normally generated before the first day. ``source`` says where the
    term came from, for the message.
    """
    term = rd.load_term(term_path)
    today = current_date(term.time_zone)
    if today > term.last_day:
        raise RelativeDueDatesError(
            f"The current term ({term_path}, from {source}) ended on "
            f"{term.last_day.isoformat()} (first day {term.first_day.isoformat()}), and "
            f"today is {today.isoformat()}. Point current_term at this term's file, "
            f"or pass --term."
        )


def _after_plan(due_dates: list[Any], changes: list[EntryChange]) -> list[dict[str, Any]]:
    """The due_dates entries as they will be once the plan is applied."""
    entries = [dict(e) if isinstance(e, dict) else e for e in due_dates]
    for change in changes:
        if change.kind == "changed":
            entries[change.index].update({k: new for k, (_old, new) in change.fields.items()})
        elif change.kind == "added":
            entries.append(_new_row(change))
    return entries


def _placeholder_errors(
    repo: Path, settings: dict[str, Any], due_dates: list[Any], changes: list[EntryChange]
) -> list[str]:
    """Every replace_date_with placeholder that will not resolve against the
    generated due_dates. ``only_if`` is not applied (this command never does),
    so every entry counts."""
    from . import date_placeholders

    try:
        ctx = date_placeholders.make_context(_after_plan(due_dates, changes), settings)
    except ValueError as exc:
        return [f"ERROR: {exc}"]
    return date_placeholders.check_repo(repo, ctx, load_ignore_matcher(repo))


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
    # Before calculating: a cutoff from an earlier term stops the run here.
    cutoff = rd.load_cutoff(settings, term, term_path)
    table = rd.select_table(rd.load_tables(settings), table_name)
    from .sync import check_virtual_due_dates  # sync imports a lot; keep it lazy

    due_dates = settings.get("due_dates", [])
    try:
        check_virtual_due_dates(due_dates, repo, load_ignore_matcher(repo))
    except ValueError as exc:
        raise RelativeDueDatesError(str(exc)) from exc
    calculation = rd.calculate(table, term)
    content = _content_titles(repo)
    _virtual_collisions(table, content)
    _kind_clashes(table, due_dates)

    changes: list[EntryChange] = []
    errors: list[str] = []
    for computed in calculation.dates:
        if computed.virtual:
            values = {"due_at": computed.due_at}
        else:
            values = {
                "unlock_at": computed.unlock_at, "due_at": computed.due_at,
                "lock_at": computed.lock_at,
            }
        index = _find_entry(due_dates, computed.name, computed.type, computed.virtual)
        if index is None:
            changes.append(
                EntryChange(computed.name, computed.type, "added", dict(
                    (k, (None, v)) for k, v in values.items()), None, values,
                    virtual=computed.virtual, lock_clamped=computed.lock_clamped)
            )
            continue
        existing = due_dates[index]
        differing = {
            k: (existing.get(k), v) for k, v in values.items() if not _same_value(existing.get(k), v)
        }
        kept: dict[str, tuple[str, str]] = {}
        if cutoff is not None:
            for key in list(differing):
                current = _as_datetime(existing.get(key), term.time_zone)
                if current is not None and current <= cutoff:
                    kept[key] = differing.pop(key)
        change = EntryChange(
            computed.name, computed.type, "changed" if differing else "unchanged",
            differing, index, values, kept, virtual=computed.virtual,
            lock_clamped=computed.lock_clamped,
        )
        if kept and differing:
            problem = _inconsistency(change, existing, term.time_zone)
            if problem is not None:
                errors.append(
                    f"ERROR: {change.label}: keeping the dates on or before "
                    f"{rd.cutoff_as_written(cutoff)} puts {problem}. None of its dates were "
                    f"changed; fix the entry by hand."
                )
                change.kind = "skipped"
                change.fields = {}
        changes.append(change)

    warnings, notices = title_warnings(table, due_dates, content)
    section = settings.get(rd.SECTION_KEY, {})
    return GenerationPlan(
        table_name=table.name,
        changes=changes,
        warnings=[*(f"WARNING: {w}" for w in calculation.warnings), *warnings],
        notices=notices,
        settings_path=settings_path,
        source_text=source_text,
        cutoff=cutoff,
        errors=errors,
        placeholder_errors=_placeholder_errors(repo, settings, due_dates, changes),
        term_end=datetime.combine(term.last_day, rd.TERM_END_TIME, tzinfo=term.time_zone),
        fingerprint=rd.fingerprint(section),
        recorded_hash=section.get(rd.HASH_KEY),
    )


# ---------------------------------------------------------------------------
# Showing the plan
# ---------------------------------------------------------------------------


def render_plan(plan: GenerationPlan, verbose: bool = False) -> list[tuple[str, bool]]:
    """Lines describing the plan, each with True when it describes a real change.

    The first line states the cutoff. Skipped entries are not listed here; their
    errors are in ``plan.errors``. With ``verbose``, the resources kept by the
    cutoff are listed under the line that counts them. Virtual entries are
    listed like the others; an added one has only ``due_at``.
    """
    if plan.cutoff is None:
        cutoff_line = f"Not rescheduling dates: no cutoff ({rd.CUTOFF_KEY} is not set)"
    else:
        cutoff_line = (
            f"Not rescheduling dates on or before: {rd.format_cutoff(plan.cutoff)} "
            f"({rd.CUTOFF_KEY})"
        )
    lines: list[tuple[str, bool]] = [
        (cutoff_line, False),
        (f"Relative table: {plan.table_name}", False),
    ]
    unchanged = 0
    for change in plan.changes:
        if change.kind == "unchanged":
            unchanged += 1
            continue
        if change.kind == "skipped":
            continue
        label = change.label
        if change.kind == "added":
            lines.append((f"{label} (new entry):", True))
            for key in sorted(change.values):
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
    kept = plan.not_rescheduled
    if kept and plan.cutoff is not None:
        noun = "resource was" if len(kept) == 1 else "resources were"
        lines.append((
            f"{len(kept)} {noun} not rescheduled because of {rd.CUTOFF_KEY} date of "
            f"{rd.format_cutoff(plan.cutoff)}",
            False,
        ))
        if verbose:
            for change in kept:
                fields = ", ".join(k for k in DATE_KEYS if k in change.kept)
                lines.append((f"\t{change.label}: {fields}", False))
    lines.extend(_clamp_lines(plan, verbose))
    if unchanged:
        lines.append((f"{unchanged} unchanged entr{'y' if unchanged == 1 else 'ies'}", False))
    lines.extend((n, False) for n in plan.notices)
    return lines


def _clamp_lines(plan: GenerationPlan, verbose: bool) -> list[tuple[str, bool]]:
    """The clamp_lock_at_to_last_day_of_term summary line (and, with verbose, its list)."""
    clamped = plan.clamped
    if not clamped or plan.term_end is None:
        return []
    later = sum(1 for c in clamped if c.lock_clamped == rd.CLAMPED_LATER)
    was_none = len(clamped) - later
    parts = []
    if later:
        parts.append(f"{later} {'was' if later == 1 else 'were'} later")
    if was_none:
        parts.append(f"{was_none} {'was' if was_none == 1 else 'were'} NONE")
    noun = "lock date" if len(clamped) == 1 else "lock dates"
    lines = [(
        f"{len(clamped)} {noun} set to the term's last day "
        f"({rd.format_cutoff(plan.term_end)}): {', '.join(parts)}",
        False,
    )]
    if verbose:
        for change in clamped:
            cause = "later" if change.lock_clamped == rd.CLAMPED_LATER else "was NONE"
            lines.append((f"\t{change.label}: {cause}", False))
    return lines


# ---------------------------------------------------------------------------
# Writing
# ---------------------------------------------------------------------------


def _new_row(change: EntryChange) -> dict[str, Any]:
    if change.virtual:
        return {"name": change.name, "virtual": True, "due_at": change.values["due_at"]}
    row: dict[str, Any] = {"name": change.name}
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


def _with_hash(text: str, value: str) -> str:
    """``text`` with ``last_generated_hash = value`` at the top level of
    ``[relative_due_dates]``.

    An existing key is replaced in place. A new one goes directly under the
    section header, with HASH_COMMENT above it, text-level like migration
    8 -> 9 so it cannot land inside a subtable; a section that exists only
    through its subtables gets a header. Raises RelativeDueDatesError if the
    parsed result is anything other than the old parse plus the key.
    """
    doc = tomlkit.parse(text)
    section = doc.get(rd.SECTION_KEY)
    if section is not None and rd.HASH_KEY in section:
        section[rd.HASH_KEY] = value
        new_text = tomlkit.dumps(doc)
    else:
        line = f"# {rd.HASH_COMMENT}\n{rd.HASH_KEY} = {tomlkit.string(value).as_string()}\n"
        new_text, _header_added = repo_format._insert_in_relative_section(text, line)
    expected = tomllib.loads(text)
    expected.setdefault(rd.SECTION_KEY, {})[rd.HASH_KEY] = value
    try:
        same = tomllib.loads(new_text) == expected
    except tomllib.TOMLDecodeError:
        same = False
    if not same:
        raise RelativeDueDatesError(
            f"could not add {rd.HASH_KEY} to [{rd.SECTION_KEY}] (unusual layout); "
            "nothing was written"
        )
    return new_text


def _check_unchanged(plan: GenerationPlan) -> None:
    path = plan.settings_path
    if path.read_text(encoding="utf-8") != plan.source_text:
        raise RelativeDueDatesError(f"{path} changed while generating; nothing was written")


def record_fingerprint(plan: GenerationPlan) -> None:
    """Write only ``last_generated_hash`` (a clean plan with nothing to change).

    Raises RelativeDueDatesError if the file changed since the plan was made.
    """
    _check_unchanged(plan)
    new_text = _with_hash(plan.source_text, plan.fingerprint)
    plan.settings_path.write_text(new_text, encoding="utf-8")


def apply_plan(plan: GenerationPlan) -> None:
    """Write the plan's added and changed entries into ``due_dates``.

    When the plan is clean, ``last_generated_hash`` is written in the same
    write. Everything else in course_settings.toml is left as it is. Raises
    RelativeDueDatesError if the file changed since the plan was made.
    """
    path = plan.settings_path
    _check_unchanged(plan)
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
    new_text = tomlkit.dumps(doc)
    if plan.clean:
        new_text = _with_hash(new_text, plan.fingerprint)
    path.write_text(new_text, encoding="utf-8")
