# Tasks

## 1. Spike

- [x] 1.1 Write a scratch script (in the scratchpad, not the repo) that builds a small `tomlkit` document with an inline `tab_configuration`, block `grading_standards` whose `data` is a multi-line outer array of one-line `[name, value]` pairs, and leading and top-level comments. Verify it prints the expected layout and that `tomllib` parses it to the expected data.
- [x] 1.2 In the same script, check how `tomlkit` renders strings containing newlines, quotes and backslashes, and how it renders a long inline array. Record the answers to both Open Questions in design.md.

## 2. Shared helpers

- [x] 2.1 Add a small helper module (for example `toml_write.py`) with builders for inline arrays of inline tables, block arrays of tables, and a "commented key" line rendered from a key and value. Verify with unit tests that each style is produced regardless of row count or row length (a 1-row and a 500-character-row case for each).

## 3. `import` writers

- [x] 3.1 Rewrite `_write_course_settings_toml` to build one `tomlkit` document in the order: version keys, flat keys, commented blocks, `due_dates` and `tab_configuration` (top-level inline arrays), `[late_policy]`/`[default_post_policy]`, then `grading_standards` and `assignment_groups` in their fixed styles. Verify the existing settings tests pass with parsed-data assertions and that `format_version`, `created_by`, `due_dates` and `tab_configuration` are top-level keys.
- [x] 3.2 Replace `_commented_toml` and `format_due_dates_toml` (if the spike shows equivalent output) with the shared helpers. Verify uncommenting each commented key in a generated file parses to the original value, including a value with a quote and a backslash.
- [x] 3.3 Rewrite `_write_rubrics_toml` (criteria block, ratings inline, import-only rubric and criterion keys commented, header as a leading comment) and delete `_comment_out_keys`. Verify with a rubric test that ratings stay inline for both a short and a long rating row and that commented keys precede the table they belong to.
- [x] 3.3a Write `grading_standards[].data` as an outer multi-line array of inner arrays, each pair on a single line in plain `tomlkit` style (`["A (4.0)", 0.95],`). Verify with a test that a many-pair `data` produces one line per pair and parses back to the original pairs.
- [x] 3.4 Rewrite `_write_files_meta_toml` and the question-bank `.toml` write with `tomlkit`. Verify the parsed data equals the input dicts.
- [x] 3.5 Write `module_order.toml` in `import` with `tomlkit` instead of hand-built text. Verify it parses to `{"order": [...]}` with the same entries as before.

## 4. `mv`

- [x] 4.1 Change the `module_order.toml` update in `mv.py` to parse with `tomlkit`, set `order`, and dump. Verify with a `test_mv.py` test that a comment in the file survives a module rename and that only the affected `order` entry changes.
- [x] 4.2 Verify a test that moves a non-module file leaves `module_order.toml` byte-identical.

## 5. Tests and cleanup

- [x] 5.1 Update tests that assert on `tomli_w` output text or reference it in docstrings (`tests/test_imscc_convert.py:104`, `tests/test_imscc_import.py:553`, and any others found by `grep -rn tomli_w tests`). Verify `uv run pytest` passes with Canvas mocked.
- [x] 5.2 Add a regression test that a `tab_configuration` with rows over 100 characters and a `grading_standards` entry with a long `data` list both keep their fixed style and leave top-level keys top-level.
- [x] 5.3 Confirm `grep -rn tomli_w src` shows only `manifest.py` and `repo_format._write_manifest`. Verify manifest tests still pass unchanged.
- [x] 5.4 Run `import` on an existing test cartridge and compare the parsed data of each generated TOML file with the output from before the change (git stash or worktree). Verify they are equal.

## 6. Core subcommands

- [x] 6.1 Confirm the change is applied to the core subcommands where applicable: `import` (3.x) and `mv` (4.x) are covered; `update` and `publish` write none of these files and read them as before, so verify their existing tests pass unchanged.

## 7. Documentation

- [x] 7.1 Update ARCHITECTURE.md: rewrite the import mechanics paragraphs that describe `tomli_w` workarounds (commented import-only keys, ordering, `tab_configuration` humanising), document the fixed per-key array styles, and change the `upgrade` note that says `import` still writes with `tomli_w` to say only manifests do.
- [x] 7.2 Update README.md only if it describes the layout of generated files; verify by grepping README.md for `tab_configuration`, `rubrics.toml` and `module_order`.
- [x] 7.3 Remove item 2 (the `tomlkit` entry) from NEW_FEATURES.md and check TODO.md for any item this affects; verify no "DONE" markers are left behind.
