"""fix-markdown's grid-table conversion (grid_tables.convert_grid_tables)."""
from __future__ import annotations

import re
from pathlib import Path

import pypandoc

from markdown_to_canvas.grid_tables import convert_grid_tables
from markdown_to_canvas.markdown_cleanup import (
    clean_markdown_body,
    clean_markdown_file_text,
    plan_fix_markdown,
)


def _render(md: str) -> str:
    return pypandoc.convert_text(md, to="html5", format="markdown+smart")


def _counts(html: str) -> tuple[int, int]:
    return len(re.findall(r"<th[ >]", html)), len(re.findall(r"<td[ >]", html))


def _text(html: str) -> str:
    return re.sub(r"<[^>]+>", "", html)


# The College 101 "Type of Motivation" table as import wrote it: <h2>s in the
# cells, the {#id style} blocks stripped without re-padding, and every row a
# header row (the "=" border at the bottom).
MOTIVATION = """\
Intro.

+-------------------------------------------------------+------------------------------------------+------------------------------+
| ## **Type of Motivation** | ## **Description**                                  | ## **Examples**                       |
+-------------------------------------------------------+------------------------------------------+------------------------------+
| ## **Intrinsic**          | Doing something because it's interesting.  | Curiosity, enjoyment |
+-------------------------------------------------------+------------------------------------------+------------------------------+
| ## **Extrinsic**          | Doing something because of outside rewards | Grades, praise |
+=======================================================+==========================================+==============================+

After.
"""

# The podcast rubric's broken header row: spans unwrapped without re-padding.
RUBRIC = """\
+--------------------------+------------------------+------------------------+
| **Criteria**             | **Sophisticated **                          |** Developed **|
+==========================+========================+========================+
| **Content** *(30 pts)*   | Theme is clear, insightful,  | Theme is clear  |
|                          | and fully developed.   | and mostly developed.  |
+--------------------------+------------------------+------------------------+
"""


def test_misaligned_inline_table_becomes_pipe_table() -> None:
    out, warnings = convert_grid_tables(RUBRIC)
    assert warnings == []
    assert out.splitlines()[:2] == [
        "| **Criteria** | **Sophisticated ** | ** Developed ** |",
        "| --- | --- | --- |",
    ]
    # Lines of a wrapped cell are joined.
    assert "| Theme is clear, insightful, and fully developed. |" in out
    th, td = _counts(_render(out))
    assert (th, td) == (3, 3)
    assert "|" not in _text(_render(out))


def test_table_with_headings_in_cells_becomes_html_and_only_first_row_is_header() -> None:
    out, warnings = convert_grid_tables(MOTIVATION)
    assert warnings == []
    assert "+---" not in out and "<table>" in out
    assert out.startswith("Intro.\n\n<table>")
    assert out.endswith("</table>\n\nAfter.\n")
    html = _render(out)
    assert _counts(html) == (3, 6)
    assert html.count("<h2") == 5
    assert "|" not in _text(html)


def test_cell_with_several_paragraphs_becomes_html_table() -> None:
    md = """\
+-----------+-------+
| **A**     | **B** |
+===========+=======+
| one       | two   |
|           |       |
| *note*    |       |
+-----------+-------+
"""
    out, _ = convert_grid_tables(md)
    assert "<td>\n\none\n\n*note*\n\n</td>" in out
    assert "<td>two</td>" in out
    html = _render(out)
    assert _counts(html) == (2, 2)
    assert "<em>note</em>" in html


def test_table_without_header_gets_empty_pipe_header() -> None:
    md = "+----+----+\n| a  | b  |\n+----+----+\n| c  | d  |\n+----+----+\n"
    out, _ = convert_grid_tables(md)
    assert out.splitlines()[:3] == ["|  |  |", "| --- | --- |", "| a | b |"]
    assert _counts(_render(out)) == (0, 4)


def test_alignment_colons_carry_over() -> None:
    md = (
        "+----+----+----+\n| a  | b  | c  |\n+:===+:==:+===:+\n"
        "| 1  | 2  | 3  |\n+----+----+----+\n"
    )
    out, _ = convert_grid_tables(md)
    assert out.splitlines()[1] == "| :--- | :---: | ---: |"


def test_escaped_pipe_stays_in_its_cell() -> None:
    md = "+------+------+\n| a \\| b | c |\n+======+======+\n| 1    | 2    |\n+------+------+\n"
    out, _ = convert_grid_tables(md)
    assert out.splitlines()[0] == "| a \\| b | c |"
    assert _counts(_render(out)) == (2, 2)


def test_pipe_inside_inline_code_forces_html_table() -> None:
    md = "+---------+---+\n| `a|b`   | c |\n+=========+===+\n| 1       | 2 |\n+---------+---+\n"
    out, _ = convert_grid_tables(md)
    assert "<th>`a|b`</th>" in out
    html = _render(out)
    assert _counts(html) == (2, 2)
    assert "<code>a|b</code>" in html


def test_indented_table_in_list_item_keeps_its_indent() -> None:
    md = """\
1. Step one:

      +------+------+
      | A    | B    |
      +======+======+
      | one  | two  |
      +------+------+

2. Step two
"""
    out, _ = convert_grid_tables(md)
    assert "      | A | B |\n      | --- | --- |\n      | one | two |" in out
    html = _render(out)
    assert re.search(r"<li>.*<table>.*</table>.*</li>", html, re.S)


def test_merged_cells_are_reported_and_left_alone() -> None:
    md = "x\n\n+------+------+\n| a    | b    |\n+------+------+\n| wide        |\n+-------------+\n"
    out, warnings = convert_grid_tables(md)
    assert out == md
    assert len(warnings) == 1 and warnings[0].line == 3
    assert "columns" in warnings[0].reason or "cells" in warnings[0].reason


def test_table_in_code_block_is_left_alone() -> None:
    md = "```\n+----+----+\n| a  | b  |\n+----+----+\n```\n"
    assert clean_markdown_body(md) == md


def test_warning_line_numbers_count_frontmatter(tmp_path: Path) -> None:
    text = "---\ntitle: x\n---\n\n+----+----+\n| a  | b  |\n+----+----+\n| wide    |\n+---------+\n"
    warnings: list = []
    assert clean_markdown_file_text(text, warnings) == text
    assert [w.line for w in warnings] == [5]

    p = tmp_path / "page.md"
    p.write_text(text, encoding="utf-8")
    plan = plan_fix_markdown([p])
    assert [(path, w.line) for path, w in plan.tables] == [(p, 5)]
    assert plan.fixes == []


def test_fix_markdown_converts_and_later_passes_keep_html_cell_paragraphs() -> None:
    """The conversion's blank lines must survive _tidy_changed_lines."""
    md = (
        "+------+------+\n| **A** | B |\n+======+======+\n"
        "| one  | two  |\n|      |      |\n| more |      |\n+------+------+\n"
    )
    out = clean_markdown_body(md)
    assert "<td>\n\none\n\nmore\n\n</td>" in out


def test_already_converted_text_is_unchanged() -> None:
    out, _ = convert_grid_tables(RUBRIC)
    again, warnings = convert_grid_tables(out)
    assert again == out and warnings == []
