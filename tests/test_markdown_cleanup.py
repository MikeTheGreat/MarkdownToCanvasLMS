"""Tests for markdown_cleanup: Word / import debris removal shared by import
and the fix-markdown subcommand."""

from __future__ import annotations

from pathlib import Path

from click.testing import CliRunner

from markdown_to_canvas.cli import main
from markdown_to_canvas.imscc_import import _html_to_markdown, _simplify_pandoc_attrs
from markdown_to_canvas.markdown_cleanup import (
    clean_markdown_body,
    clean_markdown_file_text,
    collect_markdown_files,
    drop_final_hard_breaks,
    fix_emphasis_spaces,
    shorten_horizontal_rules,
    flatten_stacked_list_markers,
    split_empty_break_paragraphs,
    unescape_quotes,
)

from .conftest import make_current

WORD_HTML = (
    '<p><strong>Tip</strong>: C<span class="NormalTextRun SCXW1 BCX0">heck out our </span>'
    '<a href="https://a.com/x"><span class="TextRun SCXW1">Finding Data</span></a>'
    '<span class="TextRun SCXW1"> and </span><a href="https://b.com/y">Job Searching</a>'
    '<span class="NormalTextRun"> for info. </span>'
    '<span class="EOP SCXW1 BCX0" data-ccp-props="{&quot;134233117&quot;:false}"> </span></p>'
)


# ---------------------------------------------------------------------------
# Import
# ---------------------------------------------------------------------------


def test_import_unwraps_spans_whose_attributes_are_all_dropped() -> None:
    md = _html_to_markdown(WORD_HTML)
    assert md.strip() == (
        "**Tip**: Check out our [Finding Data](https://a.com/x) and "
        "[Job Searching](https://b.com/y) for info."
    )


def test_import_strips_attribute_values_that_contain_braces() -> None:
    md = '[text]{.EOP ccp-props="{\\"134233117\\":false}"} after\n'
    assert _simplify_pandoc_attrs(md) == "text after\n"


def test_import_keeps_a_span_that_still_has_a_style() -> None:
    assert _simplify_pandoc_attrs('[hi]{.TextRun style="color:red"}\n') == (
        '[hi]{style="color:red"}\n'
    )


def test_import_leaves_an_image_with_dropped_attributes_as_an_image() -> None:
    assert _simplify_pandoc_attrs("![alt](a.png){.foo}\n") == "![alt](a.png)\n"


# ---------------------------------------------------------------------------
# fix-markdown: attribute blocks
# ---------------------------------------------------------------------------


def test_word_attribute_block_is_removed_and_span_unwrapped() -> None:
    md = '- [Job Data](https://x)[\u00a0]{.EOP .SCXW3793864 .BCX0 ccp-props="{}"}\n'
    assert clean_markdown_body(md) == "- [Job Data](https://x)\n"


def test_word_block_keeps_id_and_style() -> None:
    md = '[text]{#keep .TextRun .SCXW1 style="color:red" lang="EN-US"}\n'
    assert clean_markdown_body(md) == '[text]{#keep style="color:red"}\n'


def test_non_word_classes_are_left_alone() -> None:
    md = (
        '[Syllabus](https://x/syllabus){class="inline_disabled Button Button--primary"}\n'
        "[underlined]{.underline} and [x]{lang=\"fr\"}\n"
    )
    assert clean_markdown_body(md) == md


def test_word_fenced_div_is_unwrapped() -> None:
    md = "::: {.OutlineElement .SCXW1}\ntext\n:::\n"
    assert clean_markdown_body(md) == "text\n"


# ---------------------------------------------------------------------------
# fix-markdown: stray brackets
# ---------------------------------------------------------------------------


def test_seam_debris_around_links_is_removed() -> None:
    md = (
        "**Tip**: C[heck out our ][Finding Data](https://a)[ and ]"
        "[Job Searching](https://b)[ for info. ][ ]{.EOP .SCXW1}\n"
    )
    assert clean_markdown_body(md) == (
        "**Tip**: Check out our [Finding Data](https://a) and "
        "[Job Searching](https://b) for info.\n"
    )


def test_unbalanced_seam_debris_is_removed() -> None:
    md = "your research, ][identify][ themes or plan your ][work][, ]**[however**\n"
    assert clean_markdown_body(md) == (
        "your research, identify themes or plan your work, **however**\n"
    )


