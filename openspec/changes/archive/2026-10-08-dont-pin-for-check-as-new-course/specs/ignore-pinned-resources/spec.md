# Spec Delta

## Purpose

Lets `update --check-as-new-course` check pinned content too, by treating every
`pinned_resources` entry as unpinned for that simulated run only.

## ADDED Requirements

### Requirement: --ignore-pinned-resources unpins for the check run

`update` SHALL accept `--ignore-pinned-resources`. With `--check-as-new-course
--ignore-pinned-resources`, the check SHALL process every file covered by a
`pinned_resources` entry exactly as it processes an unpinned file: the file
SHALL be converted and checked, problems in it SHALL be reported and SHALL make
the run exit non-zero, it SHALL NOT produce a "pinned ... NOT uploaded" warning,
and it SHALL NOT appear in the end-of-run pinned summary. Modules and links that
reference pinned content SHALL be checked as if that content had been created.
`course_settings.toml` SHALL NOT be modified.

#### Scenario: Pinned quiz is checked
- **WHEN** `pinned_resources = ["quizzes/midterm"]`, the quiz description links to a file that does not exist, and `update --check-as-new-course --ignore-pinned-resources` runs
- **THEN** the broken link is reported as a problem and the command exits non-zero

#### Scenario: No pinned warnings
- **WHEN** `pinned_resources` lists a page and `update --check-as-new-course --ignore-pinned-resources` runs
- **THEN** no "pinned ... NOT uploaded" warning is printed for it and no pinned-resources summary is printed

#### Scenario: Module listing a pinned item
- **WHEN** a module lists a pinned quiz and `update --check-as-new-course --ignore-pinned-resources` runs on an otherwise clean repo
- **THEN** the module reports no problem about that item and the command exits 0

### Requirement: Pins are still honored without the option

Without `--ignore-pinned-resources`, `update --check-as-new-course` SHALL skip
pinned content exactly as before this change: each pinned file that would be
uploaded SHALL produce the "pinned ... NOT uploaded" warning and appear in the
end-of-run pinned summary.

#### Scenario: Check without the option
- **WHEN** `pinned_resources` lists a page and `update --check-as-new-course` runs
- **THEN** the page is reported as pinned and not uploaded, as before this change

### Requirement: Option requires --check-as-new-course

`update` SHALL stop with an error before contacting Canvas or reading any
content when `--ignore-pinned-resources` is given without
`--check-as-new-course`. The error SHALL say that the option only works with
`--check-as-new-course`.

#### Scenario: Plain update
- **WHEN** `update --ignore-pinned-resources` runs
- **THEN** it exits non-zero with an error naming `--check-as-new-course`, and nothing in Canvas or the repo changes

#### Scenario: With --noop
- **WHEN** `update --noop --ignore-pinned-resources` runs
- **THEN** it exits non-zero with the same error

### Requirement: Pin entries are still validated

With `--ignore-pinned-resources`, a `pinned_resources` value that a real
`update` would reject (not an array of strings, an empty entry, an absolute
path, or a path inside a quiz or question-bank folder other than the folder or
its main file) SHALL still stop the check with the same error. An entry that
matches no file or folder in the repo SHALL still produce the same warning.

#### Scenario: Invalid entry
- **WHEN** `pinned_resources = ["/abs/path.md"]` and `update --check-as-new-course --ignore-pinned-resources` runs
- **THEN** it stops with the absolute-path error

#### Scenario: Entry matching nothing
- **WHEN** `pinned_resources = ["pages/gone.md"]`, that file does not exist, and `update --check-as-new-course --ignore-pinned-resources` runs
- **THEN** the "does not match any file or folder in the repo" warning is printed

### Requirement: Check mode prints a note about pins

When `pinned_resources` has at least one entry, `update --check-as-new-course`
SHALL print one note after the check-mode banner and before any item is
processed:

- with `--ignore-pinned-resources`: that the N entries are temporarily
  unpinned for this simulated run, so pinned content is checked like
  everything else; with `--verbose` it SHALL also list each entry;
- without it: that the N entries will be skipped, and that adding
  `--ignore-pinned-resources` checks them too.

When `pinned_resources` is absent or empty, no note SHALL be printed.

#### Scenario: Note with the option
- **WHEN** `pinned_resources` has 2 entries and `update --check-as-new-course --ignore-pinned-resources` runs
- **THEN** a note says 2 pinned_resources entries are temporarily unpinned for this simulated run, and the entries are not listed

#### Scenario: Entries listed with --verbose
- **WHEN** `pinned_resources` has 2 entries and `update --check-as-new-course --ignore-pinned-resources --verbose` runs
- **THEN** the note is followed by both entries

#### Scenario: Hint without the option
- **WHEN** `pinned_resources` has 4 entries and `update --check-as-new-course` runs
- **THEN** a note says 4 pinned_resources entries will be skipped and names `--ignore-pinned-resources`

#### Scenario: No pins
- **WHEN** `course_settings.toml` has no `pinned_resources` and `update --check-as-new-course` runs, with or without `--ignore-pinned-resources`
- **THEN** no pin note is printed
