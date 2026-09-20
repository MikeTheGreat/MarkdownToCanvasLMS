"""Tests for relative_dates: loading, table selection, and the date arithmetic."""
from __future__ import annotations

from datetime import date, time
from pathlib import Path
from zoneinfo import ZoneInfo

import pytest

from markdown_to_canvas import relative_dates as rd
from markdown_to_canvas.relative_dates import RelativeDueDatesError

WED = date(2026, 9, 30)  # first day used throughout: a Wednesday


def _term(**over) -> rd.Term:
    values = dict(
        first_day=WED,
        last_day=date(2026, 12, 18),
        time_zone=ZoneInfo("America/Los_Angeles"),
        default_due_time=time(23, 59),
        noninstructional_days={date(2026, 10, 21): "Non-Instructional Day"},
    )
    values.update(over)
    return rd.Term(**values)


def _item(name, anchor="START_OF_QUARTER", offsets=(), anchor_name=None, **extra) -> dict:
    row = {"name": name, "relative_to": {"type": anchor}, "offsets": list(offsets)}
    if anchor_name:
        row["relative_to"]["assignment_name"] = anchor_name
    row.update(extra)
    return row


def _table(items, name="default", **section) -> rd.RelativeTable:
    settings = {
        "days_of_week": ["Mon", "Wed"],
        "class_on_noninstructional_days": False,
        **section,
        "tables": {name: {"items": items}},
    }
    return rd.load_tables({"relative_due_dates": settings})[name]


def _calc(items, term=None, **section) -> dict[str, rd.ComputedDates]:
    result = rd.calculate(_table(items, **section), term or _term())
    return {d.name: d for d in result.dates}


def _due(item: dict, term=None, **section) -> str:
    return _calc([item], term, **section)[item["name"]].due_at


# --- loading the section ---------------------------------------------------


def test_missing_section_gives_no_tables():
    assert rd.load_tables({}) == {}


def test_defaults_when_nothing_is_set():
    table = rd.load_tables(
        {"relative_due_dates": {"tables": {"default": {"items": []}}}}
    )["default"]
    assert table.settings.class_on_noninstructional_days is False
    assert table.settings.days_of_week is None
    assert table.settings.unlock_relative_default is None
    assert table.items == ()


def test_table_overrides_shared_setting_and_other_tables_keep_it():
    section = {
        "days_of_week": ["Mon", "Wed"],
        "lock_relative_default": "+7 CALENDAR_DAY",
        "tables": {
            "quarter11": {"items": []},
            "summer8": {
                "days_of_week": ["Mon", "Tue", "Wed", "Thu"],
                "lock_relative_default": ["+3 CALENDAR_DAY", "08:00 ABS_TIME"],
                "items": [],
            },
        },
    }
    tables = rd.load_tables({"relative_due_dates": section})
    assert tables["quarter11"].settings.days_of_week == ("Mon", "Wed")
    assert tables["summer8"].settings.days_of_week == ("Mon", "Tue", "Wed", "Thu")
    assert tables["quarter11"].settings.lock_relative_default == ("+7 CALENDAR_DAY",)
    assert tables["summer8"].settings.lock_relative_default == (
        "+3 CALENDAR_DAY",
        "08:00 ABS_TIME",
    )


def test_day_abbreviations_are_case_insensitive():
    table = _table([], days_of_week=["mon", "WED"])
    assert table.settings.days_of_week == ("Mon", "Wed")


def test_class_days_are_put_in_week_order():
    table = _table([], days_of_week=["Fri", "Mon", "Wed", "Mon"])
    assert table.settings.days_of_week == ("Mon", "Wed", "Fri")
    # so an unordered list still finds the next class day, not the next entry
    assert _due(_item("A", offsets=["+1 CLASS_DAY"]), days_of_week=["Fri", "Wed", "Mon"]) == (
        "2026-10-02T23:59:00-07:00"
    )


