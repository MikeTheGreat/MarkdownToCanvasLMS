# Design

## Context

See proposal.md for motivation. Current state that shapes the approach:

- `due_dates` is a top-level inline array in `course_settings.toml`. `update`
  reads it (`sync.load_due_dates`), applies `only_if`
  (`filter_due_dates_by_flags`), and sends only changed dates. It also has a
  title-based coverage check (`_check_due_dates_coverage`,
  `find_due_date_override`) that the new warnings mirror.
- Generated TOML is written through `toml_write` (tomlkit). Layout depends on
  the key: keys in `INLINE_TABLE_ARRAY_KEYS` are inline arrays of inline
  tables, any other list of dicts becomes `[[table]]` blocks. `mv.py` already
  edits `course_settings.toml` in place with tomlkit while preserving comments
  and array formatting.
- `sync._NON_METADATA_SETTINGS_KEYS` lists top-level keys that are not Canvas
  course metadata. Any other top-level key counts as metadata and would trigger
  a course-settings upload when it changes.
- `repo_format.py` holds `FORMAT_VERSION = 1`, the `MIGRATIONS` registry
  (`_migrate_0_to_1`), `run_upgrade`, and `check_repo_format`, which every
  repo-reading operation calls.
- `find-local-orphans` never scans `course_settings/` (`local_orphans.py`
  excludes it), so an extra file there is not reported as an orphan.
- The calculation to copy is `calculateDueDate` /
  `apply_offsets_to_due_date` in MikesGradingTool's `CanvasHelper.py`. It
  uses `pytz`, does its date arithmetic on timezone-aware datetimes, and
  mutates the offsets list for `FIRST_CLASS_OF_QUARTER`.
- Confirmation convention for commands that change local files or Canvas:
  `click.confirm`, with a non-terminal stdin failing unless `--yes`
  (`clean-manifest --apply` in `cli.py`).

## Goals / Non-Goals

**Goals:**
- One command that fills `due_dates` from a relative schedule and a term file.
- The relative schedule lives in the course repo, in one section, with named
  tables so one repo serves quarters of different length.
- Same dates as the grading tool for the same inputs, except the daylight-saving
  difference described below.
- Existing `update` behavior with `due_dates` is unchanged.

**Non-Goals:**
- Reading dates back from Canvas, or changing anything on Canvas.
- Course flags or `only_if` inside the relative table (`only_if` stays on
  `due_dates` and is applied by `update`).
- Sections with different term lengths in one repo: `due_dates` is a single
  array shared by every section, so one run yields one set of dates. Document
  as a limit.
- An AI skill to build a relative table from existing dates (tabled).
- Converting the grading tool's config inside the tool; a standalone script
  does that.

## Decisions

Each item below was confirmed by the user unless it appears under Open
Questions.

1. **A separate command that writes into `due_dates`.** `generate-due-dates`
   is its own subcommand, so it can't be triggered by another command. The
   relative table is an addition to `due_dates`, not a replacement, so `update`
   needs no knowledge of offsets. Alternative: have `update` resolve offsets on
   the fly; rejected because users hand-edit `due_dates` after the first run.

2. **All settings in one `[relative_due_dates]` section, with named tables.**
   Shared settings sit at section level and each table may override them.
   Tables live under a `tables` key so a table name can never collide with a
   setting name. A table's `items` are inline-table rows like `due_dates`.
   The term file, or `--table`, picks the table; a single table is used
   automatically. Alternatives: separate files per term length (rejected,
   more files to keep in step), or a `table = "..."` key on every item
   (rejected, repeats names across tables).

3. **Term file is TOML and is a required CLI argument.** The parts that change
   each term (dates, holidays, zone) stay out of the committed course settings.
   The zone is an IANA name so the emitted offset is right on both sides of a
   DST change. Python's `zoneinfo` is used (standard library, so no new
   dependency). Alternative: fixed offset; rejected because a term crosses a
   DST change.

4. **Copy the grading tool's arithmetic, on local dates, with memoization.**
   Offsets are applied to local calendar dates and the zone's UTC offset is
   attached at the end. The grading tool adds `timedelta` to a `pytz`-localized
   value without re-localizing, so after a DST change its due time moves by an
   hour (verified by running it: `23:59 PDT + 60 days` prints as `22:59 PST`; counting
   backwards across the change it is an hour late, so an item due 23:59 on
   Oct 31 came out as 00:59 on Nov 1 in one real course). Comparing all 170
   dates of courses 101, 142 and 143 (tests/test_relative_dates_vs_grading_tool.py)
   found 11 differences, all of exactly this kind.
   The user chose to keep the local time fixed. Results for each item are
   cached by item within a run, and the input offsets are never modified (the
   grading tool inserts into the list for `FIRST_CLASS_OF_QUARTER`, which
   only works there because of its cache). Anchor cycles are detected and
   reported. Alternative: exact copy including the hour shift; rejected by the
   user.

5. **Lock and unlock are offsets from the item's own due date.** `unlock_offset`
   and `lock_offset` take a string or list, allow `NONE` and absolute times;
   `unlock_relative_default` and `lock_relative_default` are the fallbacks;
   `KEEP` is the last fallback. With no due date, warn and write `KEEP`.
   Revisit later (TODO.md item added): a fixed distance from the due date may
   not suit every course.

6. **Writes go through tomlkit edits of the existing document.** The command
   parses `course_settings.toml`, updates or appends rows in the `due_dates`
   array in place, and writes the file back, as `mv.py` does. That keeps
   comments and formatting outside the changed rows. Alternative: rewrite the
   file through `toml_write`; rejected because it would drop comments.

