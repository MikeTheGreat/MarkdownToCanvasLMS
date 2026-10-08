# Proposal

## Why

Date placeholders (`[TEXT]{.replace_date_with item="..."}`) resolve only
against `due_dates`, and virtual relative-table items (change
`virtual-relative-due-dates`) are never written there. So text such as "Week 3
begins on ..." cannot quote `Start_of_week_3`. Writing virtual items into
`due_dates` with a `virtual = true` marker lets placeholders quote them while
`update` keeps them away from Canvas.

## What Changes

- A `due_dates` entry may have `virtual = true`. A virtual entry names a date;
  it is not content. Its allowed keys are `name`, `virtual`, `due_at` and
  `only_if`. `unlock_at`, `lock_at` and `type` on a virtual entry are errors.
  `virtual` must be a boolean.
- A virtual entry whose `name` equals the title of an assignment, discussion or
  quiz is an error.
- `update` (including `--noop` and `--check-as-new-course`) and `publish` check
  the virtual entries before doing anything else, and the errors above stop the
  run like other `due_dates` configuration errors.
- `update` never sends a virtual entry's date to Canvas, never matches it to a
  content file, and leaves it out of the "Checking due_dates coverage" warnings.
- Date placeholders resolve against virtual entries in the same way as against
  ordinary ones. This works in `update`, `publish`, `generate-due-dates` and
  `cp` because they all build the placeholder context from `due_dates`.
- Virtual entries may be written by hand. They do not have to come from a
  relative table.
- `generate-due-dates` writes each virtual item of the selected table to
  `due_dates` as a virtual entry with a full datetime `due_at` (the item's
  computed date and time, which is `default_due_time` unless its offsets set a
  time). It adds, changes and reports virtual entries in the same added/changed/
  unchanged listing as ordinary entries, and they count toward whether there is
  anything to write. The separate `--verbose`-only list of virtual dates is
  removed.
- `generate-due-dates` does not remove a virtual entry that the selected table
  no longer produces. It appears in the existing notice of entries not produced
  by the table, as other leftover entries do.
- `generate-due-dates` checks placeholders against `due_dates` as it will be
  after the run, which now includes the virtual entries, so a placeholder naming
  a virtual item resolves.
- **BREAKING** (format): `repo_format.FORMAT_VERSION` goes from 11 to 12. An
  older tool would treat a virtual entry as an ordinary one: it would warn on
  every `update` that the entry matches no content, and a placeholder with
  `type=` could resolve to it. Migration 11 -> 12 only records the new version.

### Existing mechanisms

- Virtual relative-table items (`virtual = true` in
  `[relative_due_dates.tables.<name>].items`, format 11) compute these dates
  already; this change only stores them where placeholders can read them.
- Making the item an ordinary relative-table item writes it to `due_dates` and
  lets placeholders quote it today, but `generate-due-dates` warns that it
  matches no content and every `update` warns that the entry matched no content
  file. This change replaces that workaround.
- `due_dates` entries already carry `type` and `only_if`, and `update` already
  skips an entry whose `type` differs from the content's. Reusing `type =
  "virtual"` was considered and rejected by the user in favor of a `virtual`
  key that matches the relative table.

### TODO.md

Implements "Date placeholders that name virtual relative dates", which is
removed. "`generate-due-dates`: generate week anchors automatically" is not
implemented and stays.

### Core subcommands

- `update`: validates virtual entries, excludes them from Canvas dates and the
  coverage check, and resolves placeholders against them.
- `publish`: validates virtual entries and resolves placeholders against them.
  It sends nothing to Canvas, so it needs no other change.
- `import`: writes no virtual entries (Canvas has none to export). Its
  commented help for `[relative_due_dates]` currently says a virtual item is
  never written to `due_dates`; that paragraph is reworded. It stamps new repos
  with version 12 through `FORMAT_VERSION`.
- `mv`: not affected. It does not read `due_dates`; placeholders name entries by
  title, not by path.

## Capabilities

### New Capabilities

- `virtual-due-dates`: the `virtual` key on `due_dates` entries, which keys a
  virtual entry may have, the content-title collision error, and how `update`,
  `publish` and `list-titles` treat virtual entries.

### Modified Capabilities

- `generate-due-dates-command`: virtual items are written to `due_dates` as
  virtual entries and listed with the other changes; the `--verbose` virtual
  list is removed; leftover and title-warning rules for virtual entries;
  placeholders naming virtual items resolve.
- `date-placeholders`: placeholders may name virtual entries; a `type=` filter
  does not match a virtual entry.
- `repo-format-version`: migration 11 to 12.

## Impact

- `src/markdown_to_canvas/sync.py`: `find_due_date_override`,
  `_check_due_dates_coverage`, a validation call where `update` and the
  targeted sync load `due_dates`.
- A new validation function (location decided in design.md) shared by `update`,
  `publish`, `list-titles` and `generate-due-dates`.
- `src/markdown_to_canvas/generate_due_dates.py`: plan building, `_find_entry`,
  `_new_row`, `title_warnings`, `render_plan`, `GenerationPlan.virtual_dates`.
- `src/markdown_to_canvas/relative_dates.py`: `Calculation.virtual_dates`
  (how the plan receives virtual dates).
- `src/markdown_to_canvas/date_placeholders.py`: `find_entry` type filter.
- `src/markdown_to_canvas/cp.py`: `_warn_unresolvable_placeholders` type filter.
- `src/markdown_to_canvas/publish.py`: validation call.
- `src/markdown_to_canvas/repo_format.py`: `FORMAT_VERSION`, new migration.
- `src/markdown_to_canvas/imscc_import.py`: `_RELATIVE_DUE_DATES_HELP` text.
- Tests for each of the above, and tests that assert the literal format version.
- README.md, ARCHITECTURE.md, TODO.md.
- No Canvas API behavior is involved: virtual entries are never sent to Canvas.