def test_type_and_ignore_are_loaded():
    section = {
        "tables": {
            "t": {
                "items": [_item("Quiz 1", type="quiz")],
                "ignore": ["Week 10 Problem Set"],
            }
        }
    }
    table = rd.load_tables({"relative_due_dates": section})["t"]
    assert table.items[0].type == "quiz"
    assert table.ignore == ("Week 10 Problem Set",)


@pytest.mark.parametrize(
    "section, message",
    [
        ({"days_of_wek": ["Mon"], "tables": {}}, "unknown key 'days_of_wek'"),
        ({"days_of_week": ["Tues"], "tables": {}}, "not a day abbreviation"),
        ({"days_of_week": [], "tables": {}}, "non-empty list"),
        ({"class_on_noninstructional_days": "no", "tables": {}}, "true or false"),
        ({"lock_relative_default": "+7 WEEKS", "tables": {}}, "cannot read offset"),
        ({"tables": {"t": {"itmes": []}}}, "unknown key 'itmes'"),
        ({"tables": {"t": {"items": [{"relative_to": {"type": "NO_DUE_DATE"}}]}}}, "needs a name"),
        ({"tables": {"t": {"items": [{"name": "A"}]}}}, "relative_to must be a table"),
        (
            {"tables": {"t": {"items": [_item("A", "SOMETIME")]}}},
            "relative_to type 'SOMETIME'",
        ),
        (
            {"tables": {"t": {"items": [_item("A", "ASSIGNMENT")]}}},
            "needs an assignment_name",
        ),
        (
            {"tables": {"t": {"items": [_item("A", type="page")]}}},
            "type 'page'",
        ),
        (
            {"tables": {"t": {"items": [_item("A", lock_offset=["NONE", "+1 CALENDAR_DAY"])]}}},
            "NONE cannot be combined",
        ),
        (
            {"tables": {"t": {"items": [_item("A", offsets=["NONE"])]}}},
            "offsets cannot contain NONE",
        ),
        (
            {"tables": {"t": {"items": [_item("A", lock_ofset="+1 CALENDAR_DAY")]}}},
            "unknown key 'lock_ofset'",
        ),
        ({"tables": {"t": {"items": [_item("A"), _item("A")]}}}, "more than one item named 'A'"),
        (
            {"tables": {"t": {"items": [_item("A", type="quiz"), _item("A")]}}},
            "more than one item named 'A'",
        ),
    ],
)
def test_bad_settings_are_reported(section, message):
    with pytest.raises(RelativeDueDatesError, match=message):
        rd.load_tables({"relative_due_dates": section})


def test_same_title_with_different_types_is_allowed():
    table = _table([_item("Week 1", type="discussion"), _item("Week 1", type="assignment")])
    assert len(table.items) == 2


# --- selecting a table -----------------------------------------------------


def _tables(*names):
    section = {"tables": {name: {"items": []} for name in names}}
    return rd.load_tables({"relative_due_dates": section})


def test_the_only_table_is_used_without_a_choice():
    assert rd.select_table(_tables("default"), None).name == "default"


def test_default_is_used_when_there_are_several_tables():
    assert rd.select_table(_tables("default", "summer8"), None).name == "default"


def test_several_tables_without_a_default_list_the_names():
    with pytest.raises(RelativeDueDatesError) as exc:
        rd.select_table(_tables("quarter11", "summer8"), None)
    message = str(exc.value)
    assert "quarter11" in message and "summer8" in message and "--table" in message


def test_one_table_not_named_default_still_needs_a_choice():
    with pytest.raises(RelativeDueDatesError) as exc:
        rd.select_table(_tables("quarter11"), None)
    assert "quarter11" in str(exc.value) and "--table" in str(exc.value)


def test_the_command_line_names_the_table():
    assert rd.select_table(_tables("default", "summer8"), "summer8").name == "summer8"


def test_unknown_table_name_lists_the_names():
    with pytest.raises(RelativeDueDatesError, match="'fall'.*quarter11, summer8"):
        rd.select_table(_tables("quarter11", "summer8"), "fall")


def test_no_tables_at_all():
    with pytest.raises(RelativeDueDatesError, match="no tables"):
        rd.select_table({}, None)


# --- the term file ---------------------------------------------------------

