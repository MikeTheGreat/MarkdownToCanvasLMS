# Tasks

## 1. Loading virtual items

- [x] 1.1 Add `virtual` to `_ITEM_KEYS` and `virtual: bool = False` to `RelativeItem`. In `_load_item`, reject a non-bool value and, when it is true, reject `type`, `unlock_offset`, `lock_offset` and a `NO_DUE_DATE` anchor, each with an error naming the item. Verify with new tests in `tests/test_relative_dates.py`: one per rejected case plus the "Not a boolean" scenario.
- [x] 1.2 Add a test that a virtual item and an ordinary item with the same name in one table hit the existing duplicate-name error in `load_tables`. This confirms no new check is needed.

## 2. Calculation

- [x] 2.1 Add `virtual_dates: list[tuple[str, datetime]]` to `Calculation`. In `_Calculator.compute`, compute and term-check every item as now, but send virtual items to `virtual_dates` instead of `dates` and do not call `_lock_field` for them. Verify with tests: the "Week anchor" scenario (Lab 3 due on the second class day of week 3, including a holiday in week 2 that does not move it), "Virtual anchored to virtual", that a virtual item is absent from `Calculation.dates`, and that a section-level `lock_relative_default` produces no warning for a virtual item.
- [x] 2.2 Test the "Virtual date outside the term" scenario: the out-of-term error lists the virtual item and nothing is computed further.

## 3. generate-due-dates

- [x] 3.1 Extend `_content_titles` to return the repo-relative path, and update `title_warnings` to match. Verify that the existing `tests/test_generate_due_dates.py` tests still pass.
- [x] 3.2 In `plan_generation`, raise `RelativeDueDatesError` when a virtual name equals a content title, listing each collision with its file, before building any changes. Test the "Name collides with content" scenario, including that nothing is written with `--yes`.
- [x] 3.3 In `title_warnings`, skip virtual items in the "matches no content" loop, in `in_table`, and in the leftover check. Test the "Virtual item is not a missing title" and "Entry left from before the item was virtual" scenarios.
- [x] 3.4 Carry `virtual_dates` on `GenerationPlan`. In `render_plan(verbose=True)`, print a heading and one tab-indented `name  date` line per virtual item, sorted by name with the dates aligned in one column, after the changes and cutoff summary and before the unchanged count, not flagged as changes. Test "Verbose lists virtual dates", "Without --verbose", and that the list is printed with `--noop`, through the CLI with `CliRunner`.
- [x] 3.5 Test "Virtual item not written" (after `--yes`, `due_dates` has Lab 3 and no `Start_of_week_3`) and "Only virtual items" (says nothing would change and does not prompt).
- [x] 3.6 Test "Placeholder names a virtual item": `_placeholder_errors` reports it as a missing entry. This needs no code change; the test confirms it.

## 4. cp

- [x] 4.1 Make `cp._relative_names` skip items whose `virtual` is `True`. Verify with a test in the existing cp test module: a virtual name that equals a copied file's title does not produce the "dates ... were not copied" warning.

## 5. Format version

- [x] 5.1 Set `repo_format.FORMAT_VERSION = 11` and add `_migrate_10_to_11` (stamp the manifests only) to `MIGRATIONS`. Add tests in `tests/test_repo_format.py` for "Upgrade a version-10 repo" (parsed settings unchanged except `format_version`), "Noop run", and "Older tool refuses a version-11 repo" (with the migrations or version patched, as the 9 -> 10 tests do). Run the full suite (`uv run pytest`) and fix any test that hard-codes version 10.

## 6. Other core subcommands

- [x] 6.1 Check `update`, `import`, `mv` and `publish`. `update` and `publish` need no change: they read only `due_dates` and the version check comes from `FORMAT_VERSION`. `mv` does not read the relative table. `import` changes only in task 6.2. Confirm with `grep` that none of them reads `relative_due_dates` items directly, and record the result in the task when checking it off. Result: only `cp`, `generate_due_dates`, `relative_dates`, `imscc_import`, `repo_format`, `cli` and `sync` mention the section; `sync` only lists it in `_NON_METADATA_SETTINGS_KEYS`, and `mv` and `publish` never read it.
- [x] 6.2 Add a commented `virtual = true` line and a short paragraph to `imscc_import._RELATIVE_DUE_DATES_HELP`. Verify that the import test that parses the written `course_settings.toml` still passes, and that the help comment appears in a fresh import's output.

## 7. Documentation

- [x] 7.1 README.md: in "The `[relative_due_dates]` section", add `virtual` to the item key table and add a subsection with the week-anchor example. It should cover that only the date carries over, that virtual dates are term-checked, the four errors, the content-title collision, `--verbose` listing, and that placeholders cannot name them. Mention migration 10 to 11 in the format-version list.
- [x] 7.2 ARCHITECTURE.md: in the `generate-due-dates` section, describe `RelativeItem.virtual`, `Calculation.virtual_dates`, why virtual items produce no `ComputedDates` row, the title-warning and collision changes, and `cp._relative_names`. Add migration 10 -> 11 to the migration list.
- [x] 7.3 TODO.md: confirm the two parked items ("generate week anchors automatically" and "Date placeholders that name virtual relative dates") still describe accurate follow-ups, and update their wording to the final key name if it changed. Check BUGS.md for related entries.