def test_single_letter_seam_is_removed_when_paragraph_has_debris() -> None:
    md = "- [F][inding] [Salary Data](https://x)[ ][ ]{.EOP .SCXW2}\n"
    assert clean_markdown_body(md) == "- Finding [Salary Data](https://x)\n"


def test_prose_indexing_without_whitespace_is_left_alone() -> None:
    md = "Use a[i][j] to reach the cell.\n"
    assert clean_markdown_body(md) == md


def test_inline_code_brackets_are_kept_in_a_repaired_paragraph() -> None:
    md = "Write [the ][value] as `grid[r][ c]` or `a[0]`.\n"
    assert clean_markdown_body(md) == "Write the value as `grid[r][ c]` or `a[0]`.\n"


def test_fenced_code_block_is_untouched() -> None:
    md = "```\nx = m[a ][b]\ny = \"q\\'\"\\\n```\n"
    assert clean_markdown_body(md) == md


def test_reference_links_task_boxes_and_footnotes_survive_repair() -> None:
    md = (
        "- [ ] See [the guide][g] and note[^1], [odd ][bits] here.\n"
        "\n"
        "[g]: https://example.com\n"
    )
    assert clean_markdown_body(md) == (
        "- [ ] See [the guide][g] and note[^1], odd bits here.\n"
        "\n"
        "[g]: https://example.com\n"
    )


def test_styled_span_survives_repair() -> None:
    md = '[a ][b]{style="color:red"}\n'
    assert clean_markdown_body(md) == 'a [b]{style="color:red"}\n'


def test_swapped_link_is_repaired() -> None:
    md = "[Label][https://u.com/a]( and )[Other][https://u.com/b]( for more )\n"
    assert clean_markdown_body(md) == (
        "[Label](https://u.com/a) and [Other](https://u.com/b) for more\n"
    )


# ---------------------------------------------------------------------------
# fix-markdown: quotes and backslashes
# ---------------------------------------------------------------------------


def test_escaped_quotes_in_prose_are_unescaped() -> None:
    assert unescape_quotes("you\\'ve said \\\"hi\\\"\n") == "you've said \"hi\"\n"


def test_escaped_quotes_are_kept_where_the_backslash_matters() -> None:
    md = (
        "`it\\'s` [a](https://x \"say \\\"hi\\\"\") "
        "[s]{style=\"font-family: \\\"Arial\\\"\"} <b title=\"\\'\"> $\\'{e}$ \\\\'\n"
    )
    assert unescape_quotes(md) == md


def test_final_hard_break_is_removed() -> None:
    md = "one\\\n\ntwo\\\n"
    assert drop_final_hard_breaks(md) == "one\n\ntwo\n"


def test_mid_paragraph_hard_break_is_kept() -> None:
    md = "**Heading**\\\nbody text\n"
    assert drop_final_hard_breaks(md) == md


def test_double_break_blank_line_is_kept() -> None:
    md = "text\\\n  \\\n\nnext\n"
    assert drop_final_hard_breaks(md) == md


def test_lone_backslash_line_ending_a_paragraph_is_removed() -> None:
    md = "text\n\\\n\nnext\n"
    assert clean_markdown_body(md) == "text\n\nnext\n"


def test_break_after_a_lone_image_is_kept() -> None:
    """Without it the image becomes a figure whose alt text shows as a caption."""
    md = "![A diagram](a.png)\\\n\nnext\n"
    assert drop_final_hard_breaks(md) == md


def test_escaped_backslash_at_line_end_is_not_a_break() -> None:
    md = "path C:\\\\\n\nnext\n"
    assert drop_final_hard_breaks(md) == md


# ---------------------------------------------------------------------------
# Empty paragraphs made of backslash lines
# ---------------------------------------------------------------------------


def test_empty_break_paragraph_becomes_a_paragraph_break() -> None:
    md = "First part.\\\n\\\nSecond part.\\\n\\\n**Respond:**\n"
    assert clean_markdown_body(md) == "First part.\n\nSecond part.\n\n**Respond:**\n"


def test_empty_break_in_a_list_item_is_deleted_without_a_blank_line() -> None:
    """A blank line would make the whole list loose."""
    md = "- one\n- item text\\\n  \\\n- three\n"
    assert clean_markdown_body(md) == "- one\n- item text\n- three\n"


