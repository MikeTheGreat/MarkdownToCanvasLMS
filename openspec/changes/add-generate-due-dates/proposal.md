# Proposal

## Why

Every term the `due_dates` table in `course_settings.toml` has to be rebuilt as
absolute dates, and today that is done by hand or by the separate
MikesGradingTool script, which reads its own `~/.../config.json`. The
calculation ("this is due 4 class days after the start of the quarter, at
23:59, and locks a week later") is the same every term; only the term's start
date and holidays change. Moving the calculation into this tool lets a course
repo carry its own relative schedule and produce a full set of absolute dates
at the start of each quarter.

## What Changes

- New subcommand `generate-due-dates`. It reads a per-term TOML file (quarter
  start and end, time zone, default due time, non-instructional days) and a
  table of relative due dates from `course_settings.toml`, computes absolute
  `unlock_at` / `due_at` / `lock_at` values, and writes them into the existing
  `due_dates` array. It shows a per-entry diff (real changes in yellow), asks
  for confirmation, and has a `--noop` mode that changes nothing.
- New `[relative_due_dates]` section in `course_settings.toml`: shared settings
  (class days, whether class meets on non-instructional days, default unlock
  and lock offsets) plus one or more named tables of items. A term file (or
  `--table`) chooses which table to use, so an 11-week quarter and an 8-week
  summer quarter can share one file.
- Date arithmetic is an exact copy of MikesGradingTool's behavior (four
  anchors: `START_OF_QUARTER`, `FIRST_CLASS_OF_QUARTER`, `NO_DUE_DATE`,
  `ASSIGNMENT`; four offsets: `CALENDAR_DAY`, `CLASS_DAY`,
  `NEAREST_CALENDAR_DAY`, `ABS_TIME`), with results memoized and the input
  offsets never mutated.
- Lock and unlock dates are expressed as offsets from the item's own due date
  (`unlock_offset`, `lock_offset`, with `unlock_relative_default` and
  `lock_relative_default` as section defaults). Values may be a string or a
  list, may be `NONE`, and may include absolute times. With no rule the field
  is `KEEP`.
- Warnings for relative-table items that match no content file, and for
  content files (assignment, discussion, quiz) listed in neither the relative
  table nor `due_dates`; each is reported once and names the table(s)
  responsible.
- `import` writes an empty `[relative_due_dates.tables.default]` into the new
  `course_settings.toml` and, when it does not already exist, a fully
  commented-out example term file in `course_settings/`.
- **BREAKING (format):** `repo_format.FORMAT_VERSION` goes from 1 to 2. A new
  migration 1 -> 2 adds the empty `[relative_due_dates]` section to existing
  repos. A repo at version 1 is refused by every repo-reading command until
  `upgrade` is run.
- A separate script in `scripts/` reads the grading tool's config (JSON with
  `//` comments) and prints the equivalent relative-due-dates TOML to stdout.
- Housekeeping after the feature is done: delete `NEW_FEATURES.md` and
  `RELATIVE_DUE_DATES.md`; add a TODO.md item to revisit the fixed-distance
  lock/unlock handling.

### Existing features considered

- `due_dates` array (README "Centralized due dates"): already holds absolute
  `unlock_at` / `due_at` / `lock_at`, sentinels (`NONE`, `KEEP`,
  `CREATE_NONE_THEN_KEEP`) and `only_if`, and `update` already applies it.
  This change does not replace it; it generates entries for it.
- `update`'s due_dates coverage check already warns about unmatched entries
  and uncovered content. The new command's warnings mirror it, but check the
  relative table and `due_dates` together so a resource missing from both is
  reported once.
- `import` copies absolute dates out of a cartridge into `due_dates`; it has
  no notion of relative dates.
- `list-titles` prints titles with current due dates and is useful for writing
  the relative table but does not compute anything.
- `mv`, `publish`, `prune` and the orphan finders do not deal with dates.

### TODO.md

No existing item describes this feature. A new item is added for the
lock/unlock follow-up. `NEW_FEATURES.md` item 3 is the seed of this change and
is removed when the change is done.

### Core subcommands

- `import`: affected (writes the empty default table and the example term
  file).
- `update`: affected only in that `relative_due_dates` must not count as course
  metadata, so editing it never triggers a course-settings upload; it also
  gains no date logic of its own.
- `mv`: not affected. Relative-table items are keyed by content title, and
  `mv` changes paths, not titles.
- `publish`: not affected. It does not read or write dates.

## Capabilities

### New Capabilities

- `relative-due-dates`: the `[relative_due_dates]` section of
  `course_settings.toml`, the term file, and how relative offsets resolve to
  absolute dates.
- `generate-due-dates-command`: the `generate-due-dates` subcommand: options,
  diff and confirmation, what it writes into `due_dates`, warnings, and the
  `import` output that supports it.

### Modified Capabilities

- `repo-format-version`: format version 2, migration 1 -> 2, and
  `generate-due-dates` joins the commands that refuse a mismatched repo.

## Impact

- New module for the calculation and the command (planned:
  `src/markdown_to_canvas/relative_dates.py`), plus a `generate-due-dates`
  entry in `cli.py`.
- `repo_format.py`: `FORMAT_VERSION = 2`, `_migrate_1_to_2`, entry in
  `MIGRATIONS`. Existing tests that assert version 1 change.
- `toml_write.py`: layout rule for the new `items` arrays.
- `imscc_import.py`: writes the new section and the example term file.
- `sync.py`: `_NON_METADATA_SETTINGS_KEYS` gains `relative_due_dates`.
- `scripts/`: new harvest script.
- Docs: README.md, ARCHITECTURE.md, TODO.md; NEW_FEATURES.md and
  RELATIVE_DUE_DATES.md removed at the end.
- No Canvas API calls and no manifest layout changes. Manifests only receive
  the new version stamp through `upgrade`.
