# Spec Delta

## Purpose

Defines how the TOML files the tool generates or rewrites in a course repo are
laid out, so that an array of tables never changes style with its content and
hand-written comments survive the tool's edits.

## ADDED Requirements

### Requirement: Array-of-tables style is fixed per key

The TOML files written by `import` SHALL lay out each array of tables in a
style that depends only on which key it is, never on the length or number of
its rows. `tab_configuration`, `due_dates`, rubric `ratings`,
`assignment_groups` `rules`, and the `folders` and `files` lists in
`files_meta.toml` SHALL be written as inline arrays of inline tables. `grading_standards`,
`assignment_groups`, and rubric `criteria` SHALL be written in `[[table]]`
block style. The `data` array inside each `grading_standards` entry, a list of
`[name, value]` pairs, SHALL be written with one pair per line, each pair on a
single line.

#### Scenario: Long rows stay inline
- **WHEN** `import` writes a `tab_configuration` whose rows are each longer than 100 characters
- **THEN** `tab_configuration` is still an inline array under a top-level key, and no `[[tab_configuration]]` header appears

#### Scenario: Short rows stay in block style
- **WHEN** `import` writes a single short `assignment_groups` entry
- **THEN** it is written as an `[[assignment_groups]]` block, not an inline array

#### Scenario: Grading standard pairs are one per line
- **WHEN** a `grading_standards` entry has a `data` array of many `[name, value]` pairs
- **THEN** `data` is written inside the `[[grading_standards]]` block with each pair on its own single line, for example `["A (4.0)", 0.95],`

#### Scenario: Grading standard data round-trips
- **WHEN** the generated `grading_standards` is parsed
- **THEN** `data` equals the original list of `[name, value]` pairs

### Requirement: Top-level keys stay top-level

In every generated TOML file, all top-level keys, including commented-out
import-only keys, SHALL appear before the first `[table]` or `[[table]]`
header, so that a user who uncomments or adds a key does not silently nest it
under a table.

#### Scenario: Commented keys precede table headers
- **WHEN** `import` writes a `course_settings.toml` that has a late policy and grading standards
- **THEN** every commented-out import-only key line appears before `[late_policy]`

#### Scenario: Parsed structure is style-independent
- **WHEN** the generated `course_settings.toml` is parsed
- **THEN** `format_version`, `created_by`, `due_dates` and `tab_configuration` are top-level keys and none is a member of a table

### Requirement: Import-only keys are commented with their values intact

Keys that `import` records for round-trip fidelity but the tool never uploads
SHALL be written as commented-out lines of the form `# key = value`. The value
SHALL be valid TOML, so that removing the leading `# ` yields a working
assignment. Keys inside an inline table (for example a rating's `id`) cannot
be commented individually and SHALL be explained in the file's header comment.

#### Scenario: Uncommenting yields valid TOML
- **WHEN** a user removes the `# ` from a commented `course_settings.toml` key
- **THEN** the file parses and the key has the value that was commented

#### Scenario: Values needing escapes
- **WHEN** an import-only value contains a quote or backslash
- **THEN** the commented line escapes it so the uncommented line parses to the original string

### Requirement: Generated content is unchanged

Changing the TOML writer SHALL NOT change which keys and values `import` writes.
A file written by the previous version of the tool SHALL still be read
identically by the current tool, and no `upgrade` step is required.

#### Scenario: Same data as before
- **WHEN** `import` runs on the same cartridge as before this change
- **THEN** each generated TOML file parses to the same data as the previously generated file

### Requirement: mv preserves comments in module_order.toml

When `mv` rewrites `course_settings/module_order.toml` after a module file is
moved or renamed, comments and blank lines in that file SHALL be preserved,
and only the changed entries in `order` SHALL differ.

#### Scenario: Comment survives a module rename
- **WHEN** `module_order.toml` contains a `# comment` line and `mv` renames a module file listed in `order`
- **THEN** the comment is still present in the file and the `order` entry shows the new path

#### Scenario: Unrelated file is untouched
- **WHEN** `mv` moves a file that is not a module
- **THEN** `module_order.toml` is not modified

### Requirement: Manifests are unaffected

Manifest files (`.manifest-*.toml`) SHALL be written as before, including the
`_repo_format` table, and SHALL remain readable by earlier tool versions of the
same format version.

#### Scenario: Manifest round trip
- **WHEN** `update` flushes a manifest after this change
- **THEN** the manifest parses to the same data and carries the same `_repo_format` as before this change
