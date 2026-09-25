# repo-format-version Specification

## Purpose

Records which file-format version a course repo and each of its local
manifests are written in, stops the tool from misreading a repo written for a
different version, provides an `upgrade` command that migrates a repo to the tool's current
format.

## Requirements

### Requirement: Repo format version is recorded in course_settings.toml

A course repo's format version SHALL be the integer value of the top-level
`format_version` key in `course_settings/course_settings.toml`. A repo whose
`course_settings.toml` has no `format_version` key, or that has no
`course_settings.toml`, SHALL be treated as format version 0. When present,
`format_version`, `created_by` and `upgraded_by` SHALL be the first keys in
the file, before any other key or section header.

#### Scenario: Version read from the file
- **WHEN** `course_settings.toml` begins with `format_version = 1`
- **THEN** the repo's format version is 1

#### Scenario: Missing key means version 0
- **WHEN** `course_settings.toml` exists and has no `format_version` key
- **THEN** the repo's format version is 0

#### Scenario: Invalid value
- **WHEN** `format_version` is not a non-negative integer (for example `"1"` or `1.5`)
- **THEN** any command that checks the version exits with an error naming the file and the bad value, and changes nothing

### Requirement: Each manifest records its own format version

Every `.manifest-*.toml` written by the tool SHALL record the format version
it was written in. A manifest with no recorded format version SHALL be
treated as format version 0. A manifest created for the first time SHALL
record the tool's current format version.

#### Scenario: New manifest is stamped
- **WHEN** `update` runs on a current-version repo that has no manifest for the config in use
- **THEN** the manifest it writes records the tool's current format version

#### Scenario: Unstamped manifest
- **WHEN** a manifest has no recorded format version
- **THEN** that manifest's format version is 0

### Requirement: import records the version and the creating tool

`import` SHALL write `format_version` set to the tool's current format
version, and `created_by` set to the running tool's version string, as the
first keys of the `course_settings.toml` it creates.

#### Scenario: Fresh import
- **WHEN** a user runs `import` on a cartridge
- **THEN** the new `course_settings.toml` starts with `format_version = <current version>` followed by `created_by = "<tool version>"`
- **AND** every other command can run on the new repo without first running `upgrade`

### Requirement: Repo-reading operations refuse a mismatched version

The format check SHALL be part of the tool's library operations, not only of
the command-line layer, so that every code path that reads a course repo
performs it. The operations behind `update` (including `--check-all`),
`mv`, `publish`, `prune`, `fix-manifest`, `find-local-orphans`,
`find-canvas-orphans`, `list-titles`, `generate-due-dates` and `cp` SHALL check the format version of
the repo and of every `.manifest-*.toml` in it (for `cp`, both the source and the
destination repo) before reading content files,
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

#### Scenario: cp with an old destination
- **WHEN** a user runs `cp` from a current source repo into a destination repo at an older format version
- **THEN** the command exits with an error naming the destination repo and telling the user to run `upgrade`, and writes nothing in either repo

### Requirement: upgrade keeps tab_configuration at the top level

`upgrade` SHALL check whether `tab_configuration` appears nested under a table
(or an element of an array of tables) in `course_settings.toml`. If it is
nested and there is no top-level `tab_configuration`, `upgrade` SHALL move it
to a top-level key placed before the first table, keep its value, leave the
rest of the file (other keys, comments, layout) unchanged, and print a notice
naming the location it was moved from. If `tab_configuration` exists both at
the top level and nested, `upgrade` SHALL fail with an error naming both
locations and change nothing. With `--noop` it SHALL report the misplacement
without editing the file. Other commands SHALL NOT check or change the
placement: a repo at the current format version is taken to be set up
correctly.

#### Scenario: Nested under a table
- **WHEN** `course_settings.toml` has `tab_configuration` under `[default_post_policy]` and the user runs `upgrade`
- **THEN** `tab_configuration` becomes a top-level key with the same value, placed before the first section header, `[default_post_policy]` keeps its other keys, and a notice is printed

#### Scenario: Correct placement
- **WHEN** `tab_configuration` is already a top-level key, or absent
- **THEN** the file is not modified and nothing is printed about it

#### Scenario: In both places
- **WHEN** `tab_configuration` is both a top-level key and nested under a table
- **THEN** `upgrade` exits with an error naming both locations and changes nothing

#### Scenario: Other commands leave it alone
- **WHEN** `update`, `mv` or another repo-reading command runs on a current-version repo with a nested `tab_configuration`
- **THEN** the file is not modified and no placement notice is printed

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

