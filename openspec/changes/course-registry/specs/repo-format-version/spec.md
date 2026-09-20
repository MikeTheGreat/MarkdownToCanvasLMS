# Spec Delta

## MODIFIED Requirements

### Requirement: upgrade migrates a repo to the current format

The `upgrade` subcommand SHALL take an optional `COURSE_DIR`, resolved as
described in the `course-registry` capability. It SHALL apply each migration from the repo's lowest
format version (across `course_settings.toml` and every manifest) up to the
tool's current version, in order, and then apply the `tab_configuration`
placement fix. It SHALL print each change it makes. It SHALL run whether
or not the git working tree has uncommitted changes. It SHALL preserve the
comments, key order and formatting of `course_settings.toml` except where a
migration changes them. It SHALL NOT contact Canvas.

#### Scenario: Upgrade an old repo
- **WHEN** a user runs `upgrade` on a version-0 repo and the tool's format version is 3
- **THEN** migrations 0 -> 1, 1 -> 2 and 2 -> 3 are applied, each change is printed, `format_version = 3` is written, and every manifest records version 3
- **AND** comments elsewhere in `course_settings.toml` are unchanged

#### Scenario: Already current
- **WHEN** a user runs `upgrade` on a repo whose file and manifests all have the current version and whose `tab_configuration` is correctly placed
- **THEN** it reports that the repo is already current and changes no file

#### Scenario: Repo newer than the tool
- **WHEN** a user runs `upgrade` on a repo whose format version is higher than the tool's
- **THEN** it exits with an error telling the user to update the tool, and changes nothing

#### Scenario: Dry run
- **WHEN** a user runs `upgrade --noop`
- **THEN** it prints the changes it would make and writes no file

#### Scenario: Migration cannot proceed
- **WHEN** a migration finds a condition it cannot resolve automatically
- **THEN** `upgrade` exits with an error describing the condition, and the repo's `format_version` is not advanced past the last migration that completed

#### Scenario: Registered course
- **WHEN** a user runs `upgrade 142` from an unrelated directory and `142` is a registered course
- **THEN** the registered course is upgraded

## ADDED Requirements

### Requirement: Migration 2 to 3

Migration 2 -> 3 SHALL do the following, and record format version 3 in every
`.manifest-*.toml`:

1. Remove an uncommented `relative_table` key from `course_settings/term_dates.toml`
   when that file exists, printing that it did. Comments, other keys and
   formatting of that file SHALL be preserved. It SHALL NOT create the file and
   SHALL NOT touch any term file outside the repo.
2. Make the relative-due-dates table selectable by default. When
   `[relative_due_dates.tables]` in `course_settings.toml` holds exactly one
   table and it is not named `default`, rename it to `default`. When it holds
   exactly two tables, one of them `default` with an empty `items` array and no
   other keys, and the other not, remove the empty `default` and rename the other
   table to `default`. In every other case, leave the tables as they are and print
   a notice that `--table NAME` is needed.

The migration SHALL preserve the comments, key order and formatting of
`course_settings.toml` except for the renamed and removed tables. It SHALL make
these changes only to a settings file whose own format version is below 3.

#### Scenario: Lone renamed table
- **WHEN** a version-2 repo has only `[relative_due_dates.tables.quarter11]` and the user runs `upgrade`
- **THEN** the table is named `default`, `format_version = 3` is written, and the change is printed

#### Scenario: Empty default beside a used table
- **WHEN** the tables are an empty `default` (left by migration 1 -> 2) and `quarter11` with items
- **THEN** the empty `default` is removed, `quarter11` becomes `default` with its items, and both changes are printed

#### Scenario: Several real tables
- **WHEN** the tables are `quarter11` and `summer8`, both with items
- **THEN** the tables are unchanged and the output says `--table NAME` is needed

#### Scenario: Term file in the repo
- **WHEN** `course_settings/term_dates.toml` has the line `relative_table = "quarter11"` and other keys and comments
- **THEN** only that line is removed, the change is printed, and the rest of the file is unchanged

#### Scenario: Term file with the key only in a comment
- **WHEN** `course_settings/term_dates.toml` has `# relative_table = "default"` only as a comment
- **THEN** the file is not modified

#### Scenario: Term file outside the repo
- **WHEN** a term file in `~/.config/markdown-to-canvas/terms/` has `relative_table`
- **THEN** `upgrade` does not read or change it
