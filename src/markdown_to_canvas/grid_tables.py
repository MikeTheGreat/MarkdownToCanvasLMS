"""Convert pandoc grid tables to pipe tables or HTML tables (fix-markdown).

A grid table pads every cell to a fixed width, and pandoc finds the cells by
column position. Any edit that shortens a cell's text without re-padding it
(removing a ``{#id style="..."}`` block, unwrapping a styled span) leaves the
``|`` separators out of line with the ``+---+`` borders, and pandoc then reads
each row as one merged cell with literal ``|`` and ``**`` in it. Imports made
before import switched to pipe tables contain such tables.

This parser is deliberately lenient: it finds cells by splitting each row line
on unescaped ``|`` characters, not by column position, so it recovers the
cells of a misaligned table as well as an intact one. Cell text is carried
over as written (links, snippet references and attribute blocks included).

Output follows import (`imscc_import._PANDOC_TO_MARKDOWN`): a pipe table when
every cell is one paragraph of inline text, otherwise an HTML ``<table>``
whose cells hold Markdown (pandoc's ``markdown_in_html_blocks`` parses it).
Only the first header row becomes the header; any further header rows (pandoc
writes ``+===+`` at the bottom of a table whose rows are all headers) and
footer rows become body rows, as pandoc's own pipe-table writer does.
"""

from __future__ import annotations

import re
import textwrap
from dataclasses import dataclass

_BORDER_RE = re.compile(r"^\+[-=:+]*[-=][-=:+]*\+$")
_ROW_RE = re.compile(r"^\|.*\|$")
# A partial separator inside a row: pandoc's grid-table row spans.
_INNER_BORDER_RE = re.compile(r"\+[-=]{3,}")
_BLOCK_LINE_RE = re.compile(
    r"^(?:#{1,6}[ \t]|[-*+][ \t]|\d+[.)][ \t]|>|```|~~~|:::|<(?:div|p|ul|ol|table|h[1-6])\b)",
    re.IGNORECASE,
)


@dataclass
class TableWarning:
    line: int  # 1-based, within the text passed in
    reason: str


def _split_cells(inner: str) -> list[str] | None:
    """Split a row line's text (outer pipes removed) on unescaped ``|`` that
    are outside inline code. None if a code span is left open."""
    cells: list[str] = []
    start = i = 0
    n = len(inner)
    while i < n:
        ch = inner[i]
        if ch == "\\":
            i += 2
            continue
        if ch == "`":
            j = i
            while j < n and inner[j] == "`":
                j += 1
            run = inner[i:j]
            close = inner.find(run, j)
            while close != -1 and (
                (close + len(run) < n and inner[close + len(run)] == "`")
                or (close > 0 and inner[close - 1] == "`")
            ):
                close = inner.find(run, close + 1)
            if close == -1:
                return None
            i = close + len(run)
            continue
        if ch == "|":
            cells.append(inner[start:i])
            start = i + 1
        i += 1
    cells.append(inner[start:])
    return cells


def _border_segments(border: str) -> list[str]:
    return border[1:-1].split("+")


def _alignment(segment: str) -> str | None:
    left, right = segment.startswith(":"), segment.endswith(":")
    if left and right:
        return "center"
    if right:
        return "right"
    if left:
        return "left"
    return None


def _cell_lines(lines: list[str]) -> list[str]:
    """A cell's lines, dedented, right-stripped, outer blank lines removed."""
    text = textwrap.dedent("\n".join(line.rstrip() for line in lines))
    out = text.split("\n")
    while out and not out[0].strip():
        out.pop(0)
    while out and not out[-1].strip():
        out.pop()
    return out


def _is_inline(cell: list[str]) -> bool:
    """One paragraph of inline text, writable on one line."""
    if any(not line.strip() for line in cell):
        return False  # a blank line: several paragraphs
    for k, line in enumerate(cell):
        if _BLOCK_LINE_RE.match(line):
            return False
        if line.endswith("\\") or line.endswith("  "):
            return False  # a hard line break
        if k and line.startswith(" "):
            return False  # indented continuation: nested block content
    return True


def _inline_text(cell: list[str]) -> str:
    return " ".join(line.strip() for line in cell)


def _pipe_safe(cell: list[str]) -> bool:
    """Inline, and with no "|" (inside inline code) that a pipe table would
    take for a cell boundary."""
    if not cell:
        return True
    if not _is_inline(cell):
        return False
    parts = _split_cells(_inline_text(cell))
    return parts is not None and len(parts) == 1 and "|" not in "".join(
        m.group(0) for m in re.finditer(r"(`+).+?\1", _inline_text(cell))
    )


@dataclass
class _Table:
    aligns: list[str | None]
    header: list[list[str]] | None  # one row of cells, each a list of lines
    body: list[list[list[str]]]


