# generate-due-dates-command Specification

## Purpose

Defines the `generate-due-dates` subcommand, which turns a course repo's
relative due dates and a term file into absolute entries in the `due_dates`
table, and the `import` output that gives new repos a place to start.

## Requirements

### Requirement: generate-due-dates writes computed dates into due_dates

`generate-due-dates` SHALL take a required `TERM_FILE` (a path or a term name,
see the `course-registry` capability), an optional `COURSE_DIR` (resolved as
described in the `course-registry` capability), and the options `--table NAME`,
`--noop`, `--yes`/`-y` and `--verbose`/`-v`. The term comes first and the course second. It SHALL
compute the dates of every item of the selected table (see the
`relative-due-dates` capability) and write them to the
top-level `due_dates` array of `course_settings/course_settings.toml`: an
existing entry with the same `name` (and the same `type` when both give one)
gets its `due_at`, `unlock_at` and `lock_at` set, except for fields kept by
`dont_reschedule_dates_before` (see "Dates at or before the cutoff are not
rescheduled") and entries skipped as inconsistent (see "Inconsistent entries
are reported and left unchanged"); an item with no entry gets a
new entry, with `name`, `type` only when the item has one, and the three date
fields. Any other key of an existing entry (for example `only_if`) SHALL be
left as it is. The command SHALL NOT evaluate `only_if` or any course flag. It
SHALL NOT contact Canvas.

#### Scenario: New entries
- **WHEN** the table has items "Week 1 Problem Set" and "Midterm Quiz" and `due_dates` has neither
- **THEN** after confirmation `due_dates` contains one entry for each, each with `due_at`, `unlock_at` and `lock_at`

#### Scenario: Existing entry keeps its other keys
- **WHEN** `due_dates` has `{ name = "Lab 3", due_at = "2026-01-01T00:00:00-08:00", only_if = "in_person_class" }`, there is no cutoff, and the table computes a different `due_at` for "Lab 3"
- **THEN** the entry's `due_at`, `unlock_at` and `lock_at` are updated and `only_if` is still `"in_person_class"`

#### Scenario: Entries and formatting outside the table are preserved
- **WHEN** `due_dates` has an entry for an item that is not in the relative table, and `course_settings.toml` has comments
- **THEN** that entry, the comments, and the order and formatting of the rest of the file are unchanged

#### Scenario: No due date
- **WHEN** an item is anchored to `NO_DUE_DATE`
- **THEN** its entry's `due_at` is `"NONE"`

#### Scenario: Fallback fields
- **WHEN** an item has no lock rule and no unlock rule
- **THEN** its entry's `unlock_at` and `lock_at` are `"KEEP"`

#### Scenario: Not in a repo
- **WHEN** the resolved course directory has no `course_settings/course_settings.toml`
- **THEN** the command exits with a non-zero status and an error, and creates no file

#### Scenario: Term name and course key
- **WHEN** the user runs `generate-due-dates 2026Fall 142` from an unrelated directory, and `2026Fall` is a term name and `142` a registered course
- **THEN** the dates from that term are computed for that course

#### Scenario: Course omitted
- **WHEN** the user runs `generate-due-dates 2026Fall` from inside a course
- **THEN** the enclosing course directory is used

### Requirement: Changes are shown before anything is written

The first line of output after the course directory (and, when the term comes
from the course registry, the term file line) SHALL state the cutoff from
`dont_reschedule_dates_before`: its date, time and time zone, or that no cutoff
is set. This line SHALL be printed on every run that gets past validation,
including runs where nothing changes.

Unless `--noop` is given, the command SHALL calculate all dates first, print
each entry that would be added or changed, and ask the user to confirm before
writing. An entry is shown as its name on one line (marked "(new entry)" when
added) followed by the fields in alphabetical order, indented with a tab: `field: old -> new`
for a changed field, `field: value` for an added entry. When the old and new
value of a changed field are both dates, they are printed on two lines
(`field: old`, then `-> new` right-aligned under the field name) so the values
start in the same column. Lines for changes SHALL be shown in yellow when the output is a
terminal; entries whose computed values equal the current ones SHALL be
listed as unchanged, in normal colour, or counted in a summary line.

When one or more resources had a field kept by the cutoff, the output SHALL
include one line giving their number and the cutoff, saying they were not
rescheduled because of `dont_reschedule_dates_before`. With `--verbose`, each
of those resources SHALL be listed under that line, indented with one tab: its
name, its type when the entry has one, and the names of the kept fields. This
line, and the list, SHALL be printed whether or not anything else changes.
Errors for inconsistent entries SHALL be printed with the changes, before the
confirmation prompt.

If the user declines, nothing is written. If nothing would change, the command says
so and does not ask. A run without a terminal on standard input and without
`--yes` SHALL fail with an error that says to pass `--yes`, and write nothing.
With `--yes`, the confirmation is skipped and the diff is still printed.

#### Scenario: Confirmed
- **WHEN** the user runs the command, sees the diff, and answers yes
- **THEN** `due_dates` is updated as shown

#### Scenario: Declined
- **WHEN** the user answers no
- **THEN** `course_settings.toml` is not modified and the command exits without an error

#### Scenario: Nothing to change
- **WHEN** every computed value already equals the entry's current value
- **THEN** the command prints that nothing changed, does not prompt, and does not modify the file

#### Scenario: Hand-edited entry is overwritten visibly
- **WHEN** a user changed an entry's `due_at` by hand to a date after the cutoff (or there is no cutoff) and that item is in the table
- **THEN** the diff lists the entry with the hand-edited value as old and the computed value as new, and it is overwritten only if the user confirms

#### Scenario: No terminal, no --yes
- **WHEN** standard input is not a terminal and `--yes` is absent
- **THEN** the command exits with a non-zero status, names `--yes`, and writes nothing

#### Scenario: Cutoff shown
- **WHEN** `dont_reschedule_dates_before = "2026-10-01"` and the term's time zone is `America/Los_Angeles`
- **THEN** the output, before any entry, states the cutoff as 2026-10-01 at 11:59 PM with the zone (PDT)

#### Scenario: No cutoff shown
- **WHEN** `dont_reschedule_dates_before` is absent or `""`
- **THEN** the output, before any entry, says no cutoff is set

#### Scenario: Kept resources counted when nothing else changes
- **WHEN** three resources would have had fields changed but every such field was kept by the cutoff, and no other entry changes
- **THEN** the output includes a line saying 3 resources were not rescheduled because of `dont_reschedule_dates_before` and naming the cutoff, says nothing changed, and does not prompt

#### Scenario: Verbose list of kept resources
- **WHEN** the command runs with `--verbose`, "Week 1 Problem Set" had `unlock_at`, `due_at` and `lock_at` kept, and the discussion "Week 2 Discussion" had only `unlock_at` kept
- **THEN** the summary line is followed by one tab-indented line per resource, naming "Week 1 Problem Set" with `unlock_at, due_at, lock_at`, and "Week 2 Discussion" with its type and `unlock_at`

#### Scenario: Without --verbose
- **WHEN** resources had fields kept and `--verbose` is not given
- **THEN** the summary line is printed and the resources are not listed

### Requirement: --noop changes nothing

With `--noop` the command SHALL print the same output it would print without
it (the cutoff line, the diff, the kept-resources line and, with `--verbose`,
its list, and any errors for inconsistent entries), ask nothing, write nothing
and print no confirmation prompt. Its exit status SHALL be the same as a run
that wrote the changes.

#### Scenario: Dry run
- **WHEN** the user runs the command with `--noop`
- **THEN** the diff is printed, `course_settings.toml` is byte-for-byte unchanged, and no prompt is shown

#### Scenario: Dry run with kept fields
- **WHEN** the user runs the command with `--noop` and two resources had fields kept by the cutoff
- **THEN** the cutoff line and the line saying 2 resources were not rescheduled are printed, and `course_settings.toml` is unchanged

### Requirement: Warnings about titles that do not line up

The command SHALL warn, once per title, about (a) an item of the selected
table that matches no assignment, discussion or quiz in the repo, and (b) an
assignment, discussion or quiz that has no item in the selected table and no
`due_dates` entry. Each warning SHALL say which table or tables are
responsible (the relative table, `due_dates`, or both). A title listed in the
table's `ignore` array SHALL NOT be reported as in (b), nor listed in the
notice below. `due_dates` entries
left over from an earlier table SHALL NOT be changed or removed; they SHALL be
listed in a notice as entries not produced by the selected table. Warnings
SHALL NOT change the exit status.

#### Scenario: Item matches nothing
- **WHEN** the table has an item "Week 12 Quiz" and no content file has that title
- **THEN** the output has one warning naming "Week 12 Quiz" and the selected table

#### Scenario: Content missing from both tables
- **WHEN** a discussion "Intro Post" is in neither the relative table nor `due_dates`
- **THEN** the output mentions "Intro Post" once, saying it is in neither table

#### Scenario: Content missing only from the relative table
- **WHEN** an assignment is in `due_dates` but not in the selected relative table
- **THEN** the output mentions it once, saying it has no relative-table item

#### Scenario: Ignored title
- **WHEN** "Week 10 Problem Set" is listed in the table's `ignore` array and is in no other table
- **THEN** no warning is printed for it

#### Scenario: Leftover entries from another table
- **WHEN** `due_dates` has an entry that the selected table has no item for, because an earlier run used a different table
- **THEN** the entry is unchanged after the run and appears in the notice

### Requirement: import creates the relative-due-dates scaffolding

`import` SHALL write an empty `[relative_due_dates.tables.default]` table (an
empty `items` array) into the new `course_settings.toml`, after all top-level
keys, together with the shared settings listed in the `relative-due-dates`
capability, commented out and each with a comment listing its allowed values.
Among them SHALL be the line `# dont_reschedule_dates_before = "YYYY-MM-DD"`
inside `[relative_due_dates]`, with a comment saying that dates on or before it
are not rescheduled and that the time zone is the term file's, and the real
(uncommented) settings `default_unlock_time = "00:00"` and
`default_lock_time = "23:59"`.
`import` SHALL also write an example term file at
`course_settings/term_dates.toml` when that file does not exist; every line of
the example is a comment, filled with example values so the format is visible.
When the file exists, `import` SHALL NOT change it. The example SHALL parse as
an empty TOML document.

#### Scenario: Fresh import
- **WHEN** a user runs `import` into an output directory with no `course_settings/term_dates.toml`
- **THEN** the file is created, contains only comments and blank lines, and the new `course_settings.toml` has `[relative_due_dates.tables.default]` with an empty `items` array

#### Scenario: Term file already exists
- **WHEN** `course_settings/term_dates.toml` already exists in the output directory
- **THEN** `import` leaves its content unchanged

#### Scenario: Default table alone
- **WHEN** a repo imported by this version runs `generate-due-dates` with the untouched default table
- **THEN** the command finds no items, reports which content has no item, and writes nothing

#### Scenario: Default times written
- **WHEN** a user runs `import`
- **THEN** the parsed `[relative_due_dates]` section of the new `course_settings.toml` has `default_unlock_time = "00:00"` and `default_lock_time = "23:59"`

#### Scenario: Commented-out cutoff
- **WHEN** a user runs `import`
- **THEN** the `[relative_due_dates]` section of the new `course_settings.toml` contains the line `# dont_reschedule_dates_before = "YYYY-MM-DD"`, and the parsed section has no `dont_reschedule_dates_before` key

### Requirement: The example term file is not treated as content

The example term file in `course_settings/` SHALL NOT be uploaded, reported as
an orphan, or otherwise change the behavior of `update`, `find-local-orphans`
or `prune`.

#### Scenario: Update with the example file present
- **WHEN** `update` runs on a repo containing `course_settings/term_dates.toml`
- **THEN** the file is not uploaded and produces no warning

### Requirement: Dates at or before the cutoff are not rescheduled

When `dont_reschedule_dates_before` sets a cutoff, the command SHALL compute
every item's dates as usual and then decide each of `unlock_at`, `due_at` and
`lock_at` separately for each existing `due_dates` entry. A field SHALL be kept
(left as it is in `due_dates`) when its current value is a date at or before the
cutoff. A current date without a UTC offset SHALL be read in the term file's
time zone. A field whose current value is after the cutoff, is a sentinel
(`NONE`, `KEEP`, `CREATE_NONE_THEN_KEEP`), is empty, or is absent SHALL be
written as computed, even when the computed date is at or before the cutoff. A
new entry SHALL be written in full. A resource counts as "not rescheduled" when
at least one of its fields was kept and the computed value of that field
differs from the current one. The cutoff SHALL apply to assignments,
discussions and quizzes alike. `update` SHALL NOT read
`dont_reschedule_dates_before`.

#### Scenario: Past item untouched
- **WHEN** the cutoff is 2026-10-01 23:59:59, "Week 1 Problem Set" currently has `unlock_at` 2026-09-24, `due_at` 2026-09-30 and `lock_at` 2026-10-01 (all 23:59), and the table computes different dates for all three
- **THEN** none of its fields change, and it is counted as not rescheduled with fields `unlock_at, due_at, lock_at`

#### Scenario: Due exactly at the cutoff
- **WHEN** the cutoff is `"2026-10-01 23:59"` and an entry's current `due_at` is `2026-10-01T23:59:00-07:00`
- **THEN** its `due_at` is kept

#### Scenario: Open item
- **WHEN** the cutoff is 2026-10-01 23:59:59 and an entry currently has `unlock_at` 2026-09-28, `due_at` 2026-10-06 and `lock_at` 2026-10-13, and the table computes 2026-10-04, 2026-10-08 and 2026-10-15
- **THEN** `unlock_at` stays 2026-09-28, `due_at` becomes 2026-10-08 and `lock_at` becomes 2026-10-15

#### Scenario: Future date moved into the past
- **WHEN** the cutoff is 2026-10-01 23:59:59, an entry's current `due_at` is 2026-10-06, and the table computes 2026-09-29
- **THEN** `due_at` becomes 2026-09-29

#### Scenario: Sentinel is not protected
- **WHEN** an entry's current `lock_at` is `"KEEP"` and the table computes a date before the cutoff for it
- **THEN** `lock_at` is written as computed

#### Scenario: New entry
- **WHEN** an item has no `due_dates` entry and its computed dates are all before the cutoff
- **THEN** a new entry with all three computed dates is added

#### Scenario: Kept field with no difference
- **WHEN** an entry's current `due_at` is before the cutoff and equals the computed `due_at`
- **THEN** the entry is not counted as not rescheduled on account of `due_at`

#### Scenario: update ignores the key
- **WHEN** `dont_reschedule_dates_before` is set and the user runs `update`
- **THEN** `update` applies `due_dates` exactly as it would without the key

### Requirement: Inconsistent entries are reported and left unchanged

After deciding which fields to keep, the command SHALL check every existing
entry that has at least one kept field and at least one field that would be
written with a new value. Among the resulting values that are dates, it is an
inconsistency when `unlock_at` is after `due_at`, `due_at` is after `lock_at`,
or `unlock_at` is after `lock_at`. For each inconsistent entry the command
SHALL print an error naming the entry, the kept and the computed values, and
the rule broken, and SHALL leave every field of that entry unchanged. All other
entries SHALL be written as usual. When at least one entry was inconsistent,
the command SHALL exit with a non-zero status after it finishes (after writing,
after the user declines, or after a `--noop` run).

#### Scenario: Kept unlock after new due date
- **WHEN** an entry's current `unlock_at` is 2026-09-30 (before the cutoff, so kept), its current `due_at` is 2026-10-06, and the table computes a `due_at` of 2026-09-29
- **THEN** an error names the entry and says `unlock_at` (kept, 2026-09-30) is after `due_at` (computed, 2026-09-29), none of the entry's fields change, other entries are written, and the exit status is non-zero

#### Scenario: Error shown before the prompt
- **WHEN** a run without `--yes` or `--noop` has one inconsistent entry and other changes
- **THEN** the error is printed before the confirmation prompt

#### Scenario: Only inconsistent entries
- **WHEN** the only entry that would change is inconsistent
- **THEN** the error is printed, the command says nothing changed, does not prompt, does not modify the file, and exits non-zero

#### Scenario: No kept fields, no check
- **WHEN** no field of an entry is kept
- **THEN** that entry is written as computed without this check

### Requirement: Date placeholders are checked against the generated dates

After computing its plan, `generate-due-dates` SHALL check every
`replace_date_with` placeholder in the repo's content (the files and snippets
listed under "Where placeholders are expanded" in the `date-placeholders`
capability, honoring `.canvasignore`) against the `due_dates` array as it
would be after the plan is applied. It SHALL use the same resolution rules as
`update` (see the `date-placeholders` capability), except that `only_if` is not
evaluated, consistent with the rest of this command, so every entry counts.
Each placeholder that does not resolve SHALL be reported as an error naming the
file and the placeholder, printed with the plan's other errors before any
prompt. These errors SHALL NOT stop the dates from being written, and SHALL make
the command exit non-zero, as the plan's other errors do. With `--noop` they
SHALL be reported the same way.

#### Scenario: Placeholder names a missing entry
- **WHEN** a discussion has `[x]{.replace_date_with item="HW 9"}` and no `due_dates` entry or table item will be named `HW 9`
- **THEN** `generate-due-dates` reports an error naming the discussion and `HW 9`, writes the plan if confirmed, and exits non-zero

#### Scenario: Entry the plan adds
- **WHEN** a placeholder names `HW 3`, which has no `due_dates` entry yet but is an item of the selected table
- **THEN** no error is reported for it

#### Scenario: Entry with no due date
- **WHEN** a placeholder quotes `due_at` of an entry whose `due_at` will be `NONE`
- **THEN** an error is reported for it
