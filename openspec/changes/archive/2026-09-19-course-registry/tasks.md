# Tasks

## 1. Registry module

- [x] 1.1 Add `course_registry.py` that reads `~/.config/markdown-to-canvas/course_registry.toml` (string or `{ path, config }` entries, `~` expansion, relative path and unknown-key errors) and verify with unit tests in `tests/test_course_registry.py` that use a temporary home directory
- [x] 1.2 Add `resolve_course(arg)` (path first, then key; missing key lists registered keys; missing registered directory names the key) and verify with tests for path-wins, key-fallback, unknown key, deleted directory, and a broken registry that does not affect a path argument
- [x] 1.3 Add term-name lookup (`terms/<name>.toml`, path wins, error lists available terms) and verify with unit tests
- [x] 1.4 Add `add_entry()` that writes a key with `tomlkit`, creates the file and directory when absent, refuses an existing key, and verify with tests that hand-written comments and other entries survive

## 2. Shared CLI resolution

- [x] 2.1 Add a shared `COURSE_DIR` argument decorator and one resolving helper in `cli.py` that applies `--config` > entry config > default, prints `Course dir:` (with the key when one was used), and replaces `_resolve_repo`; verify with CliRunner tests on `update --check-all` (no token needed) for path, key, walk-up and unknown-key cases
- [x] 2.2 Switch `update`, `publish`, `clean-manifest`, `upgrade` and `generate-due-dates` to the helper and remove their `Repo:` lines; verify each with a CliRunner test that the first output line is `Course dir:` and that a key resolves from an unrelated cwd
- [x] 2.3 Switch `find-canvas-orphans`, `find-local-orphans`, `list-titles` and `emit-workflow` from a `"."` default to walk-up via the helper; verify with tests run from a course subdirectory and from a directory with no course (error asks for the argument)
- [x] 2.4 Switch `prune` to the helper while keeping the argument required, printing the resolved directory before any prompt or Canvas call; verify with a test using a mocked Canvas that the `Course dir:` line precedes the confirmation and that omitting the argument is a usage error
- [x] 2.5 Rename every `REPO`/`COURSE_DIR` metavariable and docstring to `COURSE_DIR`; verify with a test that walks the click command tree and asserts no `REPO` argument remains in any `--help` output for the listed commands
- [x] 2.6 Verify registry `config` handling with tests: entry config used, `--config` overrides it, a path argument ignores it, and the manifest name follows the chosen config

## 3. Term file and table selection

- [x] 3.1 Remove `relative_table` from `_TERM_KEYS` and `Term`, and make `load_term` report it as an unknown key with a message that mentions `--table`; verify by updating `tests/test_relative_dates.py`
- [x] 3.2 Change `select_table` to use `--table`, else `default`, and to fail with the table list otherwise (including a lone non-`default` table); verify by updating `tests/test_relative_dates.py` and `tests/test_generate_due_dates.py` to cover every scenario in the `relative-due-dates` delta
- [x] 3.3 Make `generate-due-dates` accept a term name as well as a path and take `COURSE_DIR` after it; verify with a CliRunner test running `generate-due-dates 2026Fall 142 --noop` from an unrelated directory against a temporary home
- [x] 3.4 Drop the `relative_table` lines from the commented example written by `import` in `imscc_import.py`; verify that `tests/test_imscc_import.py` still finds an example that parses as an empty TOML document and that it no longer mentions `relative_table`

## 4. Format version 3

- [x] 4.1 Extend `UpgradeState` with an optional document for `course_settings/term_dates.toml`, written where the settings document is written and skipped under `--noop`; verify with a test that `upgrade --noop` writes neither file
- [x] 4.2 Bump `FORMAT_VERSION` to 3 and add `MIGRATIONS[2]` (remove an uncommented `relative_table` from the in-repo term file; rename a lone non-`default` table; drop an empty `default` beside one other table; otherwise print the `--table` notice; only for a settings file below version 3); verify with tests for each scenario in the `repo-format-version` delta
- [x] 4.3 Verify migration layout preservation with a fixture that has comments, blank lines and both inline and `[[...items]]` item layouts, asserting that everything outside the renamed table is byte-identical
- [x] 4.4 Update the existing format-version tests (`tests/test_repo_format.py`, `tests/test_repo_format_enforcement.py`) for version 3 and verify the full suite passes

## 5. Token fallback and completion

- [x] 5.1 Load `~/.config/markdown-to-canvas/.env` after the existing `load_dotenv` call with `override=False`, quiet when absent; verify with a subprocess-free test of the loading function covering local-beats-shell-beats-fallback, and that the existing import-order comment still holds
- [x] 5.2 Add `shell_complete` callbacks for `COURSE_DIR` (registry keys plus directories) and `TERM_FILE` (term names plus files) that return nothing and raise nothing on a missing or broken registry; verify with tests calling the callbacks and with a check that a key added after `install-completion` is offered without reinstalling
- [x] 5.3 Run `install-completion --shell bash` into a temporary home and exercise the generated script's completion entry point against a temporary registry to confirm the keys appear in a real completion request

## 6. import --register and the other core subcommands

- [x] 6.1 Add `import --register KEY`: reject an existing key before writing anything, register only after a successful import, print the key and path; verify with tests for a new key, a taken key (output directory not created), a failing import (registry unchanged) and preserved registry comments
- [x] 6.2 Apply the change across the core subcommands and record the result: confirm `update` and `publish` use key resolution and `Course dir:`, `import` gets `--register`, and `mv` is left unchanged by decision; verify by re-reading each command's help output and adding the mv exception to the TODO.md note in 7.3

## 7. Documentation

- [x] 7.1 Update README.md: a section on the registry and term files (file format, per-entry `config`, key-versus-path rules, walk-up rules including `prune`), `import --register`, the token fallback file, the `COURSE_DIR` rename, the new `generate-due-dates` table rule and term names, and the removal of `relative_table` from "The term file"; verify by grepping README.md for `relative_table` and `REPO` and confirming only intentional mentions remain
- [x] 7.2 Update ARCHITECTURE.md: replace "Repo-root resolution" with the shared resolver, describe the registry module, precedence rules and completion, document migration 2 -> 3, and fix the stale reference to a `--repo` flag; verify by grepping for `--repo` and `_resolve_repo`
- [x] 7.3 Edit TODO.md: remove the "Registry of courses, term" item and add a note that `-t`, `-s` and `mv` could resolve their paths relative to a registered course (for example `142:pages/a.md`); verify the item is gone and the note is present
- [x] 7.4 Update TESTING.md if it lists per-command test files or the format-version tests, and verify the run of the whole suite passes with `uv run pytest`
