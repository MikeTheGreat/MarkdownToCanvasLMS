# New Features

Feature ideas to write up as OpenSpec proposals later. Each entry records the idea
and the parts of the current tool it would build on.

## 1. Record the tool version that generated or last touched the files

### Problem

The repo's file formats change as the tool changes (for example, `import` used to
place `tab_configuration` under `[default_post_policy]`, and `import`'s default
`.canvasignore` has gained entries). A repo carries no record of which version of
the tool created it, so it is hard to tell whether a problem comes from an old
import or from the current code.

### Idea

Write the tool's version into the repo:

- `import` writes the version that created the repo.
- Possibly `update` records the version that last synced it.
- Possible locations: `course_settings/canvas.toml`, `course_settings/course_settings.toml`,
  or the manifest. `canvas.toml` is per course section and may not be committed;
  `course_settings.toml` is shared and committed; the manifest is written by
  `update` already.

### Existing mechanisms to account for

- `pyproject.toml` has `version = "0.2.0"`, but nothing in `src/` reads it, and the
  version is not bumped as features land. This feature needs a version bump
  policy (or a git commit hash) to be useful.
- `course_settings.toml` uses section hashes for change detection; a new
  top-level key there would fall into the `metadata` section, so changing it would
  re-send course metadata to Canvas unless it is excluded the way `due_dates` and
  `pinned_resources` are.

### Open questions

- Store only "created by", or also "last synced by"?
- Should `update` warn when the repo was created by a newer version than the one
  running, or offer migrations for known format changes from older versions?

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
