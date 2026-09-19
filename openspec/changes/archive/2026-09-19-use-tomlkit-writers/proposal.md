# Proposal

## Why

`tomli_w` chooses between block (`[[table]]`) and inline (`[{...}, {...}]`)
style for an array of tables from a hardcoded row-length heuristic, and the
caller cannot override it. In TOML, once a `[[table]]` header appears, later
bare top-level keys belong to that table. A row that grows past the threshold
can therefore flip the style and silently move keys out of the top level.
`import` already hit this once (`tab_configuration` landed under
`[default_post_policy]`) and works around it with careful key ordering and a
single combined dump. The same flip also applies to nested arrays: in
`grading_standards`, the `data` list of `[name, value]` pairs is written one
pair per line today (four lines each), and its layout also depends on the
heuristic.

`tomlkit` builds documents from explicit typed objects, so the style becomes a
choice made at write time. `tomlkit` is already a runtime dependency (added for
`upgrade`), so this completes the migration begun there.

`mv` also has a bug users can hit today: it rewrites `module_order.toml` with a
load and `tomli_w.dump` round trip, which drops any hand-written comments.

## What Changes

- `import` writes `course_settings.toml`, `rubrics.toml`, `files_meta.toml`,
  question-bank `.toml` files and `module_order.toml` with `tomlkit`.
- Each array of tables gets an explicit style:
  - inline: `tab_configuration`, `due_dates`, rubric `ratings`,
    `assignment_groups[].rules`, and `folders` and `files` in `files_meta.toml`
  - block: `grading_standards`, `assignment_groups`, and rubric `criteria`
  - `grading_standards[].data` (a list of `[name, value]` pairs): one pair per
    line, each pair on a single line, in plain `tomlkit` style
    (`["A (4.0)", 0.95],`)
- The comment-out workarounds are replaced by real `tomlkit` comments while
  keeping commented keys above the first table header: `_commented_toml`,
  `_comment_out_keys`, and the hand-built `files_meta.toml` and `rubrics.toml`
  header text.
- `mv` updates `module_order.toml` by parsing it with `tomlkit`, changing
  `order`, and dumping it, so comments and layout survive.
- Manifest writers (`manifest.flush`, `repo_format._write_manifest`) stay on
  `tomli_w`. `tomli_w` remains a dependency.
- No `repo_format.FORMAT_VERSION` bump. The keys and values written are
  unchanged, and files written by the old tool still parse.
- Tests that assert on `tomli_w`'s output text are updated.
- `NEW_FEATURES.md` item 2 is removed once done.

## Capabilities

### New Capabilities
- `toml-writer-style`: how the tool's generated TOML files (settings, rubrics,
  files metadata, question banks, module order) lay out arrays of tables and
  commented import-only keys, and that `mv` preserves comments in
  `module_order.toml`.

### Modified Capabilities
<!-- None. repo-format-version requirements are unchanged; see design.md for why no version bump is needed. -->

## Impact

- Existing mechanisms: `upgrade` and the `tab_configuration` placement fix
  (`repo_format.py`) already edit `course_settings.toml` with `tomlkit`. `mv`
  already edits `course_settings.toml` as raw text (`_set_toml_string_value`,
  `_replace_toml_quoted_string`). These are kept as they are. Only
  `mv`'s `module_order.toml` write uses `tomli_w`.
- TODO.md: no item is affected. NEW_FEATURES.md item 2 is the source and is
  removed when complete.
- Core subcommands:
  - `import`: affected, since it is the main writer.
  - `mv`: affected, for `module_order.toml` only.
  - `update`: not affected. It only reads these files and writes manifests,
    which stay on `tomli_w`.
  - `publish`: not affected. It reads settings and writes none of these files.
- Code: `imscc_import.py` (about 10 `tomli_w` call sites), `mv.py:786`.
  `manifest.py` and `repo_format._write_manifest` are unchanged.
- Tests: `tests/test_imscc_convert.py`, `tests/test_imscc_import.py`,
  `tests/test_mv.py`, and any other test asserting on generated TOML text.
- Docs: ARCHITECTURE.md (import mechanics, `tab_configuration` note, `upgrade`
  note saying `import` still uses `tomli_w`), README.md only if generated-file
  layout is described, NEW_FEATURES.md.
- Dependencies: none added or removed.
