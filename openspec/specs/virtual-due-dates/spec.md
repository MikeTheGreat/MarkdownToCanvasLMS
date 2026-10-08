# virtual-due-dates Specification

## Purpose

Lets the top-level `due_dates` array hold named dates that are not content,
such as the start of a week, so date placeholders can quote them while they are
never sent to Canvas.

## Requirements

### Requirement: Virtual due_dates entries

A `due_dates` entry with `virtual = true` SHALL be a virtual entry: a name for
a date, not the dates of an assignment, discussion or quiz. `virtual` SHALL be
a boolean; any other value SHALL be an error naming the entry. An entry with
`virtual = false` or without `virtual` SHALL be an ordinary entry, as before.

A virtual entry SHALL have `name` and `due_at`, MAY have `only_if`, and SHALL
NOT have `type`, `unlock_at` or `lock_at`. Its `due_at` SHALL be a date or
datetime; the sentinels (`NONE`, `KEEP`, `CREATE_NONE_THEN_KEEP`) and an empty
value SHALL be errors. Each violation SHALL be an error naming the entry and
the key.

A virtual entry SHALL NOT have the same `name` as the title (frontmatter
`title`, else the file name without `.md`) of an assignment, discussion or quiz
in the repo that is not excluded by `.canvasignore`. Such a collision SHALL be
an error naming the entry and the content file. A virtual entry SHALL NOT have
the same `name` as an ordinary `due_dates` entry; that SHALL be an error naming
the entry. Two virtual entries MAY share a name (for example with different
`only_if` conditions); a placeholder that finds both after `only_if` is applied
reports the existing ambiguous-name error.

Virtual entries MAY be written by hand; they do not have to come from a
relative table. Every entry is checked, whether or not its `only_if` is met by
the run's course flags.

#### Scenario: Hand-written virtual entry
- **WHEN** `due_dates` has `{ name = "Last day to withdraw", virtual = true, due_at = "2026-11-13T17:00:00-08:00" }` and no content has that title
- **THEN** `update` runs without an error or warning about that entry

#### Scenario: Virtual entry with a lock date
- **WHEN** a virtual entry has `lock_at`
- **THEN** the run fails with an error naming the entry and `lock_at`

#### Scenario: Virtual entry with a type
- **WHEN** a virtual entry has `type = "assignment"`
- **THEN** the run fails with an error naming the entry and `type`

#### Scenario: Virtual entry without a date
- **WHEN** a virtual entry has no `due_at`, or `due_at = "NONE"`
- **THEN** the run fails with an error naming the entry and `due_at`

#### Scenario: Non-boolean virtual
- **WHEN** an entry has `virtual = "yes"`
- **THEN** the run fails with an error naming the entry and `virtual`

#### Scenario: Name of a content file
- **WHEN** a virtual entry is named "Midterm" and `quizzes/midterm.md` has title "Midterm"
- **THEN** the run fails with an error naming "Midterm" and `quizzes/midterm.md`

#### Scenario: Name shared with an ordinary entry
- **WHEN** `due_dates` has a virtual entry `Start_of_week_3` and an ordinary entry `Start_of_week_3`
- **THEN** the run fails with an error naming `Start_of_week_3`

#### Scenario: Error in an entry excluded by only_if
- **WHEN** a virtual entry has `only_if = "online"`, the run's flags set `online = false`, and the entry has `lock_at`
- **THEN** the run still fails with the `lock_at` error

### Requirement: Invalid virtual entries stop the run

`update` (including `--noop` and `--check-as-new-course`, and a run limited to
named files), `publish`, `list-titles` and `generate-due-dates` SHALL check the
virtual entries before doing anything else. Any error from "Virtual due_dates
entries" SHALL stop the command with a non-zero exit status, after listing every
such error, before any Canvas request, upload, staging or write. This is the
same handling as other `due_dates` configuration errors, such as an undefined
flag in `only_if`.

#### Scenario: update stops before Canvas
- **WHEN** `update` runs and a virtual entry has `unlock_at`
- **THEN** the error is printed, the exit status is non-zero, and no Canvas request is made

#### Scenario: Several errors
- **WHEN** two virtual entries each have an error
- **THEN** both errors are printed before the command stops

#### Scenario: publish stops
- **WHEN** `publish` runs and a virtual entry has the title of an assignment
- **THEN** the error is printed, the exit status is non-zero, and no site is built

### Requirement: Virtual entries are never sent to Canvas

`update` SHALL NOT match a virtual entry to any content file, so no date from a
virtual entry is sent to Canvas, whether the file is uploaded in full or only
its dates are updated. The "Checking due_dates coverage" step SHALL NOT warn
that a virtual entry did not match any content file. `list-titles` SHALL NOT
take a due date from a virtual entry. Removing a virtual entry SHALL NOT print
the "due_dates entry ... was removed" notice, since no content used it.

#### Scenario: No coverage warning
- **WHEN** `due_dates` has a valid virtual entry `Start_of_week_3`
- **THEN** `update` prints no warning naming `Start_of_week_3`

#### Scenario: Dates pass ignores virtual entries
- **WHEN** `update` runs after only a virtual entry's `due_at` changed, and no file quotes it
- **THEN** no Canvas date update is made and nothing is counted as updated

#### Scenario: Quoting files still re-upload
- **WHEN** `update` runs after a virtual entry's `due_at` changed, and a page quotes it with a date placeholder
- **THEN** the page is re-uploaded with the new date, as for a changed ordinary entry