def _parse(block: list[str]) -> _Table | str:
    """Parse a grid table's lines (indent removed); a str is why it can't be."""
    borders = [i for i, line in enumerate(block) if _BORDER_RE.match(line)]
    ncols = len(_border_segments(block[0]))
    for i in borders:
        if len(_border_segments(block[i])) != ncols:
            return "a border has a different number of columns (merged cells)"
    rows: list[list[list[str]]] = []
    current: list[list[str]] | None = None
    for line in block:
        if _BORDER_RE.match(line):
            if current is not None:
                rows.append(current)
            current = [[] for _ in range(ncols)]
            continue
        cells = _split_cells(line[1:-1])
        if cells is None:
            return "a row has an unclosed `code span`"
        if len(cells) != ncols:
            return f"a row has {len(cells)} cells instead of {ncols}"
        if any(_INNER_BORDER_RE.search(c) for c in cells):
            return "a cell spans several rows"
        assert current is not None
        for col, text in enumerate(cells):
            current[col].append(text)
    rows = [[_cell_lines(c) for c in row] for row in rows if row and row[0]]
    if not rows:
        return "it has no rows"

    # The first "=" border below the top one ends the header rows.
    first_eq = next((i for i in borders[1:] if "=" in block[i]), None)
    align_src = block[first_eq] if first_eq is not None else block[0]
    aligns = [_alignment(s) for s in _border_segments(align_src)]
    if first_eq is None:
        return _Table(aligns, None, rows)
    return _Table(aligns, rows[0], rows[1:])


def _pipe_lines(table: _Table) -> list[str]:
    def row(cells: list[list[str]]) -> str:
        return "| " + " | ".join(_inline_text(c) for c in cells) + " |"

    seps = {None: "---", "left": ":---", "right": "---:", "center": ":---:"}
    header = row(table.header) if table.header else "|" + "  |" * len(table.aligns)
    out = [header, "| " + " | ".join(seps[a] for a in table.aligns) + " |"]
    out.extend(row(r) for r in table.body)
    return out


def _html_lines(table: _Table) -> list[str]:
    def cell(tag: str, lines: list[str], align: str | None) -> list[str]:
        attr = f' style="text-align: {align};"' if align else ""
        if not lines:
            return [f"<{tag}{attr}></{tag}>"]
        if _is_inline(lines):
            return [f"<{tag}{attr}>{_inline_text(lines)}</{tag}>"]
        # Blank lines around the content make pandoc parse it as Markdown blocks.
        return [f"<{tag}{attr}>", "", *lines, "", f"</{tag}>"]

    def row(tag: str, cells: list[list[str]]) -> list[str]:
        out = ["<tr>"]
        for c, a in zip(cells, table.aligns):
            out.extend(cell(tag, c, a))
        out.append("</tr>")
        return out

    out = ["<table>"]
    if table.header:
        out += ["<thead>", *row("th", table.header), "</thead>"]
    out.append("<tbody>")
    for r in table.body:
        out.extend(row("td", r))
    out += ["</tbody>", "</table>"]
    return out


def convert_grid_tables(
    markdown: str, skip_lines: set[int] | None = None
) -> tuple[str, list[TableWarning]]:
    """Replace every grid table with a pipe table, or an HTML table when a
    cell holds more than one paragraph of inline text.

    `skip_lines` holds 0-based indices of lines in code blocks; a table
    starting on one is left alone. A table that can't be parsed (merged cells,
    rows with differing cell counts) is left unchanged and reported.
    """
    skip = skip_lines or set()
    lines = markdown.split("\n")
    out: list[str] = []
    warnings: list[TableWarning] = []
    i = 0
    while i < len(lines):
        line = lines[i]
        stripped = line.strip()
        if i in skip or not _BORDER_RE.match(stripped):
            out.append(line)
            i += 1
            continue
        indent = line[: len(line) - len(line.lstrip())]
        j = i + 1
        while j < len(lines) and lines[j].startswith(indent):
            s = lines[j].strip()
            if not (_BORDER_RE.match(s) or _ROW_RE.match(s)):
                break
            j += 1
        # The table ends at its last border line.
        end = j
        while end > i and not _BORDER_RE.match(lines[end - 1].strip()):
            end -= 1
        block = [lines[k].strip() for k in range(i, end)]
        if end - i < 3:
            out.append(line)
            i += 1
            continue
        parsed = _parse(block)
        if isinstance(parsed, str):
            warnings.append(TableWarning(i + 1, parsed))
            out.extend(lines[i:end])
        else:
            cells = ([parsed.header] if parsed.header else []) + parsed.body
            inline = all(_pipe_safe(c) for r in cells for c in r)
            new = _pipe_lines(parsed) if inline else _html_lines(parsed)
            out.extend(indent + n if n else "" for n in new)
        i = end
    return "\n".join(out), warnings
