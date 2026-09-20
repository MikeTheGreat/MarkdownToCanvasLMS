"""Layout of generated TOML: the style of an array depends on its key, not its size."""
from __future__ import annotations

import tomllib
from typing import Any

import pytest
import tomlkit

from markdown_to_canvas import toml_write as w

LONG = "x" * 500


def _dump(build) -> str:
    doc = tomlkit.document()
    build(doc)
    return tomlkit.dumps(doc)


@pytest.mark.parametrize("key", sorted(w.INLINE_TABLE_ARRAY_KEYS))
@pytest.mark.parametrize("size", ["short", "long"])
def test_inline_keys_stay_inline_at_any_row_size(key: str, size: str) -> None:
    value = "a" if size == "short" else LONG
    rows = [{"id": value, "hidden": True}]
    text = _dump(lambda d: w.fill_table(d, {key: rows}))
    assert f"[[{key}]]" not in text
    assert text.startswith(f"{key} = [")
    assert tomllib.loads(text) == {key: rows}


@pytest.mark.parametrize("size", ["short", "long"])
def test_other_lists_of_dicts_are_blocks_at_any_row_size(size: str) -> None:
    value = "a" if size == "short" else LONG
    rows = [{"title": value}]
    text = _dump(lambda d: w.fill_table(d, {"assignment_groups": rows}))
    assert text.startswith("[[assignment_groups]]")
    assert tomllib.loads(text) == {"assignment_groups": rows}


def test_pairs_are_one_per_line() -> None:
    pairs = [[f"Grade {i} ({i}.0)", i / 100] for i in range(40)]
    text = _dump(lambda d: w.fill_table(d, {"grading_standards": [{"title": "T", "data": pairs}]}))
    lines = text.splitlines()
    assert lines[0] == "[[grading_standards]]"
    assert lines[2] == "data = ["
    assert lines[3] == '    ["Grade 0 (0.0)", 0.0],'
    assert len(lines) == 2 + 1 + 40 + 1  # header, title, `data = [`, pairs, `]`
    assert tomllib.loads(text)["grading_standards"][0]["data"] == pairs


def test_plain_keys_precede_sub_tables_whatever_the_dict_order() -> None:
    data = {"criteria": [{"description": "d"}], "title": "T", "nested": {"a": 1}, "after": 2}
    text = _dump(lambda d: w.fill_table(d, {"rubrics": [data]}))
    parsed = tomllib.loads(text)["rubrics"][0]
    assert parsed["title"] == "T" and parsed["after"] == 2
    assert parsed["criteria"] == [{"description": "d"}]
    assert parsed["nested"] == {"a": 1}


def test_top_level_keys_stay_top_level_with_long_inline_rows() -> None:
    def build(doc: Any) -> None:
        doc.add("before", 1)
        doc.add("tab_configuration", w.value_for("tab_configuration", [{"id": LONG}] * 3))
        doc.add("late_policy", tomlkit.table())
        w.fill_table(doc, {"grading_standards": [{"title": "T"}]})

    parsed = tomllib.loads(_dump(build))
    assert parsed["before"] == 1
    assert len(parsed["tab_configuration"]) == 3
    assert "tab_configuration" not in parsed["late_policy"]


def test_commented_keys_round_trip_when_uncommented() -> None:
    values = {"plain": "x", "quote": 'say "hi"', "slash": "a\\b", "nl": "a\nb", "n": 5, "f": 0.5, "b": False}
    doc = tomlkit.document()
    w.add_commented(doc, values)
    text = tomlkit.dumps(doc)
    assert all(line.startswith("# ") for line in text.splitlines())
    uncommented = "".join(line[2:] + "\n" for line in text.splitlines())
    assert tomllib.loads(uncommented) == values


def test_fill_table_comments_a_key_in_place() -> None:
    text = _dump(lambda d: w.fill_table(d, {"rubrics": [{"identifier": "i", "title": "T"}]}, frozenset({"identifier"})))
    assert text.splitlines() == ["[[rubrics]]", '# identifier = "i"', 'title = "T"']
    assert tomllib.loads(text) == {"rubrics": [{"title": "T"}]}


def test_comment_text_keeps_blank_and_bare_hash_lines() -> None:
    doc = tomlkit.document()
    w.add_comment_text(doc, "# one\n#\n# two\n\n")
    assert tomlkit.dumps(doc) == "# one\n#\n# two\n\n"
    with pytest.raises(ValueError):
        w.add_comment_text(doc, "not a comment")


def test_long_scalar_array_is_one_item_per_line() -> None:
    text = _dump(lambda d: w.fill_table(d, {"order": [f"module-number-{i}.md" for i in range(10)], "short": ["a", "b"]}))
    assert text.splitlines()[0] == "order = ["
    assert 'short = ["a", "b"]' in text


@pytest.mark.parametrize("size", ["short", "long"])
def test_relative_due_dates_items_are_inline_rows_inside_nested_tables(size: str) -> None:
    """A table's `items` must not become `[[...items]]` blocks, whatever the row size."""
    name = "a" if size == "short" else LONG
    row = {
        "name": name,
        "relative_to": {"type": "ASSIGNMENT", "assignment_name": "b"},
        "offsets": ["+7 CALENDAR_DAY", "23:59 ABS_TIME"],
    }
    data = {
        "format_version": 2,
        "relative_due_dates": {
            "days_of_week": ["Mon", "Wed"],
            "tables": {"default": {"items": [row]}, "summer8": {"items": []}},
        },
    }
    text = _dump(lambda d: w.fill_table(d, data))
    assert "[[" not in text
    assert text.startswith("format_version = 2")
    assert tomllib.loads(text) == data
