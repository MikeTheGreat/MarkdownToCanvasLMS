# Tasks

## 1. CLI option

- [x] 1.1 Add `--ignore-pinned-resources` to `update` in `src/markdown_to_canvas/cli.py` (help text: check pinned_resources content too; only with `--check-as-new-course`) and pass it to `run_sync`; verify `update --help` lists it
- [x] 1.2 Reject `--ignore-pinned-resources` without `--check-as-new-course` alongside the existing check-mode combination errors, before config loading; verify with tests for plain `update` and `update --noop` (non-zero exit, error names `--check-as-new-course`, Canvas not contacted)

## 2. Sync

- [x] 2.1 Give `run_sync` an `ignore_pinned` keyword (default False). Keep validating with `load_pinned_resources`, then pass an empty list as `SyncContext.pinned` when set; verify with a test that a pinned quiz with a broken link is reported and the check exits non-zero, with no pinned warning or summary
- [x] 2.2 Call `check_pinned_resources_coverage` with the loaded list (not the emptied one); verify with a test that an entry matching nothing still warns under the flag
- [x] 2.3 In `new_course` mode with a non-empty pin list, print the note after the CHECK MODE banner: the "temporarily unpinned for this simulated run" note (entries listed only with `--verbose`) when the flag is set, and the hint naming `--ignore-pinned-resources` otherwise; verify with tests for both notes, the verbose listing, and no note when there are no pins
- [x] 2.4 Verify with tests that a module listing a pinned item reports no problem under the flag, and that without the flag pinned content is still skipped with the existing warning and summary
- [x] 2.5 Verify with a test that an invalid pin entry (absolute path) still stops the check under the flag

## 3. Other core subcommands

- [x] 3.1 Confirm `import`, `mv` and `publish` need no change (none uploads or has a check-as-new-course mode) and `run_targeted_sync` is unreachable with the flag; record this in the ARCHITECTURE.md note in 4.2

## 4. Documentation

- [x] 4.1 README.md: add the option to the `update` options listing and the "Checking a course before deploying" section (what it does, that it requires `--check-as-new-course`, that a real deploy to a new course still honors pins so clear `pinned_resources` first); update the line listing check-mode restrictions if needed
- [x] 4.2 ARCHITECTURE.md: in the pinned-resources paragraph and the check-as-new-course description, say that `--ignore-pinned-resources` empties `SyncContext.pinned` after validation, that the coverage warning uses the loaded list, and where the notes print
- [x] 4.3 Check TODO.md and BUGS.md for items this change affects (none expected) and update them if any
- [x] 4.4 After 1-2 are implemented and the full test suite passes, update `/home/mike/Dropbox/Work/Courses/_COLL_101/mpanitz-OL-College101/CLAUDE.md` (the user asked for this edit in another repo): add `--ignore-pinned-resources` to the `--check-as-new-course` command, and replace the "items in `pinned_resources` are skipped ... That error is expected" sentences with a note that the flag checks pinned content as if unpinned and that a real deploy to a new course still skips pinned items unless `pinned_resources` is cleared; verify by running the updated command in that repo and confirming the module "some items could not be added" errors are gone
