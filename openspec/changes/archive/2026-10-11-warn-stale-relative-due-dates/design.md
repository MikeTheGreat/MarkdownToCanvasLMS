# Design

## Context

See proposal.md (Why). The relevant current code:

- `relative_dates.py` owns `[relative_due_dates]`: `SECTION_KEY`, the allowed
  section keys (`_SECTION_KEYS`) and table keys (`_TABLE_KEYS`), and
  `load_tables`, which rejects unknown keys. `update` and `publish` never call
  `load_tables`; only `generate-due-dates` (and `cp`) parse the section.
- `generate_due_dates.plan_generation` reads `course_settings.toml` once into
  `plan.source_text` and builds a `GenerationPlan`. `apply_plan` re-parses that
  text with tomlkit, edits `due_dates`, and writes the file, refusing if the file
  changed since the plan was made.
- `cli._write_generated_dates` returns early with "Nothing to change" when
  `plan.has_changes` is false, and otherwise confirms and calls `apply_plan`.
  After it returns, `generate_due_dates_cmd` exits with status 1 (`die`) when
  `plan.errors` or `plan.placeholder_errors` is non-empty. So today dates can be
  written and the run still fail.
- `sync._section_hash` already computes a canonical-JSON SHA-256 (truncated to
  16 hex digits) for course-settings sections, and
  `_NON_METADATA_SETTINGS_KEYS` already excludes `relative_due_dates`, so a new
  key there does not make course settings look stale to `update`.
- `update` prints its due-dates output in `sync._phase_due_dates` (full,
  `--noop` and `--check-as-new-course` runs go through `run_sync`) and in
  `run_targeted_sync` (`-t`/`-s`, coverage check only). Its final status lines
  are printed in `cli.py`'s update command; the `--noop` and
  `--check-as-new-course` error branches call `sys.exit(1)` right after their
  line.
- `publish.run_publish` checks virtual due dates, stages, builds, and prints
  "Built static site: ...". It never contacts Canvas.
- `repo_format.FORMAT_VERSION` is 14. Format 9 and 13 were bumped for the same
  reason this change needs a bump: new keys in `[relative_due_dates]` that an
  older tool rejects.

No Canvas API behavior is involved.

## Goals / Non-Goals

**Goals:**
- One function, shared by `update`, `publish` and `generate-due-dates`, decides
  the fingerprint and whether to warn, so the three cannot disagree.
- The fingerprint is recorded only when `generate-due-dates` has actually
  brought `due_dates` in line with the table.

**Non-Goals:**
- Detecting changes to the term file.
- Detecting hand edits to `due_dates`.
- Telling the user which items' dates would change (that is
  `generate-due-dates --noop`).
- Making `update` refuse to run, or regenerate dates itself.

## Decisions

These were confirmed by the user in the explore conversation.

1. **Fingerprint, not timestamps.** Both tables live in one file, so file mtimes
   cannot tell them apart. Recomputing the dates inside `update` was rejected: it
   needs the term file on every run and warns permanently about deliberate hand
   overrides in `due_dates`.
2. **What the fingerprint covers.** The whole parsed `[relative_due_dates]`
   section except `last_generated_hash`: all tables (not only the one used) and
   `dont_reschedule_dates_before`. It is computed from parsed values, so comments
   and formatting do not affect it. `due_dates` and the term file are not part
   of it.
3. **Key name and place.** `last_generated_hash`, a key at the top level of
   `[relative_due_dates]`.
4. **When it is recorded.** On every clean `generate-due-dates` run, including
   "Nothing to change" runs. A run with nothing to change writes the fingerprint
   alone, without asking. It is not recorded on `--noop`, when the user
   declines, or when the run fails (including runs that write dates and then
   exit with status 1).
5. **Missing fingerprint.** Treated as changed, with its own message that says
   no fingerprint is present.
