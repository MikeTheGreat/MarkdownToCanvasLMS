#!/usr/bin/env python3
"""
Record what MikesGradingTool computes for some courses' relative due dates, as a
test fixture (tests/fixtures/grading_tool_relative_dates.json).

tests/test_relative_dates_vs_grading_tool.py checks that `generate-due-dates`
gives the same dates as the grading tool for the same inputs. The test does not
need the grading tool: this script runs it once and stores the inputs (the
harvested [relative_due_dates] table and the term) and its results.

The grading tool's date functions are copied out of CanvasHelper.py with `ast`
and run in an empty namespace, so importing the grading tool (and its config,
disk cache and Canvas dependencies) is not needed. Only `pytz` is:

    uv run --with pytz python scripts/record_grading_tool_dates.py \\
        /path/to/MikesGradingTool /path/to/config.json 142 143 101 115

Results are the grading tool's wall-clock times in the config's time zone
("YYYY-MM-DD HH:MM"), "NONE" for NO_DUE_DATE, or "ERROR: ..." when it could not
compute a date. The grading tool moves a time by an hour after a daylight-saving
change; the test knows about that.
"""
from __future__ import annotations

import ast
import calendar
import copy
import datetime
import json
import sys
from pathlib import Path

import pytz

sys.path.insert(0, str(Path(__file__).parent))
from harvest_relative_due_dates import build_section, load_config  # noqa: E402

FIXTURE = Path(__file__).parent.parent / "tests" / "fixtures" / "grading_tool_relative_dates.json"

WANTED_FUNCTIONS = {
    "calculateDueDate",
    "apply_offsets_to_due_date",
    "set_due_date_time",
    "date_time_from_local_to_utc",
    "day_to_daynum",
    "set_course_due_date_info_defaults",
    "noninstructional_day_json_to_python",
}
WANTED_ASSIGNMENTS = {"NO_DUE_DATE_MARKER_STRING", "FMT_DATE_WITHOUT_TIME", "FMT_TIME_WITHOUT_DATE"}


class _AssignmentForDisplay:
    """Stand-in for the grading tool's class of the same name (only hashed and stored)."""

    def __init__(self, due_at, title, unlock_at=None, lock_at=None):
        self.key = (due_at, title)

    def __hash__(self):
        return hash(self.key)

    def __eq__(self, other):
        return self.key == other.key


def load_grading_tool_functions(grading_tool_dir: Path) -> dict:
    path = grading_tool_dir / "mikesgradingtool" / "Canvas" / "CanvasHelper.py"
    source = path.read_text(encoding="utf-8")
    tree = ast.parse(source)
    chunks: list[str] = []
    for node in tree.body:
        wanted = (
            isinstance(node, ast.FunctionDef) and node.name in WANTED_FUNCTIONS
        ) or (
            isinstance(node, ast.Assign)
            and any(getattr(t, "id", None) in WANTED_ASSIGNMENTS for t in node.targets)
        )
        if wanted:
            chunks.append(ast.get_source_segment(source, node))
    namespace: dict = {
        "datetime": datetime,
        "calendar": calendar,
        "pytz": pytz,
        "sys": sys,
        "printError": lambda msg: print(f"grading tool error: {msg}", file=sys.stderr),
        "AssignmentForDisplay": _AssignmentForDisplay,
    }
    exec(compile("\n\n".join(chunks), str(path), "exec"), namespace)
    missing = (WANTED_FUNCTIONS | WANTED_ASSIGNMENTS) - namespace.keys()
    if missing:
        raise SystemExit(f"Could not find in CanvasHelper.py: {sorted(missing)}")
    return namespace


def general_info(config: dict, gt: dict) -> dict:
    info = copy.deepcopy(config["due_date_info"])
    tz = pytz.timezone(config["app-wide_config"]["preferred_time_zone"])
    fmt_date = gt["FMT_DATE_WITHOUT_TIME"]
    first = datetime.datetime.strptime(info["date_of_first_day_of_the_quarter"], fmt_date)
    return {
        "time_zone": tz,
        "first_day_local": info["date_of_first_day_of_the_quarter"],
        "start_of_quarter": gt["date_time_from_local_to_utc"](first, tz),
        "assignment_default_due_time": datetime.datetime.strptime(
            info["assignment_default_due_time"], gt["FMT_TIME_WITHOUT_DATE"]
        ).time(),
        "noninstructional_days": [
            gt["noninstructional_day_json_to_python"](dict(d))
            for d in info.get("noninstructional_days", [])
        ],
        "raw": info,
    }


def record_course(config: dict, gt: dict, general: dict, course: str) -> dict:
    section, notes = build_section(config, course, course)
    course_info = copy.deepcopy(config["courses"][course])
    course_due_info = gt["set_course_due_date_info_defaults"](copy.deepcopy(course_info["due_date_info"]))
    assignments = course_info["assignments"]
    expected: dict[str, str] = {}
    for key, assignment in assignments.items():
        name = " ".join(assignment.get("canvas_api", {}).get("canvas_name", "").split())
        if not name or "due_date" not in assignment:
            continue
        result = gt["calculateDueDate"](
            assignment,
            general["start_of_quarter"],
            course_due_info,
            general,
            assignments,
        )
        if isinstance(result, datetime.datetime):
            expected[name] = result.astimezone(general["time_zone"]).strftime("%Y-%m-%d %H:%M")
        elif isinstance(result, str) and result.endswith(gt["NO_DUE_DATE_MARKER_STRING"]):
            expected[name] = "NONE"
        else:
            expected[name] = f"ERROR: {result}"
    return {"section": section, "expected": expected, "notes": notes}


def main(argv: list[str]) -> int:
    if len(argv) < 4:
        print(__doc__)
        return 2
    grading_tool_dir, config_path, courses = Path(argv[1]), Path(argv[2]), argv[3:]
    config = load_config(config_path)
    gt = load_grading_tool_functions(grading_tool_dir)
    general = general_info(config, gt)
    raw = general["raw"]
    fixture = {
        "note": "Generated by scripts/record_grading_tool_dates.py; do not edit by hand.",
        "term": {
            "first_day": raw["date_of_first_day_of_the_quarter"],
            "last_day": raw["date_of_last_day_of_the_quarter"],
            "time_zone": config["app-wide_config"]["preferred_time_zone"],
            "default_due_time": raw["assignment_default_due_time"],
            "noninstructional_days": raw.get("noninstructional_days", []),
        },
        "courses": {c: record_course(config, gt, general, c) for c in courses},
    }
    FIXTURE.parent.mkdir(parents=True, exist_ok=True)
    FIXTURE.write_text(json.dumps(fixture, indent=1, sort_keys=True) + "\n", encoding="utf-8")
    for course, data in fixture["courses"].items():
        errors = [n for n, v in data["expected"].items() if v.startswith("ERROR")]
        print(f"{course}: {len(data['expected'])} items, {len(errors)} errors")
    print(f"Wrote {FIXTURE}")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
