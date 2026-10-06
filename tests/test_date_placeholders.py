"""Unit tests: [text]{.replace_date_with ...} date placeholders."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from markdown_to_canvas.convert import markdown_to_html
from markdown_to_canvas.date_placeholders import (
    DEFAULT_FORMAT,
    DatePlaceholderContext,
    Placeholder,
    PlaceholderError,
    check_leftovers_html,
    expand,
    find_placeholders,
    first_stale_reason,
    format_date,
    load_default_format,
    make_context,
    parse_attributes,
)

DUE_DATES = [
    {"name": "HW 1", "unlock_at": "NONE", "due_at": "2026-10-27T23:59:00-07:00",
     "lock_at": "2026-11-03T23:59:00-08:00"},
    {"name": "HW 2", "due_at": "NONE", "unlock_at": "KEEP", "lock_at": ""},
    {"name": "Week 3", "type": "quiz", "due_at": "2026-10-12T09:00:00-07:00"},
    {"name": "Week 3", "type": "assignment", "due_at": "2026-10-13T09:05:00-07:00"},
    {"name": "Naive", "due_at": "2026-10-27T08:30:00"},
    {"name": "Bad", "due_at": "next tuesday"},
    {"name": "Sentinel", "due_at": "create_none_then_keep"},
]


def _ctx(own_title=None, own_type=None, fmt=DEFAULT_FORMAT, due_dates=DUE_DATES):
    return DatePlaceholderContext(tuple(due_dates), fmt, own_title, own_type)


def _expand(text, ctx=None):
    errors: list[str] = []
    out, records = expand(text, ctx or _ctx(), "pages/p.md", errors)
    return out, records, errors


# ---------------------------------------------------------------------------
# Parsing
# ---------------------------------------------------------------------------


class TestParse:
    def test_quoted_and_bare_values(self):
        ph = parse_attributes(
            '.replace_date_with item="HW 1: Loops" type=quiz field=lock_at format=\'%B %-d\'',
            "src",
        )
        assert ph == Placeholder("HW 1: Loops", "quiz", "lock_at", "%B %-d", "src")

    def test_escaped_quote(self):
        ph = parse_attributes(r'.replace_date_with item="Say \"hi\""', "src")
        assert ph.item == 'Say "hi"'

    def test_defaults(self):
        ph = parse_attributes(".replace_date_with", "src")
        assert (ph.item, ph.type, ph.field, ph.format) == (None, None, "due_at", None)

    @pytest.mark.parametrize(
        "attrs, fragment",
        [
            (".replace_date_with feild=lock_at", "unknown attribute 'feild'"),
            (".replace_date_with .big", "unexpected class .big"),
            (".replace_date_with #x", "unexpected id #x"),
            (".replace_date_with field=due", "field='due'"),
            (".replace_date_with type=page", "type='page'"),
            (".replace_date_with item=\"\"", "item is empty"),
            (".replace_date_with format=\"\"", "format is empty"),
            (".replace_date_with item=a item=b", "given twice"),
            ('.replace_date_with item="unclosed', "cannot read"),
        ],
    )
    def test_invalid(self, attrs, fragment):
        with pytest.raises(PlaceholderError, match=fragment):
            parse_attributes(attrs, "src")

    def test_find_skips_code(self):
        text = (
            "A [x]{.replace_date_with item=\"HW 1\"} and `[y]{.replace_date_with}`\n"
            "```\n[z]{.replace_date_with}\n```\n"
            "and ``code [w]{.replace_date_with} here``\n"
        )
        found = find_placeholders(text)
        assert [p.item for p in found] == ["HW 1"]

    def test_find_ignores_other_spans(self):
        assert find_placeholders('[hi]{style="color: red"} [x]{.big}') == []

    def test_find_reports_bad_span(self):
        (bad,) = find_placeholders("[x]{.replace_date_with nope=1}")
        assert isinstance(bad, PlaceholderError)


# ---------------------------------------------------------------------------
# Resolution
# ---------------------------------------------------------------------------


class TestResolve:
    def test_named_entry(self):
        out, records, errors = _expand(
            'Submit by [Oct 20]{.replace_date_with item="HW 1" format="%A, %B %-d"}.'
        )
        assert out == "Submit by Tuesday, October 27."
        assert errors == []
        assert records == [
            {"item": "HW 1", "type": "", "field": "due_at", "format": "%A, %B %-d",
             "text": "Tuesday, October 27"}
        ]

    def test_other_field(self):
        out, _, errors = _expand('[x]{.replace_date_with item="HW 1" field=lock_at format="%b %-d %H:%M %z"}')
        assert out == "Nov 3 23:59 -0800"
        assert errors == []

    def test_own_entry(self):
        out, records, errors = _expand(
            "[x]{.replace_date_with}", _ctx(own_title="Week 3", own_type="assignment")
        )
        assert out == "Tuesday, October 13 by 9:05 AM"
        assert records[0]["item"] == "Week 3"
        assert records[0]["type"] == "assignment"
        assert records[0]["format"] == ""
        assert errors == []

    def test_own_entry_missing_for_page(self):
        out, _, errors = _expand("[x]{.replace_date_with}")
        assert out == "[x]{.replace_date_with}"
        assert len(errors) == 1
        assert "needs item=" in errors[0]
        assert "pages/p.md" in errors[0]

    def test_ambiguous(self):
        _, _, errors = _expand('[x]{.replace_date_with item="Week 3"}')
        assert "add type=" in errors[0]

    def test_type_disambiguates(self):
        out, _, errors = _expand('[x]{.replace_date_with item="Week 3" type=quiz format="%-d"}')
        assert (out, errors) == ("12", [])

    def test_untyped_entry_matches_any_type(self):
        out, _, errors = _expand('[x]{.replace_date_with item="HW 1" type=quiz format="%-d"}')
        assert (out, errors) == ("27", [])

    @pytest.mark.parametrize(
        "attrs, fragment",
        [
            ('item="HW 9"', "no due_dates entry named 'HW 9'"),
            ('item="HW 2"', "has no date for due_at (NONE)"),
            ('item="HW 2" field=unlock_at', "(KEEP)"),
            ('item="HW 2" field=lock_at', "has no lock_at"),
            ('item="Sentinel"', "create_none_then_keep"),
            ('item="Bad"', "is not a date-time"),
            ('item="Week 3" field=lock_at type=quiz', "has no lock_at"),
        ],
    )
    def test_unresolved(self, attrs, fragment):
        text = f"[x]{{.replace_date_with {attrs}}}"
        out, records, errors = _expand(text)
        assert out == text
        assert records == []
        assert len(errors) == 1 and fragment in errors[0]

    def test_only_filtered_list_is_used(self):
        _, _, errors = _expand('[x]{.replace_date_with item="HW 1"}', _ctx(due_dates=[]))
        assert "no due_dates entry" in errors[0]

    def test_toml_datetime_value(self):
        when = datetime(2026, 10, 27, 23, 59, tzinfo=timezone(timedelta(hours=-7)))
        out, _, errors = _expand(
            '[x]{.replace_date_with item="T" format="%-I:%M %p"}',
            _ctx(due_dates=[{"name": "T", "due_at": when}]),
        )
        assert (out, errors) == ("11:59 PM", [])


# ---------------------------------------------------------------------------
# Formatting
# ---------------------------------------------------------------------------


class TestFormat:
    def test_offset_kept(self):
        out, _, _ = _expand('[x]{.replace_date_with item="HW 1" format="%-I:%M %p"}')
        assert out == "11:59 PM"

    def test_naive_shown_as_written(self):
        out, _, _ = _expand('[x]{.replace_date_with item="Naive" format="%H:%M"}')
        assert out == "08:30"

    def test_default_format(self):
        out, _, _ = _expand('[x]{.replace_date_with item="HW 1"}')
        assert out == "Tuesday, October 27 by 11:59 PM"

    def test_no_pad_directives(self):
        when = datetime(2026, 2, 3, 4, 5)
        assert format_date(when, "%-d|%-m|%-H|%-I|%-M|%-j") == "3|2|4|4|5|34"
        assert format_date(datetime(2026, 1, 1, 0, 7), "%-I %-H") == "12 0"
        assert format_date(datetime(2026, 1, 1, 12), "%-I %p") == "12 PM"

    def test_percent_literal(self):
        assert format_date(datetime(2026, 1, 1), "100%% on %-d") == "100% on 1"

    def test_load_default_format(self):
        assert load_default_format({}) == DEFAULT_FORMAT
        assert load_default_format({"replace_date_with_format": "%b"}) == "%b"
        with pytest.raises(ValueError, match="must be a string"):
            load_default_format({"replace_date_with_format": 3})

    def test_make_context(self):
        ctx = make_context(DUE_DATES, {"replace_date_with_format": "%b"})
        assert ctx.default_format == "%b"
        assert ctx.own_title is None


# ---------------------------------------------------------------------------
# Expansion
# ---------------------------------------------------------------------------


class TestExpand:
    def test_nested_in_styled_span(self):
        text = (
            '[**Complete Step 5 by [x]{.replace_date_with item="HW 1" format="%B %-d"}**]'
            '{style="background-color: #fbeeb8;"}'
        )
        out, _, errors = _expand(text)
        assert errors == []
        html = " ".join(markdown_to_html(out).split())
        assert '<span style="background-color: #fbeeb8;"><strong>Complete Step 5 by October 27</strong></span>' in html
        assert "replace_date_with" not in html

    def test_code_left_alone(self):
        text = "`[x]{.replace_date_with}`\n\n```\n[x]{.replace_date_with}\n```\n"
        out, records, errors = _expand(text)
        assert (out, records, errors) == (text, [], [])

    def test_escapes_markdown(self):
        out, _, _ = _expand('[x]{.replace_date_with item="HW 1" format="*%-d_"}')
        assert out == r"\*27\_"

    def test_brackets_in_text_reported(self):
        text = '[a [b] c]{.replace_date_with item="HW 1"}'
        out, _, errors = _expand(text)
        assert out == text
        assert len(errors) == 1 and "must not contain [ or ]" in errors[0]

    def test_duplicate_records_collapsed(self):
        _, records, _ = _expand(
            '[x]{.replace_date_with item="HW 1"} and [y]{.replace_date_with item="HW 1"}'
        )
        assert len(records) == 1

    def test_failed_span_not_double_reported(self):
        _, _, errors = _expand('[x]{.replace_date_with item="HW 9"}')
        assert len(errors) == 1

    def test_html_leftover_check(self):
        errors: list[str] = []
        html = markdown_to_html("[a [b] c]{.replace_date_with}")
        assert check_leftovers_html(html, "pages/p.md", errors)
        assert len(errors) == 1
        assert not check_leftovers_html("<p>fine</p>", "pages/p.md", errors)


# ---------------------------------------------------------------------------
# Staleness records
# ---------------------------------------------------------------------------


class TestStale:
    def _records(self, text, ctx=None):
        _, records, _ = _expand(text, ctx)
        return records

    def test_unchanged(self):
        records = self._records('[x]{.replace_date_with item="HW 1"}')
        assert first_stale_reason(records, _ctx()) is None

    def test_date_changed(self):
        records = self._records('[x]{.replace_date_with item="HW 1"}')
        moved = [dict(DUE_DATES[0], due_at="2026-10-28T23:59:00-07:00")] + DUE_DATES[1:]
        reason = first_stale_reason(records, _ctx(due_dates=moved))
        assert reason is not None and "'HW 1'" in reason

    def test_default_format_changed(self):
        records = self._records('[x]{.replace_date_with item="HW 1"}')
        assert first_stale_reason(records, _ctx(fmt="%b %-d")) is not None

    def test_explicit_format_ignores_default(self):
        records = self._records('[x]{.replace_date_with item="HW 1" format="%-d"}')
        assert first_stale_reason(records, _ctx(fmt="%b %-d")) is None

    def test_no_longer_resolves(self):
        records = self._records('[x]{.replace_date_with item="HW 1"}')
        reason = first_stale_reason(records, _ctx(due_dates=[]))
        assert reason is not None and "no longer resolves" in reason

    def test_own_entry_record(self):
        ctx = _ctx(own_title="Week 3", own_type="quiz")
        records = self._records("[x]{.replace_date_with}", ctx)
        # Re-resolved without the file's own context: the record names the entry.
        assert first_stale_reason(records, _ctx()) is None

    def test_no_records(self):
        assert first_stale_reason(None, _ctx()) is None
        assert first_stale_reason([], _ctx()) is None