### Requirement: upgrade records its runs in upgraded_by

Each `upgrade` run that changes `format_version` in `course_settings.toml`
SHALL append one entry to the top-level `upgraded_by` array, creating the
array if absent. Each entry SHALL be a string of the form
`"<tool version> on <YYYY-MM-DD>: <from> -> <to>"`. `upgrade` SHALL NOT add
or change `created_by`.

#### Scenario: First upgrade
- **WHEN** tool version `0.2.1.dev3+gabc1234` upgrades a repo from 0 to 1 on 2026-09-20
- **THEN** `upgraded_by = ["0.2.1.dev3+gabc1234 on 2026-09-20: 0 -> 1"]` is written and no `created_by` key is added

#### Scenario: Later upgrade appends
- **WHEN** a repo already has one `upgraded_by` entry and is upgraded again
- **THEN** the existing entry is kept and a second entry is appended after it

#### Scenario: Only manifests needed upgrading
- **WHEN** `course_settings.toml` is current but a manifest is not
- **THEN** `upgrade` migrates the manifest and does not append an `upgraded_by` entry

### Requirement: Migration 0 to 1

Migration 0 -> 1 SHALL:
1. Rename a legacy `.canvas-manifest.toml` to `.manifest-canvas.toml` when
   the latter does not exist.
2. Record format version 1 in every `.manifest-*.toml`.

A nested `tab_configuration` in a version-0 repo is corrected by the
placement check that `upgrade` runs after the migrations.

#### Scenario: Legacy manifest
- **WHEN** the repo has `.canvas-manifest.toml` and no `.manifest-canvas.toml`
- **THEN** `upgrade` renames it to `.manifest-canvas.toml` and stamps it with version 1

#### Scenario: Legacy manifest and current manifest both present
- **WHEN** the repo has both `.canvas-manifest.toml` and `.manifest-canvas.toml`
- **THEN** `upgrade` leaves `.canvas-manifest.toml` untouched and prints a warning that it is unused

#### Scenario: Old import with nested tab_configuration
- **WHEN** a version-0 repo has `tab_configuration` under `[default_post_policy]` and the user runs `upgrade`
- **THEN** after `upgrade` the repo is at version 1 and `tab_configuration` is a top-level key

#### Scenario: Other commands no longer rename the legacy manifest
- **WHEN** `update`, `prune` or `fix-manifest` runs on a version-1 repo
- **THEN** no manifest is renamed

### Requirement: Migration 1 to 2

Migration 1 -> 2 SHALL add an empty `[relative_due_dates.tables.default]`
table (an empty `items` array) at the end of `course_settings.toml`, and
record format version 2 in every `.manifest-*.toml`. It SHALL NOT change the
file when a top-level `relative_due_dates` key already exists, and SHALL
NOT create a term file. It SHALL preserve the comments, key order and
formatting of the rest of the file. It SHALL add the section only to a settings
file whose own format version is below 2, so a current settings file whose
manifests lag behind is not given the section. A repo with no
`course_settings.toml` is given one by `upgrade` (migration 0 -> 1) and so
receives the section as well.

#### Scenario: Version 1 repo gains the section
- **WHEN** a version-1 repo has no `relative_due_dates` key and the user runs `upgrade`
- **THEN** `course_settings.toml` ends with `[relative_due_dates.tables.default]` and an empty `items` array, the file's other content is unchanged, `format_version = 2` is written, and every manifest records version 2

#### Scenario: Section already present
- **WHEN** a version-1 repo already has a `[relative_due_dates]` section
- **THEN** that section is not modified and only the version stamps change

#### Scenario: Manifest behind a current settings file
- **WHEN** `course_settings.toml` is at version 2 without a `relative_due_dates` section and a manifest is at version 1
- **THEN** `upgrade` stamps the manifest and does not add the section

#### Scenario: Upgrade from version 0
- **WHEN** a user runs `upgrade` on a version-0 repo
- **THEN** migration 0 -> 1 and then migration 1 -> 2 are applied and each change is printed

#### Scenario: Current repo untouched
- **WHEN** a user runs `upgrade` on a version-2 repo
- **THEN** it reports the repo is already current and changes no file

### Requirement: Version keys do not affect Canvas

`format_version`, `created_by` and `upgraded_by` SHALL NOT be sent to Canvas,
and a change to any of them SHALL NOT cause `update` to send course settings
to Canvas.

#### Scenario: Update after upgrade
- **WHEN** `update` runs after `upgrade` changed only the version keys in `course_settings.toml`
- **THEN** no course-settings API call is made

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
