# Spec Delta

## Purpose

Warns `update` and `publish` users when `[relative_due_dates]` has been edited
since `generate-due-dates` last brought `due_dates` in line with it, so stale
dates are not sent to Canvas or a website without notice.

## ADDED Requirements

### Requirement: The fingerprint of [relative_due_dates]

The fingerprint SHALL be computed from the parsed `[relative_due_dates]` section
of `course_settings/course_settings.toml`: every key and table in it, including
tables other than the one `generate-due-dates` used and
`dont_reschedule_dates_before`, except `last_generated_hash` itself. Comments,
whitespace, key order and the way values are written in the file SHALL NOT
affect it. `due_dates`, the term file, and every other part of
`course_settings.toml` SHALL NOT affect it.

#### Scenario: Comment edited
- **WHEN** only a comment inside `[relative_due_dates]` is changed
- **THEN** the fingerprint is unchanged

#### Scenario: Offset edited
- **WHEN** an item's offsets change from `["+1 CLASS_DAY"]` to `["+1 CLASS_DAY", "13:15 ABS_TIME"]`
- **THEN** the fingerprint changes

#### Scenario: Unused table edited
- **WHEN** an item is added to `[relative_due_dates.tables.summer8]` and `generate-due-dates` uses the `default` table
- **THEN** the fingerprint changes

#### Scenario: due_dates edited by hand
- **WHEN** only an entry of `due_dates` is changed
- **THEN** the fingerprint is unchanged

### Requirement: update and publish warn when the fingerprint is missing or out of date

`update` (a full run, a run with `-t` or `-s`, `--noop`, and
`--check-as-new-course`) and `publish` SHALL check the fingerprint when some table
under `[relative_due_dates.tables]` has at least one item (ordinary or virtual).
When no table has an item, or the section is absent, they SHALL print nothing
about it.

When `last_generated_hash` is present and differs from the fingerprint, the
command SHALL print:

`WARNING: [relative_due_dates] has changed since generate-due-dates last wrote due_dates. Run generate-due-dates to update due_dates.`

When `last_generated_hash` is absent, the command SHALL print:

`WARNING: [relative_due_dates] has no fingerprint, so it is assumed to have changed since generate-due-dates last wrote due_dates. Run generate-due-dates to update due_dates and record a fingerprint.`

When `last_generated_hash` equals the fingerprint, the command SHALL print
nothing about it.

The warning SHALL be printed twice: once with the command's due-dates output
(for `update`, alongside "Applying due_dates..." and "Checking due_dates
coverage..."; for `publish`, before staging begins), and once more after the
command's final status line ("Update successful", "Update complete; ...",
"Noop complete; ...", "Check successful ..." or "Check complete; ..." for
`update`; "Built static site: ..." for `publish`). The warning SHALL NOT change
the exit status, SHALL NOT stop the command, and SHALL NOT change which dates
are sent to Canvas or used by `publish`.

#### Scenario: Table edited after generating
- **WHEN** `generate-due-dates` ran cleanly, then an offset in the default table was edited, and the user runs `update`
- **THEN** the "has changed since generate-due-dates" warning is printed with the due-dates output and again after "Update successful", and `update` sends the dates in `due_dates` as before

#### Scenario: No fingerprint yet
- **WHEN** the default table has items, `[relative_due_dates]` has no `last_generated_hash`, and the user runs `update`
- **THEN** the "has no fingerprint" warning is printed in both places

#### Scenario: In sync
- **WHEN** `last_generated_hash` equals the fingerprint
- **THEN** `update` and `publish` print no warning about `[relative_due_dates]`

#### Scenario: Course that does not use relative dates
- **WHEN** `[relative_due_dates.tables.default]` has an empty `items` array, no other table has items, and there is no `last_generated_hash`
- **THEN** `update` and `publish` print no warning about `[relative_due_dates]`

#### Scenario: Targeted update
- **WHEN** the fingerprint is out of date and the user runs `update -t modules/week03`
- **THEN** the warning is printed with the due-dates output and after the final status line

#### Scenario: Noop and new-course check
- **WHEN** the fingerprint is out of date and the user runs `update --noop` or `update --check-as-new-course`
- **THEN** the warning is printed in both places and the exit status is the same as without the warning

#### Scenario: publish
- **WHEN** the fingerprint is out of date and the user runs `publish`
- **THEN** the warning is printed before staging and again after "Built static site: ..."

### Requirement: Upgrading to format 15 does not record a fingerprint

The format 14 to 15 migration run by `upgrade` SHALL NOT add
`last_generated_hash`. A repo whose tables have items SHALL therefore get the
"has no fingerprint" warning from `update` and `publish` until
`generate-due-dates` is run.

#### Scenario: Upgraded repo
- **WHEN** a format-14 repo whose default table has items is upgraded and the user runs `update`
- **THEN** `course_settings.toml` has no `last_generated_hash` and the "has no fingerprint" warning is printed

#### Scenario: Older tool
- **WHEN** a tool at format 14 runs `generate-due-dates` on a repo that has `last_generated_hash`
- **THEN** it stops with its format-version error instead of an unknown-key error, because the repo records format 15
