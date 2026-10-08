# Design

## Context

See proposal.md (Why). Lock dates are computed in `relative_dates.py`:
`_Calculator._lock_field(item, "lock_at", due)` picks the rule (item, table,
section), returns `KEEP` for no rule, `NONE` for a `NONE` rule, `KEEP` plus a
warning for an offset rule without a due date, and otherwise applies the
offsets and `default_lock_time`, returning an ISO string. Shared settings are
listed in `_SETTING_KEYS` and layered section -> table by `_load_settings()`
into `TableSettings`. `generate_due_dates.plan_generation()` turns the
`Calculation` into per-entry changes, applies the `dont_reschedule_dates_before`
cutoff per field, and `render_plan()` prints the cutoff line, the diff, the
kept-resources line (list under `--verbose`) and notices.

Format 9 set the precedent for this kind of addition: `CUTOFF_HELP` in
`relative_dates.py` is used both by `import` (`_RELATIVE_DUE_DATES_HELP`) and by
migration 8 -> 9 (`_with_new_settings()` in `repo_format.py`, which inserts
text after the `[relative_due_dates]` header, handles the subtables-only and
no-section cases, and re-parses to check nothing else changed).

## Goals / Non-Goals

**Goals:**
- One setting that caps every generated lock date at the end of the term.

**Non-Goals:**
- Clamping lock dates that `generate-due-dates` does not write (`KEEP`), or
  hand-written lock dates in `due_dates` during `update`.
- Clamping `unlock_at`, or making the clamp time configurable.
- Lock rules measured from other anchors (the broader TODO.md item).

## Decisions

Confirmed by the user in the explore conversation: 1, 2, 3, 6 and the summary
wording in 5. Decision 4 and the counting rules in 5 were not discussed; see
Open Questions.

1. **Key and placement.** `clamp_lock_at_to_last_day_of_term` joins
   `_SETTING_KEYS`, so `_check_keys` accepts it at section and table level and
   `_load_settings()` layers it like `class_on_noninstructional_days` (bool,
   error otherwise). New `TableSettings` field, default False.

2. **What is clamped.** End of term = `datetime.combine(term.last_day,
   time(23, 59))` in the term's zone. Computed dates later than that become it.
   A `NONE` rule becomes it, with or without a due date (the `NONE` branch
   already runs before the no-due-date check). `KEEP` is untouched. Virtual
   items never reach `_lock_field`.

3. **Order.** The clamp runs last in `_lock_field`, after `default_lock_time`
   and `ABS_TIME`, so it compares the value that would otherwise be written.
   Since due dates cannot fall after `last_day` (the out-of-term check stops
   the run first), a clamped lock is never before its due date. The existing
   unlock/due/lock order check in `plan_generation` still applies.

4. **Where the cause is recorded.** `_lock_field` records each clamp on the
   `Calculation` (item name, type, cause `"later"` or `"NONE"`), next to its
   existing `warnings`. `plan_generation` copies into `GenerationPlan` only the
   clamps whose `lock_at` field was not kept by the cutoff, and `render_plan`
   prints the line after the kept-resources line, with the list under
   `--verbose`. Alternative: re-derive the clamp in `generate_due_dates` by
   comparing values with the end of term. Rejected: a computed date that
   happens to equal `last_day` 23:59 without clamping would be miscounted, and
   the `NONE` case would be invisible.

5. **Summary line.** Format:
   `N lock dates set to the term's last day (<format_cutoff(end)>): A were later, B was/were NONE`,
   omitting a zero part. `rd.format_cutoff()` already prints a datetime with
   weekday, 12-hour time and zone abbreviation. Unchanged clamped entries are
   counted, so the line explains a lock date that is not "+7 days" even on a
   run with no diff. Cutoff-kept fields are not counted.

6. **Format 13 and migration.** `FORMAT_VERSION = 13`. A `CLAMP_HELP` block
   (comment plus `# clamp_lock_at_to_last_day_of_term = true`) lives in
   `relative_dates.py` and is used by both `import` and migration 12 -> 13. The
   migration generalizes or reuses `_with_new_settings()`'s header-finding and
   insertion logic (directly after the header; subtables-only and no-section
   cases; parsed TOML must be unchanged). Manifests are stamped as in every
   migration.

## Risks / Trade-offs

- [The clamped value looks like an arbitrary date in the diff] -> The summary
  line and `--verbose` list explain it.
- [A user expects `KEEP` fields to be clamped too] -> The import comment and
  README say items with no lock rule are left as they are.
- [Older tool on an upgraded repo] -> The format bump makes it refuse with the
  existing newer-version error, instead of an "unknown key" error.

## Canvas API behavior

None. `generate-due-dates` writes only `course_settings.toml`; `update` sends
`lock_at` as it already does.

## Migration Plan

`upgrade` applies 12 -> 13. A version-12 repo works with the new tool only
after `upgrade` (the existing version check). No rollback beyond git.

## Open Questions

- Decision 4 (recording clamps in `Calculation`) is an implementation choice
  that was not discussed. The specs do not depend on it.
- Decision 5's counting rules (unchanged entries counted; cutoff-kept fields
  not counted) were not discussed. They are in the spec; changing them would
  change two scenarios but not the approach or tasks.
- Migration placement directly after the header follows 8 -> 9 and was not
  discussed.
