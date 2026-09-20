#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.11"
# dependencies = ["tomlkit>=0.12"]
# ///
"""
Print MikesGradingTool's due date settings in the form `generate-due-dates` reads:
a course's [relative_due_dates] section (paste into course_settings.toml), or,
with --term, the term file (save it, e.g. as course_settings/term_dates.toml).

The grading tool keeps each course's schedule in its config.json: the class days
under courses/<course>/due_date_info and, for every assignment, a
"due_date": {"relative_to": ..., "offsets": [...]} entry. This script reads that
file (JSON with // comments) and writes the same schedule in the form
`generate-due-dates` reads. Items are keyed by the assignment's Canvas name,
because that is what course_settings.toml matches on; an "ASSIGNMENT" anchor is
rewritten from the grading tool's own key to the anchor's Canvas name.

The script needs only `uv` (it installs tomlkit itself), not the markdown-to-canvas
environment, so it can be copied anywhere on your PATH, made executable, and run
by name.

Installation
-----
cp scripts/harvest_relative_due_dates.py ~/bin/zzHarvestRelativeDueDates.py
chmod +x ~/bin/zzHarvestRelativeDueDates.py   # already set on the source, but cp may not keep it


Usage
-----
    harvest_relative_due_dates.py <config.json> <course> [--table NAME]
    harvest_relative_due_dates.py <config.json> --term [<course>]

    <config.json>   The grading tool's config, e.g. mikes_config/config.json.
    <course>        A key under "courses", e.g. 142 or 143s (aliases are not resolved).
    --table NAME    Name of the table to write (default: the course key).
    --term          Print the term file instead: the quarter's first and last day,
                    time zone, default due time and non-instructional days, from
                    the config's top-level "due_date_info" and "app-wide_config".
                    The term file no longer names a table: pass the table to
                    `generate-due-dates` with --table <name> (the course key
                    unless --table was given here; `default` is used when
                    --table is omitted there).

Output goes to stdout, so redirect it or paste it. Notes about anything that could
not be carried over (assignments without a due_date or a Canvas name) go to stderr.

Lock and unlock dates are not in the grading tool's config, so no lock or unlock
rules are written; add unlock_relative_default / lock_relative_default by hand.

Examples
-----
Then run it like this:

zzHarvestRelativeDueDates.py ~/.../mikes_config/config.json 142          # relative table
zzHarvestRelativeDueDates.py ~/.../mikes_config/config.json --term 142   # term file

"""

from __future__ import annotations

import argparse
import json
import sys
import calendar
from datetime import date
from pathlib import Path
from typing import Any

import tomlkit

DAY_ABBREVIATIONS = tuple(calendar.day_abbr)  # Mon .. Sun


def strip_json_comments(text: str) -> str:
    """Remove ``//`` line comments and ``/* */`` block comments, leaving strings alone."""
    out: list[str] = []
    i, n = 0, len(text)
    in_string = False
    while i < n:
        ch = text[i]
        if in_string:
            out.append(ch)
            if ch == "\\" and i + 1 < n:
                out.append(text[i + 1])
                i += 1
            elif ch == '"':
                in_string = False
        elif ch == '"':
            in_string = True
            out.append(ch)
        elif text.startswith("//", i):
            while i < n and text[i] != "\n":
                i += 1
            continue
        elif text.startswith("/*", i):
            end = text.find("*/", i + 2)
            i = n if end == -1 else end + 1
        else:
            out.append(ch)
        i += 1
    return "".join(out)


def load_config(path: Path) -> dict[str, Any]:
    return json.loads(strip_json_comments(path.read_text(encoding="utf-8")))


def _canvas_name(assignment: dict[str, Any]) -> str | None:
    name = assignment.get("canvas_api", {}).get("canvas_name")
    return " ".join(name.split()) if isinstance(name, str) and name.strip() else None


def _day(text: str) -> str:
    for day in DAY_ABBREVIATIONS:
        if text.casefold() == day.casefold():
            return day
    raise SystemExit(
        f"Class day {text!r} is not one of {', '.join(DAY_ABBREVIATIONS)}. "
        f"Fix days_of_week in the grading tool's config first."
    )


def build_section(
    config: dict[str, Any], course: str, table_name: str
) -> tuple[dict, list[str]]:
    """The ``[relative_due_dates]`` data for ``course`` and notes about skipped items."""
    courses = config.get("courses", {})
    if course not in courses or not isinstance(courses[course], dict):
        known = sorted(k for k, v in courses.items() if isinstance(v, dict))
        raise SystemExit(
            f"No course {course!r} in the config. Courses: {', '.join(known)}"
        )
    info = courses[course]
    due_info = info.get("due_date_info") or {}
    assignments = info.get("assignments") or {}

    names = {
        key: _canvas_name(a) for key, a in assignments.items() if isinstance(a, dict)
    }
    notes: list[str] = []
    items: list[dict[str, Any]] = []
    for key, assignment in assignments.items():
        if not isinstance(assignment, dict):
            continue
        canvas_name = names.get(key)
        if canvas_name is None:
            notes.append(f"skipped {key!r}: no canvas_api.canvas_name")
            continue
        due = assignment.get("due_date")
        if not isinstance(due, dict):
            notes.append(f"skipped {canvas_name!r}: no due_date")
            continue
        relative_to = dict(due.get("relative_to") or {})
        anchor = relative_to.get("type")
        if anchor is None:
            notes.append(f"skipped {canvas_name!r}: due_date has no relative_to type")
            continue
        row_anchor: dict[str, Any] = {"type": anchor}
        if anchor == "ASSIGNMENT":
            target = relative_to.get("assignment_name")
            target_name = names.get(target)
            if target_name is None:
                notes.append(
                    f"skipped {canvas_name!r}: it is relative to {target!r}, "
                    f"which has no Canvas name in the config"
                )
                continue
            row_anchor["assignment_name"] = target_name
        items.append(
            {
                "name": canvas_name,
                "relative_to": row_anchor,
                "offsets": list(due.get("offsets") or []),
            }
        )

    section: dict[str, Any] = {}
    if due_info.get("days_of_week"):
        section["days_of_week"] = [_day(d) for d in due_info["days_of_week"]]
    section["class_on_noninstructional_days"] = bool(
        due_info.get("class_on_noninstructional_days", False)
    )
    section["tables"] = {table_name: {"items": items}}
    return section, notes