TERM_TOML = """
first_day = 2026-09-30
last_day = "2026-12-18"
time_zone = "America/Los_Angeles"
default_due_time = "23:59"
noninstructional_days = [
  { title = "Veterans Day", date = 2026-11-11 },
]
"""


def _term_file(tmp_path: Path, text: str = TERM_TOML) -> Path:
    path = tmp_path / "term.toml"
    path.write_text(text)
    return path


def test_term_file_is_read(tmp_path):
    term = rd.load_term(_term_file(tmp_path))
    assert term.first_day == date(2026, 9, 30)
    assert term.last_day == date(2026, 12, 18)
    assert term.time_zone == ZoneInfo("America/Los_Angeles")
    assert term.default_due_time == time(23, 59)
    assert term.noninstructional_days == {date(2026, 11, 11): "Veterans Day"}


def test_term_file_missing_key_names_key_and_file(tmp_path):
    path = _term_file(tmp_path, TERM_TOML.replace("first_day = 2026-09-30\n", ""))
    with pytest.raises(RelativeDueDatesError) as exc:
        rd.load_term(path)
    assert "first_day" in str(exc.value) and str(path) in str(exc.value)


def test_term_file_unknown_time_zone(tmp_path):
    path = _term_file(tmp_path, TERM_TOML.replace("America/Los_Angeles", "Mars/Olympus"))
    with pytest.raises(RelativeDueDatesError, match="'Mars/Olympus' is not an IANA"):
        rd.load_term(path)


@pytest.mark.parametrize(
    "old, new, message",
    [
        ('default_due_time = "23:59"', 'default_due_time = "late"', "time like 23:59"),
        ("first_day = 2026-09-30", 'first_day = "soon"', "first_day must be a date"),
        ('last_day = "2026-12-18"', 'last_day = "2026-09-01"', "last_day is before first_day"),
        ('default_due_time = "23:59"', 'default_due_time = "23:59"\nrelative_tabel = "x"', "unknown key 'relative_tabel'"),
    ],
)
def test_term_file_bad_values(tmp_path, old, new, message):
    with pytest.raises(RelativeDueDatesError, match=message):
        rd.load_term(_term_file(tmp_path, TERM_TOML.replace(old, new)))


def test_term_file_rejects_the_old_relative_table_key(tmp_path):
    path = _term_file(tmp_path, TERM_TOML + 'relative_table = "quarter11"\n')
    with pytest.raises(RelativeDueDatesError) as exc:
        rd.load_term(path)
    message = str(exc.value)
    assert "relative_table" in message and str(path) in message
    assert "--table" in message and "first_day" in message  # says what to do, lists allowed keys


def test_term_file_not_found_and_not_toml(tmp_path):
    with pytest.raises(RelativeDueDatesError, match="not found"):
        rd.load_term(tmp_path / "nope.toml")
    with pytest.raises(RelativeDueDatesError, match="not valid TOML"):
        rd.load_term(_term_file(tmp_path, "first_day = = ="))


# --- anchors ---------------------------------------------------------------


def test_start_of_quarter_uses_the_default_due_time():
    assert _due(_item("A")) == "2026-09-30T23:59:00-07:00"


def test_first_class_of_quarter_is_the_first_class_day_on_or_after_the_first_day():
    # Wednesday is a class day: the first class is that day itself.
    assert _due(_item("A", "FIRST_CLASS_OF_QUARTER")) == "2026-09-30T23:59:00-07:00"
    # First day on a Tuesday, classes Mon/Wed: first class is the Wednesday.
    tue = _term(first_day=date(2026, 9, 29))
    assert _due(_item("A", "FIRST_CLASS_OF_QUARTER"), tue) == "2026-09-30T23:59:00-07:00"
    # First day on a Wednesday, classes Mon only: first class is the next Monday.
    assert (
        _due(_item("A", "FIRST_CLASS_OF_QUARTER"), days_of_week=["Mon"])
        == "2026-10-05T23:59:00-07:00"
    )


def test_no_due_date_anchor():
    dates = _calc([_item("A", "NO_DUE_DATE")])["A"]
    assert dates.due_at == "NONE"


