# Design

## Context

See proposal.md for the motivation and the specs for the required behavior.

How the code works today:

- `generate_due_dates.plan_generation()` loads `course_settings.toml` with
  `tomllib`, loads the term file (`relative_dates.load_term`), selects a table
  (`load_tables` / `select_table`), runs `relative_dates.calculate()`, and
  compares each computed item with its `due_dates` entry field by field
  (`_same_value`). The result is a `GenerationPlan` of `EntryChange`s (`added`,
  `changed`, `unchanged`). `render_plan()` turns the plan into lines, and
  `apply_plan()` writes the `changed` fields and the `added` rows with
  tomlkit, refusing if the file changed since planning.
- `cli.generate_due_dates_cmd` prints the plan, handles `--noop`, `--yes` and
  the confirmation prompt, and calls `apply_plan`. The command has no
  `--verbose` option today.
- `relative_dates.load_tables()` rejects any key in `[relative_due_dates]` not
  in `_SECTION_KEYS`, and any key in a table not in `_TABLE_KEYS`.
  `_TABLE_KEYS` is built from `_SETTING_KEYS`, so the new key must go into
  `_SECTION_KEYS` only, not `_SETTING_KEYS`. That is how a table setting it
  becomes an unknown-key error.
- `import` writes the shared settings as commented-out lines in the
  `_RELATIVE_DUE_DATES_HELP` block (`imscc_import.py`). That block is attached
  to the `[relative_due_dates]` table by `toml_write.add_comment_text`.
- `repo_format.FORMAT_VERSION` is 8. `check_repo_format` refuses a repo whose
  version is lower or higher than the tool's.

## Goals / Non-Goals

**Goals:**

- All of the cutoff logic lives in the planning step, so `--noop`, the
  confirmation prompt and `apply_plan` all see the same decisions.
- `apply_plan` keeps its current shape. A kept field is simply absent from
  `EntryChange.fields`, so it is never written.

**Non-Goals:**

- No change to `update`, the manifest, or the `resolved_dates` cache.
- No command-line override for the cutoff (in TODO.md).
- No consistency check on entries without kept fields. If the generator itself
  produces `unlock_at` after `due_at`, that is a separate, existing issue.

## Decisions

These were confirmed by the user in the explore session (2026-10-03).

1. **The cutoff is applied in `generate-due-dates`, not `update`.** Leaving the
   toml unchanged for past fields keeps `due_dates` an accurate record of what
   is on Canvas. `update` already sends only entries whose resolved dates
   changed. The alternative, filtering in `update`, would leave the toml and
   Canvas disagreeing.
2. **The key is `dont_reschedule_dates_before` in `[relative_due_dates]`,
   section-wide.** It describes when the current term is, not a schedule, so
   it is not a per-table setting.
3. **Value forms.** The key accepts only `"YYYY-MM-DD"` (end of that day) and
   `"YYYY-MM-DD HH:MM"`, read in the term file's `time_zone`. `""` means no
   cutoff. Everything else is an error.
4. **The comparison is `<=`.** A date equal to the cutoff is protected, so the
   tool errs toward leaving dates alone.
5. **Out-of-term cutoff is an error, raised before any date is computed.** This
   catches a cutoff left over from an earlier term. Since the comparison is
   against current `due_dates` values, which then all hold the earlier term's
   dates, a stale cutoff would otherwise freeze much or all of the new term.
6. **Per-field decision based on the current value.** A field is kept when its
   current value is a date at or before the cutoff. A field whose current value
   is after the cutoff is written even if the new date is earlier. New entries
   are written in full.
7. **Inconsistent entries are errors.** The whole entry is left unchanged, the
   others are written, the error is printed before the prompt, and the exit
   status is non-zero.
8. **Output.** The cutoff line is always printed. The kept-resources count line
   prints whenever the count is at least one, including runs with nothing else
   to change. `--verbose`/`-v` lists the resources one tab in, with their kept
   fields. `--noop` shows the same output.
9. **`import` and upgrading existing repos.** `import` writes
   `# dont_reschedule_dates_before = "YYYY-MM-DD"` commented out. The format
   version goes from 8 to 9, and a migration adds the same line to existing
   repos.

Folded in later the same day (confirmed 2026-10-03):

