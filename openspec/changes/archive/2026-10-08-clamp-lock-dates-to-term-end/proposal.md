# Proposal

## Why

`generate-due-dates` computes `lock_at` as an offset from each item's due date
(`lock_offset` / `lock_relative_default`). For items due near the end of the
quarter that offset lands after the term's `last_day`, and an item whose lock
rule is `NONE` stays open forever. Nothing limits either case today. The only
workaround is a hand-written `lock_offset` on each late item, which breaks
whenever the term length changes.

## What Changes

- New optional boolean setting `clamp_lock_at_to_last_day_of_term` in
  `[relative_due_dates]`. Like the other schedule settings, a table
  (`[relative_due_dates.tables.NAME]`) may override it. Default: false.
- When it is true, `generate-due-dates` writes `lock_at` as the term file's
  `last_day` at 23:59 (term time zone) for:
  - a computed lock date later than that, and
  - a lock rule of `NONE`, including on an item with no due date.

  Lock dates at or before that time are unchanged. An item with no lock rule
  (`KEEP`) is left untouched, as are virtual items (they have no lock date).
  A field kept by `dont_reschedule_dates_before` stays kept.
- `generate-due-dates` prints a summary line when lock dates were set this way,
  split by cause, e.g. `4 lock dates set to the term's last day (Fri Dec 18,
  2026 11:59 PM PST): 3 were later, 1 was NONE`. With `--verbose`, the items
  are listed under it.
- `import` writes the setting commented out, with an explanatory comment, in
  `[relative_due_dates]`.
- **BREAKING (format version):** an older tool rejects the new key as unknown,
  so `FORMAT_VERSION` goes from 12 to 13. Migration 12 -> 13 adds the same
  commented-out line to existing repos.

## Existing mechanisms

- `lock_offset` / `lock_relative_default` set lock dates relative to the due
  date only. A per-item `lock_offset` can be hand-tuned for late items, but it
  has to be redone each term.
- `default_lock_time` sets the time of day of computed lock dates. It is
  applied before the clamp, so the clamp compares the final value.
- The out-of-term check stops the run for due dates outside the term. It does
  not look at lock dates and is unchanged.
- `dont_reschedule_dates_before` keeps past fields. It interacts only in that
  a kept field is not clamped.
- TODO.md "`generate-due-dates`: revisit lock and unlock handling" asks for
  lock rules measured from something other than the due date. This change
  covers one such case (the end of the term) and that item gets a sentence
  saying so. It is not removed, since its other points remain open.

## Core subcommands

- `import`: writes the commented-out setting.
- `update`: unchanged. It sends whatever `due_dates` holds and does not clamp
  hand-written lock dates. `relative_due_dates` is already excluded from
  course-settings syncing.
- `mv`, `publish`: unchanged; neither reads `[relative_due_dates]`.
- `upgrade` (not a core subcommand) gets migration 12 -> 13.

## Capabilities

### New Capabilities

None.

### Modified Capabilities

- `relative-due-dates`: adds the `clamp_lock_at_to_last_day_of_term` setting
  and how it changes computed lock dates.
- `generate-due-dates-command`: adds the clamp summary line and the
  commented-out setting that `import` writes.
- `repo-format-version`: adds migration 12 -> 13.

## Impact

- `src/markdown_to_canvas/relative_dates.py`: setting parsing, clamping in the
  lock computation, a commented-out help block.
- `src/markdown_to_canvas/generate_due_dates.py`: summary line and verbose list.
- `src/markdown_to_canvas/imscc_import.py`: scaffolding.
- `src/markdown_to_canvas/repo_format.py`: `FORMAT_VERSION = 13`, migration.
- Tests: `tests/test_relative_dates.py`, `tests/test_generate_due_dates.py`,
  `tests/test_imscc_import.py`, `tests/test_repo_format.py`, and fixtures that
  pin `format_version`.
- README.md, ARCHITECTURE.md, TODO.md.
