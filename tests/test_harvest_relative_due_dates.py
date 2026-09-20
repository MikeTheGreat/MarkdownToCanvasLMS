"""scripts/harvest_relative_due_dates.py: the grading tool's config -> a relative table."""
from __future__ import annotations

import sys
import tomllib
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent / "scripts"))
import harvest_relative_due_dates as harvest  # noqa: E402

from markdown_to_canvas import relative_dates as rd  # noqa: E402

CONFIG = """
{
    // comment with "quotes" and a // second slash
    "courses": {
        "142": {
            "due_date_info": { "days_of_week": ["mon", "Wed"], "class_on_noninstructional_days": false },
            "assignments": {
                "A1": {
                    "canvas_api": { "canvas_name": "  Assignment   1 " },
                    "due_date": { "relative_to": { "type": "FIRST_CLASS_OF_QUARTER" }, "offsets": [] }
                },
                "A2": {
                    /* block comment */
                    "canvas_api": { "canvas_name": "Assignment 2" },
                    "due_date": {
                        "relative_to": { "type": "ASSIGNMENT", "assignment_name": "A1" },
                        "offsets": ["+7 CALENDAR_DAY", "18:00 ABS_TIME"]
                    }
                },
                "A3": { "canvas_api": { "canvas_name": "No dates" } },
                "A4": { "due_date": { "relative_to": { "type": "NO_DUE_DATE" }, "offsets": [] } },
                "A5": {
                    "canvas_api": { "canvas_name": "Dangling" },
                    "due_date": { "relative_to": { "type": "ASSIGNMENT", "assignment_name": "ZZ" }, "offsets": [] }
                }
            }
        }
    }
}
"""


def _config(tmp_path):
    path = tmp_path / "config.json"
    path.write_text(CONFIG)
    return harvest.load_config(path)


def test_comments_are_stripped_but_strings_are_not():
    text = '{"a": "x // not a comment", // real\n "b": 1 /* gone */}'
    assert harvest.strip_json_comments(text) == '{"a": "x // not a comment", \n "b": 1 }'


def test_harvested_section_loads_and_uses_canvas_names(tmp_path):
    section, notes = harvest.build_section(_config(tmp_path), "142", "142")
    text = harvest.render(section, "142")
    parsed = tomllib.loads(text)
    assert parsed == {"relative_due_dates": section}

    table = rd.load_tables(parsed)["142"]
    assert table.settings.days_of_week == ("Mon", "Wed")
    assert [i.name for i in table.items] == ["Assignment 1", "Assignment 2"]
    second = table.items[1]
    assert (second.anchor, second.anchor_name) == ("ASSIGNMENT", "Assignment 1")
    assert second.offsets == ("+7 CALENDAR_DAY", "18:00 ABS_TIME")

    joined = "\n".join(notes)
    assert "'No dates'" in joined and "no due_date" in joined
    assert "'A4'" in joined and "canvas_name" in joined
    assert "'Dangling'" in joined and "'ZZ'" in joined


def test_unknown_course_lists_the_known_ones(tmp_path):
    with pytest.raises(SystemExit, match="142"):
        harvest.build_section(_config(tmp_path), "999", "999")


def test_bad_class_day_is_reported(tmp_path):
    config = _config(tmp_path)
    config["courses"]["142"]["due_date_info"]["days_of_week"] = ["Tues"]
    with pytest.raises(SystemExit, match="Tues"):
        harvest.build_section(config, "142", "142")


def test_term_file_is_harvested_and_loads(tmp_path):
    config = _config(tmp_path)
    config["due_date_info"] = {
        "date_of_first_day_of_the_quarter": "2026-09-30",
        "date_of_last_day_of_the_quarter": "2026-12-18",
        "assignment_default_due_time": "23:59",
        "noninstructional_days": [
            {"title": "Holiday \u2013 Veterans Day", "date": "2026-11-11"},
            {"title": "Thanksgiving", "date": "2026-11-26"},
        ],
    }
    config["app-wide_config"] = {"preferred_time_zone": "US/Pacific"}

    text = harvest.render_term(harvest.build_term(config, "142"))
    path = tmp_path / "term.toml"
    path.write_text(text, encoding="utf-8")
    term = rd.load_term(path)

    assert (term.first_day.isoformat(), term.last_day.isoformat()) == ("2026-09-30", "2026-12-18")
    assert term.time_zone.key == "US/Pacific"
    assert term.default_due_time.isoformat() == "23:59:00"
    assert sorted(d.isoformat() for d in term.noninstructional_days) == ["2026-11-11", "2026-11-26"]
    assert term.relative_table == "142"
    assert "relative_table" not in harvest.build_term(config, None)


def test_term_needs_the_term_wide_settings(tmp_path):
    with pytest.raises(SystemExit, match="preferred_time_zone"):
        harvest.build_term(_config(tmp_path), None)


def test_command_line_prints_the_term_or_needs_a_course(tmp_path, capsys):
    path = tmp_path / "config.json"
    path.write_text(
        '{"courses": {}, "app-wide_config": {"preferred_time_zone": "US/Pacific"}, '
        '"due_date_info": {"date_of_first_day_of_the_quarter": "2026-09-30", '
        '"date_of_last_day_of_the_quarter": "2026-12-18", "assignment_default_due_time": "23:59"}}'
    )
    assert harvest.main([str(path), "--term"]) == 0
    assert "first_day = 2026-09-30" in capsys.readouterr().out
    with pytest.raises(SystemExit):
        harvest.main([str(path)])
