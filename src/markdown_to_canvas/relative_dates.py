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
ANCHOR_TYPES = (
    "START_OF_QUARTER",
    "FIRST_CLASS_OF_QUARTER",
    "NO_DUE_DATE",
    "ASSIGNMENT",
    "ABSOLUTE_DATE",
)

CONTENT_TYPES = ("assignment", "discussion", "quiz")

DAY_ABBREVIATIONS = tuple(calendar.day_abbr)  # Mon .. Sun

NONE = "NONE"
KEEP = "KEEP"

_SETTING_KEYS = (
    "days_of_week",
    "class_on_noninstructional_days",
    "unlock_relative_default",
    "lock_relative_default",
    "default_unlock_time",
    "default_lock_time",
)
_TABLE_KEYS = _SETTING_KEYS + ("items", "ignore")
#: Section-wide only: a table may not set it (it describes the term, not a schedule).
CUTOFF_KEY = "dont_reschedule_dates_before"
_SECTION_KEYS = _SETTING_KEYS + ("tables", CUTOFF_KEY)
_ITEM_KEYS = ("name", "type", "relative_to", "offsets", "unlock_offset", "lock_offset")
_TERM_KEYS = (
    "first_day",
    "last_day",
    "time_zone",
    "default_due_time",
    "noninstructional_days",
)

#: The table to use is chosen on the command line (--table), never by the term file.
DEFAULT_TABLE = "default"

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


def _has_abs_time(offsets: tuple[str, ...]) -> bool:
    """True when one of ``offsets`` (already validated) sets the time of day."""
    return any(o != NONE and parse_offset(o, "").kind == "ABS_TIME" for o in offsets)


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
    #: The fixed date of an ABSOLUTE_DATE anchor; None for every other anchor.
    anchor_date: date | None = None

    @property
    def due_time_is_explicit(self) -> bool:
        """True when the item's own offsets set its due time (an ABS_TIME offset)."""
        return _has_abs_time(self.offsets)


