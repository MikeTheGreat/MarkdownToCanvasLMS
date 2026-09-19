# Tasks

Read proposal.md, specs/repo-format-version/spec.md and design.md before
starting. Design decision numbers below refer to design.md. Never commit to
git; the user handles commits, tags and pushes.

## 1. Build and dependencies

- [x] 1.1 In `pyproject.toml`, replace `version = "0.2.0"` with `dynamic = ["version"]`, add `hatch-vcs` to `[build-system] requires`, add `[tool.hatch.version]` with `source = "vcs"` and `fallback-version = "0.0.0+unknown"`, and add `tomlkit` to `dependencies`; run `uv lock` and `uv sync`, and verify `uv run python -c "import importlib.metadata as m; print(m.version('markdown-to-canvas'))"` prints a VCS-derived version (decision 8)
- [x] 1.2 Verify the existing suite still passes after the build change (`uv run pytest -q`)

## 2. Core module `repo_format.py`

- [x] 2.1 Create `repo_format.py` with `FORMAT_VERSION = 1`, `RepoFormatError(Exception)` (not a `ValueError` subclass), `tool_version()` (package version, or `"unknown"` on `PackageNotFoundError`), and `read_repo_version(repo)` (missing file or key -> 0; non-integer or negative -> `RepoFormatError` naming the file and value); resolve the `manifest` <-> `repo_format` import order as described at the end of decision 2; verify with unit tests for each case
- [x] 2.2 Add `read_manifest_versions(repo)` returning each `.manifest-*.toml` path with its `_repo_format.format_version` (missing -> 0); verify with unit tests for stamped, unstamped and no-manifest repos
- [x] 2.3 Add `fix_tab_configuration(doc)` operating on a `tomlkit` document (decision 4): no nested key -> `None`; nested only -> move to a top-level key before the first table and return a notice naming the old location; nested and top-level -> `RepoFormatError` naming both; verify with unit tests for nesting under `[default_post_policy]` (its other keys kept), nesting inside a `[[...]]` element, the conflict case, a correctly placed key, an absent key, and that comments elsewhere in the file survive byte-for-byte
- [x] 2.4 Add `check_repo_format(repo) -> None` (decision 2): version mismatch of the repo or any manifest raises `RepoFormatError` (older: message names `markdown-to-canvas upgrade`; newer: says to update the tool; both versions stated; the offending manifest named); it edits nothing and ignores `tab_configuration`; verify with unit tests for each branch, including that a nested `tab_configuration` is left byte-identical

## 3. Manifest stamp

- [x] 3.1 In `manifest.py`, add the reserved key `_repo_format`, make `load()` of a nonexistent path return a dict containing `_repo_format = {format_version = FORMAT_VERSION}`, and replace `is_course_key()` with `is_reserved_key()` covering both reserved keys (decision 3); verify with unit tests that a new manifest is written with the stamp on first `flush()` and that `has_content_entries()` ignores it
- [x] 3.2 Audit every loop over manifest entries (`is_reserved_key` callers, `has_content_entries`, `mv` key rewriting, `clean_manifest`, `run_prune`, orphan detection, `course_guard`) and make each skip reserved keys; verify with a test per command that runs on a manifest containing `_repo_format` and asserts the entry is neither reported, pruned, rewritten nor removed

## 4. Test scaffolding

- [x] 4.1 Add a `make_current(repo)` helper to `tests/conftest.py` that creates `course_settings/course_settings.toml` with `format_version = FORMAT_VERSION`, or prepends the key to an existing file (decision 10); verify with a small test of the helper itself
- [x] 4.2 Add `tests/fixtures/course_settings/course_settings.toml` containing only `format_version = 1`; run `uv run pytest -q` and record which tests change behavior (expected: a new `course_settings/course_settings.toml` manifest entry, no new Canvas calls). Do not fix failures yet; group 6 does that once the checks are in place

## 5. Library-level version check

