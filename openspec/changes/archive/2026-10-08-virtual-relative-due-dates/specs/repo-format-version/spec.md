## ADDED Requirements

### Requirement: Migration 10 to 11

Format version 11 adds the optional `virtual` key to items of
`[relative_due_dates]` tables (see the `relative-due-dates` capability). An
older tool rejects that key as unknown, which is why the version changes
although older files need no rewriting. Migration 10 -> 11 SHALL record format
version 11 in `course_settings.toml` and in every `.manifest-*.toml`, and SHALL
NOT change any other part of `course_settings.toml`, any content file, the
term file, or any manifest entry other than the version.

#### Scenario: Upgrade a version-10 repo
- **WHEN** `upgrade` runs on a version-10 repo
- **THEN** `format_version` becomes 11, every manifest records 11, and the parsed `course_settings.toml` is otherwise unchanged

#### Scenario: Older tool refuses a version-11 repo
- **WHEN** a tool whose current format version is 10 runs `update` on a version-11 repo
- **THEN** it refuses, as for any newer format version, and nothing is uploaded

#### Scenario: Noop run
- **WHEN** `upgrade --noop` runs on a version-10 repo
- **THEN** it prints the version records it would make, and writes nothing
