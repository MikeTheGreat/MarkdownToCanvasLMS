"""Relative due dates: offsets from the start of a term -> absolute dates.

The relative schedule lives in the ``[relative_due_dates]`` section of
``course_settings/course_settings.toml``; the parts that change every term (first
and last day, time zone, default due time, holidays) live in a separate *term
file* passed to ``generate-due-dates``. This module loads both and resolves each
item of one table to ``due_at`` / ``unlock_at`` / ``lock_at`` strings in the
form the ``due_dates`` table uses: an ISO 8601 date with UTC offset, ``NONE`` or
``KEEP``.

The arithmetic is a port of MikesGradingTool's ``calculateDueDate`` /
``apply_offsets_to_due_date``, with these deliberate differences:

- Offsets are applied to *local* calendar dates and the zone's UTC offset is
  attached at the end, so a 23:59 due time stays 23:59 across a daylight-saving
  change (the original moves it by an hour).
- Results are memoized per item, and the offsets list of an item is never
  modified (the original inserts into it for ``FIRST_CLASS_OF_QUARTER``).
- ``-N CLASS_DAY`` moves to the previous class day. The original looks for the
  *next* class day's index while moving backwards, which only agrees with it
  for one or two class days a week.
"""
from __future__ import annotations

import calendar
import re
import tomllib
from dataclasses import dataclass, field
from datetime import date, datetime, time, timedelta
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

SECTION_KEY = "relative_due_dates"

#: The relative_to types an item may use.
ANCHOR_TYPES = ("START_OF_QUARTER", "FIRST_CLASS_OF_QUARTER", "NO_DUE_DATE", "ASSIGNMENT")

CONTENT_TYPES = ("assignment", "discussion", "quiz")

DAY_ABBREVIATIONS = tuple(calendar.day_abbr)  # Mon .. Sun

NONE = "NONE"
KEEP = "KEEP"

_SETTING_KEYS = (
    "days_of_week",
    "class_on_noninstructional_days",
    "unlock_relative_default",
    "lock_relative_default",
)
_TABLE_KEYS = _SETTING_KEYS + ("items", "ignore")
_SECTION_KEYS = _SETTING_KEYS + ("tables",)
_ITEM_KEYS = ("name", "type", "relative_to", "offsets", "unlock_offset", "lock_offset")
_TERM_KEYS = (
    "first_day",
    "last_day",
    "time_zone",
    "default_due_time",
    "noninstructional_days",
    "relative_table",
)

#: Guards a runaway CLASS_DAY search (for example, every class day a holiday).
_MAX_CLASS_DAY_SEARCH = 3660


class RelativeDueDatesError(Exception):
    """A problem in the relative-due-dates settings or term file; the message says what.

    Deliberately not a ValueError: the CLI's ValueError handler would prefix the
    message with "KeyError or ValueError:".
    """


# ---------------------------------------------------------------------------
# Offsets
# ---------------------------------------------------------------------------

_INT_OFFSET = re.compile(r"^([+-]?\d+)\s+(CALENDAR_DAY|CLASS_DAY)$")
_DAY_OFFSET = re.compile(r"^([A-Za-z]{3})\s+NEAREST_CALENDAR_DAY$")
_TIME_OFFSET = re.compile(r"^(\d{1,2}:\d{2})\s+ABS_TIME$")


@dataclass(frozen=True)
class Offset:
    """One parsed offset. ``kind`` is CALENDAR_DAY, CLASS_DAY, NEAREST_CALENDAR_DAY or ABS_TIME."""

    kind: str
    days: int = 0  # CALENDAR_DAY, CLASS_DAY
    weekday: int = 0  # NEAREST_CALENDAR_DAY: 0 = Mon
    at: time | None = None  # ABS_TIME