def test_anchored_to_another_item_counts_from_its_date_not_its_time():
    dates = _calc(
        [
            _item("Find Topics", offsets=["+1 CLASS_DAY", "17:00 ABS_TIME"]),
            _item("Topic Approval", "ASSIGNMENT", ["+7 CALENDAR_DAY"], "Find Topics"),
        ]
    )
    assert dates["Find Topics"].due_at == "2026-10-05T17:00:00-07:00"
    # seven days after Find Topics' date, at the default time (not 17:00)
    assert dates["Topic Approval"].due_at == "2026-10-12T23:59:00-07:00"


def test_anchor_order_in_the_table_does_not_matter():
    dates = _calc(
        [
            _item("B", "ASSIGNMENT", ["+1 CALENDAR_DAY"], "A"),
            _item("A", offsets=["+1 CALENDAR_DAY"]),
        ]
    )
    assert dates["B"].due_at == "2026-10-02T23:59:00-07:00"


def test_anchor_to_a_missing_item():
    with pytest.raises(RelativeDueDatesError, match="'Nope'.*not an item of table 'default'"):
        _calc([_item("A", "ASSIGNMENT", anchor_name="Nope")])


def test_anchor_to_an_item_without_a_due_date():
    with pytest.raises(RelativeDueDatesError, match="no due date"):
        _calc([_item("A", "NO_DUE_DATE"), _item("B", "ASSIGNMENT", anchor_name="A")])


def test_circular_anchors_name_the_cycle():
    with pytest.raises(RelativeDueDatesError, match="circular.*A -> B -> A"):
        _calc(
            [
                _item("A", "ASSIGNMENT", anchor_name="B"),
                _item("B", "ASSIGNMENT", anchor_name="A"),
            ]
        )


def test_class_day_offsets_need_class_days():
    with pytest.raises(RelativeDueDatesError, match="days_of_week is set neither"):
        rd.calculate(
            rd.load_tables(
                {
                    "relative_due_dates": {
                        "tables": {"t": {"items": [_item("A", offsets=["+1 CLASS_DAY"])]}}
                    }
                }
            )["t"],
            _term(),
        )


def test_memoization_and_offsets_are_not_mutated():
    table = _table(
        [
            _item("A", "FIRST_CLASS_OF_QUARTER", ["+1 CALENDAR_DAY"]),
            _item("B", "ASSIGNMENT", ["+1 CALENDAR_DAY"], "A"),
            _item("C", "ASSIGNMENT", ["+2 CALENDAR_DAY"], "A"),
        ]
    )
    calc = rd._Calculator(table, _term())
    first = calc.compute()
    assert table.items[0].offsets == ("+1 CALENDAR_DAY",)  # no inserted offsets
    assert calc._due.keys() == {"A", "B", "C"}
    assert calc.compute().dates == first.dates  # same result the second time
    assert rd.calculate(table, _term()).dates == first.dates


# --- offsets ---------------------------------------------------------------


def test_calendar_day_offsets_forward_and_back():
    assert _due(_item("A", offsets=["+7 CALENDAR_DAY"])) == "2026-10-07T23:59:00-07:00"
    assert _due(_item("A", offsets=["-2 CALENDAR_DAY"])) == "2026-09-28T23:59:00-07:00"
    assert _due(_item("A", offsets=["+7 CALENDAR_DAY", "-1 CALENDAR_DAY"])) == (
        "2026-10-06T23:59:00-07:00"
    )


def test_class_day_offset():
    assert _due(_item("A", offsets=["+1 CLASS_DAY"])) == "2026-10-05T23:59:00-07:00"  # Mon
    assert _due(_item("A", offsets=["+2 CLASS_DAY"])) == "2026-10-07T23:59:00-07:00"  # Wed
    assert _due(_item("A", offsets=["+3 CLASS_DAY"])) == "2026-10-12T23:59:00-07:00"  # Mon


def test_class_day_offset_from_a_non_class_day_lands_on_the_first_class_day():
    # Friday 2026-10-02 is not a class day; the next one is Monday.
    assert (
        _due(_item("A", offsets=["+2 CALENDAR_DAY", "+1 CLASS_DAY"]))
        == "2026-10-05T23:59:00-07:00"
    )


