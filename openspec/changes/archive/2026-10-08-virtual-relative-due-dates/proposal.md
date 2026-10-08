# Proposal

## Why

A relative table can only name real assignments, discussions and quizzes, so
there is no way to write "due on the second class day of week 3" except by
counting class days from the start of the term, which shifts by one whenever a
holiday falls in an earlier week. Named reference dates such as
`Start_of_week_3`, computed from the term but never written to `due_dates`,
let real items anchor to a calendar week instead.

## What Changes

- An item in `[relative_due_dates.tables.<name>].items` may be marked virtual
  with a new optional key, `virtual = true`. Its date is computed
  with the same anchors and offsets as any other item, and other items in the
  same table can anchor to it with the existing
  `relative_to = { type = "ASSIGNMENT", assignment_name = "..." }`.
- `generate-due-dates` never writes a virtual item to `due_dates`, never warns
  that it matches no content, and does not list it in the notice of `due_dates`
  entries the table did not produce.
- A virtual item's date is checked against the term (`first_day` ..
  `last_day`) like a real due date, and an out-of-term date is the same error.
- A virtual item whose name is also the title of an assignment, discussion or
  quiz in the repo is an error. (Two items with the same name in one table are
  already an error.)
- `generate-due-dates --verbose` lists each virtual item and its computed date;
  without `--verbose` they are not shown.
- `cp` stops treating virtual item names as dates that live in the source
  course's settings.
- **BREAKING** (format): `repo_format.FORMAT_VERSION` goes from 10 to 11.
  An older tool rejects the new item key as unknown, so the version changes.
  Migration 10 -> 11 only records the new version; no file content changes.

### Existing mechanisms

- Today a real item can already serve as an anchor for others. Putting a
  pseudo-item such as `Start_of_week_3` in the table gives the right dates,
  but it is written to `due_dates`, `generate-due-dates` warns that it matches
  no content, and every `update` warns that its `due_dates` entry matched no
  content file. This change removes those three effects. The
  calculation itself (the `ASSIGNMENT` anchor, memoized per item) is reused
  unchanged.
- `ABSOLUTE_DATE` anchors give a fixed date, but it has to be edited every
  term; a virtual item computed from the term does not.
- `FIRST_CLASS_OF_QUARTER` with `+N CLASS_DAY` counts class days, which is not
  the same as a calendar week when there are holidays.
- The table's `ignore` list only silences warnings for content titles; it does
  not keep an item out of `due_dates`.

### TODO.md

Two follow-ups were added to TODO.md during exploration and stay out of
scope: "`generate-due-dates`: generate week anchors automatically" and "Date
placeholders that name virtual relative dates". No existing TODO.md item is
implemented by this change.

### Core subcommands

- `update` and `publish`: no behavior change. They read only `due_dates`, which
  never contains virtual items, and `relative_due_dates` is already excluded
  from what they send. They do enforce the format version, so they refuse a
  version-10 repo until `upgrade` runs, as for every format bump.
- `import`: its help comments for `[relative_due_dates]` gain one line about
  the new key, and it stamps new repos with version 11 through
  `FORMAT_VERSION`.
- `mv`: not affected; it does not read the relative table.

## Capabilities

### New Capabilities

None.

### Modified Capabilities

- `relative-due-dates`: items may be virtual; which keys a virtual item may
  have; its date is computed and term-checked but it does not name content.
- `generate-due-dates-command`: virtual items are not written to `due_dates`,
  are left out of the title warnings and the leftover notice, collide with
  content titles as an error, and are listed with `--verbose`.
- `repo-format-version`: migration 10 to 11.

## Impact

- `src/markdown_to_canvas/relative_dates.py`: item key list, `RelativeItem`,
  item validation, `_Calculator.compute` output.
- `src/markdown_to_canvas/generate_due_dates.py`: plan building,
  `title_warnings`, `render_plan` verbose output, content-title collision
  check.
- `src/markdown_to_canvas/cp.py`: `_relative_names`.
- `src/markdown_to_canvas/repo_format.py`: `FORMAT_VERSION`, new migration.
- `src/markdown_to_canvas/imscc_import.py`: `_RELATIVE_DUE_DATES_HELP` text.
- Tests in `tests/test_relative_dates.py`, `tests/test_generate_due_dates.py`,
  `tests/test_repo_format.py`, plus any test that asserts the current format
  version.
- README.md, ARCHITECTURE.md.
- No Canvas API behavior is involved.
