# Spec Delta

## ADDED Requirements

### Requirement: Migration 11 to 12

Format version 12 adds the optional `virtual` key to `due_dates` entries (see
the `virtual-due-dates` capability), and `generate-due-dates` writes virtual
items as such entries. An older tool would treat a virtual entry as an ordinary
one, which is why the version changes although older files need no rewriting.
Migration 11 -> 12 SHALL record format version 12 in `course_settings.toml` and
in every `.manifest-*.toml`, and SHALL NOT change any other part of
`course_settings.toml`, any content file, the term file, or any manifest entry
other than the version.

#### Scenario: Upgrade a version-11 repo
- **WHEN** `upgrade` runs on a version-11 repo
- **THEN** `format_version` becomes 12, every manifest records 12, and the parsed `course_settings.toml` is otherwise unchanged

#### Scenario: Older tool refuses a version-12 repo
- **WHEN** a tool whose current format version is 11 runs `update` on a version-12 repo
- **THEN** it refuses, as for any newer format version, and nothing is uploaded

#### Scenario: Noop run
- **WHEN** `upgrade --noop` runs on a version-11 repo
- **THEN** it prints the version records it would make, and writes nothing
