# Tasks

Tasks marked "(Open Question default)" follow a proposed default from design.md
that the user has not confirmed yet; adjust them if the user decides otherwise.

## 1. Format version

- [x] 1.1 Set `repo_format.FORMAT_VERSION = 15` and add `_migrate_14_to_15` to `MIGRATIONS`, changing no repo content and returning one "Record format version 15 in <manifest>" line per manifest; verify with a `tests/test_repo_format.py` test that upgrading a format-14 repo leaves `course_settings.toml`'s parsed content unchanged apart from `format_version`, adds no `last_generated_hash`, and stamps the manifests
- [x] 1.2 (Open Question default) In `_migrate_14_to_15`, add a NOTICE line when some table has items, saying to run `generate-due-dates` to record the fingerprint; verify with a test for a repo with items (line present) and one with only an empty default table (line absent)
- [x] 1.3 Update the existing fixtures and tests that hard-code format 14 (search `tests/` for `format_version = 14` and `FORMAT_VERSION`) and verify the full test suite passes

## 2. Fingerprint and warning check

- [x] 2.1 Move `_section_hash` from `sync.py` to a module that `sync.py` and `relative_dates.py` can both import without a cycle, keeping `sync`'s behavior; verify the existing course-settings hash tests pass unchanged
- [x] 2.2 In `relative_dates.py`, add `last_generated_hash` to the section-level allowed keys only (not `_TABLE_KEYS`); verify with `tests/test_relative_dates.py` tests that the section accepts it and produces the same dates, and that a table setting it fails with an unknown-key error naming the key and the table
- [x] 2.3 Add a fingerprint function over the parsed section minus `last_generated_hash`; verify with unit tests that it ignores comments, whitespace and key order, ignores `due_dates` and other top-level keys, and changes when an offset, an unused table, or `dont_reschedule_dates_before` changes
- [x] 2.4 Add a check function taking the parsed settings and returning the "has changed" warning, the "has no fingerprint" warning, or nothing, returning nothing when the section is absent or no table has an item (ordinary or virtual), and never raising on a malformed section; verify with unit tests for each case, using the exact wording from the spec

## 3. generate-due-dates records the fingerprint

- [x] 3.1 Make `apply_plan` set `last_generated_hash` (the fingerprint of the section as read into `plan.source_text`) in the same write as the dates, only when the plan has no `errors` and no `placeholder_errors`; verify with `tests/test_generate_due_dates.py` tests that a confirmed clean run writes both, and that runs with an inconsistent entry or an unresolved placeholder write the dates, leave `last_generated_hash` unchanged, and exit with status 1
- [x] 3.2 Add a fingerprint-only write for a run with nothing to change: when `last_generated_hash` is absent or out of date and the plan has no errors, write only the key, without a prompt and without requiring a terminal or `--yes`, and print one line saying so (Open Question default wording); when it is current, leave the file byte-for-byte unchanged; verify with tests for both cases, including one run with no terminal and no `--yes`
- [x] 3.3 Verify with tests that `--noop` (with and without changes), a declined prompt, the no-terminal-no-`--yes` failure when there are changes, and the out-of-term error all leave `course_settings.toml` byte-for-byte unchanged
- [x] 3.4 Check that the key lands at the top level of `[relative_due_dates]` (before its subtables) and that the parsed file equals the old parse plus the key, for an explicit `[relative_due_dates]` header with keys and for a file with only `[relative_due_dates.tables.default]` headers (implicit section); fall back to `repo_format._insert_in_relative_section` if tomlkit misplaces it; verify with tests for both layouts and for replacing an existing value
- [x] 3.5 (Open Question default) Write a `# Written by generate-due-dates; do not edit.` comment above the key when the key is first added, and not again on later writes; verify in the layout tests of 3.4

## 4. update prints the warning

- [x] 4.1 Print the warning (yellow; Open Question default) in `sync._phase_due_dates`, independent of whether `due_dates` is empty, so full runs, `--noop` and `--check-as-new-course` show it next to "Applying due_dates..." / "Checking due_dates coverage..."; verify with `tests/test_sync.py` tests (mocked Canvas) for a stale fingerprint, a missing fingerprint, a current fingerprint and an empty table
- [x] 4.2 Print the warning in `run_targeted_sync` next to its due-dates coverage check; verify with a targeted-run test (`-t`) with a stale fingerprint
- [x] 4.3 In `cli.py`'s update command, print the warning again after every final status line ("Update successful", "Update complete; ...", "Noop complete; ..." in both branches, "Check successful ...", "Check complete; ..."), before any `sys.exit(1)`; verify with CLI tests (CliRunner, mocked Canvas) that the warning appears after the status line in each branch and the exit status is unchanged

## 5. Other core subcommands

- [x] 5.1 `publish`: print the warning in `run_publish` before staging and again after "Built static site: ..."; verify with `tests/test_publish.py` tests for a stale fingerprint (two warnings, in order) and a current one (none)
- [x] 5.2 `import` and `mv`: confirm no change is needed (`import` writes an empty default table, so no warning applies; `mv` does not read `due_dates` or `[relative_due_dates]`); verify with an import test that a freshly imported course gets no warning from the check `update` and `publish` print from (`sync.relative_due_dates_warning`)

## 6. Documentation

- [x] 6.1 README.md: in the `generate-due-dates` section, describe `last_generated_hash` (what it is, when it is written, do not edit it), the fingerprint-only write, and the `update`/`publish` warnings with their exact text and when they appear; state that term-file edits and hand edits to `due_dates` are not detected; add the format 15 upgrade note; verify by reading the rendered section
- [x] 6.2 ARCHITECTURE.md: document the fingerprint (what it covers, the hash function, where the check lives), the recording rules in `generate-due-dates` including the errors-after-write case, where `update` and `publish` print the warning, the tomlkit placement handling, and the 14 -> 15 migration; verify ARCHITECTURE.md matches the code
- [x] 6.3 Update the `generate-due-dates` `--help` docstring in `cli.py` to mention that a clean run records `last_generated_hash`; verify with `gg generate-due-dates --help`
- [x] 6.4 Check TODO.md and BUGS.md for items this change completes or affects (none known at proposal time) and update them if any; verify by reading both files
