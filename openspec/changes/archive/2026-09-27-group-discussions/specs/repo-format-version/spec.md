# Spec Delta

## ADDED Requirements

### Requirement: Migration 6 to 7

Format version 7 allows `group_category_id` to name a group set/group category and
adds the top-level `group_categories` array to `course_settings.toml`. Migration
6 -> 7 SHALL:
1. Add `group_categories = []` to `course_settings.toml` when the file has no
   top-level `group_categories` key. Because it is a top-level key, it SHALL be
   placed before the first table or array-of-tables header (at the end of the
   file if there is none). The rest of the file (other keys, comments, layout)
   SHALL be unchanged. An existing top-level `group_categories` key SHALL be left
   as it is.
2. Record format version 7 in `course_settings.toml` and in every
   `.manifest-*.toml`.

It SHALL add the key only to a settings file whose own format version is below
7, and SHALL NOT change any content file. Existing numeric `group_category_id`
values remain valid at version 7.

#### Scenario: Upgrade a version-6 repo
- **WHEN** `upgrade` runs on a version-6 repo whose assignments use `group_category_id: 12345`
- **THEN** `format_version` becomes 7, `course_settings.toml` gains `group_categories = []` above its first table, every manifest records 7, and no `.md` file changes

#### Scenario: Key already present
- **WHEN** a version-6 `course_settings.toml` already has `group_categories = ["Project Groups"]`
- **THEN** the migration leaves that line unchanged and only updates the version

#### Scenario: Noop run
- **WHEN** `upgrade --noop` runs on a version-6 repo
- **THEN** it reports that `group_categories = []` would be added and changes no file

#### Scenario: Older tool refuses a version-7 repo
- **WHEN** a tool whose format version is 6 runs `update` on a version-7 repo
- **THEN** it exits with the "newer format" error and changes nothing on Canvas
