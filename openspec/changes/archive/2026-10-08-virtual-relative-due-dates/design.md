# Design

## Context

See proposal.md for the motivation and specs/ for the required behavior.

The relevant current code:

- `relative_dates._load_item` validates one item against `_ITEM_KEYS` and builds
  a frozen `RelativeItem`. `load_tables` already rejects two items with the
  same name when either has no `type`, so a virtual item (which never has a
  `type`) cannot share a name with any other item. No new check is needed for
  that.
- `_Calculator.due()` resolves and memoizes every item by name, following
  `ASSIGNMENT` anchors through `by_name`. `compute()` walks `table.items`,
  checks each due date against the term, and appends a `ComputedDates` row
  (with `_lock_field` for unlock and lock) for every item.
- `generate_due_dates.plan_generation` turns each `ComputedDates` row into an
  `EntryChange` against `due_dates`. Then it calls
  `title_warnings(table, due_dates, _content_titles(repo))` and
  `_placeholder_errors`. `render_plan(plan, verbose)` already takes `verbose`
  for the cutoff list.
- `_content_titles` returns `(title, canvas_type)` and drops the file path.
- `cp._relative_names` collects every item name of every table from the raw
  settings dict, without validation.
- `repo_format.FORMAT_VERSION` is 10, and `MIGRATIONS` ends at
  `9: _migrate_9_to_10`. `_migrate_3_to_4` and others show the
  stamp-the-manifests pattern.

No Canvas API behavior is involved. The change only affects what is written to
the local `course_settings.toml`.

## Goals / Non-Goals

**Goals:**
- Reuse the existing calculator unchanged for virtual dates: same anchors,
  offsets, memo and cycle detection.
- Keep virtual items out of everything downstream of the calculation (the plan,
  `apply_plan`, placeholders) by not producing rows for them, so no downstream
  code needs a virtual check.

**Non-Goals:**
- Generated week anchors and placeholders that name virtual dates (both in
  TODO.md).
- Cross-table virtual items. An anchor still refers only to its own table.
- A new anchor spelling. `ASSIGNMENT` / `assignment_name` is kept, as the user
  decided.

## Decisions

**Per-item key.** Confirmed by the user: virtual is a key on the item, not a
separate list. `RelativeItem` gains `virtual: bool = False`. `_ITEM_KEYS` gains
the key, and `_load_item` checks that the value is a bool. When it is `True`,
`_load_item` rejects `type`, `unlock_offset`, `lock_offset` and a
`NO_DUE_DATE` anchor with errors that name the item. Validating at load time
reports these errors before any date is computed, like other settings errors.

**Calculation output.** `Calculation` gains
`virtual_dates: list[tuple[str, datetime]]` (name and aware datetime, formatted when shown).
`compute()` still calls `self.due(item)` and runs the out-of-term check for
every item, which gives the confirmed behavior that virtual dates are
term-checked. For a virtual item it appends to `virtual_dates` instead of
`dates` and does not call `_lock_field`. Not calling `_lock_field` matters:
otherwise a section-level `lock_relative_default` would apply to the virtual
item and do pointless work. The alternative was a `virtual` flag on
`ComputedDates` that every consumer filters on. It was rejected because each
consumer would need the filter, and forgetting it in one place would write a
virtual entry to `due_dates`.

**Title warnings.** In `title_warnings`, the "matches no content" loop and
`in_table` look only at ordinary items. The leftover notice also looks only at
ordinary items, so a `due_dates` entry named after a virtual item is reported
as not produced by the table. That entry is what the pre-feature workaround
leaves behind, and the notice tells the user it can be deleted.

**Collision with content titles.** Confirmed by the user that this is an error.
`_content_titles` is extended to return the repo-relative path as well. The one
caller that uses the tuples positionally (`title_warnings`) is updated.
`plan_generation` checks virtual names against the titles before building
changes and raises `RelativeDueDatesError` listing every collision with its
file, so nothing is shown or written. Content excluded by `.canvasignore` is
not in `iter_gradeable_content` and is not checked; it is never uploaded, so it
cannot be confused with a virtual name in Canvas.

**Verbose output.** Confirmed: shown only with `--verbose`. `GenerationPlan`
carries `virtual_dates`. `render_plan` prints them after the change entries and
the cutoff summary and before the unchanged count, under a heading line, one
tab-indented line each, sorted by name, with the name padded so the dates
start in one column (`name  <date>`; the user asked for this layout). The date is formatted with the same
human-readable form as the cutoff line (`relative_dates.format_cutoff` style,
e.g. `Mon Oct 12, 2026 11:59 PM PDT`). The lines are not flagged as changes, so
they are not yellow. The time of day printed is `default_due_time` unless the
item's offsets set one; it is shown because a `+N CLASS_DAY` count from it can
depend only on the date, and a user reading the list should not need to know
that.

**cp.** `_relative_names` skips items with `virtual = true`. It reads the raw
dict, so the check is `item.get("virtual") is True`.

**Format version.** Confirmed: bump to 11. `_migrate_10_to_11` only stamps the
manifests and returns their "Record format version 11" lines. The settings
file's `format_version` is written by `run_upgrade` as for every migration. The
import help text (`_RELATIVE_DUE_DATES_HELP`) gains a commented
`virtual = true` line in the example item and a short paragraph about it.
`import` is not otherwise changed. Tests that assert the literal current
version need updating. `test_repo_format.py` has the per-migration tests to
copy.

## Risks / Trade-offs

- [A virtual item's date prints at `default_due_time`, which may confuse a
  reader who thinks of "the start of week 3" as midnight] → It matches how
  `ASSIGNMENT` anchors already work: they use only the anchor's date. The
  README states that only the date carries over.
- [Content-title collision is checked only for gradeable content: assignments,
  discussions and quizzes] → Pages have no `due_dates` entries, so a virtual
  name that equals a page title is harmless.
- [Bumping the format version forces `upgrade` on every repo for an additive
  key] → This follows the precedent of migration 8 -> 9 and the user's decision.
  The migration is trivial and `upgrade` is one command.
- [A user who adopted the pseudo-item workaround keeps stale `due_dates`
  entries] → The leftover notice names them on every run.

## Migration Plan

`upgrade` takes a version-10 repo to 11 with no content change. Rollback means
reverting the tool. A version-11 repo with no `virtual` keys can be returned to
version 10 by editing `format_version` and the manifests' `_repo_format` by
hand. This is not supported by a command.

## Resolved defaults

The user confirmed these after the first draft: the key is `virtual = true`;
`type`, `unlock_offset`, `lock_offset` and a `NO_DUE_DATE` anchor on a virtual
item are errors; the content-title collision check includes titles in the
table's `ignore` list; the `--verbose` list is `name  date`, sorted by name,
with the dates aligned.