def test_class_day_offset_skips_a_non_instructional_day():
    # 2026-10-21 (a Wednesday) is a holiday: +1 class day from Mon 10-19 is Mon 10-26.
    dates = _calc(
        [
            _item("Base", offsets=["+19 CALENDAR_DAY"]),  # Mon 2026-10-19
            _item("A", "ASSIGNMENT", ["+1 CLASS_DAY"], "Base"),
        ]
    )
    assert dates["Base"].due_at == "2026-10-19T23:59:00-07:00"
    assert dates["A"].due_at == "2026-10-26T23:59:00-07:00"


def test_class_on_noninstructional_days_keeps_the_holiday():
    dates = _calc(
        [
            _item("Base", offsets=["+19 CALENDAR_DAY"]),
            _item("A", "ASSIGNMENT", ["+1 CLASS_DAY"], "Base"),
        ],
        class_on_noninstructional_days=True,
    )
    assert dates["A"].due_at == "2026-10-21T23:59:00-07:00"


def test_negative_class_day_offset_goes_to_the_previous_class_day():
    # Wed 09-30 -> Mon 09-28 with Mon/Wed; and with Mon/Wed/Fri, still the previous class day.
    assert _due(_item("A", offsets=["-1 CLASS_DAY"])) == "2026-09-28T23:59:00-07:00"
    assert (
        _due(_item("A", offsets=["-1 CLASS_DAY"]), days_of_week=["Mon", "Wed", "Fri"])
        == "2026-09-28T23:59:00-07:00"
    )
    assert (
        _due(_item("A", offsets=["-2 CLASS_DAY"]), days_of_week=["Mon", "Wed", "Fri"])
        == "2026-09-25T23:59:00-07:00"
    )


def test_single_class_day_a_week():
    assert _due(_item("A", offsets=["+1 CLASS_DAY"]), days_of_week=["Wed"]) == (
        "2026-10-07T23:59:00-07:00"
    )


def test_class_days_all_holidays_give_an_error():
    term = _term(
        noninstructional_days={date(2026, 9, 30) + rd.timedelta(days=i): "x" for i in range(1, 4000)}
    )
    with pytest.raises(RelativeDueDatesError, match="no usable class day"):
        _due(_item("A", offsets=["+1 CLASS_DAY"]), term)


def test_nearest_calendar_day():
    # Wed 2026-10-07 -> Fri 10-09 (2 ahead beats 5 behind)
    assert _due(_item("A", offsets=["+7 CALENDAR_DAY", "Fri NEAREST_CALENDAR_DAY"])) == (
        "2026-10-09T23:59:00-07:00"
    )
    # Wed 10-07 -> Sun: 4 ahead (11), 3 behind (10-04): the earlier one is nearer
    assert _due(_item("A", offsets=["+7 CALENDAR_DAY", "Sun NEAREST_CALENDAR_DAY"])) == (
        "2026-10-04T23:59:00-07:00"
    )
    # already that weekday: unchanged
    assert _due(_item("A", offsets=["Wed NEAREST_CALENDAR_DAY"])) == "2026-09-30T23:59:00-07:00"


def test_absolute_time_replaces_the_time_and_keeps_the_date():
    assert _due(_item("A", offsets=["+3 CALENDAR_DAY", "17:00 ABS_TIME"])) == (
        "2026-10-03T17:00:00-07:00"
    )
    # a later day offset keeps the time set by ABS_TIME
    assert _due(_item("A", offsets=["17:00 ABS_TIME", "+1 CALENDAR_DAY"])) == (
        "2026-10-01T17:00:00-07:00"
    )


# --- daylight-saving time --------------------------------------------------


