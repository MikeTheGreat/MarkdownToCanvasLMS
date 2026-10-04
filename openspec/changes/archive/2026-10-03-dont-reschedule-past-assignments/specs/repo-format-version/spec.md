# Spec Delta

## ADDED Requirements

### Requirement: Migration 8 to 9

Format version 9 adds the optional `dont_reschedule_dates_before`,
`default_unlock_time` and `default_lock_time` settings to the
`[relative_due_dates]` section (see the `relative-due-dates` capability).
Migration 8 -> 9 SHALL:
1. Add, directly after the `[relative_due_dates]` header of
   `course_settings.toml`, each of these that the section lacks:
   - the line `# dont_reschedule_dates_before = "YYYY-MM-DD"` with the same
     explanatory comment `import` writes, unless a line of the section already
     mentions `dont_reschedule_dates_before` (as a key or in a comment);
   - `default_unlock_time = "00:00"`, unless the section sets that key;
   - `default_lock_time = "23:59"`, unless the section sets that key.

   Each item left out SHALL be reported. The rest of the file (other keys,
   comments, layout) SHALL be unchanged. When the section exists only through
   its subtables (for example only `[relative_due_dates.tables.default]`, as
   migration 1 -> 2 wrote it), the migration SHALL add a `[relative_due_dates]`
   header with the same lines under it, directly before the first subtable
   header. When the file has no `[relative_due_dates]` section at all, the
   migration SHALL add nothing and print a notice saying so.
2. Record format version 9 in `course_settings.toml` and in every
   `.manifest-*.toml`.

It SHALL edit only a settings file whose own format version is below 9, and
SHALL NOT change any content file or manifest entry other than the version.

#### Scenario: Upgrade a version-8 repo
- **WHEN** `upgrade` runs on a version-8 repo whose `course_settings.toml` has a `[relative_due_dates]` section
- **THEN** `format_version` becomes 9, the section gains `# dont_reschedule_dates_before = "YYYY-MM-DD"`, `default_unlock_time = "00:00"` and `default_lock_time = "23:59"` after its header, the parsed TOML is otherwise unchanged, and every manifest records 9

#### Scenario: Line already present
- **WHEN** a version-8 `[relative_due_dates]` section already has `dont_reschedule_dates_before = "2026-10-01"`, `default_unlock_time = "08:00"` and `default_lock_time = "17:00"`
- **THEN** the migration leaves the section unchanged, reports each skipped item, and only updates the version

#### Scenario: One default time already set
- **WHEN** a version-8 `[relative_due_dates]` section sets `default_lock_time = "17:00"` and nothing else of the three
- **THEN** the migration adds the commented cutoff and `default_unlock_time = "00:00"`, leaves `default_lock_time = "17:00"`, and reports that it was left

#### Scenario: Section with only subtables
- **WHEN** a version-8 `course_settings.toml` has `[relative_due_dates.tables.default]` but no `[relative_due_dates]` header
- **THEN** a `[relative_due_dates]` header followed by the commented-out cutoff and the two default times is inserted directly before `[relative_due_dates.tables.default]`, and the parsed TOML is otherwise unchanged apart from the two new keys

#### Scenario: No relative section
- **WHEN** a version-8 `course_settings.toml` has no `[relative_due_dates]` section
- **THEN** the migration prints a notice, adds no section, and records version 9

#### Scenario: Noop run
- **WHEN** `upgrade --noop` runs on a version-8 repo
- **THEN** it reports the lines it would add and changes no file

#### Scenario: Older tool refuses a version-9 repo
- **WHEN** a tool whose format version is 8 runs `update` on a version-9 repo
- **THEN** it refuses with the existing newer-version error and changes nothing
