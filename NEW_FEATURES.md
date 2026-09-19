# New Features

Feature ideas to write up as OpenSpec proposals later. Each entry records the idea
and the parts of the current tool it would build on.

## 2. Consider `tomlkit` instead of `tomli_w` for writing `course_settings`

### Problem

`tomli_w` decides on its own whether an array of tables gets written in
`[[table]]` block style or inline `[{...}, {...}]` style, based on a hardcoded
100-character-per-row heuristic with no way to force one style or the other.
In TOML, once a `[[table]]` block header appears, any bare top-level keys that
follow it in the file get silently swallowed into that table instead of
staying at the top level — so if a future edit (by us or by hand) pushes a
row over that length threshold, `tomli_w` could switch styles on us and
corrupt the file's structure without raising any error.

### Idea

Use `tomlkit` for writing `course_settings` files instead. `tomlkit` builds
TOML documents from explicit typed objects (`tomlkit.aot()` for array-of-tables
block style, `tomlkit.array()` + `tomlkit.inline_table()` for inline style), so
the style is a deliberate choice at write time rather than a length-based
guess — removing the risk entirely.

### Current state

`tomlkit` is now a runtime dependency. `upgrade` and the `tab_configuration`
placement fix use it to edit `course_settings.toml` in place (comments and
layout preserved; see ARCHITECTURE.md "Repo format version and `upgrade`").
`import` and `mv` still write with `tomli_w`; replacing it there is the
remaining work.

## 3. Move the 'relative due date' calculations from ~/mikesgradingtool/config.json to course_settings.toml