def parse_offset(text: str, where: str) -> Offset:
    """Parse one offset string such as ``+7 CALENDAR_DAY``; ``where`` names it in errors."""
    if not isinstance(text, str):
        raise RelativeDueDatesError(f"{where}: offset {text!r} must be a string")
    stripped = text.strip()
    if m := _INT_OFFSET.match(stripped):
        return Offset(kind=m.group(2), days=int(m.group(1)))
    if m := _DAY_OFFSET.match(stripped):
        day = _parse_day(m.group(1), where)
        return Offset(kind="NEAREST_CALENDAR_DAY", weekday=DAY_ABBREVIATIONS.index(day))
    if m := _TIME_OFFSET.match(stripped):
        return Offset(kind="ABS_TIME", at=_parse_time(m.group(1), f"{where}: {text!r}"))
    raise RelativeDueDatesError(
        f"{where}: cannot read offset {text!r}. Use '+N CALENDAR_DAY', '+N CLASS_DAY', "
        f"'<Mon..Sun> NEAREST_CALENDAR_DAY' or 'HH:MM ABS_TIME'"
    )


def _parse_day(text: str, where: str) -> str:
    """Normalise a day abbreviation to ``Mon`` .. ``Sun`` (case-insensitive)."""
    for day in DAY_ABBREVIATIONS:
        if isinstance(text, str) and text.casefold() == day.casefold():
            return day
    raise RelativeDueDatesError(
        f"{where}: {text!r} is not a day abbreviation; use one of {', '.join(DAY_ABBREVIATIONS)}"
    )


def _parse_time(value: Any, where: str) -> time:
    if isinstance(value, time):
        return value.replace(second=0, microsecond=0)
    if isinstance(value, str):
        try:
            return datetime.strptime(value.strip(), "%H:%M").time()
        except ValueError:
            pass
    raise RelativeDueDatesError(f"{where} must be a time like 23:59, not {value!r}")


def _offset_list(value: Any, where: str) -> list[str]:
    """A string or list of strings as a list; validates each offset (or ``NONE``)."""
    if value is None:
        return []
    items = [value] if isinstance(value, str) else value
    if not isinstance(items, list):
        raise RelativeDueDatesError(f"{where} must be a string or a list of strings")
    out: list[str] = []
    for item in items:
        if isinstance(item, str) and item.strip().upper() == NONE:
            out.append(NONE)
        else:
            parse_offset(item, where)
            out.append(item.strip())
    if NONE in out and len(out) > 1:
        raise RelativeDueDatesError(f"{where}: NONE cannot be combined with other offsets")
    return out


# ---------------------------------------------------------------------------
# Settings
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class RelativeItem:
    """One row of a table's ``items``."""

    name: str
    type: str | None
    anchor: str
    anchor_name: str | None
    offsets: tuple[str, ...]
    #: None means "no rule of its own": the table / section default applies.
    unlock_offset: tuple[str, ...] | None
    lock_offset: tuple[str, ...] | None


@dataclass(frozen=True)
class TableSettings:
    """Settings after the table's own values were laid over the section's."""

    days_of_week: tuple[str, ...] | None
    class_on_noninstructional_days: bool
    #: None (or an empty tuple) means no default rule, so ``KEEP``.
    unlock_relative_default: tuple[str, ...] | None
    lock_relative_default: tuple[str, ...] | None


@dataclass(frozen=True)
class RelativeTable:
    name: str
    settings: TableSettings
    items: tuple[RelativeItem, ...]
    ignore: tuple[str, ...]


def _check_keys(mapping: dict[str, Any], allowed: tuple[str, ...], where: str) -> None:
    for key in mapping:
        if key not in allowed:
            raise RelativeDueDatesError(
                f"{where}: unknown key {key!r}; allowed keys are {', '.join(allowed)}"
            )