def test_offset_follows_the_date_and_wall_clock_time_is_kept():
    dates = _calc(
        [
            _item("Before", offsets=["+30 CALENDAR_DAY"]),  # 2026-10-30, PDT
            _item("After", offsets=["+33 CALENDAR_DAY"]),  # 2026-11-02, PST
            _item("Sixty", offsets=["+60 CALENDAR_DAY"]),
        ]
    )
    assert dates["Before"].due_at == "2026-10-30T23:59:00-07:00"
    assert dates["After"].due_at == "2026-11-02T23:59:00-08:00"
    assert dates["Sixty"].due_at == "2026-11-29T23:59:00-08:00"


def test_eastern_time_zone():
    term = _term(time_zone=ZoneInfo("America/New_York"))
    assert _due(_item("A", offsets=["+60 CALENDAR_DAY"]), term) == "2026-11-29T23:59:00-05:00"
    assert _due(_item("A"), term) == "2026-09-30T23:59:00-04:00"


# --- lock and unlock -------------------------------------------------------


def test_lock_default_a_week_after_the_due_date():
    dates = _calc([_item("A", offsets=["+1 CLASS_DAY"])], lock_relative_default="+7 CALENDAR_DAY")
    assert dates["A"].due_at == "2026-10-05T23:59:00-07:00"
    assert dates["A"].lock_at == "2026-10-12T23:59:00-07:00"


def test_unlock_none():
    dates = _calc([_item("A", unlock_offset="NONE")])
    assert dates["A"].unlock_at == "NONE"


def test_none_default_applies_to_every_item():
    dates = _calc([_item("A"), _item("B")], unlock_relative_default="NONE")
    assert dates["A"].unlock_at == dates["B"].unlock_at == "NONE"


def test_lock_offset_list_with_an_absolute_time():
    dates = _calc([_item("A", offsets=["+1 CLASS_DAY"], lock_offset=["+7 CALENDAR_DAY", "08:00 ABS_TIME"])])
    assert dates["A"].lock_at == "2026-10-12T08:00:00-07:00"


def test_unlock_before_due_date():
    dates = _calc([_item("A", offsets=["+1 CLASS_DAY"], unlock_offset="-7 CALENDAR_DAY")])
    assert dates["A"].unlock_at == "2026-09-28T23:59:00-07:00"


def test_items_own_rule_beats_the_default():
    dates = _calc([_item("A", lock_offset="+2 CALENDAR_DAY")], lock_relative_default="+7 CALENDAR_DAY")
    assert dates["A"].lock_at == "2026-10-02T23:59:00-07:00"


def test_items_own_none_beats_a_default_offset():
    dates = _calc([_item("A", lock_offset="NONE")], lock_relative_default="+7 CALENDAR_DAY")
    assert dates["A"].lock_at == "NONE"


def test_no_rule_anywhere_is_keep():
    dates = _calc([_item("A")])["A"]
    assert (dates.unlock_at, dates.lock_at) == ("KEEP", "KEEP")


def test_table_default_beats_the_section_default():
    section = {
        "lock_relative_default": "+7 CALENDAR_DAY",
        "days_of_week": ["Mon", "Wed"],
        "tables": {"t": {"lock_relative_default": "+1 CALENDAR_DAY", "items": [_item("A")]}},
    }
    table = rd.load_tables({"relative_due_dates": section})["t"]
    assert rd.calculate(table, _term()).dates[0].lock_at == "2026-10-01T23:59:00-07:00"


def test_lock_rule_without_a_due_date_warns_and_keeps():
    result = rd.calculate(
        _table([_item("A", "NO_DUE_DATE")], lock_relative_default="+7 CALENDAR_DAY"), _term()
    )
    (dates,) = result.dates
    assert dates.due_at == "NONE" and dates.lock_at == "KEEP"
    assert len(result.warnings) == 1 and "'A'" in result.warnings[0]


def test_none_rules_need_no_due_date_and_do_not_warn():
    result = rd.calculate(
        _table([_item("A", "NO_DUE_DATE", unlock_offset="NONE")]), _term()
    )
    assert result.dates[0].unlock_at == "NONE"
    assert result.warnings == []


def test_type_is_carried_through():
    dates = rd.calculate(_table([_item("Q", type="quiz"), _item("P")]), _term()).dates
    assert [d.type for d in dates] == ["quiz", None]
