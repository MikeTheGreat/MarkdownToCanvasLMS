# Tasks

All tests mock Canvas (this feature never calls it). Run tests with
`uv run pytest -q`. No task includes a git commit.

## 1. Format version 2 and migration

- [ ] 1.1 Set `repo_format.FORMAT_VERSION = 2`, add `_migrate_1_to_2` (append an empty `[relative_due_dates.tables.default]` with an empty `items` array at the end of `course_settings.toml` via tomlkit; skip when a `relative_due_dates` key exists; stamp manifests) and register it in `MIGRATIONS`; verify with new tests in `tests/test_repo_format.py` for: version-1 repo gains the section, comments and order elsewhere unchanged, existing section untouched, repo with no `course_settings.toml`, and version 0 -> 2 applies both migrations
- [ ] 1.2 Update existing tests that hard-code version 1 (`test_repo_format.py`, `test_repo_format_enforcement.py`, fixtures and any repo fixtures) and add a case that `generate-due-dates` refuses a version-1 repo; verify the full suite passes
- [ ] 1.3 Add `relative_due_dates` to `sync._NON_METADATA_SETTINGS_KEYS`; verify with a test in `tests/test_settings_sections.py` that changing only that section makes `update` skip the course-settings API call

## 2. Settings and term-file loading

- [ ] 2.1 Create `src/markdown_to_canvas/relative_dates.py` with loaders for the `[relative_due_dates]` section (shared settings, named tables, per-table overrides, `ignore`) and for the term file (required keys, IANA zone via `zoneinfo`, `HH:MM` due time, non-instructional days); verify with unit tests for defaults, overrides, missing keys, bad zone, and duplicate item names
- [ ] 2.2 Implement table selection (`--table`, then the term file's `relative_table`, then the only table); verify with unit tests for one table, several tables without a choice (error lists names), unknown name, and command-line override
- [ ] 2.3 Add `items` to `toml_write.INLINE_TABLE_ARRAY_KEYS` and verify in `tests/test_toml_write.py` that a table's `items` write as an inline array of inline tables, so a long row can't turn into a `[[table]]` block

## 3. Date calculation

- [ ] 3.1 Implement the anchors (`START_OF_QUARTER`, `FIRST_CLASS_OF_QUARTER`, `NO_DUE_DATE`, `ASSIGNMENT`) with per-run memoization, cycle detection, and no mutation of the input offsets; verify with unit tests, including that calling twice gives the same result and the input list is unchanged
- [ ] 3.2 Implement the offsets (`CALENDAR_DAY`, `CLASS_DAY` with non-instructional-day skipping, `NEAREST_CALENDAR_DAY`, `ABS_TIME`) on local calendar dates with the zone's UTC offset attached at the end; verify with the scenarios in `specs/relative-due-dates/spec.md` (class-day, skipped holiday, nearest weekday, absolute time, DST `+60 CALENDAR_DAY` gives `2026-11-29T23:59:00-08:00`)
- [ ] 3.3 Implement lock/unlock offsets (string or list, `NONE`, absolute time, item -> table -> section -> `KEEP` fallback, warning plus `KEEP` when no due date); verify with unit tests for each scenario in the spec
- [ ] 3.4 Record expected results from MikesGradingTool for the 142 and 143 relative tables (run its calculation once, store the output as a fixture in `tests/fixtures/`) and add a comparison test; verify it passes, with post-DST dates expected one hour later in wall-clock terms per the DST requirement and a comment saying why

## 4. The generate-due-dates command

- [ ] 4.1 Add the `generate-due-dates` command to `cli.py` (term-file argument, optional repo, `--table`, `--noop`, `--yes`) calling `repo_format.check_repo_format` first; verify with a `CliRunner` test that `--help` lists the options and a version-1 repo is refused
- [ ] 4.2 Compute the new `due_at`/`unlock_at`/`lock_at` per item and build the per-entry diff (added, changed with old/new per field, unchanged count); verify with unit tests for new entries, changed entries, unchanged entries, `NONE`/`KEEP` values, and `type` only when the item has one
- [ ] 4.3 Print the diff with changed lines in yellow (`click.style` or the CLI's existing helper) and implement confirm / decline / nothing-to-change / no-terminal-without-`--yes` / `--noop`; verify with `CliRunner` tests for each path, including that `--noop` and a declined prompt leave `course_settings.toml` byte-for-byte unchanged
- [ ] 4.4 Write the results into the `due_dates` array through tomlkit edits (update existing rows, append new ones, keep other keys such as `only_if`, keep comments and unrelated rows); verify with a test that compares the file before and after for everything outside the changed rows
- [ ] 4.5 Implement the title warnings (item matching no content, content in neither table, content missing from one, `ignore`, leftover `due_dates` entries) using the repo's content scan, one message per title naming the table(s) responsible; verify with tests for each scenario in `specs/generate-due-dates-command/spec.md`, including no duplicate report for a title missing from both
- [ ] 4.6 End-to-end test with a temporary course repo: relative table plus term file to `due_dates`, then `update` against a mocked Canvas applies those dates and honors `only_if`; verify the mocked calls carry the generated dates

## 5. import scaffolding

- [ ] 5.1 Make `imscc_import` write `[relative_due_dates.tables.default]` (empty `items`) after all top-level keys, with the shared settings commented out and their allowed values listed; verify in `tests/test_imscc_import.py` that the output parses, the section is present, and no top-level key ended up inside it
- [ ] 5.2 Write the commented-out example term file `course_settings/term_dates.toml` only if it does not exist; verify it parses as empty TOML, that a second import leaves an existing file unchanged, and that `update` and `find-local-orphans` neither upload nor report it

## 6. Harvest script

- [ ] 6.1 Add `scripts/harvest_relative_due_dates.py`: read the grading tool's config (JSON with `//` comments) and a course id such as `142`, print the equivalent `[relative_due_dates]` TOML (shared settings and one table) to stdout; verify by running it against `mikes_config/config.json` for 142 and 143 and checking the output parses with `tomllib` and, fed to the new calculation, matches the grading tool's dates (apart from the DST hour)

## 7. Other core subcommands

- [ ] 7.1 Confirm `update`, `import`, `mv` and `publish` are the only core commands affected: `update` (task 1.3), `import` (5.x); verify `mv` and `publish` need no change by running their tests on a repo containing a `[relative_due_dates]` section and a term file

## 8. Documentation and cleanup

- [ ] 8.1 Update README.md: the `generate-due-dates` command, the `[relative_due_dates]` section and its allowed values, the term file, offset grammar, lock/unlock defaults, table selection, warnings, the one-set-of-dates-per-run limit for multi-section repos, and the DST behavior; update the table of contents; verify the examples in the text parse
- [ ] 8.2 Update ARCHITECTURE.md: the calculation and its differences from MikesGradingTool (local-date arithmetic, memoization, no list mutation), how the command edits `due_dates`, format version 2 and migration 1 -> 2, and the `_NON_METADATA_SETTINGS_KEYS` entry
- [ ] 8.3 Update TESTING.md with the new test files and the recorded grading-tool fixture
- [ ] 8.4 Add a TODO.md item to revisit lock/unlock handling (a fixed distance from the due date), and check the rest of TODO.md for items this change completes or affects
- [ ] 8.5 Delete `NEW_FEATURES.md` and `RELATIVE_DUE_DATES.md` once tasks 1 to 7 are done; verify with `git status` that only those two files are removed and nothing else refers to them (`grep -r NEW_FEATURES`)
