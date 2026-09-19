"""Write the TOML files the tool generates, with a fixed layout per key.

`tomli_w` picks between `[[table]]` blocks and inline `[{...}]` arrays from a
row-length heuristic the caller cannot override. In TOML a `[[table]]` header
captures every bare key after it, so a row that grew past the threshold could
silently move top-level keys into a table. Here the layout depends only on the
key:

- keys in INLINE_TABLE_ARRAY_KEYS are inline arrays of inline tables, however
  long the rows are;
- any other list of dicts is a `[[table]]` block array;
- a list of lists (grading-scale `data`) is one multi-line outer array with each
  inner array on a single line;
- a list of scalars is one line, or one item per line when it is long.

Items must be added in their final order: `tomlkit` appends, so a bare key added
after a table header would land inside that table. `fill_table` therefore adds
every plain key before any sub-table.
"""
from __future__ import annotations

from typing import Any

import tomlkit
from tomlkit.items import AoT, Array

#: Keys whose list of dicts is always written as an inline array of inline tables.
INLINE_TABLE_ARRAY_KEYS = frozenset(
    {"tab_configuration", "due_dates", "ratings", "rules", "folders", "files"}
)

#: A scalar array longer than this (rendered on one line) is split one item per line.
_MAX_ONE_LINE = 72


def _is_dict_list(value: Any) -> bool:
    return isinstance(value, list) and bool(value) and all(isinstance(v, dict) for v in value)


def _is_list_list(value: Any) -> bool:
    return isinstance(value, list) and bool(value) and all(isinstance(v, list) for v in value)


def is_block(key: str, value: Any) -> bool:
    """True when `value` is written as a `[table]` / `[[table]]` section."""
    if isinstance(value, dict):
        return True
    return _is_dict_list(value) and key not in INLINE_TABLE_ARRAY_KEYS


def _inline_value(value: Any) -> Any:
    """A value that must fit inside an inline table or inner array."""
    if isinstance(value, dict):
        table = tomlkit.inline_table()
        for k, v in value.items():
            table.append(k, _inline_value(v))
        return table
    if isinstance(value, list):
        arr = tomlkit.array()
        for v in value:
            arr.append(_inline_value(v))
        return arr
    return tomlkit.item(value)


def inline_table_array(rows: list[dict[str, Any]]) -> Array:
    """An array of inline tables, one row per line."""
    arr = tomlkit.array()
    arr.multiline(True)
    for row in rows:
        table = tomlkit.inline_table()
        for k, v in row.items():
            table.append(k, _inline_value(v))
        arr.append(table)
    return arr


def pair_array(rows: list[list[Any]]) -> Array:
    """A multi-line array of arrays, each inner array on one line."""
    arr = tomlkit.array()
    arr.multiline(True)
    for row in rows:
        arr.append(_inline_value(row))
    return arr


def scalar_array(values: list[Any], multiline: bool | None = None) -> Array:
    """An array of scalars; one line unless `multiline` or the line would be long."""
    arr = tomlkit.array()
    for v in values:
        arr.append(_inline_value(v))
    if multiline is None:
        multiline = len(arr.as_string()) > _MAX_ONE_LINE
    if multiline:
        arr.multiline(True)
    return arr


def value_for(key: str, value: Any) -> Any:
    """The tomlkit item for a non-block `value` stored under `key`."""
    if _is_dict_list(value):
        return inline_table_array(value)
    if _is_list_list(value):
        return pair_array(value)
    if isinstance(value, list):
        return scalar_array(value)
    return tomlkit.item(value)


def block_array(
    rows: list[dict[str, Any]], commented: frozenset[str] = frozenset()
) -> AoT:
    """A `[[table]]` array; each row is filled with `fill_table`."""
    aot = tomlkit.aot()
    for row in rows:
        table = tomlkit.table()
        fill_table(table, row, commented)
        aot.append(table)
    return aot


def fill_table(
    container: Any, data: dict[str, Any], commented: frozenset[str] = frozenset()
) -> None:
    """Add `data` to a table or document: plain keys first, then sub-tables.

    A plain key named in `commented` is written as a `# key = value` comment in
    its place instead. Sub-tables and block arrays are never commented.
    """
    for key, value in data.items():
        if is_block(key, value):
            continue
        if key in commented:
            container.add(tomlkit.comment(assignment(key, value)))
        else:
            container.add(key, value_for(key, value))
    for key, value in data.items():
        if not is_block(key, value):
            continue
        if isinstance(value, dict):
            table = tomlkit.table()
            fill_table(table, value, commented)
            container.add(key, table)
        else:
            container.add(key, block_array(value, commented))


def dumps(data: dict[str, Any], header: str = "", commented: frozenset[str] = frozenset()) -> str:
    """Serialize `data` as a whole TOML file, optionally under a comment `header`."""
    doc = tomlkit.document()
    if header:
        add_comment_text(doc, header)
    fill_table(doc, data, commented)
    return tomlkit.dumps(doc)


def assignment(key: str, value: Any) -> str:
    """The text `key = value` for one plain key, escaped by tomlkit."""
    doc = tomlkit.document()
    doc.add(key, value_for(key, value))
    return tomlkit.dumps(doc).rstrip("\n")


def add_commented(container: Any, data: dict[str, Any]) -> None:
    """Add every plain key of `data` as a `# key = value` comment line."""
    for key, value in data.items():
        container.add(tomlkit.comment(assignment(key, value)))


def add_comment_text(container: Any, text: str) -> None:
    """Add lines of `#`-prefixed text (and blank lines) to a document.

    A line is a comment when it starts with `#`, else it must be empty.
    """
    for line in text.splitlines():
        if not line:
            container.add(tomlkit.nl())
        elif line.startswith("# "):
            container.add(tomlkit.comment(line[2:]))
        elif line == "#":
            container.add(tomlkit.comment(""))
        else:
            raise ValueError(f"not a comment or blank line: {line!r}")
