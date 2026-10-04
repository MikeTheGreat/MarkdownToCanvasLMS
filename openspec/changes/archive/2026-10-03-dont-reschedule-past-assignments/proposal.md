# Proposal

## Why

`generate-due-dates` rewrites the `unlock_at`, `due_at` and `lock_at` of every
item in the selected relative table. Running it mid-term (for example after
adding a closure to the term file, or after retuning offsets) therefore also
moves dates that have already passed, and the next `update` sends those moved
dates to Canvas. The instructor wants to regenerate the schedule and push it to
Canvas without changing dates that students have already lived through.

Separately, unlock and lock dates computed from offsets inherit the due date's
time of day, so an item due at 23:59 also unlocks at 23:59 (the sandbox course
showed "Not available until Oct 7 at 11:59pm"). The instructor wants a default
unlock time and lock time for items that have no explicit time.

## What Changes

- New optional key `dont_reschedule_dates_before` in the `[relative_due_dates]`
  section of `course_settings.toml`. It applies to every table in the section.
  Its value is `"YYYY-MM-DD"` (meaning the end of that day, 23:59:59) or
  `"YYYY-MM-DD HH:MM"`, read in the term file's `time_zone`. An empty string
  means no cutoff. Any other value is an error.
- `generate-due-dates` still computes every date first. It then decides field
  by field: when a field's current value in `due_dates` is a date at or before
  the cutoff (`<=`), that field is left as it is. Every other field is written
  as computed, even when the new date lands before the cutoff. New entries are
  always written in full.
- A cutoff outside the term file's `first_day`..`last_day` stops the command
  with an error before any date is computed or written.
- Keeping some fields and writing others can leave an entry inconsistent
  (`unlock_at` after `due_at`, `due_at` after `lock_at`, or `unlock_at` after
  `lock_at`). Such an entry is reported as an error and left completely
  unchanged. Every other entry is still written, and the command exits
  non-zero. The error is shown with the diff, before the confirmation prompt.
- Output: the cutoff (date, time and zone) is always printed at the start of a
  run. Whenever at least one item had a field kept, a line says how many
  resources were not rescheduled because of `dont_reschedule_dates_before`.
  This line also prints on runs where nothing else changes. A new `--verbose` /
  `-v` option lists those items one tab in, each with the fields that were
  kept. `--noop` prints the same output as a normal run.
- New optional settings `default_unlock_time` and `default_lock_time`
  (`"HH:MM"`) in `[relative_due_dates]`, which a table may override like the
  other shared settings. After an unlock or lock rule's offsets are applied,
  the setting replaces the time of day, but only when the item's due time is
  not explicit (no `ABS_TIME` in the item's own `offsets`) and the rule itself
  has no `ABS_TIME`. An item due at 17:00 through `"17:00 ABS_TIME"` with a
  `+7 CALENDAR_DAY` lock rule still locks at 17:00 a week later. Without the
  settings, behavior is unchanged.
- `import` writes the cutoff commented out inside `[relative_due_dates]`
  (`# dont_reschedule_dates_before = "YYYY-MM-DD"`), and the two default times
  as real values: `default_unlock_time = "00:00"` and
  `default_lock_time = "23:59"`.
- **BREAKING**: `repo_format.FORMAT_VERSION` goes from 8 to 9. Migration 8 -> 9
  adds the same three lines to the `[relative_due_dates]` section of existing
  repos, skipping any that the section already has. Because the default times
  are real values, the next `generate-due-dates` run on an existing repo shows
  unlock dates moving to 00:00 (dates already past the cutoff are kept). As with every bump, a version-9 tool refuses version-8 repos
  until `upgrade` is run, and a version-8 tool refuses version-9 repos. Without
  the bump, an older tool reading a repo with the key set would stop with
  "unknown key".
- `update` does not change. It sends only `due_dates` entries whose resolved
  dates changed, so it makes no API call for an entry whose fields were all
  kept.

### Existing mechanisms and how this relates to them

- `KEEP` in a `due_dates` entry already freezes one field of one item, but
  `generate-due-dates` overwrites it on the next run. The new key gives the
  same protection across runs, chosen by date instead of by hand per entry.
- Deleting a `due_dates` entry makes `update` stop managing that item's dates,
  but `generate-due-dates` adds the entry back.
- `pinned_resources` freezes content uploads only. The dates-only pass in
  `update` (`_apply_due_dates_only`) does not check pins, so a pinned item's
  dates still change. The new key is separate from pins and does not change
  how they behave.
- The `generate-due-dates` diff and confirmation prompt already show every
  change before writing, but they can only accept or reject the whole set.
- An `ABS_TIME` offset in `unlock_relative_default` or `lock_relative_default`
  (for example `["-7 CALENDAR_DAY", "00:00 ABS_TIME"]`) already sets the time
  for items that use the default rule, but not for items with their own
  `unlock_offset` or `lock_offset`. The new settings cover both.

### TODO.md

- Partly addresses the existing "`generate-due-dates`: revisit lock and unlock
  handling" item (the time of day of lock and unlock dates). The item stays,
  with a note added.
- The deferred command-line override is already recorded in TODO.md as
  "`generate-due-dates`: command-line override for
  `dont_reschedule_dates_before`". This change does not implement it.

### Core subcommands

- `import`: affected. It writes the commented-out key.
- `update`: no behavior change, by decision. It reads the dates that
  `generate-due-dates` wrote, as it does now.
- `mv`: not affected. `due_dates` entries are matched by title, not by path,
  and the key holds a date, not a path.
- `publish`: not affected. It does not read `[relative_due_dates]`.
- All four, like every other command that reads a repo, are affected by the
  format version bump: each refuses a version-8 repo until `upgrade` is run.

## Capabilities

### New Capabilities

None.

### Modified Capabilities

- `relative-due-dates`: the `[relative_due_dates]` section gains the
  `dont_reschedule_dates_before` setting. Its format, time zone and
  term-range validation are defined here.
- `generate-due-dates-command`: the command keeps fields at or before the
  cutoff, reports and skips inconsistent entries, prints the cutoff and the
  kept-items summary, and gains `--verbose`. `import` writes the commented-out
  key.
- `repo-format-version`: adds Migration 8 to 9.

## Impact

- `src/markdown_to_canvas/relative_dates.py`: the new allowed section key,
  parsing, and validation against the term.
- `src/markdown_to_canvas/generate_due_dates.py`: per-field keeping, the
  consistency check, and the summary data on `GenerationPlan` and in
  `render_plan`.
- `src/markdown_to_canvas/cli.py`: the `--verbose`/`-v` option, the cutoff
  header, and the exit status when entries are skipped.
- `src/markdown_to_canvas/imscc_import.py`: the commented line in
  `_RELATIVE_DUE_DATES_HELP`.
- `src/markdown_to_canvas/repo_format.py`: `FORMAT_VERSION = 9` and
  `_migrate_8_to_9`.
- Tests: `tests/test_generate_due_dates.py`, the relative-dates tests,
  `tests/test_repo_format.py`, `tests/test_imscc_import.py`, and any fixture
  pinned to format version 8 (for example
  `tests/fixtures/course_settings/course_settings.toml`).
- Docs: README.md and ARCHITECTURE.md.
- Canvas: no direct effect. `generate-due-dates` never contacts Canvas.
