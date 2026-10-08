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

### Requirement: Migration 3 to 4

Migration 3 -> 4 SHALL convert relative links in block snippet files from the
old reading (relative to each including file) to the snippet-relative reading
defined by the `snippet-links` capability, and record format version 4 in
every `.manifest-*.toml`. It SHALL make changes to snippet files only when the
settings file's own format version is below 4.

The migration SHALL consider as includers every `.md` file in the repo outside
`snippets/` and outside hidden folders, including files excluded by
`.canvasignore`, that includes the snippet as a block snippet outside a fenced
code block. `PASTE_SNIPPET_INTO_FRONTMATTER` references and inline `$...$`
references SHALL NOT count as including a snippet. It SHALL examine the same
link forms that `snippet-links` rebases and skip the forms it leaves unchanged.

The migration SHALL also examine the paths of `$path.md$` inline snippet
references inside snippet files, and block snippet references to other
snippets, the same way as links: before format 4 neither was expanded inside a
snippet, and from format 4 both are resolved from the snippet's folder.

For each such link in each included snippet, where an "includer target" is
the repo file the link names when read from an includer's folder, a "working
includer target" is an includer target that exists, and the "snippet target"
is the file the link names when read from the snippet's folder:

1. When all working includer targets are the same file, and it differs from
   the snippet target, the migration SHALL rewrite the link so that, read
   from the snippet's folder, it names that file, and print the change. This
   applies even when some includers resolved the link to nothing: those
   includers were already broken, and the rewrite fixes them too.
2. When all working includer targets are the same file and it equals the
   snippet target, the link SHALL be left unchanged without a message.
3. When there is no working includer target and the snippet target exists,
   the link SHALL be left unchanged without a message.
4. When working includer targets name more than one file, or no target
   exists at all, the link SHALL be left unchanged and the migration SHALL
   print a notice naming the snippet, the link, and each includer with the
   file it resolved to (or that it resolved to nothing).

A snippet that no file includes SHALL be left unchanged; the migration SHALL
print a notice for each of its links whose snippet target does not exist.
These notices SHALL NOT stop the upgrade. The migration SHALL change only the
rewritten link paths in a snippet file and leave all other bytes as they
were. With `--noop` it SHALL print the same changes and notices and write no
file.

#### Scenario: Snippet written for deeper includers
- **WHEN** `snippets/policy.md` contains `![](../../assets/logo.png)` and its only includers are `pages/week1/a.md` and `pages/week2/b.md`
- **THEN** `upgrade` rewrites the image path to `../assets/logo.png`, prints the change, and writes `format_version = 4`

#### Scenario: Includers at the snippet's depth
- **WHEN** `snippets/policy.md` links `../pages/syllabus.md` and every includer is directly under a top-level folder
- **THEN** the snippet file is not modified

#### Scenario: Snippet reading already works
- **WHEN** a snippet links `../assets/x.png` and is included from `pages/a.md` (resolving to `assets/x.png`) and `pages/unit1/b.md` (resolving to `pages/assets/x.png`, which does not exist)
- **THEN** the only working includer target equals the snippet target `assets/x.png`, so the link is left unchanged without a message

#### Scenario: Working includers agree, another includer was broken
- **WHEN** `snippets/block/front.md` links `../instructor_info/office-hours.md`, `pages/week-1/home.md` resolves it to the existing `pages/instructor_info/office-hours.md`, and `pages/landing.md` resolves it to nothing
- **THEN** the link is rewritten to `../../pages/instructor_info/office-hours.md` and no notice is printed

#### Scenario: References to other snippets
- **WHEN** `snippets/block/weekly/front.md` contains `[NAME](../../snippets/inline/name.md)` and `[Syllabus]($../../snippets/inline/C.md$/syllabus)`, written for an includer in `pages/week-1/`
- **THEN** they become `[NAME](../../inline/name.md)` and `[Syllabus]($../../inline/C.md$/syllabus)`, and every includer shows the name and the course URL

#### Scenario: Includers resolve to different existing files
- **WHEN** a snippet links `img/x.png`, `pages/img/x.png` and `pages/unit1/img/x.png` both exist, and the snippet is included from `pages/a.md` and `pages/unit1/b.md`
- **THEN** the link is left unchanged and a notice lists both includers and the file each resolved to

#### Scenario: Includer reading wins over snippet reading
- **WHEN** a snippet links `../assets/x.png`, both `assets/x.png` and `pages/assets/x.png` exist, and the snippet's only includer is `pages/unit1/a.md` (resolving to `pages/assets/x.png`)
- **THEN** the link is rewritten to `../pages/assets/x.png`

#### Scenario: Unused snippet with a broken link
- **WHEN** no file includes `snippets/old.md` and it links `../assets/gone.png`, which does not exist
- **THEN** the file is not modified and a notice names the snippet and the link

#### Scenario: Ignored includer counts
- **WHEN** a `.canvasignore`d draft at a different depth includes a snippet
- **THEN** its reading is considered along with the other includers

#### Scenario: Dry run
- **WHEN** a user runs `upgrade --noop` on a version-3 repo with a snippet link to convert
- **THEN** the rewrite is printed and no file, including the snippet, is written

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
