"""generate-due-dates arithmetic against MikesGradingTool's results.

tests/fixtures/grading_tool_relative_dates.json holds the relative tables of
real courses (101, 142, 143, harvested from the grading tool's config) with the
dates the grading tool computed for them. It is made by
scripts/record_grading_tool_dates.py; the grading tool itself is not needed here.

Two known differences, both deliberate (see relative_dates.py):

- The grading tool adds days to a time that keeps the UTC offset of its start
  date. Counting forward across the daylight-saving change (2026-11-01) its
  wall-clock time is an hour early (22:59); counting backwards across it, an
  hour late (00:59 on the next day). Ours keeps the local time, so those dates
  differ by exactly 60 minutes.
- Every other date must match exactly.
"""
from __future__ import annotations

import json
from datetime import date, datetime, time, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

import pytest

from markdown_to_canvas import relative_dates as rd

FIXTURE = json.loads(
    (Path(__file__).parent / "fixtures" / "grading_tool_relative_dates.json").read_text()
)
DST_ENDS = date(2026, 11, 1)  # US Pacific, 2026


def _term() -> rd.Term:
    t = FIXTURE["term"]
    return rd.Term(
        first_day=date.fromisoformat(t["first_day"]),
        last_day=date.fromisoformat(t["last_day"]),
        time_zone=ZoneInfo(t["time_zone"]),
        default_due_time=time.fromisoformat(t["default_due_time"]),
        noninstructional_days={
            date.fromisoformat(d["date"]): d["title"] for d in t["noninstructional_days"]
        },
        relative_table=None,
    )


@pytest.mark.parametrize("course", sorted(FIXTURE["courses"]))
def test_same_dates_as_the_grading_tool(course):
    data = FIXTURE["courses"][course]
    table = rd.load_tables({"relative_due_dates": data["section"]})[course]
    ours = {d.name: d.due_at for d in rd.calculate(table, _term()).dates}

    assert ours.keys() == data["expected"].keys()
    assert not any(v.startswith("ERROR") for v in data["expected"].values())

    shifted = 0
    for name, theirs in data["expected"].items():
        if theirs == "NONE":
            assert ours[name] == "NONE", name
            continue
        mine = datetime.fromisoformat(ours[name]).replace(tzinfo=None)
        expected = datetime.strptime(theirs, "%Y-%m-%d %H:%M")
        minutes = int((mine - expected).total_seconds() // 60)
        if minutes == 0:
            continue
        # Only the daylight-saving hour may differ, and only around the change.
        shifted += 1
        assert abs(minutes) == 60, f"{name}: {mine} vs {expected}"
        assert mine.date() >= DST_ENDS - timedelta(days=1), (
            f"{name}: differs well before the DST change ({mine} vs {expected})"
        )

    # Most of a real term's dates are before the change or re-anchored after it.
    assert shifted < len(ours) / 2


def test_fixture_covers_the_interesting_cases():
    """The courses used exercise a single class day, two class days with holidays
    skipped, first-class anchors, and NEAREST_CALENDAR_DAY. (ABS_TIME appears
    only in courses whose config is incomplete; test_relative_dates.py covers it.)"""
    kinds: set[str] = set()
    for data in FIXTURE["courses"].values():
        for table in data["section"]["tables"].values():
            for item in table["items"]:
                kinds.add(item["relative_to"]["type"])
                kinds.update(o.split(" ", 1)[1] for o in item["offsets"])
    assert {"ASSIGNMENT", "FIRST_CLASS_OF_QUARTER", "NO_DUE_DATE"} <= kinds
    assert {"CALENDAR_DAY", "CLASS_DAY", "NEAREST_CALENDAR_DAY"} <= kinds
    day_counts = {len(d["section"]["days_of_week"]) for d in FIXTURE["courses"].values()}
    assert day_counts == {1, 2}
