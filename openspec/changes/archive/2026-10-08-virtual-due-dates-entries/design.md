# Design

## Context

See proposal.md for the motivation and specs/ for the required behavior. This
change builds on `virtual-relative-due-dates` (archived 2026-10-08, format 11).

Relevant current code:

- `relative_dates._Calculator.compute` appends `(name, aware datetime)` for
  each virtual item to `Calculation.virtual_dates` and produces no
  `ComputedDates` row for it. Ordinary due dates are formatted by
  `_Calculator._format`.
- `generate_due_dates.plan_generation` builds `EntryChange`s from
  `calculation.dates` only, matching entries with `_find_entry` /
  `_matches_entry` (name, plus type when both have one). `_new_row` writes
  `name`, optional `type` and the three date keys. `render_plan` prints a
  `--verbose`-only virtual list from `GenerationPlan.virtual_dates`.
  `_after_plan` builds the post-run `due_dates` for the placeholder check.
- `sync.load_due_dates` returns the raw list; `filter_due_dates_by_flags`
  applies `only_if` and raises `ValueError` for bad conditions, which the CLI
  reports with `die()`. It is called by `run_sync` (full, noop and
  new-course runs), the targeted sync, `list-titles` (`sync.py:2269`) and
  `publish.stage`.
- `sync.find_due_date_override` is the one matcher behind the dates pass
  (`_apply_due_dates_only`), the full-upload paths (assignment, discussion,
  quiz) and `list-titles`. `_check_due_dates_coverage` has its own matching
  loop for the "did not match any content file" warning.
- `date_placeholders.find_entry` matches name and, with a type filter, entries
  of that type or none. `cp._warn_unresolvable_placeholders` repeats that rule
  against the destination's `due_dates`.
- Nothing validates the keys of `due_dates` entries today.

No Canvas API behavior is involved. Virtual entries are filtered out before any
code that talks to Canvas sees them.

## Goals / Non-Goals

**Goals:**
- One validation function for virtual entries, called by every command that
  reads `due_dates` for its own use.
- Virtual entries kept out of Canvas by the single matcher
  (`find_due_date_override`) rather than by filters at each call site.
- Placeholder resolution unchanged apart from the type filter.

**Non-Goals:**
- `unlock_at` / `lock_at` on virtual entries (user: not now).
- Removing virtual entries the table no longer produces (user: do not remove).
- Generated week anchors (TODO.md item stays).
- Any change to how `import` writes `due_dates`; Canvas exports no virtual
  dates.

## Decisions

Confirmed by the user:

- The concept is called "virtual" and the key is `virtual = true` on a
  `due_dates` entry, the same key as on relative-table items. `type =
  "virtual"` was considered: `update`'s matcher would have ignored it for free,
  but it gives `type` two meanings and differs from the relative table.
- Hand-written virtual entries are allowed.
- `generate-due-dates` writes `due_at` as a full datetime, formatted with the
  same `_Calculator._format` as ordinary due dates, so the stored text looks
  like every other entry's.
- `generate-due-dates` does not remove virtual entries the table no longer
  produces; they go to the existing leftover notice.
- Virtual entries are listed with the other added/changed/unchanged entries;
  the `--verbose` virtual list and `GenerationPlan.virtual_dates` are removed.
- A virtual entry may have only `name`, `virtual`, `due_at` and `only_if`;
  `unlock_at`, `lock_at` and `type` are errors.
- A virtual entry named like an assignment, discussion or quiz is an error in
  `update`, `publish` and `generate-due-dates`, and these errors stop the run
  like other `due_dates` configuration errors.
- `repo_format.FORMAT_VERSION` goes from 11 to 12.

Implementation approach (follows from the confirmed decisions; listed so the
reviewer can object):

- **Validation function.** A new `sync.check_virtual_due_dates(due_dates,
  repo_path, matcher)` (next to `filter_due_dates_by_flags`) collects every
  problem and raises one `ValueError` listing them, so callers that already
  turn `ValueError` into `die()` need no new handling. It runs on the raw list,
  before `filter_due_dates_by_flags`. The content-title check uses
  `iter_gradeable_content` with the repo's ignore matcher, which reads every
  gradeable file's frontmatter once more per run; `_check_due_dates_coverage`
  already does the same scan, so the cost is one extra pass over frontmatter.
  It is skipped when no entry is virtual. Callers: `run_sync` and the targeted
  sync, `list-titles`, `publish.stage` (before staging), and
  `generate_due_dates.plan_generation` (which reports it as a
  `RelativeDueDatesError`, the error type that command already prints).
- **Canvas matching.** `find_due_date_override` skips entries whose `virtual`
  is `True`. That one change covers the dates pass, full uploads and
  `list-titles`. `_check_due_dates_coverage` skips virtual entries in its
  first loop. A virtual entry never matches content, so the "was removed"
  notice in `_apply_due_dates_only` cannot be triggered by one.