def _load_item(raw: Any, table: str, index: int) -> RelativeItem:
    where = f"[{SECTION_KEY}.tables.{table}] item {index + 1}"
    if not isinstance(raw, dict):
        raise RelativeDueDatesError(f"{where} must be a table with a name")
    name = raw.get("name")
    if not isinstance(name, str) or not name.strip():
        raise RelativeDueDatesError(f"{where} needs a name")
    where = f"[{SECTION_KEY}.tables.{table}] item {name!r}"
    _check_keys(raw, _ITEM_KEYS, where)

    item_type = raw.get("type")
    if item_type is not None and item_type not in CONTENT_TYPES:
        raise RelativeDueDatesError(
            f"{where}: type {item_type!r} must be one of {', '.join(CONTENT_TYPES)}"
        )

    relative_to = raw.get("relative_to")
    if not isinstance(relative_to, dict) or "type" not in relative_to:
        raise RelativeDueDatesError(
            f"{where}: relative_to must be a table with a type, e.g. "
            f"{{ type = \"START_OF_QUARTER\" }}"
        )
    _check_keys(relative_to, ("type", "assignment_name"), f"{where} relative_to")
    anchor = relative_to["type"]
    if anchor not in ANCHOR_TYPES:
        raise RelativeDueDatesError(
            f"{where}: relative_to type {anchor!r} must be one of {', '.join(ANCHOR_TYPES)}"
        )
    anchor_name = relative_to.get("assignment_name")
    if anchor == "ASSIGNMENT" and not isinstance(anchor_name, str):
        raise RelativeDueDatesError(
            f"{where}: relative_to type ASSIGNMENT needs an assignment_name"
        )
    if anchor != "ASSIGNMENT" and anchor_name is not None:
        raise RelativeDueDatesError(
            f"{where}: assignment_name is only used with relative_to type ASSIGNMENT"
        )

    offsets = _offset_list(raw.get("offsets"), f"{where} offsets")
    if NONE in offsets:
        raise RelativeDueDatesError(f"{where}: offsets cannot contain NONE")

    def lock_rule(key: str) -> tuple[str, ...] | None:
        if key not in raw:
            return None
        return tuple(_offset_list(raw[key], f"{where} {key}"))

    return RelativeItem(
        name=name.strip(),
        type=item_type,
        anchor=anchor,
        anchor_name=anchor_name,
        offsets=tuple(offsets),
        unlock_offset=lock_rule("unlock_offset"),
        lock_offset=lock_rule("lock_offset"),
    )


def _load_settings(raw: dict[str, Any], base: TableSettings | None, where: str) -> TableSettings:
    """The settings in ``raw`` laid over ``base`` (or over the defaults)."""
    days = base.days_of_week if base else None
    if "days_of_week" in raw:
        value = raw["days_of_week"]
        if not isinstance(value, list) or not value:
            raise RelativeDueDatesError(f"{where}: days_of_week must be a non-empty list")
        parsed = {_parse_day(v, f"{where} days_of_week") for v in value}
        # Chronological order: the class-day search steps to the next entry in the list.
        days = tuple(d for d in DAY_ABBREVIATIONS if d in parsed)
    on_holidays = base.class_on_noninstructional_days if base else False
    if "class_on_noninstructional_days" in raw:
        on_holidays = raw["class_on_noninstructional_days"]
        if not isinstance(on_holidays, bool):
            raise RelativeDueDatesError(
                f"{where}: class_on_noninstructional_days must be true or false"
            )
    unlock = base.unlock_relative_default if base else None
    if "unlock_relative_default" in raw:
        unlock = tuple(_offset_list(raw["unlock_relative_default"], f"{where} unlock_relative_default"))
    lock = base.lock_relative_default if base else None
    if "lock_relative_default" in raw:
        lock = tuple(_offset_list(raw["lock_relative_default"], f"{where} lock_relative_default"))
    return TableSettings(days, on_holidays, unlock, lock)


