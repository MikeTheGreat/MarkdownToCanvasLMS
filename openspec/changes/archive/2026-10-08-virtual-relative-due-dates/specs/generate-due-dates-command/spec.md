## MODIFIED Requirements

### Requirement: Warnings about titles that do not line up

The command SHALL warn, once per title, about (a) an ordinary (not virtual)
item of the selected table that matches no assignment, discussion or quiz in
the repo, and (b) an assignment, discussion or quiz that has no ordinary item
in the selected table and no `due_dates` entry. Each warning SHALL say which
table or tables are responsible (the relative table, `due_dates`, or both). A
title listed in the table's `ignore` array SHALL NOT be reported as in (b), nor
listed in the notice below. Virtual items SHALL NOT be reported as in (a).
`due_dates` entries left over from an earlier table SHALL NOT be changed or
removed; they SHALL be listed in a notice as entries not produced by the
selected table. A `due_dates` entry whose name is a virtual item of the
selected table is not produced by it, so it SHALL be listed in that notice too.
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
- **WHEN** `due_dates` has an entry `Start_of_week_3`, written when that item was ordinary, and the item is now virtual
- **THEN** the entry is unchanged after the run and appears in the notice of entries not produced by the selected table

## ADDED Requirements

### Requirement: Virtual items are not written to due_dates

The command SHALL NOT add, change or remove a `due_dates` entry for a virtual
item, and SHALL NOT list a virtual item among the added, changed or unchanged
entries or count it in the unchanged-entries line. Virtual items SHALL NOT
affect whether there is anything to write: a run whose only computed values
are virtual items' dates SHALL say that nothing would change and SHALL NOT ask
for confirmation.

A virtual item whose `name` equals the title of an assignment, discussion or
quiz in the repo SHALL be an error naming the item and the content file, and
nothing SHALL be written. Titles are read as they are for the title warnings
(frontmatter `title`, else the file stem), including titles listed in the
table's `ignore` array.

With `--verbose`, the output SHALL list each virtual item of the selected table
with its computed date and time, sorted by name, after the changes and before
the unchanged-entries line, under one heading line that identifies them as
virtual dates not written to `due_dates`. Each item SHALL be on its own line,
indented with one tab, as its name followed by its date, with the dates
starting in the same column. Without `--verbose`, virtual items SHALL NOT appear in
the output. The list SHALL be printed whether or not anything else changes, and
with `--noop`.

Date placeholders SHALL be checked against `due_dates` as it will be after the
run, which never contains virtual items; a placeholder that names a virtual
item SHALL be reported as naming a missing entry.

#### Scenario: Virtual item not written
- **WHEN** the table has a virtual item `Start_of_week_3` and an ordinary item "Lab 3" anchored to it, and `due_dates` has no entry for either
- **THEN** after confirming, `due_dates` gains an entry for "Lab 3" and none for `Start_of_week_3`

#### Scenario: Only virtual items
- **WHEN** every ordinary item's dates equal its current `due_dates` entry and the table also has virtual items
- **THEN** the command says nothing would change and does not prompt

#### Scenario: Name collides with content
- **WHEN** the table has a virtual item "Midterm" and `assignments/midterm.md` has title "Midterm"
- **THEN** the command fails with an error naming "Midterm" and `assignments/midterm.md`, and nothing is written

#### Scenario: Verbose lists virtual dates
- **WHEN** the command runs with `--verbose` and the table has virtual items `Start_of_week_1` and `Start_of_week_2`
- **THEN** the output has a heading line for virtual dates followed by one tab-indented line for each, with its name and computed date and time, sorted by name, the dates starting in the same column

#### Scenario: Without --verbose
- **WHEN** the command runs without `--verbose` and the table has virtual items
- **THEN** no output line names a virtual item

#### Scenario: Placeholder names a virtual item
- **WHEN** a content file has a date placeholder with `item="Start_of_week_3"` and `Start_of_week_3` is a virtual item
- **THEN** the placeholder is reported as naming a missing `due_dates` entry, as for any other missing entry