- [x] 5.1 Call `check_repo_format` at the start of `sync.run_sync`, `sync.run_targeted_sync` and `sync.run_prune`; verify with tests that each raises `RepoFormatError` on a version-0 repo before any manifest write or Canvas call (Canvas mocked), and that `run_sync` on a current repo with nested `tab_configuration` leaves the file unchanged
- [x] 5.2 Call it in `course_guard.check_course` (repo = `manifest_path.parent`) before the manifest is loaded; verify with a test that a version-0 manifest is not written by the guard
- [x] 5.3 Call it in `mv.run_mv` right after the repo root is found; verify with tests that `run_mv` refuses on a version-0 repo and moves nothing, and that `run_mv` does not edit a nested `tab_configuration`
- [x] 5.4 Call it in `publish.run_publish`, `local_orphans.find_local_orphans` and `clean_manifest.run_plan`; add `clean_manifest.load_manifest(repo, config)` (check + load) and use it in `cli.py`'s `--no-canvas-check` branch; move `list-titles`' item collection out of `cli.py` into a library function (for example `sync.collect_title_items(repo, config)`) that calls the check; in `find-canvas-orphans`, have `cli.py` call `repo_format.check_repo_format(repo)` before `find_orphans`; verify each with a test on a version-0 repo
- [x] 5.5 Add one parametrized test that calls every checked entry point (`run_sync`, `run_targeted_sync`, `run_prune`, `check_course`, `run_mv`, `run_publish`, `find_local_orphans`, `run_plan`, `load_manifest`, the list-titles function) on a version-0 repo and asserts each raises `RepoFormatError`, and a companion that a repo with a current `course_settings.toml` but an unstamped manifest is refused with the manifest named
- [x] 5.6 In `cli.py`, add an `except RepoFormatError` branch to `_handle_cli_errors` and to `list-titles` (`mv` and `publish` already `die()` on any exception); verify with `CliRunner` tests that `update`, `mv`, `publish`, `prune`, `clean-manifest`, `find-local-orphans`, `find-canvas-orphans` and `list-titles` exit non-zero with the upgrade message and no traceback on a version-0 repo, and that `import`, `emit-workflow` and `setup` do not run the check

## 6. Test repair

- [x] 6.1 Repair the rest of the suite: call `make_current` in tests that build repos in `tmp_path`, and update assertions on exact manifest contents or call lists for the `_repo_format` entry and the fixture's new `course_settings/course_settings.toml` entry; verify `uv run pytest -q` passes

## 7. import writes the version

- [x] 7.1 In `imscc_import._write_course_settings_toml`, emit `format_version = FORMAT_VERSION` and `created_by = tool_version()` as the first lines, before every other key and comment; verify in `test_imscc_import.py` that they are the first two lines, parse as top-level keys with `tomllib`, and that `check_repo_format` passes on the imported repo without `upgrade`

## 8. Hash exclusion and removal of the old warning

- [x] 8.1 Add `format_version`, `created_by` and `upgraded_by` to `_NON_METADATA_SETTINGS_KEYS` in `sync.py` (decision 9); verify with a test that changing only those keys between two `run_sync` calls produces no `course.update` call, and a test that they never appear in the course-metadata payload
- [x] 8.2 Remove the nested-`tab_configuration` warning block in `sync.py` (around line 1420) (decision 4: `upgrade` now does the fix, once); replace its existing test with one asserting that `run_sync` leaves a nested key in place and does not apply the tabs (Canvas mocked)

## 9. `upgrade` subcommand and migration 0 -> 1