def load_tables(settings: dict[str, Any]) -> dict[str, RelativeTable]:
    """The named tables of ``[relative_due_dates]`` in a parsed course_settings.toml.

    Returns an empty dict when the section is absent. Each table's settings are
    the section's settings overridden by the table's own. Raises
    RelativeDueDatesError for unknown keys, bad values, and duplicate item names.
    """
    section = settings.get(SECTION_KEY)
    if section is None:
        return {}
    if not isinstance(section, dict):
        raise RelativeDueDatesError(f"{SECTION_KEY} must be a table")
    _check_keys(section, _SECTION_KEYS, f"[{SECTION_KEY}]")
    shared = _load_settings(section, None, f"[{SECTION_KEY}]")

    raw_tables = section.get("tables", {})
    if not isinstance(raw_tables, dict):
        raise RelativeDueDatesError(f"[{SECTION_KEY}.tables] must be a table of named tables")
    tables: dict[str, RelativeTable] = {}
    for name, raw in raw_tables.items():
        where = f"[{SECTION_KEY}.tables.{name}]"
        if not isinstance(raw, dict):
            raise RelativeDueDatesError(f"{where} must be a table")
        _check_keys(raw, _TABLE_KEYS, where)
        raw_items = raw.get("items", [])
        if not isinstance(raw_items, list):
            raise RelativeDueDatesError(f"{where}: items must be an array")
        items = tuple(_load_item(r, name, i) for i, r in enumerate(raw_items))
        for i, item in enumerate(items):
            for other in items[:i]:
                if other.name == item.name and (
                    other.type == item.type or None in (other.type, item.type)
                ):
                    raise RelativeDueDatesError(
                        f"{where}: more than one item named {item.name!r}"
                    )
        ignore = raw.get("ignore", [])
        if not isinstance(ignore, list) or not all(isinstance(t, str) for t in ignore):
            raise RelativeDueDatesError(f"{where}: ignore must be a list of titles")
        tables[name] = RelativeTable(
            name=name,
            settings=_load_settings(raw, shared, where),
            items=items,
            ignore=tuple(ignore),
        )
    return tables


def select_table(
    tables: dict[str, RelativeTable], cli_name: str | None, term_name: str | None
) -> RelativeTable:
    """Pick the table: ``--table``, else the term file's ``relative_table``, else the only one."""
    names = ", ".join(sorted(tables)) or "(none)"
    wanted = cli_name or term_name
    if wanted:
        if wanted not in tables:
            source = "--table" if cli_name else "the term file's relative_table"
            raise RelativeDueDatesError(
                f"{source} names {wanted!r}, which is not a table in [{SECTION_KEY}.tables]. "
                f"Tables: {names}"
            )
        return tables[wanted]
    if len(tables) == 1:
        return next(iter(tables.values()))
    if not tables:
        raise RelativeDueDatesError(
            f"[{SECTION_KEY}.tables] has no tables. Run `upgrade` to add an empty one."
        )
    raise RelativeDueDatesError(
        f"Several tables in [{SECTION_KEY}.tables]; choose one with --table or "
        f"relative_table in the term file. Tables: {names}"
    )


# ---------------------------------------------------------------------------
# Term file
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class Term:
    first_day: date
    last_day: date
    time_zone: ZoneInfo
    default_due_time: time
    noninstructional_days: dict[date, str]
    relative_table: str | None


def _parse_date(value: Any, where: str) -> date:
    if isinstance(value, datetime):
        raise RelativeDueDatesError(f"{where} must be a date like 2026-09-30, not {value!r}")
    if isinstance(value, date):
        return value
    if isinstance(value, str):
        try:
            return date.fromisoformat(value.strip())
        except ValueError:
            pass
    raise RelativeDueDatesError(f"{where} must be a date like 2026-09-30, not {value!r}")


def load_term(path: Path) -> Term:
    """Read a term file. Raises RelativeDueDatesError naming the file and the problem."""
    try:
        with open(path, "rb") as f:
            raw = tomllib.load(f)
    except FileNotFoundError:
        raise RelativeDueDatesError(f"Term file not found: {path}") from None
    except tomllib.TOMLDecodeError as exc:
        raise RelativeDueDatesError(f"{path} is not valid TOML: {exc}") from exc

    def need(key: str) -> Any:
        if key not in raw:
            raise RelativeDueDatesError(f"{path}: missing required key {key!r}")
        return raw[key]

    for key in raw:
        if key not in _TERM_KEYS:
            raise RelativeDueDatesError(
                f"{path}: unknown key {key!r}; allowed keys are {', '.join(_TERM_KEYS)}"
            )
    first = _parse_date(need("first_day"), f"{path}: first_day")
    last = _parse_date(need("last_day"), f"{path}: last_day")
    if last < first:
        raise RelativeDueDatesError(f"{path}: last_day is before first_day")
    zone_name = need("time_zone")
    try:
        zone = ZoneInfo(zone_name)
    except (ZoneInfoNotFoundError, ValueError, TypeError):
        raise RelativeDueDatesError(
            f"{path}: time_zone {zone_name!r} is not an IANA time zone name "
            f"(for example America/Los_Angeles)"
        ) from None
    due_time = _parse_time(need("default_due_time"), f"{path}: default_due_time")

    holidays: dict[date, str] = {}
    for i, entry in enumerate(raw.get("noninstructional_days", [])):
        where = f"{path}: noninstructional_days entry {i + 1}"
        if not isinstance(entry, dict) or "date" not in entry:
            raise RelativeDueDatesError(f"{where} needs a date (and a title)")
        holidays[_parse_date(entry["date"], f"{where} date")] = str(entry.get("title", ""))

    table = raw.get("relative_table")
    if table is not None and not isinstance(table, str):
        raise RelativeDueDatesError(f"{path}: relative_table must be a string")
    return Term(first, last, zone, due_time, holidays, table)


