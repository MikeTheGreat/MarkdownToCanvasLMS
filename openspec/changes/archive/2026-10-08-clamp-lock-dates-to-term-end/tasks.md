# Tasks

## 1. Setting and calculation (relative_dates.py)

- [x] 1.1 Add `clamp_lock_at_to_last_day_of_term` to `_SETTING_KEYS` and a bool field on `TableSettings`, layered section -> table in `_load_settings()` with an error naming the key for a non-bool value; verify with tests in `tests/test_relative_dates.py` for section value, table override, absent default, and `"yes"` rejected
- [x] 1.2 Clamp in `_lock_field` after `default_lock_time` / `ABS_TIME`: a later date becomes `last_day` 23:59 in the term zone, a `NONE` rule becomes it (with or without a due date), `KEEP` and dates at or before are unchanged; record each clamp (name, type, cause) on `Calculation`; verify with tests for each scenario in the `relative-due-dates` delta, including `unlock_at`/`due_at` unaffected and setting off giving today's results
- [x] 1.3 Add a `CLAMP_HELP` constant (comment plus `# clamp_lock_at_to_last_day_of_term = true`) shared by import and the migration; verify the text parses as an empty TOML document

## 2. generate-due-dates output

- [x] 2.1 Carry clamps whose `lock_at` was not kept by the cutoff into `GenerationPlan`; verify with a test that a `NONE`-rule item whose current `lock_at` is on or before the cutoff is kept and not counted
- [x] 2.2 In `render_plan`, print the summary line (total, end of term via `rd.format_cutoff`, split with zero parts omitted) after the kept-resources line, and under `--verbose` one tab-indented line per resource with name, type and cause; also with `--noop` and when nothing changes; verify with tests for both causes, one cause, verbose list, an unchanged second run, and no line when the setting is off

## 3. import

- [x] 3.1 Add `CLAMP_HELP` to the `[relative_due_dates]` scaffolding in `imscc_import.py` next to the cutoff help; verify in `tests/test_imscc_import.py` that the line `# clamp_lock_at_to_last_day_of_term = true` is present and the parsed section has no such key, and that uncommenting it enables the clamp

## 4. Format version 13 (repo_format.py)

- [x] 4.1 Set `FORMAT_VERSION = 13` and add migration 12 -> 13: insert `CLAMP_HELP` directly after the `[relative_due_dates]` header unless the section already mentions the key (report it), add a header before the first subtable when only subtables exist, print a notice when there is no section, check the parsed TOML is unchanged, stamp manifests; verify in `tests/test_repo_format.py` with each scenario of the `repo-format-version` delta, including `upgrade --noop`
- [x] 4.2 Update `tests/fixtures/course_settings/course_settings.toml` and any tests that pin version 12 to 13; verify the full test suite passes

## 5. Other core subcommands

- [x] 5.1 Confirm `update`, `mv` and `publish` need no change (none reads the setting; `update` sends `due_dates` as written and already excludes `relative_due_dates` from settings sync) and record this in the ARCHITECTURE.md text in 6.2

## 6. Documentation

- [x] 6.1 README.md: document the setting in "The `[relative_due_dates]` section" (what it does, `NONE` and `KEEP` behavior, table override, 23:59 term zone), the summary line under `generate-due-dates`, the import scaffolding paragraph, and the `upgrade` notes for format 13
- [x] 6.2 ARCHITECTURE.md: the clamp in `_lock_field` and its ordering, how clamps reach `render_plan` and why cutoff-kept fields are excluded, `CLAMP_HELP` shared by import and migration 12 -> 13, and the format-13 entry in the format version list
- [x] 6.3 TODO.md: add a sentence to "`generate-due-dates`: revisit lock and unlock handling" noting that clamping to the term's last day now exists; check BUGS.md for related entries