6. **Only for courses that use relative dates.** The check runs only when some
   table has at least one item. `import` and the format-9 migration give every
   repo an empty default table, so without this rule every course would warn.
7. **Where and how often.** `update` (all modes) and `publish`. Printed with the
   due-dates output and again after the final status line. Wording as in the
   `stale-relative-due-dates-warning` spec.
8. **Format bump 14 to 15.** The migration records the new version and does not
   write a fingerprint, so existing repos warn until `generate-due-dates` runs.
9. **Term file not covered.** Documented in the README as a limitation.

## Risks / Trade-offs

- [Edits that do not change any date still warn, e.g. editing an unused table or
  moving the cutoff] → Running `generate-due-dates` finds nothing to change and
  records the fingerprint, which clears the warning without a prompt.
- [Term file edits (a new holiday) are not detected] → README states it; the
  user runs `generate-due-dates` after editing the term file.
- [Writing the key with tomlkit could put it in the wrong place when
  `[relative_due_dates]` has subtables, or when the section exists only as an
  implicit super-table (only `[relative_due_dates.tables.default]` headers)] →
  Tests for both layouts; after writing, re-parse and check that the parsed
  section equals the old one plus the key and that nothing else in the file
  changed. Migration 8 -> 9's `_insert_in_relative_section` is a fallback for
  the implicit-header case.
- [A user copies `last_generated_hash` between courses along with the table]
  → The fingerprint is a function of the section only, so a copied table with
  the copied hash is genuinely in sync with itself; the other course's
  `due_dates` may not be. This is the same limitation as hand-edited
  `due_dates` (non-goal).
- [Warning fatigue on a repo that never runs `generate-due-dates` but has items
  in its table, e.g. tables harvested from MikesGradingTool and not used yet] →
  Accepted; one clean `generate-due-dates` run silences it, and an unused table
  can be emptied.
- [The `--noop` / `--check-as-new-course` error branches exit right after their
  status line] → The second warning must be printed before `sys.exit(1)`.

## Migration Plan

- `FORMAT_VERSION = 15`; add `_migrate_14_to_15` to `MIGRATIONS`. It changes no
  repo content and returns one "Record format version 15 in <manifest>" line
  per manifest, like `_migrate_11_to_12`.
- Users run `upgrade` once per course, then `generate-due-dates` once in each
  course whose tables have items.
- Rollback: an older tool refuses a format-15 repo with its "newer format"
  error. Deleting `last_generated_hash` and setting `format_version = 14` by hand
  restores a repo for an older tool.

## Open Questions

These were not confirmed by the user. Each has a proposed default that does not
change the specs or the task breakdown.

- **Colour.** Print both warnings in yellow (`click.secho(..., fg="yellow")`),
  like the `generate-due-dates` change lines. In `sync.py` and `publish.py`,
  which print with `print()`, the warning would still go through click so the
  colour is dropped when output is not a terminal.
- **Hash function and length.** Reuse `sync._section_hash` (canonical JSON,
  `sort_keys`, `default=str` for TOML dates and times, SHA-256, first 16 hex
  digits), moved to a module both `sync.py` and `relative_dates.py` can import
  without the lazy-import workaround. 16 hex digits is enough to detect edits;
  this is not a security boundary.
- **Comment in the file.** Write a one-line comment above the key, e.g.
  `# Written by generate-due-dates; do not edit.`, only when the key is first
  added.
- **Message for a fingerprint-only write.** For example:
  `Recorded last_generated_hash in [relative_due_dates]; due_dates already matches.`
- **Upgrade hint.** Whether `upgrade` 14 -> 15 should print a NOTICE line, for a
  repo whose tables have items, saying to run `generate-due-dates` to record the
  fingerprint. Proposed: yes; it explains the warning the user will see next.
- **Where the check function lives.** Proposed: `relative_dates.py`
  (`fingerprint(section)` and `stale_warning(settings) -> str | None`), since that
  module owns the section's keys.