def test_empty_break_mid_list_item_keeps_the_line_break() -> None:
    md = "- item text\\\n  \\\n  more text\n"
    assert split_empty_break_paragraphs(md) == "- item text\\\n  more text\n"


def test_empty_break_before_an_indented_line_does_not_make_a_code_block() -> None:
    md = "text\\\n\\\n    indented\n"
    assert split_empty_break_paragraphs(md) == "text\\\n    indented\n"


def test_empty_break_inside_a_span_does_not_split_it() -> None:
    md = '[Please do this.\\\n\\\n]{style="font-size: 12pt;"}\n'
    assert split_empty_break_paragraphs(md) == '[Please do this.\\\n]{style="font-size: 12pt;"}\n'


def test_empty_break_at_paragraph_end_is_removed() -> None:
    md = "text\\\n\\\n\nnext\n"
    assert clean_markdown_body(md) == "text\n\nnext\n"


def test_single_break_line_after_plain_text_is_kept() -> None:
    """"text" + "\\" is one <br>, not an empty paragraph."""
    md = "text\n\\\nmore\n"
    assert split_empty_break_paragraphs(md) == md


def test_import_splits_empty_word_paragraphs() -> None:
    md = _html_to_markdown("<p>One.<br><br>Two.</p>")
    assert md.strip() == "One.\n\nTwo."


# ---------------------------------------------------------------------------
# Emphasis spaces
# ---------------------------------------------------------------------------


def test_space_inside_bold_closer_is_moved_out() -> None:
    md = "**Scenario: **In one class, **the next 2 years **to begin.\n"
    assert fix_emphasis_spaces(md) == (
        "**Scenario:** In one class, **the next 2 years** to begin.\n"
    )


def test_space_before_bold_closer_at_line_end_is_dropped() -> None:
    assert fix_emphasis_spaces("**Respond: **\n") == "**Respond:**\n"


def test_italic_closer_space_is_moved_out() -> None:
    assert fix_emphasis_spaces("*note: *then\n") == "*note:* then\n"


def test_unbalanced_emphasis_is_left_alone() -> None:
    md = "**a **b **c\n"
    assert fix_emphasis_spaces(md) == md


def test_triple_star_paragraph_is_left_alone() -> None:
    md = "***AI Guideline:** *You may use tools, **however** **you must. **AI x\n"
    assert fix_emphasis_spaces(md) == md


def test_emphasis_pairs_within_each_list_item() -> None:
    md = "1.  **a **b\n2.  **Heading\\**\n    text **\n"
    assert fix_emphasis_spaces(md) == "1.  **a** b\n2.  **Heading\\**\n    text **\n"


def test_bullets_and_arithmetic_are_not_emphasis() -> None:
    md = "* item with 5 * 3\n* **bold**\n"
    assert fix_emphasis_spaces(md) == md


def test_emphasis_in_code_is_untouched() -> None:
    md = "`**a **b` and **c **d\n"
    assert fix_emphasis_spaces(md) == "`**a **b` and **c** d\n"


# ---------------------------------------------------------------------------
# Stacked list markers
# ---------------------------------------------------------------------------


def test_stacked_bullets_are_flattened() -> None:
    md = "- - - First\n    - Second\n    - Third\n\nAfter\n"
    assert flatten_stacked_list_markers(md) == "- First\n- Second\n- Third\n\nAfter\n"


def test_stacked_numbers_are_flattened_with_continuations() -> None:
    md = "1.  1.  Think\n        more of item one\n    2.  The chapter\n"
    assert flatten_stacked_list_markers(md) == (
        "1.  Think\n    more of item one\n2.  The chapter\n"
    )


def test_stacked_markers_keep_nested_children() -> None:
    md = "- - Stop\n    - *Consider*\n  - Investigate\n"
    assert flatten_stacked_list_markers(md) == "- Stop\n  - *Consider*\n- Investigate\n"


def test_stacked_markers_inside_an_indented_block() -> None:
    md = "    - - - - Please\n          - If you\n"
    assert flatten_stacked_list_markers(md) == "    - Please\n    - If you\n"


def test_thematic_break_and_ordinary_lists_are_untouched() -> None:
    md = "- - -\n\n- a\n  - b\n"
    assert flatten_stacked_list_markers(md) == md


def test_import_flattens_stacked_lists() -> None:
    md = _html_to_markdown("<ul><li><ul><li>a</li><li>b</li></ul></li></ul>")
    assert md.strip() == "- a\n- b"


