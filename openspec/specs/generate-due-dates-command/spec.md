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
`--noop` and `--yes`/`-y`. The term comes first and the course second. It SHALL
compute the dates of every item of the selected table (see the
`relative-due-dates` capability) and write them to the
top-level `due_dates` array of `course_settings/course_settings.toml`: an
existing entry with the same `name` (and the same `type` when both give one)
gets its `due_at`, `unlock_at` and `lock_at` set; an item with no entry gets a
new entry, with `name`, `type` only when the item has one, and the three date
fields. Any other key of an existing entry (for example `only_if`) SHALL be
left as it is. The command SHALL NOT evaluate `only_if` or any course flag. It
SHALL NOT contact Canvas.

#### Scenario: New entries
- **WHEN** the table has items "Week 1 Problem Set" and "Midterm Quiz" and `due_dates` has neither
- **THEN** after confirmation `due_dates` contains one entry for each, each with `due_at`, `unlock_at` and `lock_at`

#### Scenario: Existing entry keeps its other keys
- **WHEN** `due_dates` has `{ name = "Lab 3", due_at = "2026-01-01T00:00:00-08:00", only_if = "in_person_class" }` and the table computes a different `due_at` for "Lab 3"
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

Unless `--noop` is given, the command SHALL calculate all dates first, print
each entry that would be added or changed, and ask the user to confirm before
writing. An entry is shown as its name on one line (marked "(new entry)" when
added) followed by the fields in alphabetical order, indented with a tab: `field: old -> new`
for a changed field, `field: value` for an added entry. When the old and new
value of a changed field are both dates, they are printed on two lines
(`field: old`, then `-> new` right-aligned under the field name) so the values
start in the same column. Lines for changes SHALL be shown in yellow when the output is a
terminal; entries whose computed values equal the current ones SHALL be
listed as unchanged, in normal colour, or counted in a summary line. If the
user declines, nothing is written. If nothing would change, the command says
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
- **WHEN** a user changed an entry's `due_at` by hand and that item is in the table
- **THEN** the diff lists the entry with the hand-edited value as old and the computed value as new, and it is overwritten only if the user confirms

#### Scenario: No terminal, no --yes
- **WHEN** standard input is not a terminal and `--yes` is absent
- **THEN** the command exits with a non-zero status, names `--yes`, and writes nothing

### Requirement: --noop changes nothing

With `--noop` the command SHALL print the same diff it would print without
it, ask nothing, write nothing and print no confirmation prompt.

#### Scenario: Dry run
- **WHEN** the user runs the command with `--noop`
- **THEN** the diff is printed, `course_settings.toml` is byte-for-byte unchanged, and no prompt is shown

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

### Requirement: The example term file is not treated as content

The example term file in `course_settings/` SHALL NOT be uploaded, reported as
an orphan, or otherwise change the behavior of `update`, `find-local-orphans`
or `prune`.

#### Scenario: Update with the example file present
- **WHEN** `update` runs on a repo containing `course_settings/term_dates.toml`
- **THEN** the file is not uploaded and produces no warning
