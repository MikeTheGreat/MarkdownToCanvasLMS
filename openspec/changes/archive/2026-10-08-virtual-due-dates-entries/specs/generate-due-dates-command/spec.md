# Spec Delta

## MODIFIED Requirements

### Requirement: generate-due-dates writes computed dates into due_dates

`generate-due-dates` SHALL take a required `TERM_FILE` (a path or a term name,
see the `course-registry` capability), an optional `COURSE_DIR` (resolved as
described in the `course-registry` capability), and the options `--table NAME`,
`--noop`, `--yes`/`-y` and `--verbose`/`-v`. The term comes first and the course second. It SHALL
compute the dates of every item of the selected table (see the
`relative-due-dates` capability) and write them to the
top-level `due_dates` array of `course_settings/course_settings.toml`. For an
ordinary (not virtual) item: an
existing ordinary entry with the same `name` (and the same `type` when both give one)
gets its `due_at`, `unlock_at` and `lock_at` set, except for fields kept by
`dont_reschedule_dates_before` (see "Dates at or before the cutoff are not
rescheduled") and entries skipped as inconsistent (see "Inconsistent entries
are reported and left unchanged"); an item with no entry gets a
new entry, with `name`, `type` only when the item has one, and the three date
fields. Virtual items are written as described in "Virtual items are written
as virtual entries". Any other key of an existing entry (for example `only_if`) SHALL be
left as it is. The command SHALL NOT evaluate `only_if` or any course flag. It
SHALL NOT contact Canvas.

Before computing anything, the command SHALL check the virtual entries already
in `due_dates` as described in the `virtual-due-dates` capability, and stop
with those errors, writing nothing, when any is invalid.

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

#### Scenario: Invalid virtual entry already in due_dates
- **WHEN** `due_dates` has a hand-written virtual entry with `lock_at`
- **THEN** the command fails with the error naming the entry and `lock_at`, shows no plan, and writes nothing

### Requirement: Warnings about titles that do not line up

The command SHALL warn, once per title, about (a) an ordinary (not virtual)
item of the selected table that matches no assignment, discussion or quiz in
the repo, and (b) an assignment, discussion or quiz that has no ordinary item
in the selected table and no ordinary `due_dates` entry. Each warning SHALL say which
table or tables are responsible (the relative table, `due_dates`, or both). A
title listed in the table's `ignore` array SHALL NOT be reported as in (b), nor
listed in the notice below. Virtual items SHALL NOT be reported as in (a).
`due_dates` entries not produced by the selected table, ordinary or virtual
(for example left over from an earlier table, written by hand, or a virtual
entry whose item was removed from the table), SHALL NOT be changed or removed;
they SHALL be listed in a notice as entries not produced by the selected table.
A virtual entry whose name is a virtual item of the selected table is produced
by it and SHALL NOT be listed in that notice.
Warnings SHALL NOT change the exit status.

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

#### Scenario: Virtual item is not a missing title
- **WHEN** the table has a virtual item `Start_of_week_3` and no content has that title
- **THEN** no warning names `Start_of_week_3`

#### Scenario: Entry left from before the item was virtual
- **WHEN** `due_dates` has an ordinary entry `Start_of_week_3`, written when that item was ordinary, and the item is now virtual
- **THEN** the command fails with an error naming `Start_of_week_3` (see "Virtual items are written as virtual entries"), and nothing is written

#### Scenario: Virtual item removed from the table
- **WHEN** `due_dates` has a virtual entry `Start_of_week_12` and the selected table no longer has an item of that name
- **THEN** the entry is unchanged after the run and appears in the notice of entries not produced by the selected table

#### Scenario: Hand-written virtual entry
- **WHEN** `due_dates` has a hand-written virtual entry "Last day to withdraw" that is not in the table's `ignore` array
- **THEN** the entry is unchanged after the run and appears in the notice

## REMOVED Requirements

### Requirement: Virtual items are not written to due_dates

**Reason**: Virtual items are now written to `due_dates` as virtual entries so
that date placeholders can quote them.

**Migration**: None needed. A run after upgrading adds a virtual entry for each
virtual item. The content-title collision error is kept, in "Virtual items are
written as virtual entries".

## ADDED Requirements

### Requirement: Virtual items are written as virtual entries

For each virtual item of the selected table, the command SHALL write a virtual
entry (see the `virtual-due-dates` capability) to `due_dates`. When `due_dates`
has a virtual entry with the item's `name`, that entry's `due_at` SHALL be set
to the item's computed date and time; otherwise a new entry SHALL be added with
the keys `name`, `virtual = true` and `due_at`, in that order. `due_at` SHALL
be a full date and time with its UTC offset, as for ordinary entries. Any other
key of an existing virtual entry (`only_if`) SHALL be left as it is.

An ordinary item SHALL match only ordinary entries and a virtual item only
virtual entries. When the name of a virtual item is also the `name` of an
ordinary `due_dates` entry, or the name of an ordinary item is also the `name`
of a virtual `due_dates` entry, the command SHALL fail with an error naming the
entry, and nothing SHALL be written.

`dont_reschedule_dates_before` SHALL apply to a virtual entry's `due_at` as it
does to an ordinary entry's: a current value at or before the cutoff is kept,
and the entry is counted and, with `--verbose`, listed among the resources not
rescheduled.

Virtual entries SHALL be shown in the list of added and changed entries, and
counted in the unchanged-entries line, in the same way as ordinary entries, and
SHALL count toward whether there is anything to write. A virtual entry's label
SHALL say it is virtual. A new virtual entry lists only `due_at`. The command
SHALL NOT print a separate list of virtual dates, with or without `--verbose`.

A virtual item whose `name` equals the title of an assignment, discussion or
quiz in the repo SHALL be an error naming the item and the content file, and
nothing SHALL be written. Titles are read as they are for the title warnings
(frontmatter `title`, else the file stem), including titles listed in the
table's `ignore` array.

Date placeholders SHALL be checked against `due_dates` as it will be after the
run, which includes the virtual entries, so a placeholder naming a virtual
item of the selected table resolves.

#### Scenario: Virtual item written
- **WHEN** the table has a virtual item `Start_of_week_3` and an ordinary item "Lab 3" anchored to it, and `due_dates` has no entry for either
- **THEN** after confirming, `due_dates` gains `{ name = "Start_of_week_3", virtual = true, due_at = <computed date and time> }` and an ordinary entry for "Lab 3"

#### Scenario: Virtual entry updated
- **WHEN** `due_dates` has a virtual entry `Start_of_week_3` with `only_if = "fall"` and the table computes a different date for it
- **THEN** the diff shows its `due_at` change, and after confirming only `due_at` changes and `only_if` is still `"fall"`

#### Scenario: Only virtual items changed
- **WHEN** every ordinary item's dates equal its current entry and one virtual item's computed date differs from its entry
- **THEN** the command lists that virtual entry as changed and asks for confirmation

#### Scenario: Nothing changed
- **WHEN** every item's computed values, virtual and ordinary, equal the current entries
- **THEN** the command says nothing would change and does not prompt

#### Scenario: Name collides with content
- **WHEN** the table has a virtual item "Midterm" and `assignments/midterm.md` has title "Midterm"
- **THEN** the command fails with an error naming "Midterm" and `assignments/midterm.md`, and nothing is written

#### Scenario: Cutoff keeps a past virtual date
- **WHEN** the cutoff is 2026-10-01 23:59:59, the virtual entry `Start_of_week_1` has `due_at` 2026-09-28, and the table computes 2026-09-29
- **THEN** its `due_at` stays 2026-09-28 and it is counted as not rescheduled

#### Scenario: Placeholder names a virtual item
- **WHEN** a content file has a date placeholder with `item="Start_of_week_3"`, `Start_of_week_3` is a virtual item of the selected table, and `due_dates` has no entry for it yet
- **THEN** no placeholder error is reported for it

#### Scenario: No virtual list with --verbose
- **WHEN** the command runs with `--verbose` and nothing changed
- **THEN** no separate list of virtual dates is printed
