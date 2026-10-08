# Tasks

The tasks follow the defaults written into the specs for design.md's Open
Questions. Revise the affected tasks if the user answers any of them
differently.

## 1. Format version

- [x] 1.1 Set `repo_format.FORMAT_VERSION` to 12 and add `_migrate_11_to_12` (stamps manifests only) to `MIGRATIONS`; verify with new tests in `tests/test_repo_format.py` copied from the 10 -> 11 tests (upgrade, `--noop`, older tool refuses), and make the existing 10 -> 11 tests pass `target_version=11`
- [x] 1.2 Update every test and fixture that asserts the literal current version (`tests/fixtures/course_settings/course_settings.toml` and the tests changed in the previous bump); verify `uv run pytest` has no version failures

## 2. Validating virtual entries

- [x] 2.1 Add `sync.check_virtual_due_dates(due_dates, repo_path, matcher)` raising one `ValueError` that lists every problem: non-bool `virtual`; `type`, `unlock_at`, `lock_at` on a virtual entry; missing, empty or sentinel `due_at`; name equal to a gradeable content title (with the file path); name shared with an ordinary entry. It checks every entry regardless of `only_if` and skips the content scan when nothing is virtual. Verify with unit tests in `tests/test_sync.py` (or a new test file) for each error, for several errors reported together, for two virtual entries sharing a name being allowed, and for a valid hand-written entry passing
- [x] 2.2 Call it in `run_sync` (real, `--noop`, `--check-as-new-course`) and the targeted sync, before any Canvas request; verify with a test that an invalid virtual entry makes `update` fail with the message and no mocked Canvas call
- [x] 2.3 Call it in `list-titles` and in `publish.stage` before staging; verify with tests that each command exits non-zero with the message and that `publish` writes no site

## 3. Keeping virtual entries away from Canvas

- [x] 3.1 Make `find_due_date_override` skip entries with `virtual = true`; verify with tests that the dates pass sends no update for a virtual entry named like nothing, and `list-titles` takes no date from one
- [x] 3.2 Make `_check_due_dates_coverage` skip virtual entries; verify with a test that `update` prints no "did not match any content file" warning for a virtual entry
- [x] 3.3 Verify with a test that a page quoting a virtual entry re-uploads when the entry's `due_at` changes (existing `dates_used` path), and is not re-uploaded otherwise

## 4. Placeholders

- [x] 4.1 In `date_placeholders.find_entry`, exclude virtual entries when a type filter is given; verify with tests in `tests/test_date_placeholders.py` that `item=` resolves a virtual entry and `item=... type=assignment` does not
- [x] 4.2 Apply the same rule in `cp._warn_unresolvable_placeholders`; verify with a `tests/test_cp.py` case where the destination has only a virtual entry and the placeholder gives `type=`

## 5. generate-due-dates

- [x] 5.1 In `relative_dates`, add `virtual: bool = False` to `ComputedDates`, emit a row for each virtual item (formatted `due_at`, no `_lock_field` call), and remove `Calculation.virtual_dates`; update `tests/test_relative_dates.py` virtual tests to assert the row
- [x] 5.2 In `plan_generation`, run `check_virtual_due_dates` on the existing `due_dates` (reported as `RelativeDueDatesError`), match virtual rows only to virtual entries and ordinary rows only to ordinary ones, and raise on cross-kind name clashes; verify with tests for each clash direction and that nothing is written
- [x] 5.3 Compare, keep by cutoff and write only `due_at` for virtual rows; `_new_row` writes `name`, `virtual = true`, `due_at`; check that `toml_write` keeps that key order in an inline `due_dates` row and in an array-of-tables `due_dates`; verify with `apply_plan` tests for add, change (keeping `only_if`), and cutoff-kept virtual entries
- [x] 5.4 Label virtual entries `Name (virtual)` in `render_plan`, list an added one with only `due_at`, count them in changes and the unchanged line, and remove the `--verbose` virtual list and `GenerationPlan.virtual_dates`; replace the old verbose-list tests in `tests/test_generate_due_dates.py` with tests of the new listing, including "only a virtual item changed" prompting and "nothing changed" not prompting
- [x] 5.5 Update `title_warnings`: `in_due_dates` ignores virtual entries; a virtual entry is produced only by a virtual item of the same name; others (removed items, hand-written) go to the leftover notice; verify with tests for both leftover cases and for a produced virtual entry not appearing in the notice
- [x] 5.6 Verify with a test that a placeholder naming a virtual item with no entry yet produces no placeholder error (it is in `_after_plan`), replacing the old test that expected an error

## 6. Core subcommands

- [x] 6.1 `update`: covered by groups 2-4; run `uv run pytest tests/test_sync.py tests/test_check_as_new_course.py` and verify they pass
- [x] 6.2 `publish`: covered by 2.3 and 4.1; verify a `publish` staging test where a page quotes a virtual entry renders the date
- [x] 6.3 `import`: reword the virtual-item paragraph of `_RELATIVE_DUE_DATES_HELP` (virtual items are written to `due_dates` as `virtual = true` entries that placeholders can quote and `update` never sends to Canvas); verify the `tests/test_imscc_import.py` help-text assertion is updated and passes
- [x] 6.4 `mv`: no change (it does not read `due_dates`); confirm by grep that `mv.py` has no `due_dates` use

## 7. Full suite

- [x] 7.1 Run `uv run pytest` and verify every test passes

## 8. Documentation

- [x] 8.1 README.md: document virtual `due_dates` entries (allowed keys, errors, hand-written use, the `ignore` list to silence the leftover notice), update the `generate-due-dates` section (virtual items are written and listed; no verbose list), and add a placeholder example quoting a week start with `format=`
- [x] 8.2 ARCHITECTURE.md: describe `check_virtual_due_dates` and its callers, `find_due_date_override` / coverage skipping, the `ComputedDates.virtual` row and generate matching rules (replacing the "Virtual items" paragraph that says they are never written), the `find_entry` type rule, and migration 11 -> 12; fix the statement under "Date placeholders" that placeholders cannot name virtual dates
- [x] 8.3 TODO.md: remove "Date placeholders that name virtual relative dates"; update the "generate week anchors automatically" item if its text says virtual items are never written to `due_dates`
- [x] 8.4 BUGS.md: check for entries about due_dates or placeholders affected by this change
