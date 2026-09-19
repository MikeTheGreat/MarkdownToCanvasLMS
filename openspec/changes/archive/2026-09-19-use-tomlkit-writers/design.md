# Design

## Context

See proposal.md for motivation. Current state, from the code:

- `imscc_import.py` writes `course_settings.toml` with five `tomli_w.dumps`
  calls interleaved with hand-built text (`format_due_dates_toml`,
  `_commented_toml`, literal comment headers). Ordering (flat keys, commented
  block, `due_dates`, then one combined dump of tables and arrays of tables)
  is what keeps top-level keys out of tables.
- `rubrics.toml` is one `tomli_w.dumps` call post-processed by
  `_comment_out_keys`, which relies on `tomli_w` never emitting multi-line
  values. `files_meta.toml` and question-bank `.toml` are plain dumps with a
  header.
- Measured with the installed `tomli_w`: a rubric dumps as `[[rubrics]]` with
  `[[rubrics.criteria]]` blocks and an inline `ratings` array; `grading_standards`
  dumps as `[[grading_standards]]` blocks whose `data` is a list of
  `[name, value]` pairs. `tomli_w` writes each pair across four lines
  (`[`, name, value, `],`). Which arrays are inline depends on `tomli_w`'s
  length heuristic, not on the key.
- `module_order.toml` is written by `import` as hand-built text and rewritten
  by `mv` (`mv.py:~780`) with `tomllib.load` then `tomli_w.dump`, which drops
  comments.
- `repo_format.py` already uses `tomlkit` (parse, edit, `dumps`) for
  `upgrade`. `mv` edits `course_settings.toml` as raw text and is left alone.

## Goals / Non-Goals

**Goals:**
- Array-of-tables style determined by key, not content length.
- One writer library for every file `import` generates and for `mv`'s
  `module_order.toml`.
- Keep top-level keys before the first table header by construction.
- Remove the line-based comment-out and text-assembly workarounds where
  `tomlkit` comments make them unnecessary.

**Non-Goals:**
- Manifests (`manifest.flush`, `repo_format._write_manifest`) stay on `tomli_w`.
- `mv`'s raw-text edits of `course_settings.toml` are not rewritten.
- No change to which keys or values are written, and no new user-facing options.

## Decisions

All of the following were confirmed by the user in conversation.

1. **Scope C.** Convert `import` and `mv`; leave manifests alone. Alternatives
   were only the `mv` fix (A) or A plus the `course_settings.toml` writer (B).
2. **Explicit style per key**, built with `tomlkit.aot()` for block style and
   `tomlkit.array()` of `tomlkit.inline_table()` for inline style:
   - inline: `tab_configuration`, `due_dates`, rubric `ratings`,
     `assignment_groups[].rules`, and `folders` and `files` in `files_meta.toml`
     (found in the baseline import output; they are inline today by the same
     heuristic)
   - block: `grading_standards`, `assignment_groups`, rubric `criteria`
   - `grading_standards[].data`: an outer multi-line array
     (`tomlkit.array().multiline(True)`) of inner arrays, each written on one
     line. This is plain `tomlkit` output (`["A (4.0)", 0.95],`). The user
     considered `[ "A (4.0)", 0.95, ],` (spaces inside brackets, trailing
     comma) and chose the plain style because the spaced style needs a
     parse-a-string workaround to preserve the extra whitespace. Verified in a
     scratch test with `tomlkit` 0.15.1 that this parses back to the same data.
   Except for the one-line pairs, these match what the tool produces for
   typical inputs today. The nested `data` array is listed because the same
   length heuristic applies to arrays nested in a block table.
3. **Comments replace the workarounds.** Import-only keys are added to the
   document as `tomlkit` comments carrying `key = value` text rendered by
   `tomlkit` (so escaping stays correct), in place of `_commented_toml` and
   `_comment_out_keys`. The header comments for `rubrics.toml` and
   `files_meta.toml` become document-leading comments. Commented keys are
   added before the first table so they stay above it.
4. **`mv` uses parse, modify, dump** on `module_order.toml` so comments and
   layout survive.
5. **No `FORMAT_VERSION` bump.** The bump rule in CLAUDE.md applies when the
   tool reads an existing file differently, or an older tool would misread a
   newly written file. Neither holds: keys and values are the same, only the
   text layout of arrays may differ, and both layouts are valid TOML that
   older and newer tools parse to the same data. Existing repos need no
   `upgrade` step and no migration.
6. **`tomli_w` remains a dependency** for the manifests. Manifest format is
   unchanged, so nothing needs migrating and existing manifests are read as
   before.

## Risks / Trade-offs

- [Generated files differ textually from before, so diffs in a re-imported repo
  may be noisy] → Acceptable per the user ("we can always revert in git");
  tests compare parsed data, plus targeted text assertions for style and header
  ordering.
- [`tomlkit` API details for comments and ordering inside a `Table` or `AoT`
  may not behave as assumed] → Tasks begin with a spike script that builds a
  small document and asserts the style and ordering, before rewriting the
  writers.
- [`tomlkit` renders inline tables and long inline arrays with its own
  whitespace, possibly different from the current four-space multi-line
  layout] → Style is specified as inline vs block, not exact whitespace; the
  spec does not promise byte-for-byte output.
- [`tomlkit` is slower than `tomli_w`] → Irrelevant at this file size.
- [A rating's `id` inside an inline table still cannot be commented out] →
  Unchanged from today; the header comment continues to say so.
- No Canvas API behavior is involved, so nothing here is unverified against
  Canvas, and no Canvas content is deleted or overwritten.

## Migration Plan

None required: no format version bump, no manifest change. Rollback is
`git revert`.

## Open Questions

None remaining. The two questions raised during planning were resolved by the
spike and implementation:

- `tomlkit` (0.15.1) renders strings with newlines, quotes and backslashes as
  single-line escaped strings, so a commented `key = value` is always one line.
- `format_due_dates_toml` was replaced by `_due_dates_rows` plus the shared
  inline-array builder. Parsed data is unchanged; inline tables are written
  `{a = 1}` rather than `{ a = 1 }`.
