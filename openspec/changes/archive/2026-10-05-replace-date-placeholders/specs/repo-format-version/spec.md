# Spec Delta

## ADDED Requirements

### Requirement: Migration 9 to 10

Format version 10 adds `replace_date_with` date placeholders in content bodies
(see the `date-placeholders` capability) and the optional top-level
`replace_date_with_format` key in `course_settings.toml`. An older tool would
upload a placeholder's fallback text and span markup without complaint, which
is why the version changes although older files need no rewriting.
Migration 9 -> 10 SHALL:
1. Add `replace_date_with_format = "%A, %B %-d at %-I:%M %p"`, with the same
   one-line comment directly above it that `import` writes, as a top-level key
   of `course_settings.toml` placed before the first table header, unless the
   file already sets the key. When it is already set, the migration SHALL
   report that and leave it. The rest of the file (other keys, comments,
   layout) SHALL be unchanged, and the parsed TOML SHALL equal the original
   apart from the new key; otherwise the file SHALL be left unchanged with a
   notice.
2. Record format version 10 in `course_settings.toml` and in every
   `.manifest-*.toml`.

It SHALL edit only a settings file whose own format version is below 10, and
SHALL NOT change any content file or manifest entry other than the version.

#### Scenario: Upgrade a version-9 repo
- **WHEN** `upgrade` runs on a version-9 repo
- **THEN** `format_version` becomes 10, `course_settings.toml` gains the commented `replace_date_with_format` line before its first table header, the parsed TOML is otherwise unchanged, and every manifest records 10

#### Scenario: Key already present
- **WHEN** a version-9 `course_settings.toml` already sets `replace_date_with_format = "%b %-d"`
- **THEN** the value is left as it is, the migration reports it, and only the version changes

#### Scenario: Older tool refuses a version-10 repo
- **WHEN** a tool whose current format version is 9 runs `update` on a version-10 repo
- **THEN** it refuses, as for any newer format version, and nothing is uploaded

#### Scenario: Noop run
- **WHEN** `upgrade --noop` runs on a version-9 repo
- **THEN** it prints the line it would add and the version records, and writes nothing