- **Calculation output.** `ComputedDates` gains `virtual: bool = False`, and
  `compute()` emits a row for a virtual item with `due_at` formatted and
  `unlock_at` / `lock_at` empty strings that nothing reads. The archived design
  rejected a flag on `ComputedDates` because consumers had to filter it; now
  every consumer (`plan_generation`, `_new_row`, `render_plan`, `_after_plan`)
  must handle virtual rows anyway, so a flag on the row is the simpler shape.
  `Calculation.virtual_dates` is removed. `_lock_field` is still not called
  for a virtual item.
- **Entry matching in generate.** `_matches_entry` takes the virtual flag:
  a virtual item matches only entries with `virtual is True`, an ordinary item
  only entries without it. Before building changes, `plan_generation` checks
  the cross-kind name clashes (virtual item vs ordinary entry, ordinary item
  vs virtual entry) and raises `RelativeDueDatesError` listing each, so nothing
  is shown or written. For a virtual row only `due_at` is compared, kept by the
  cutoff, and written; the inconsistency check cannot fire because there is
  only one field.
- **New row.** `_new_row` writes `name`, `virtual = true`, `due_at` for a
  virtual change. `toml_write` lays out inline rows by key; `virtual` must be
  added to its known key order for `due_dates` if it has one (checked during
  implementation).
- **Display.** `EntryChange.label` appends ` (virtual)` for a virtual entry;
  an added virtual entry prints only `due_at`.
- **Title warnings.** `title_warnings` keeps using ordinary items for (a) and
  (b); `in_due_dates` ignores virtual entries; the leftover computation treats
  a virtual entry as produced only by a virtual item of the same name.
- **Placeholders.** `find_entry` excludes virtual entries when a type filter is
  given; `cp._warn_unresolvable_placeholders` applies the same rule. Without a
  type filter both kinds match, so a virtual and an ordinary entry with the
  same name would be ambiguous; the validation rule that forbids that pairing
  keeps this from arising.
- **Format version.** `_migrate_11_to_12` stamps the manifests only, like
  `_migrate_10_to_11`. Tests asserting the literal version move to 12.
- **import help text.** `_RELATIVE_DUE_DATES_HELP` currently says a virtual
  item is "never written to due_dates"; it is reworded to say it is written as
  a `virtual = true` entry that placeholders can quote and `update` never sends
  to Canvas.

## Risks / Trade-offs

- [Hand-written virtual entries appear in `generate-due-dates`' leftover notice
  on every run] → The same is true of hand-written ordinary entries today. The
  table's `ignore` list silences the notice for a name; README says so.
- [A repo that used the pre-feature workaround has an ordinary
  `Start_of_week_3` entry; after the item becomes virtual, generate stops with
  the cross-kind clash error] → The error names the entry and says to delete it
  (or add `virtual = true` and remove its `unlock_at`/`lock_at`/`type`).
- [The default placeholder format prints a time ("by 11:59 PM"), which reads
  oddly for a week start] → README example for virtual dates uses `format=`.
  Not changed in code.
- [Validation re-reads every gradeable file's frontmatter] → Skipped when there
  are no virtual entries; otherwise one extra pass, the same scan the coverage
  check already does.

## Migration Plan

`upgrade` takes a version-11 repo to 12 with no content change. The next
`generate-due-dates` run adds a virtual entry for each virtual item. Rollback
means reverting the tool and removing virtual entries and the version by hand;
not supported by a command.

## Open Questions

These were not confirmed in conversation. Each is written into the specs as
shown; a different answer changes the named spec and the matching task.

1. Should virtual entries be validated regardless of `only_if` (specified),
   or only those that survive the run's flags? (virtual-due-dates spec,
   "Virtual due_dates entries")
2. Is a sentinel (`NONE`, `KEEP`, `CREATE_NONE_THEN_KEEP`) or empty `due_at`
   on a virtual entry an error at load time (specified), or only when a
   placeholder quotes it?
3. A virtual entry may not share its name with an ordinary entry, but two
   virtual entries may share one (specified), to allow different `only_if`
   conditions.
4. In `generate-due-dates`, a virtual item whose name is an ordinary entry's
   (or the reverse) stops the run with an error (specified), rather than
   converting the entry.
5. `dont_reschedule_dates_before` applies to a virtual entry's `due_at`
   (specified), so text quoting a past week start keeps the date students saw.
6. A placeholder with `type=` never matches a virtual entry (specified).
7. `list-titles` also runs the validation (specified); the user named only
   `update`, `publish` and `generate-due-dates`.
8. Label text for a virtual entry in the generate listing: `Name (virtual)`.