def test_import_unescapes_quotes() -> None:
    assert _html_to_markdown("<p>it's \"x\"</p>").strip() == "it's \"x\""


# ---------------------------------------------------------------------------
# Horizontal rules
# ---------------------------------------------------------------------------


def test_long_horizontal_rule_is_shortened() -> None:
    md = "## Steps\n\n" + "-" * 72 + "\n\n1.  Read\n"
    assert shorten_horizontal_rules(md) == "## Steps\n\n---\n\n1.  Read\n"


def test_rule_at_start_and_end_of_text_is_shortened() -> None:
    assert shorten_horizontal_rules("-----\n\ntext\n\n-----") == "---\n\ntext\n\n---"


def test_rule_next_to_a_div_fence_is_shortened() -> None:
    md = "::: {style=\"x\"}\n----------\n:::\n"
    assert shorten_horizontal_rules(md) == "::: {style=\"x\"}\n---\n:::\n"


def test_setext_underline_is_untouched() -> None:
    md = "Heading\n----------\n\ntext\n"
    assert shorten_horizontal_rules(md) == md


def test_multiline_table_borders_are_untouched() -> None:
    md = (
        "\n" + "-" * 30 + "\n Header   Other\n-------- ---------\n cell     cell\n"
        + "-" * 30 + "\n\n"
    )
    assert shorten_horizontal_rules(md) == md


def test_rule_in_code_block_is_untouched() -> None:
    md = "```\n\n----------\n\n```\n"
    assert shorten_horizontal_rules(md) == md


def test_import_writes_short_rules() -> None:
    assert _html_to_markdown("<p>a</p><hr><p>b</p>").strip() == "a\n\n---\n\nb"


# ---------------------------------------------------------------------------
# fix-markdown: whole file
# ---------------------------------------------------------------------------


def test_frontmatter_is_untouched() -> None:
    text = "---\ntitle: \"It\\'s [a][b]\"\n---\nbody \\'x\\'\n"
    assert clean_markdown_file_text(text) == (
        "---\ntitle: \"It\\'s [a][b]\"\n---\nbody 'x'\n"
    )


def test_existing_two_space_hard_break_is_kept_on_a_changed_line() -> None:
    md = "it\\'s here  \nnext line\n"
    assert clean_markdown_body(md) == "it's here  \nnext line\n"


def test_clean_file_is_unchanged() -> None:
    md = "# Title\n\nPlain [link](https://x) text.\n"
    assert clean_markdown_body(md) == md


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def _repo(tmp_path: Path) -> Path:
    root = tmp_path / "course"
    make_current(root)
    (root / "pages").mkdir()
    (root / "pages" / "a.md").write_text("---\ntitle: A\n---\nyou\\'re [x ][y]\n")
    (root / "pages" / "clean.md").write_text("fine\n")
    (root / "quizzes" / "q" / "questions").mkdir(parents=True)
    (root / "quizzes" / "q" / "questions" / "q1.md").write_text("it\\'s\n")
    (root / "README.md").write_text("not \\'content\\'\n")
    return root


def test_collect_markdown_files_covers_content_and_quiz_questions(tmp_path: Path) -> None:
    root = _repo(tmp_path)
    rel = {p.relative_to(root).as_posix() for p in collect_markdown_files(root)}
    assert rel == {"pages/a.md", "pages/clean.md", "quizzes/q/questions/q1.md"}


def test_cli_dry_run_reports_without_writing(tmp_path: Path) -> None:
    root = _repo(tmp_path)
    result = CliRunner().invoke(main, ["fix-markdown", str(root)])
    assert result.exit_code == 0, result.output
    assert "pages/a.md" in result.output
    assert "2 would change" in result.output
    assert (root / "pages" / "a.md").read_text().endswith("you\\'re [x ][y]\n")


def test_cli_apply_rewrites_files(tmp_path: Path) -> None:
    root = _repo(tmp_path)
    result = CliRunner().invoke(main, ["fix-markdown", str(root), "--apply"])
    assert result.exit_code == 0, result.output
    assert (root / "pages" / "a.md").read_text() == "---\ntitle: A\n---\nyou're x y\n"
    assert (root / "quizzes" / "q" / "questions" / "q1.md").read_text() == "it's\n"
    assert (root / "README.md").read_text() == "not \\'content\\'\n"