10. **Default unlock and lock times are named `default_unlock_time` and
    `default_lock_time`**, matching the term file's `default_due_time`.
11. **They are shared settings a table may override**, like `days_of_week`.
12. **`import` and the migration write real values**, `"00:00"` and `"23:59"`,
    not commented-out lines.
13. **An explicit time wins.** The default applies only when the item's own
    `offsets` have no `ABS_TIME` and the unlock or lock rule has no
    `ABS_TIME`. Otherwise the current behavior stands: the date inherits the
    due date's time, and a rule's `ABS_TIME` sets it.

### Implementation approach

- **Parsing (`relative_dates.py`).** Add a function that reads the key from the
  section, together with the loaded term, and returns an aware `datetime` or
  `None`. Use a strict regex for the two forms, then build the datetime with the
  term's `ZoneInfo`. A date-only value becomes `23:59:59`. Validate it against
  `datetime.combine(first_day, 00:00)` .. `datetime.combine(last_day,
  23:59:59)` in the same zone. Raise `RelativeDueDatesError` with the messages
  the spec requires. `plan_generation` calls it right after `load_term` and
  before `calculate`, so an error stops the run before any computation.
- **Planning (`generate_due_dates.py`).** For each existing entry, after
  computing `differing`, split it. A field whose current value parses as a
  datetime (naive values localized to the term zone) and is `<=` the cutoff
  moves to a `kept` dict, but only when it would otherwise have changed. Then,
  if both `kept` and the remaining `differing` are non-empty, build the
  resulting values (kept values plus new values), compare the date-valued pairs
  `unlock<=due`, `due<=lock`, `unlock<=lock`, and on a violation record an error
  and mark the entry `skipped` (no fields written). New `EntryChange` data: a
  `kept` field map and a `kind` of `"skipped"`. New `GenerationPlan` data: the
  cutoff (or `None`) and an `errors` list. `has_changes` still counts only
  `added`/`changed`.
- **Rendering.** `render_plan` gains a `verbose` argument. It emits the cutoff
  line first, then the existing lines. Skipped entries' errors are emitted as
  red lines with the changes. The kept-resources summary comes before the
  unchanged count, followed by the verbose list.
- **CLI.** Add `--verbose`/`-v`, using the same declaration as `mv` and `cp`.
  After printing, the existing "Nothing to change" / `--noop` / prompt / apply
  flow runs unchanged. At the end, when `plan.errors` is non-empty, the command
  exits with status 1 via `die()` or `sys.exit(1)`, after any write or decline.
- **import.** Add the commented line, with a one-line comment, to the
  shared-settings part of `_RELATIVE_DUE_DATES_HELP`.
- **Default times.** `TableSettings` gains `default_unlock_time` and
  `default_lock_time` (`time | None`), loaded with `_parse_time` and layered
  like the other settings. `RelativeItem` records whether its own `offsets`
  contain an `ABS_TIME`. In `_lock_field`, after `_apply(due, rule, ...)`, when
  the setting is set, the item's due time is not explicit, and the rule has no
  `ABS_TIME`, the result's time of day is replaced with the setting. Doing this
  after the offsets is equivalent to doing it before, since no offset depends
  on the time of day.
- **Migration 8 -> 9.** In `repo_format.py`, add `_migrate_8_to_9`, guarded by
  `read_repo_version(state.repo) < 9`. If any line of the `[relative_due_dates]`
  section already mentions `dont_reschedule_dates_before`, it reports that the
  section was left as is. Otherwise it inserts the comment lines directly after
  the section header. Text-level insertion keeps the rest of the file
  byte-identical, which is harder with tomlkit comment items attached to a
  table; the existing `_rename_table_headers` / `_drop_table_block` helpers
  already work on text. The migration then checks that `tomllib` parses the
  result to the same data. It also stamps the manifests. `FORMAT_VERSION = 9`,
  `MIGRATIONS[8] = _migrate_8_to_9`. With the default times folded in, the
  insertion works per item: the commented cutoff block (skipped when the
  section mentions the cutoff), `default_unlock_time = "00:00"` and
  `default_lock_time = "23:59"` (each skipped when the section already sets
  that key), each skip reported. The parse check then compares the data with
  the two added keys removed.