# ---------------------------------------------------------------------------
# Calculation
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class ComputedDates:
    """The three date fields for one item, as ``due_dates`` writes them."""

    name: str
    type: str | None
    due_at: str
    unlock_at: str
    lock_at: str


@dataclass
class Calculation:
    dates: list[ComputedDates] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)


class _Calculator:
    def __init__(self, table: RelativeTable, term: Term):
        self.table = table
        self.term = term
        self.by_name: dict[str, RelativeItem] = {}
        for item in table.items:
            self.by_name.setdefault(item.name, item)
        #: item name -> due datetime (naive, local) or None; the memo.
        self._due: dict[str, datetime | None] = {}
        self._in_progress: list[str] = []
        self.warnings: list[str] = []

    # -- offsets ------------------------------------------------------------

    def _class_days(self, where: str) -> tuple[str, ...]:
        days = self.table.settings.days_of_week
        if not days:
            raise RelativeDueDatesError(
                f"{where} needs class days but days_of_week is set neither in "
                f"[{SECTION_KEY}.tables.{self.table.name}] nor in [{SECTION_KEY}]"
            )
        return days

    def _move_class_days(self, day: date, how_many: int, where: str) -> date:
        days = self._class_days(where)
        n = len(days)
        step = 1 if how_many > 0 else -1
        skip_holidays = not self.table.settings.class_on_noninstructional_days
        searched = 0
        while how_many != 0:
            current = days.index(_abbr(day)) if _abbr(day) in days else None
            wanted = (current + step) % n if current is not None else None
            moved = False
            while not moved or current is None or current != wanted:
                day += timedelta(days=step)
                moved = True
                searched += 1
                if searched > _MAX_CLASS_DAY_SEARCH:
                    raise RelativeDueDatesError(f"{where}: no usable class day found")
                if _abbr(day) in days:
                    current = days.index(_abbr(day))
                    if wanted is None:
                        # started between class days: the first one found is the target
                        wanted = current
                    if skip_holidays and day in self.term.noninstructional_days:
                        wanted = (wanted + step) % n
                else:
                    current = None
            how_many -= step
        return day

    def _apply(self, start: datetime, offsets: tuple[str, ...], where: str) -> datetime:
        due = start
        for text in offsets:
            off = parse_offset(text, where)
            if off.kind == "CALENDAR_DAY":
                due += timedelta(days=off.days)
            elif off.kind == "CLASS_DAY":
                moved = self._move_class_days(due.date(), off.days, f"{where} ({text})")
                due = datetime.combine(moved, due.time())
            elif off.kind == "NEAREST_CALENDAR_DAY":
                due = datetime.combine(_nearest_weekday(due.date(), off.weekday), due.time())
            else:  # ABS_TIME
                due = datetime.combine(due.date(), off.at)
        return due

    # -- due dates ----------------------------------------------------------

    def due(self, item: RelativeItem) -> datetime | None:
        """The item's due datetime (naive, local), or None for NO_DUE_DATE. Memoized."""
        if item.name in self._due:
            return self._due[item.name]
        if item.name in self._in_progress:
            cycle = " -> ".join([*self._in_progress[self._in_progress.index(item.name):], item.name])
            raise RelativeDueDatesError(
                f"[{SECTION_KEY}.tables.{self.table.name}]: circular relative_to: {cycle}"
            )
        self._in_progress.append(item.name)
        try:
            result = self._compute_due(item)
        finally:
            self._in_progress.pop()
        self._due[item.name] = result
        return result

    def _compute_due(self, item: RelativeItem) -> datetime | None:
        where = f"[{SECTION_KEY}.tables.{self.table.name}] item {item.name!r}"
        offsets = item.offsets
        if item.anchor == "NO_DUE_DATE":
            return None
        if item.anchor in ("START_OF_QUARTER", "FIRST_CLASS_OF_QUARTER"):
            day = self.term.first_day
            if item.anchor == "FIRST_CLASS_OF_QUARTER":
                offsets = ("-1 CALENDAR_DAY", "+1 CLASS_DAY", *offsets)
        else:
            base = self.by_name.get(item.anchor_name or "")
            if base is None:
                raise RelativeDueDatesError(
                    f"{where}: relative_to names {item.anchor_name!r}, which is not an item "
                    f"of table {self.table.name!r}"
                )
            base_due = self.due(base)
            if base_due is None:
                raise RelativeDueDatesError(
                    f"{where}: relative_to names {base.name!r}, which has no due date "
                    f"(NO_DUE_DATE), so there is nothing to count from"
                )
            day = base_due.date()
        # The default due time is set first; a later ABS_TIME offset can replace it.
        start = datetime.combine(day, self.term.default_due_time)
        return self._apply(start, offsets, where)

    # -- lock / unlock ------------------------------------------------------

    @staticmethod
    def _rule(own: tuple[str, ...] | None, default: tuple[str, ...] | None) -> tuple[str, ...]:
        """The item's own rule, else the default; empty means no rule (``KEEP``)."""
        return own if own is not None else (default or ())

    def _lock_field(self, item: RelativeItem, which: str, due: datetime | None) -> str:
        if which == "unlock_at":
            rule = self._rule(item.unlock_offset, self.table.settings.unlock_relative_default)
        else:
            rule = self._rule(item.lock_offset, self.table.settings.lock_relative_default)
        if not rule:
            return KEEP
        if rule == (NONE,):
            return NONE
        if due is None:
            self.warnings.append(
                f"item {item.name!r} has no due date, so its {which} rule "
                f"({', '.join(rule)}) cannot be applied; writing {KEEP}"
            )
            return KEEP
        where = f"[{SECTION_KEY}.tables.{self.table.name}] item {item.name!r} {which}"
        return self._format(self._apply(due, rule, where))

    def _format(self, local: datetime) -> str:
        return local.replace(tzinfo=self.term.time_zone).isoformat(timespec="seconds")

    def compute(self) -> Calculation:
        result = Calculation()
        for item in self.table.items:
            due = self.due(item)
            result.dates.append(
                ComputedDates(
                    name=item.name,
                    type=item.type,
                    due_at=NONE if due is None else self._format(due),
                    unlock_at=self._lock_field(item, "unlock_at", due),
                    lock_at=self._lock_field(item, "lock_at", due),
                )
            )
        result.warnings = self.warnings
        return result


def _abbr(day: date) -> str:
    return DAY_ABBREVIATIONS[day.weekday()]


def _nearest_weekday(day: date, weekday: int) -> date:
    """The closest date, earlier or later, on ``weekday`` (0 = Mon); ``day`` itself if it is one."""
    for k in range(7):
        ahead = day + timedelta(days=k)
        if ahead.weekday() == weekday:
            return ahead
        behind = day - timedelta(days=k)
        if behind.weekday() == weekday:
            return behind
    return day  # unreachable: every weekday occurs within 3 days of any date


def calculate(table: RelativeTable, term: Term) -> Calculation:
    """Resolve every item of ``table`` to its three date fields.

    Raises RelativeDueDatesError for an anchor naming a missing item, a cycle, or
    a CLASS_DAY offset with no days_of_week.
    """
    return _Calculator(table, term).compute()