7. **Diff, then confirm; `--noop` prints the diff and stops.** The same
   `click.confirm` / `--yes` / non-terminal rule as `clean-manifest`. Changes
   are printed in yellow using the colour helper the CLI already uses, if one
   exists (see Open Questions).

8. **Warnings check the relative table and `due_dates` together.** A resource
   missing from both is reported once and names both. `ignore` lists titles
   that are intentionally absent (for example items that only exist in an
   11-week quarter). Leftover `due_dates` entries from another table are
   reported, never removed.

9. **`FORMAT_VERSION` becomes 2.** The user chose to bump although the new
   section is additive. Migration 1 -> 2 appends the empty default table (and
   stamps manifests), so repos match what `import` now writes. Older repos are
   refused by every repo-reading command until `upgrade` runs, including
   `generate-due-dates`.

10. **`relative_due_dates` joins `_NON_METADATA_SETTINGS_KEYS`** so editing it
    never triggers a course-settings upload. Verified in `sync.py`: keys not
    listed count as metadata.

11. **`import` writes the scaffolding.** An empty default table, with the shared
    settings commented out and their allowed values listed, and a commented
    example term file in `course_settings/` if none exists.

12. **A standalone harvest script in `scripts/`** reads the grading tool's
    config (JSON with `//` comments) and prints the equivalent table to
    stdout. It is not part of the installed tool.

Canvas API behavior: the design depends on none. The command never contacts
Canvas. Operations that overwrite content overwrite only the local `due_dates`
rows, guarded by the diff, the confirmation, `--noop`, and the non-terminal
`--yes` rule. `update` afterwards sends dates to Canvas exactly as it does for
hand-written `due_dates`; that path is unchanged and already documented.

Manifest format: unchanged. Manifests are stamped with version 2 by
`upgrade` (and by new manifest creation) through the existing mechanism.

## Risks / Trade-offs

- [DST differs from the grading tool] -> The comparison test expects equality
  for dates before the change and a one-hour difference for later dates,
  stated in the test.
- [The comparison test needs the grading tool's output] -> Record expected
  results in a fixture rather than importing the grading tool (see Open
  Questions).
- [Re-running overwrites hand edits of items in the table] -> The diff lists
  every overwrite; the user must confirm; `--noop` previews.
- [Bumping the format version makes every repo run `upgrade` once] -> The
  migration is a small append; the older-tool message already says what to do.
- [A term file with the wrong zone or start date writes wrong dates to many
  entries] -> The diff is shown first and nothing is written without
  confirmation.
- [`CLASS_DAY` has edge cases, for example a start date that is not a class
  day] -> Cover those cases in tests derived from the grading tool's results.
- [Sections of one repo can't have different term lengths] -> Document the
  limit.

## Migration Plan

1. Ship `FORMAT_VERSION = 2`, migration 1 -> 2 and tests for it.
2. Users run `upgrade` once per repo; it adds the empty default table.
3. To adopt: fill in a table (by hand or with the harvest script), write a
   term file, run `generate-due-dates --noop`, then the real run, then `update`.
Rollback: revert the tool; a version-2 repo is refused by an older tool with a
message to update it, so a repo needs `format_version` set back by hand to
run on the older tool. The added section is ignored by older code apart from
the version check.

## Open Questions

These were not confirmed and are assumptions carried into the specs and tasks:

- Name and location of the example term file: assumed
  `course_settings/term_dates.toml`.
- Names of the term-file keys: assumed `first_day`, `last_day`, `time_zone`,
  `default_due_time`, `noninstructional_days` (each with `title`, `date`) and
  `relative_table`. The grading tool's own names differ
  (`date_of_first_day_of_the_quarter` and so on).
- Shape of item rows: assumed inline tables with `relative_to = { type = ...,
  assignment_name = ... }` as in the grading tool's JSON, with `items` added to
  `toml_write.INLINE_TABLE_ARRAY_KEYS`.
- How a list of lock/unlock offsets combines: assumed to apply in order from
  the due date, the same as `offsets`, with `NONE` allowed only alone.
- `generate-due-dates` writes only `due_at`, `unlock_at` and `lock_at`, keeps
  every other key of an existing entry, and appends new entries at the end of
  `due_dates`.
- The command does not evaluate `published_if` or course flags when deciding
  which content to warn about (the relative table has no flags); `ignore`
  covers intentionally absent items.
- The repo path is resolved like other commands (`_resolve_repo`); the term
  file path is resolved against the current directory.
- The comparison test with the grading tool uses expected values recorded once
  from the grading tool into a fixture, so the test suite does not depend on
  the other repo or on `pytz`.
- Whether the CLI has an existing colour helper for the yellow diff or this
  needs `click.style`; either is acceptable.
- The migration does not create the example term file.
- Differences from the grading tool found while implementing, beyond the
  daylight-saving one the user chose: `-N CLASS_DAY` goes to the previous class
  day (the original only does with one or two class days a week; none of the
  user's courses use a negative class-day offset); `days_of_week` is sorted into
  week order (the original sorts with Sunday first, which is the same cycle);
  an item anchored to an item with no due date is an error for the whole run
  (the original reports an error for that one item and continues); unknown
  keys, unreadable offsets and bad day abbreviations are errors.
- Term-file dates and times are accepted either as TOML dates/times or as
  strings.
- The standard-library `zoneinfo` needs a time zone database, which Windows
  does not have; the `tzdata` package is therefore a dependency on every
  platform (small, pure Python, and harmless where the OS already has one).
- `generate-due-dates` fixture: 142s and 143s (the summer courses) and 115
  could not be used for the comparison because their config inherits from
  another course or has dangling references, so the comparison covers 101, 142
  and 143.
