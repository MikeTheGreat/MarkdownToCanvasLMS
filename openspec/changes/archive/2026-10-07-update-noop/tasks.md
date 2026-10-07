# Tasks

The tasks follow the recommendations in design.md "Open Questions". Confirm or
change those before starting.

## 1. Rename --check-all to --check-as-new-course

- [x] 1.1 In `cli.py`, rename the `update` option to `--check-as-new-course` (parameter `check_as_new_course`), drop `-ca`, and update the three combination errors to name the new flag; verify with a CLI test that `--check-as-new-course` runs the offline check and `--check-all` fails with click's unknown-option error
- [x] 1.2 Rename the internal `check_all` names in `sync.py`, `dryrun.py`, `manifest.py` and `config.py` (parameters, comments, docstrings, the `(check-all: ...)` placeholder text) and the "CHECK MODE" banner wording if it names the flag; verify `grep -rn "check.all" src` finds nothing
- [x] 1.3 Update every test that passes `--check-all` or `check_all=` (`test_check_all.py`, `test_group_categories.py`, `test_repo_format_enforcement.py`, `test_cli_course_dir.py`, `test_unrecorded_moves.py`, `test_sync.py`); rename `test_check_all.py` to `test_check_as_new_course.py`; verify the full test suite passes

## 2. Mode parameter and API indirection

- [x] 2.1 Replace `run_sync(check_all: bool)` with a `mode` parameter (`"real"`, `"noop"`, `"new_course"`), keeping `ctx.check_only` true for both simulated modes; verify existing real-run and new-course tests pass unchanged
- [x] 2.2 Give `run_targeted_sync` an `api` parameter passed to `SyncContext`, and route its direct `capi.*` calls (`get_course`, `get_assignment_group_ids`, `get_rubric_ids`, `get_orphan_item`, `upload_asset`) through it; verify existing `-t`/`-s` tests pass
- [x] 2.3 Add `get_quiz(course, quiz_id)` to `canvas_api` and `DryRunCanvas` and call `ctx.api.get_quiz` in `_sync_quiz` instead of `course.get_quiz`; verify quiz sync tests and the new-course full-fixture test pass

## 3. NoopCanvas

- [x] 3.1 Add `dryrun.NoopCanvas(DryRunCanvas)` that takes the real course, hands out negative fake IDs, forwards each read function the pipeline calls to `canvas_api` (answering locally for negative IDs), and merges simulated groups, rubrics, group sets/group categories and modules into the real name -> ID maps; verify with unit tests using a mocked course that reads reach the mock, writes do not, and a group created in the run appears in the next `get_assignment_group_ids`
- [x] 3.2 Add the request-level safety net: in noop mode, wrap the course requester so any non-GET request raises `NoopWriteError`; verify with a test that a deliberate POST through the requester raises and that a full noop run over the fixtures issues only GETs
- [x] 3.3 Add a test in the style of the existing full-fixture check that runs `run_sync(mode="noop")` and `run_targeted_sync` in noop mode over the whole fixture repo with a mocked course, so a pipeline call without a `NoopCanvas` twin fails as an `AttributeError`; verify it passes

## 4. Noop pipeline behavior

- [x] 4.1 In `run_sync` and `run_targeted_sync` noop mode, load the manifest from disk and pass `manifest_path=None` everywhere, including to `check_unrecorded_moves`; verify with a test that the manifest file is byte-identical after a noop run that would upload stale and new files, and after `--noop --new PATH`
- [x] 4.2 Give `course_guard.check_course` a noop mode per design.md Open Question 1 (same course: continue; none recorded: message, no prompt, no write, continue; different course: message, no prompt, no write, exit 1) and call it from `_guard_course` with the flag; verify with tests for all three cases that no prompt is shown and the manifest is unchanged
- [x] 4.3 Print a noop banner at the start of the run naming the manifest file that will not be modified; verify in a CLI test
- [x] 4.4 Add the summary counters to `SyncContext` (created, updated, skipped, newer on Canvas, problems) and print the summary at the end of a noop run, full and targeted; verify with a test on a fixture with known stale, new and up-to-date files that the counts match
- [x] 4.5 Verify with tests that a noop run lists only stale and new files, reports a newer-on-Canvas item in the existing summary without a "Would upload" line, and that `--force-uploads` makes every file appear

## 5. CLI

- [x] 5.1 Add `--noop`/`-n` to `update`: require the API token, reject `--noop` with `--check-as-new-course` before contacting Canvas, accept it with `-t`, `-s`, `--force-uploads`, `--force-overwrite`, `--new`, `--config`, `--yes`, and dispatch to the noop mode of `run_sync`/`run_targeted_sync`; verify with CLI tests for each accepted and rejected combination
- [x] 5.2 Exit 1 when the noop run collected any error or warning, else print a green "nothing was changed" line and exit 0; verify with CLI tests for both outcomes and for the unrecorded-move stop
- [x] 5.3 Apply the change to the other core subcommands where applicable: confirm `mv` (already has `--noop`), `import` and `publish` (never write to Canvas) need no change, and check that `emit-workflow`'s template does not use `--check-all`; verify by grep and record the result in ARCHITECTURE.md's update section

## 6. Live verification

- [x] 6.1 Run `update --noop` and `update --noop --force-uploads` against the sandbox course 2758791 (see CLAUDE_NOTES/CLAUDE-IN-CHROME.md) with request logging on; verify that every request was a GET and that the course shows no edits afterwards; note the result in ARCHITECTURE.md

## 7. Documentation

- [x] 7.1 README.md: rename the "Checking a course before deploying (`--check-all`)" section and its TOC entry to `--check-as-new-course`, update every other mention, and add a section on `update --noop` (what it reads, what it never writes, option combinations, summary, exit status); verify `grep -n "check-all" README.md` finds nothing
- [x] 7.2 ARCHITECTURE.md: rename the `--check-all` section, describe the three sync modes, `NoopCanvas`, negative fake IDs, the request safety net, the course-guard and unrecorded-move behavior under noop, the summary counters, and `get_quiz` going through the API object; verify `grep -n "check-all" ARCHITECTURE.md` finds nothing
- [x] 7.3 TESTING.md: update the `--check-all` references and describe the noop tests; verify by grep
- [x] 7.4 Check TODO.md and BUGS.md for items this change completes or affects and remove or revise them (none are expected)