def build_term(config: dict[str, Any], course: str | None) -> dict[str, Any]:
    """The term file's data from the grading tool's term-wide settings."""
    info = config.get("due_date_info") or {}
    zone = (config.get("app-wide_config") or {}).get("preferred_time_zone")
    missing = [
        name
        for name, value in (
            (
                "due_date_info/date_of_first_day_of_the_quarter",
                info.get("date_of_first_day_of_the_quarter"),
            ),
            (
                "due_date_info/date_of_last_day_of_the_quarter",
                info.get("date_of_last_day_of_the_quarter"),
            ),
            (
                "due_date_info/assignment_default_due_time",
                info.get("assignment_default_due_time"),
            ),
            ("app-wide_config/preferred_time_zone", zone),
        )
        if not value
    ]
    if missing:
        raise SystemExit(f"The config has no {', '.join(missing)}")
    term: dict[str, Any] = {
        "first_day": date.fromisoformat(info["date_of_first_day_of_the_quarter"]),
        "last_day": date.fromisoformat(info["date_of_last_day_of_the_quarter"]),
        "time_zone": zone,
        "default_due_time": info["assignment_default_due_time"],
    }
    holidays = [
        {"title": d["title"], "date": date.fromisoformat(d["date"])}
        for d in info.get("noninstructional_days", [])
        if isinstance(d, dict) and "title" in d and "date" in d
    ]
    if holidays:
        term["noninstructional_days"] = holidays
    return term


def _value(value: Any) -> Any:
    """A tomlkit value: dicts become inline tables, lists become arrays."""
    if isinstance(value, dict):
        table = tomlkit.inline_table()
        for k, v in value.items():
            table.append(k, _value(v))
        return table
    if isinstance(value, list):
        array = tomlkit.array()
        for v in value:
            array.append(_value(v))
        if value and all(isinstance(v, dict) for v in value):
            array.multiline(True)  # one row per line
        return array
    return tomlkit.item(value)


def _fill(container: Any, data: dict[str, Any]) -> None:
    """Plain keys first, then sub-tables: tomlkit appends, so a key added after a
    table header would land inside that table."""
    for key, value in data.items():
        if not isinstance(value, dict):
            container.add(key, _value(value))
    for key, value in data.items():
        if isinstance(value, dict):
            table = tomlkit.table(
                is_super_table=all(isinstance(v, dict) for v in value.values())
            )
            _fill(table, value)
            container.add(key, table)


def _comments(container: Any, lines: list[str]) -> None:
    for line in lines:
        container.add(tomlkit.comment(line) if line else tomlkit.nl())


def render_term(term: dict[str, Any]) -> str:
    doc = tomlkit.document()
    _comments(
        doc,
        [
            "Term file harvested from MikesGradingTool's config.",
            "Save it (for example as course_settings/term_dates.toml) and pass it to",
            "`markdown-to-canvas generate-due-dates`.",
            "",
        ],
    )
    _fill(doc, term)
    return tomlkit.dumps(doc)


def render(section: dict[str, Any], course: str) -> str:
    doc = tomlkit.document()
    _comments(
        doc,
        [
            f"Relative due dates harvested from MikesGradingTool, course {course}.",
            "Paste over the [relative_due_dates] section of course_settings.toml.",
            "Lock and unlock rules are not in the grading tool's config; add",
            "unlock_relative_default / lock_relative_default here if you want them.",
            "",
        ],
    )
    _fill(doc, {"relative_due_dates": section})
    return tomlkit.dumps(doc)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("config", type=Path, help="the grading tool's config.json")
    parser.add_argument("course", nargs="?", help="a key under courses, e.g. 142")
    parser.add_argument("--table", help="name for the table (default: the course key)")
    parser.add_argument(
        "--term", action="store_true", help="print the term file instead"
    )
    args = parser.parse_args(argv)

    if args.term:
        sys.stdout.write(
            render_term(build_term(load_config(args.config), args.table or args.course))
        )
        return 0
    if not args.course:
        parser.error("a course is required unless --term is given")

    section, notes = build_section(
        load_config(args.config), args.course, args.table or args.course
    )
    sys.stdout.write(render(section, args.course))
    for note in notes:
        print(f"note: {note}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