@dataclass(frozen=True)
class TableSettings:
    """Settings after the table's own values were laid over the section's."""

    days_of_week: tuple[str, ...] | None
    class_on_noninstructional_days: bool
    #: None (or an empty tuple) means no default rule, so ``KEEP``.
    unlock_relative_default: tuple[str, ...] | None
    lock_relative_default: tuple[str, ...] | None
    #: Time of day for unlock / lock dates when nothing sets one explicitly.
    default_unlock_time: time | None = None
    default_lock_time: time | None = None


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
    _check_keys(relative_to, ("type", "assignment_name", "date"), f"{where} relative_to")
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

    anchor_date = None
    if anchor == "ABSOLUTE_DATE":
        if "date" not in relative_to:
            raise RelativeDueDatesError(
                f"{where}: relative_to type ABSOLUTE_DATE needs a date, e.g. "
                f"{{ type = \"ABSOLUTE_DATE\", date = \"2026-09-28\" }}"
            )
        anchor_date = _parse_date(relative_to["date"], f"{where}: relative_to date")
    elif "date" in relative_to:
        raise RelativeDueDatesError(
            f"{where}: date is only used with relative_to type ABSOLUTE_DATE"
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
        anchor_date=anchor_date,
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
    times = {}
    for key in ("default_unlock_time", "default_lock_time"):
        times[key] = getattr(base, key) if base else None
        if key in raw:
            times[key] = _parse_time(raw[key], f"{where} {key}")
    return TableSettings(days, on_holidays, unlock, lock, **times)


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


def select_table(tables: dict[str, RelativeTable], cli_name: str | None) -> RelativeTable:
    """Pick the table: ``--table``, else the one named ``default``."""
    names = ", ".join(sorted(tables)) or "(none)"
    if cli_name:
        if cli_name not in tables:
            raise RelativeDueDatesError(
                f"--table names {cli_name!r}, which is not a table in "
                f"[{SECTION_KEY}.tables]. Tables: {names}"
            )
        return tables[cli_name]
    if DEFAULT_TABLE in tables:
        return tables[DEFAULT_TABLE]
    if not tables:
        raise RelativeDueDatesError(
            f"[{SECTION_KEY}.tables] has no tables. Run `upgrade` to add an empty one."
        )
    raise RelativeDueDatesError(
        f"[{SECTION_KEY}.tables] has no table named {DEFAULT_TABLE!r}; choose one "
        f"with --table. Tables: {names}"
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
        if key == "relative_table":
            raise RelativeDueDatesError(
                f"{path}: unknown key 'relative_table'; the term file no longer names a "
                f"table. Remove it and choose the table with --table (default: the table "
                f"named {DEFAULT_TABLE!r}). Allowed keys are {', '.join(_TERM_KEYS)}"
            )
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

    return Term(first, last, zone, due_time, holidays)


# ---------------------------------------------------------------------------
# Rescheduling cutoff
# ---------------------------------------------------------------------------

#: The commented-out cutoff that `import` writes and migration 8 -> 9 adds.
CUTOFF_HELP = f"""\
# Dates already in due_dates on or before this cutoff are not rescheduled by
# `generate-due-dates`. "YYYY-MM-DD" means the end of that day; "YYYY-MM-DD HH:MM"
# also works. Read in the term file's time zone; it must fall inside the term.
# Empty ("") or absent: no cutoff. Only here, not in a table.
# {CUTOFF_KEY} = "YYYY-MM-DD"
"""

#: The default times `import` writes and migration 8 -> 9 adds, as real keys.
DEFAULT_TIMES = {"default_unlock_time": "00:00", "default_lock_time": "23:59"}

#: The comment written above them.
DEFAULT_TIMES_HELP = """\
# Time of day for computed unlock and lock dates. Not used for an item whose
# offsets set its due time (e.g. "17:00 ABS_TIME"): its unlock and lock dates
# keep that time. An ABS_TIME in the unlock or lock rule itself also wins.
"""

_CUTOFF_RE = re.compile(r"^(\d{4}-\d{2}-\d{2})(?: (\d{2}):(\d{2}))?$")

#: The cutoff for a date given without a time, and the end of the term's last day.
_END_OF_DAY = time(23, 59, 59)


def load_cutoff(settings: dict[str, Any], term: Term, term_path: Path) -> datetime | None:
    """The ``dont_reschedule_dates_before`` cutoff as an aware datetime, or None.

    ``"YYYY-MM-DD"`` means 23:59:59 that day; ``"YYYY-MM-DD HH:MM"`` that time.
    Both are read in the term's time zone. An absent key or ``""`` means no
    cutoff. Raises RelativeDueDatesError for any other value, and for a cutoff
    outside the term (00:00 on first_day through 23:59:59 on last_day): a cutoff
    left over from an earlier term would otherwise freeze the new term's dates.
    """
    section = settings.get(SECTION_KEY)
    if not isinstance(section, dict) or CUTOFF_KEY not in section:
        return None
    value = section[CUTOFF_KEY]
    where = f"[{SECTION_KEY}] {CUTOFF_KEY}"
    forms = '"YYYY-MM-DD" (the end of that day) or "YYYY-MM-DD HH:MM"'
    if isinstance(value, str) and value == "":
        return None
    match = _CUTOFF_RE.match(value) if isinstance(value, str) else None
    if match is None:
        raise RelativeDueDatesError(
            f"{where} = {value!r} is not a cutoff the tool can read. Use {forms} as a "
            f'quoted string, in the term file\'s time zone, or "" for no cutoff'
        )
    try:
        day = date.fromisoformat(match.group(1))
        at = _END_OF_DAY if match.group(2) is None else time(int(match.group(2)), int(match.group(3)))
    except ValueError:
        raise RelativeDueDatesError(
            f"{where} = {value!r} is not a real date and time. Use {forms}"
        ) from None
    cutoff = datetime.combine(day, at, tzinfo=term.time_zone)
    start = datetime.combine(term.first_day, time(0, 0), tzinfo=term.time_zone)
    end = datetime.combine(term.last_day, _END_OF_DAY, tzinfo=term.time_zone)
    if not start <= cutoff <= end:
        raise RelativeDueDatesError(
            f"{where} = {value!r} is outside the term in {term_path} (first_day "
            f"{term.first_day.isoformat()}, last_day {term.last_day.isoformat()}). It is "
            f"probably left over from an earlier term: set it to a date in this term, or "
            f'to "" for no cutoff. Nothing was written.'
        )
    return cutoff


def cutoff_as_written(cutoff: datetime) -> str:
    """The cutoff in the form the setting takes: ``2026-10-01`` or ``2026-10-01 08:30``."""
    if cutoff.time() == _END_OF_DAY:
        return cutoff.date().isoformat()
    return cutoff.strftime("%Y-%m-%d %H:%M")


def format_cutoff(cutoff: datetime) -> str:
    """``Thu Oct 1, 2026 11:59 PM PDT``: the cutoff as the output shows it."""
    hour = cutoff.strftime("%I").lstrip("0")
    return (
        f"{cutoff.strftime('%a %b')} {cutoff.day}, {cutoff.year} "
        f"{hour}:{cutoff.strftime('%M %p %Z')}"
    )


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
        elif item.anchor == "ABSOLUTE_DATE":
            assert item.anchor_date is not None  # guaranteed by _load_item
            day = item.anchor_date
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
        settings = self.table.settings
        if which == "unlock_at":
            rule = self._rule(item.unlock_offset, settings.unlock_relative_default)
            default_time = settings.default_unlock_time
        else:
            rule = self._rule(item.lock_offset, settings.lock_relative_default)
            default_time = settings.default_lock_time
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
        result = self._apply(due, rule, where)
        # The default time is only for dates whose time nothing chose: an
        # explicit due time carries over, and the rule's own ABS_TIME wins.
        if default_time is not None and not item.due_time_is_explicit and not _has_abs_time(rule):
            result = datetime.combine(result.date(), default_time)
        return self._format(result)

    def _format(self, local: datetime) -> str:
        return local.replace(tzinfo=self.term.time_zone).isoformat(timespec="seconds")

    def _absolute_root(self, item: RelativeItem) -> RelativeItem | None:
        """The ABSOLUTE_DATE item that ``item``'s due date counts from, if any."""
        seen: set[str] = set()
        while item.anchor == "ASSIGNMENT" and item.name not in seen:
            seen.add(item.name)
            base = self.by_name.get(item.anchor_name or "")
            if base is None:
                return None
            item = base
        return item if item.anchor == "ABSOLUTE_DATE" else None

    def _outside_term(self, item: RelativeItem, due: datetime) -> str:
        """The error line for an item whose due date falls outside the term."""
        line = f"item {item.name!r} is due {due.date().isoformat()}."
        root = self._absolute_root(item)
        if root is not None:
            assert root.anchor_date is not None
            fixed = f"ABSOLUTE_DATE {root.anchor_date.isoformat()}"
            if root is item:
                line += f" Its relative_to is {fixed}."
            else:
                line += f" It counts from {root.name!r}, whose relative_to is {fixed}."
            line += (
                " That date is probably left from an earlier term; if you left a note "
                "beside the item about where it belongs, put that back."
            )
        return line

    def compute(self) -> Calculation:
        result = Calculation()
        outside: list[str] = []
        for item in self.table.items:
            due = self.due(item)
            if due is not None and not self.term.first_day <= due.date() <= self.term.last_day:
                outside.append(self._outside_term(item, due))
            result.dates.append(
                ComputedDates(
                    name=item.name,
                    type=item.type,
                    due_at=NONE if due is None else self._format(due),
                    unlock_at=self._lock_field(item, "unlock_at", due),
                    lock_at=self._lock_field(item, "lock_at", due),
                )
            )
        if outside:
            count = len(outside)
            raise RelativeDueDatesError(
                f"{count} item{' is' if count == 1 else 's are'} due outside the term "
                f"({self.term.first_day.isoformat()} to {self.term.last_day.isoformat()}) "
                f"in [{SECTION_KEY}.tables.{self.table.name}]. Nothing was written.\n"
                + "\n".join(f"  {line}" for line in outside)
                + "\nFix the items (or the term file's first_day / last_day) and run "
                "generate-due-dates again."
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

    Raises RelativeDueDatesError for an anchor naming a missing item, a cycle, a
    CLASS_DAY offset with no days_of_week, or any due date outside the term
    (first_day .. last_day; unlock and lock dates are not checked). The
    out-of-term error lists every such item.
    """
    return _Calculator(table, term).compute()