- [x] 9.1 Implement `run_upgrade(repo, noop)` per decision 6: start version is the minimum over the repo and its manifests; refuse when newer than the tool; apply each registered migration in order, printing its change lines and writing manifests then `format_version` after each step; then run the placement check; report "already current" when nothing changed; verify with unit tests using a fake two-step migration registry, including a failing second step that leaves `format_version` at the first step's result
- [x] 9.2 Implement the `course_settings.toml` version edits with `tomlkit` (decision 5): set or insert `format_version` at the top, create a missing file containing only the version keys, and append one `upgraded_by` entry `"<tool version> on <YYYY-MM-DD>: <from> -> <to>"` per run that changed `format_version` (never touching `created_by`); verify with tests that comments and key order elsewhere survive byte-for-byte, that a second upgrade appends a second entry, and that a manifest-only upgrade adds no entry
- [x] 9.3 Implement migration 0 -> 1 (decision 7): the legacy manifest rename (`.canvas-manifest.toml` -> `.manifest-canvas.toml` when the target is absent; warning and no change when both exist) and stamping every `.manifest-*.toml` with version 1; verify with tests for both rename cases and for a repo with two manifests (default and a second config) that are both stamped and otherwise unchanged
- [x] 9.4 Add the `upgrade` click command (optional REPO resolved with `_resolve_repo`, `-n/--noop`, `RepoFormatError` -> `die()`); verify with `CliRunner` tests for a normal run, `--noop` writing nothing, and a newer-than-tool repo refusing
- [x] 9.5 Add an end-to-end test: import the IMSCC fixture into `tmp_path`, strip the version keys and nest `tab_configuration` under `[default_post_policy]` to simulate an old repo, run `upgrade`, and assert the spec's "Upgrade an old repo" and "Old import with nested tab_configuration" scenarios, and that `run_sync(check_all=True)` then runs without a format error

## 10. Remove superseded code

- [x] 10.1 Delete `manifest.migrate_legacy_manifest()`, replace its callers in `cli.py`, `clean_manifest.py` and `sync.py` with `manifest_path_for()`, and remove the legacy-manifest handling in `mv.py` (around line 632); verify with a test that `run_sync` on a version-1 repo containing a stray `.canvas-manifest.toml` does not rename it, and that `uv run pytest -q` passes after updating tests that exercised the old rename

## 11. Core subcommands consistency

- [x] 11.1 Review `update`, `import`, `mv` and `publish` together against the spec: `import` writes the version; the library operations behind `update`, `mv` and `publish` check it (and fix `tab_configuration`) and never change the version; none of them performs a migration. Verify by the tests in groups 5 and 7 and a full `uv run pytest -q` run

## 12. Documentation

- [x] 12.1 Add the format-version rule to the project `CLAUDE.md` (decision 11) and verify it names `repo_format.FORMAT_VERSION`, what counts as breaking, and the requirement to add a migration with tests
- [x] 12.2 README.md: document `upgrade` (usage, `--noop`, the refusal messages, running it on every machine that holds a manifest), the three new `course_settings.toml` keys in the `course_settings.toml` reference, the automatic `tab_configuration` correction (replacing any text about the old warning), and how to see the installed tool version; add `upgrade` to the Contents list; verify each new section is linked from Contents
- [x] 12.3 README.md and ARCHITECTURE.md: replace every instruction to commit manifest files (README lines ~149, ~479, ~2414, ~2420; ARCHITECTURE ~1500) with a statement that manifests are local, must never be committed, and are excluded by `import`'s default `.gitignore`; verify with `grep -n -i "commit" README.md ARCHITECTURE.md | grep -i manifest` showing no remaining advice to commit them
- [x] 12.4 ARCHITECTURE.md: add a repo format / `upgrade` section covering `repo_format.py`, the library call sites table from decision 2, the `tab_configuration` placement fix, the migration registry and step-by-step write order, the `_repo_format` manifest entry and reserved-key handling, hatch-vcs versioning, and the removal of `migrate_legacy_manifest()`; update the manifest file-format example to show `_repo_format` and the `update` workflow description to mention the format check
- [x] 12.5 TESTING.md: describe the new test areas and the `make_current` helper, note the fixture's new `course_settings.toml`, and update the test count after `uv run pytest -q`
- [x] 12.6 Remove item 1 from NEW_FEATURES.md, and update item 2 to note that `tomlkit` is now a dependency used for editing `course_settings.toml`; check TODO.md for anything this change affects and verify no completed item remains there
- [x] 12.7 In the final report to the user, remind them to tag the current commit `v0.2.0` (they handle tags and pushes) so hatch-vcs produces readable versions
