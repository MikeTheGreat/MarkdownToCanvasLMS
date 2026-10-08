# Spec Delta

## ADDED Requirements

### Requirement: Migration 12 to 13

Format version 13 adds the optional `clamp_lock_at_to_last_day_of_term`
setting to `[relative_due_dates]` and its tables (see the
`relative-due-dates` capability). An older tool rejects that key as unknown,
which is why the version changes. Migration 12 -> 13 SHALL:
1. Add, directly after the `[relative_due_dates]` header of
   `course_settings.toml`, the line
   `# clamp_lock_at_to_last_day_of_term = true` with the same explanatory
   comment `import` writes, unless a line of the section already mentions
   `clamp_lock_at_to_last_day_of_term` (as a key or in a comment); in that case
   it SHALL report that and add nothing. The rest of the file (other keys,
   comments, layout) SHALL be unchanged, and the parsed TOML SHALL equal the
   original. When the section exists only through its subtables, the migration
   SHALL add a `[relative_due_dates]` header with the same lines under it,
   directly before the first subtable header. When the file has no
   `[relative_due_dates]` section at all, the migration SHALL add nothing and
   print a notice saying so.
2. Record format version 13 in `course_settings.toml` and in every
   `.manifest-*.toml`.

It SHALL edit only a settings file whose own format version is below 13, and
SHALL NOT change any content file, the term file, or any manifest entry other
than the version.

#### Scenario: Upgrade a version-12 repo
- **WHEN** `upgrade` runs on a version-12 repo whose `course_settings.toml` has a `[relative_due_dates]` section
- **THEN** `format_version` becomes 13, the section gains `# clamp_lock_at_to_last_day_of_term = true` and its comment after the header, the parsed TOML is otherwise unchanged, and every manifest records 13

#### Scenario: Line already present
- **WHEN** a version-12 `[relative_due_dates]` section already mentions `clamp_lock_at_to_last_day_of_term`
- **THEN** the migration leaves the section unchanged, reports it, and only updates the version

#### Scenario: Section with only subtables
- **WHEN** a version-12 `course_settings.toml` has `[relative_due_dates.tables.default]` but no `[relative_due_dates]` header
- **THEN** a `[relative_due_dates]` header followed by the commented-out line is inserted directly before `[relative_due_dates.tables.default]`, and the parsed TOML is otherwise unchanged

#### Scenario: No relative section
- **WHEN** a version-12 `course_settings.toml` has no `[relative_due_dates]` section
- **THEN** the migration prints a notice, adds no section, and records version 13

#### Scenario: Older tool refuses a version-13 repo
- **WHEN** a tool whose current format version is 12 runs `update` on a version-13 repo
- **THEN** it refuses, as for any newer format version, and nothing is uploaded

#### Scenario: Noop run
- **WHEN** `upgrade --noop` runs on a version-12 repo
- **THEN** it prints the line it would add and the version records, and writes nothing
