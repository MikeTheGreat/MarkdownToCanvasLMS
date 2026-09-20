# Spec Delta

## MODIFIED Requirements

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
