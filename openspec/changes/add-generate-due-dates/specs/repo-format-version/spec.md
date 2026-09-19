# Spec Delta

## ADDED Requirements

### Requirement: Migration 1 to 2

Migration 1 -> 2 SHALL add an empty `[relative_due_dates.tables.default]`
table (an empty `items` array) at the end of `course_settings.toml`, and
record format version 2 in every `.manifest-*.toml`. It SHALL NOT change the
file when a top-level `relative_due_dates` key already exists, and SHALL
NOT create a term file. It SHALL preserve the comments, key order and
formatting of the rest of the file. When the repo has no
`course_settings.toml`, it SHALL add nothing beyond the version stamps.

#### Scenario: Version 1 repo gains the section
- **WHEN** a version-1 repo has no `relative_due_dates` key and the user runs `upgrade`
- **THEN** `course_settings.toml` ends with `[relative_due_dates.tables.default]` and an empty `items` array, the file's other content is unchanged, `format_version = 2` is written, and every manifest records version 2

#### Scenario: Section already present
- **WHEN** a version-1 repo already has a `[relative_due_dates]` section
- **THEN** that section is not modified and only the version stamps change

#### Scenario: Upgrade from version 0
- **WHEN** a user runs `upgrade` on a version-0 repo
- **THEN** migration 0 -> 1 and then migration 1 -> 2 are applied and each change is printed

#### Scenario: Current repo untouched
- **WHEN** a user runs `upgrade` on a version-2 repo
- **THEN** it reports the repo is already current and changes no file

## MODIFIED Requirements

### Requirement: Repo-reading operations refuse a mismatched version

The format check SHALL be part of the tool's library operations, not only of
the command-line layer, so that every code path that reads a course repo
performs it. The operations behind `update` (including `--check-all`),
`mv`, `publish`, `prune`, `clean-manifest`, `find-local-orphans`,
`find-canvas-orphans`, `list-titles` and `generate-due-dates` SHALL check the format version of
the repo and of every `.manifest-*.toml` in it before reading content files,
writing any file, or making any change on Canvas. If any of them differs from
the tool's current format version, the operation SHALL fail with an error
(the command exits with a non-zero status) and change nothing. `import`,
`setup`, `install-completion`, `create-tool-aliases` and `emit-workflow`
SHALL NOT perform this check. `upgrade` performs its own version handling
(see its requirement).

#### Scenario: Repo older than the tool
- **WHEN** the repo's format version is lower than the tool's
- **THEN** the command exits with an error that states both versions and tells the user to run `markdown-to-canvas upgrade`

#### Scenario: Repo newer than the tool
- **WHEN** the repo's format version is higher than the tool's
- **THEN** the command exits with an error that states both versions and tells the user to update the tool

#### Scenario: Manifest older than the repo
- **WHEN** `course_settings.toml` has the current format version but a `.manifest-*.toml` in the repo does not
- **THEN** the command exits with an error naming that manifest and telling the user to run `upgrade`

#### Scenario: Matching versions
- **WHEN** the repo and all of its manifests have the tool's current format version
- **THEN** the command runs as it did before this change

#### Scenario: Library call without the CLI
- **WHEN** code calls the library operation behind `update` (or any other listed command) directly on a version-0 repo
- **THEN** the operation raises the format error before reading content or writing any file

#### Scenario: generate-due-dates on an old repo
- **WHEN** a user runs `generate-due-dates` on a version-1 repo
- **THEN** the command exits with an error telling the user to run `upgrade`, and writes nothing

### Requirement: upgrade migrates a repo to the current format

The `upgrade` subcommand SHALL take an optional repo path, resolved the same
way as `update`'s. It SHALL apply each migration from the repo's lowest
format version (across `course_settings.toml` and every manifest) up to the
tool's current version, in order, and then apply the `tab_configuration`
placement fix. It SHALL print each change it makes. It SHALL run whether
or not the git working tree has uncommitted changes. It SHALL preserve the
comments, key order and formatting of `course_settings.toml` except where a
migration changes them. It SHALL NOT contact Canvas.

#### Scenario: Upgrade an old repo
- **WHEN** a user runs `upgrade` on a version-0 repo and the tool's format version is 2
- **THEN** migrations 0 -> 1 and 1 -> 2 are applied, each change is printed, `format_version = 2` is written, and every manifest records version 2
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
