# Tasks

## 1. Test fixtures

- [x] 1.1 In `tests/test_cp.py`, add a fixture that builds two minimal current-format course repos, a source and a destination. Each has `course_settings/course_settings.toml` with `format_version`, and the source has pages, assignments, a discussion, a quiz folder, a question bank, a module, assets, snippets (including `snippets/inline/CANVAS_COURSE_ID.md`) and `rubrics.toml`. Verify with a smoke test that both repos pass `repo_format.check_repo_format`.

## 2. Planning phase (`src/markdown_to_canvas/cp.py`)

- [x] 2.1 Add the `CopyPlan` dataclass (file actions `new`/`identical`/`conflict`/`snippet-kept`/`ignored`, rubric appends, rubric-difference warnings, `module_order` change, links not followed, warnings) and write `build_copy_plan(srcs, dest_root, overwrite)` skeleton. It resolves the source repo from each SRC via `find_repo_root`, errors on a SRC outside any repo, on SRCs from two repos, on source == destination (message suggests `mv`), and on a SRC inside `course_settings/`, and runs `check_repo_format` on both repos first. Verify with tests for each error, asserting nothing is written in either repo.
- [x] 2.2 Expand SRC arguments: expand a directory to every file under it, a file inside a quiz or question bank to the whole folder, and skip a SRC matched by the source `.canvasignore` with a report. Verify with tests for a directory SRC, a question-file SRC expanding to its quiz folder, and an ignored SRC.
- [x] 2.3 Implement the dependency walk. Use `local_orphans.collect_local_refs` (inside `_quiet()`) to copy `assets/` refs; `convert.find_referenced_snippets` on raw text (plus quiz and bank question files) for snippets; for module files, follow each listed local item as a copied item. Record other content refs as links not followed, noting whether the destination has the target. Skip `.canvasignore`d dependencies with a report. Verify with tests: an assignment pulls in its image and snippet; an asset referenced only inside a snippet; `annotatable_attachment`; an asset inside a false `#if` branch is still copied; a module pulls in its items and their assets; a link to an uncopied page is listed as missing or present and not copied; an ignored asset is skipped.
- [x] 2.4 Classify each destination path as new, identical (byte compare) or conflict. Treat a dependency snippet that already exists in the destination as `snippet-kept` even with `--overwrite`, while a snippet named as SRC follows the normal rule. Verify with tests for identical skip, conflict listing, the kept `CANVAS_COURSE_ID` snippet, and a snippet SRC conflicting.
- [x] 2.5 Implement rubric merging for copied assignments and discussions. Split the source `rubrics.toml` at top-level `[[rubrics]]` lines and parse each block with `tomllib` for its title. If the destination has the title, keep it and warn when criteria or ratings (`description`, `long_description`, `points`) differ. Otherwise plan an append of the raw block, once per title. Warn on a missing source title or a numeric `rubric:`. Validate the planned destination text with `tomllib` and abort if it doesn't parse or lacks the title. Verify with tests: present-same (no change, no warning), present-different (warning, unchanged), missing (appended with existing bytes preserved and comments kept), no destination `rubrics.toml` (created), a shared rubric appended once, a numeric id warned, and a discussion's rubric merged.
- [x] 2.6 Plan the `module_order.toml` change. When a module is copied and the destination's `module_order.toml` exists and doesn't list it, append the filename with `tomlkit`. Never create the file. Verify with tests for append with comments preserved, already listed (unchanged), and no file (not created).
- [x] 2.7 Implement the warnings:
  - an `assignment_group_id` name missing from the destination;
  - numeric `group_category_id`, `final_grader_id` or `assignment_group_id`;
  - flags from `find_referenced_flags` / `find_referenced_flags_in_frontmatter` that the destination's `load_course_flags` doesn't define;
  - titles found in the source's `due_dates` or `relative_due_dates`;
  - title plus content-type collisions with a different destination file;
  - absolute `/courses/<id>/` URLs matching a `course_id` read with `tomllib` from the source's `course_settings/canvas*.toml`.

  Verify with one test per warning, asserting the copied file is still byte-identical.

## 3. Write phase and CLI

- [x] 3.1 Implement `run_cp(srcs, dest_root, noop, verbose, overwrite)`. It prints the plan (identical files as a count unless `--verbose`), exits non-zero on conflicts without `--overwrite` having written nothing, writes nothing under `--noop`, and otherwise writes files with `shutil.copyfile` (creating parent directories), rubric appends and the `module_order` change. It ends with a reminder to run `update` on the destination. Verify with tests: conflict aborts with zero files written, including the non-conflicting ones; `--overwrite` replaces; `--noop` leaves both repos unchanged; the fresh-mtime test (a replaced file's mtime is later than a destination manifest's `last_synced` set in the future of the source mtime); no manifest file is touched; nothing is `git add`ed.
- [x] 3.2 Add the `cp` command to `cli.py` next to `mv`: `SRC...` plus a required `COURSE_DIR` using `_course_dir_argument(required=True)` and `_resolve_course`, with `-n/--noop`, `-v/--verbose` and `--overwrite`. It calls `_ensure_pandoc()` and maps errors through `die()`. Verify with `CliRunner` tests: copy by registry key from an unrelated cwd prints `Course dir: … (course KEY)`; a missing destination gives a usage error; `--help` shows `COURSE_DIR`.
- [x] 3.3 Add `cp` to `COURSE_COMMANDS` in `tests/test_cli_course_dir.py`, and `run_cp` to `ENTRY_POINTS` (and to the CLI command list) in `tests/test_repo_format_enforcement.py`, including an old-destination case. Verify with `uv run pytest -q tests/test_cli_course_dir.py tests/test_repo_format_enforcement.py`.

## 4. End-to-end and other core subcommands

- [x] 4.1 End-to-end test: `cp` a module into the destination, then run `update --check-all` on the destination and assert the only problems reported are the expected links that were not followed. Run `run_sync` with the mocked Canvas and assert the copied assignment is created and associated with the rubric resolved by title. Verify with `uv run pytest -q tests/test_cp.py`.
- [x] 4.2 Check the other core subcommands (`update`, `import`, `mv`, `publish`) for anything that should change alongside `cp`, as the proposal says none should. Record the result in ARCHITECTURE.md's `cp` section. Verify by review, and by the full suite passing: `uv run pytest -q`.

## 5. Documentation

- [x] 5.1 Add a README.md section "Copying content between courses (`cp`)" after the `mv` section, plus a Contents entry. Cover usage, what gets copied, conflicts and `--overwrite`, the snippet rule, rubrics (including the note that discussion rubrics aren't attached by `update` yet), warnings, `--noop`, and the reminder to run `update`. Verify by reading the rendered section against the spec's scenarios.
- [x] 5.2 Add an ARCHITECTURE.md section on `cp` internals: plan/write phases, the reuse of `collect_local_refs`, the raw-text rubric append, fresh mtimes, and why links are not rewritten. Add the new test file to TESTING.md. Verify the sections exist and name the functions used.
- [x] 5.3 Review TODO.md. Update "Let `-t`, `-s` and `mv` use the course registry" to mention a possible `KEY:path` form for `cp` SRC. Keep "Add discussion rubric support" (not done here). Verify TODO.md has no item this change completes.