## Canvas API behavior this depends on

- **No Canvas call is made by `generate-due-dates`.** Verified in code: the
  module never imports the Canvas client, and the existing spec requires it.
- **`update` makes no API call for an entry whose resolved dates are
  unchanged.** Verified in code: `sync._apply_due_dates_only` compares
  `resolve_dates_symbolic(override)` with the manifest's `resolved_dates` and
  skips on a match. A fully kept entry is therefore untouched on Canvas.
- **When some fields of an entry change, `update` re-sends every non-sentinel
  date field of that entry, kept ones included.** Verified in code:
  `sync._resolve_date_overrides` puts every dated field into the request. The
  kept value equals what the toml already said, so Canvas normally gets the
  value it already has. See the first risk below for when it doesn't.

No unverified Canvas behavior is relied on. This change adds no operation that
deletes or overwrites Canvas content beyond what `update` already does.

## Manifest format

Unchanged. Migration 8 -> 9 only stamps `_repo_format = 9` in each manifest, as
every migration does.

## Risks / Trade-offs

- [After `upgrade`, the next `generate-due-dates` run on an existing repo moves
  every unlock time from the due time (usually 23:59) to 00:00.] → Intended.
  The diff shows it before anything is written, and unlocks on or before
  `dont_reschedule_dates_before` are kept.

- [A date changed by hand in the Canvas UI, for example a past `unlock_at`, is
  reverted when `update` re-sends the entry because another field of it
  changed.] → This is existing `update` behavior for any partially changed
  entry, and this change does not make it worse. README will mention that
  `due_dates` remains the record `update` enforces.
- [A stale cutoff blocks the next term's generation.] → It is an error, by
  design. The message tells the user to clear or move the key.
- [The `<=` comparison and the end-of-day reading of a date-only value protect
  items due late on the cutoff day.] → Intended. The user can edit those
  entries by hand.
- [A naive date string in `due_dates` (no offset) is compared in the term zone,
  while `update` sends it to Canvas as written.] → Canvas interprets a naive
  date in the user's or course's zone, which may differ. This affects only the
  comparison of hand-written naive entries, and `generate-due-dates` always
  writes offsets. Accepted.
- [Text-level insertion in the migration could misplace the line in an unusual
  layout, such as the section header in a different form.] → The migration
  re-parses the result and, if the data differs, leaves the file unchanged with
  a NOTICE, as `_migrate_relative_tables` does.

## Migration Plan

1. Ship the tool with `FORMAT_VERSION = 9`.
2. The user runs `markdown-to-canvas upgrade` on each course repo. Until then
   every repo-reading command refuses the repo with the existing
   older-version error.
3. Rollback: an older tool refuses a version-9 repo. Reverting means checking
   out the repo's pre-upgrade `course_settings.toml` and manifests from git.

## Confirmed after the proposal

The user confirmed these on 2026-10-03, after the proposal was written:

1. A resource counts as "not rescheduled" only when a kept field's computed
   value differs from its current value.
2. The output wording: `Not rescheduling dates on or before: Thu Oct 1, 2026
   11:59 PM PDT (dont_reschedule_dates_before)`, `Not rescheduling dates: no
   cutoff (dont_reschedule_dates_before is not set)`, `3 resources were not
   rescheduled because of dont_reschedule_dates_before date of …`, and verbose
   rows like `\tWeek 2 Discussion (discussion): unlock_at`.
3. "Inside the term" includes both ends.
4. Sentinel, empty and absent current values are not protected.
5. `HH:MM` accepts any time.
6. `--noop` with an inconsistent entry exits non-zero.
7. The migration puts the line directly after the `[relative_due_dates]`
   header line.
8. A file with no `[relative_due_dates]` section gets a notice instead of a new
   section.

## Found during implementation

Migration 1 -> 2 wrote only `[relative_due_dates.tables.default]`, with no
bare `[relative_due_dates]` header, so many existing repos have the section
only implicitly. Following decision 8 literally, those repos would have
received a notice and no line. Instead, migration 8 -> 9 inserts a
`[relative_due_dates]` header with the commented line before the first
subtable header. The notice is kept for files with no section at all. The
repo-format-version delta spec was updated with a scenario for this case.
