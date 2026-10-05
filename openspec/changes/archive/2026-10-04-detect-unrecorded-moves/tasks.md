# Tasks

## 1. Matching (pure)

- [x] 1.1 Create `src/markdown_to_canvas/unrecorded_moves.py` with a function that lists orphans from a manifest and repo root using `run_prune`'s rule (file gone, not a reserved key, not `external_module`). Have `run_prune` call it too. Verify with unit tests in `tests/test_unrecorded_moves.py` (reserved keys and external modules excluded) and that `tests/test_sync.py`'s prune tests still pass.
- [x] 1.2 Add a pure `match_orphans(orphans, orphan_canvas_info, local_items, manifest)` that returns new-file pairs and tracked-file pairs, each with the reason (file name, title, or both). Rules: equal Canvas type; equal last path component, or equal `pair_manifest.normalize_title` (not for `file`); an orphan whose Canvas item is gone never matches. Verify with unit tests covering every scenario under "Terms used by the unrecorded-move check" in the `unrecorded-move-detection` spec, plus the ambiguous one-to-many and many-to-one cases.
- [x] 1.3 Add the report formatter for stops (`OLD → NEW (reason)`, the `mv --after` command and the `update --new NEW` alternative per pair) and for duplicate warnings (both paths and IDs, `update --new TRACKED`, and `prune` with the note that it acts on every orphan and that deleting an assignment removes its submissions). Verify with unit tests asserting on the printed text.

## 2. Canvas read

- [x] 2.1 Add a function that fetches each orphan's Canvas item with `canvas_api._GETTERS` / `_object_key` and returns its title (`title`, `name` or `display_name` by type) or "gone" on a 404. Make no call when there are no orphans. Verify with mocked-Canvas tests: a 404 gives "gone", each type reads the right title field, and zero orphans makes zero calls.

## 3. update pre-flight

- [x] 3.1 Call the check in `run_sync` after the manifest is loaded and before `sync_course_settings`, skipping it when `check_all` is true. On any new-file pair, print the stop report and return with errors before any Canvas write. Print duplicate warnings and continue otherwise. Verify with `test_sync.py` integration tests (in `tests/test_unrecorded_moves.py`): an unrecorded move makes no create call and leaves the manifest byte-identical; a duplicate prints the warning and the sync proceeds; `--check-all` runs no check.
- [x] 3.2 Call the same check in `run_targeted_sync`, over the whole repo. Verify with a test where `-s` names an unrelated file and the run stops.
- [x] 3.3 Add the repeatable `--new PATH` option to `update` in `cli.py`, rejected together with `--check-all`, and pass it to both sync entry points. Before the check, validate every PATH (exists, is a file `update` syncs, matches at least one orphan) and stop with no change when any fails. Then remove the matching orphans' entries, flush the manifest once, and print one inline warning per removed entry. Verify with tests: the declare-new scenario creates the page and removes only the matching entry; a non-matching PATH stops with no Canvas or manifest change; `--new` with `--check-all` is a usage error.
- [x] 3.4 Allow `--new` to name a tracked file and remove the orphans matching it. Verify with the "Clearing an existing duplicate warning" scenario test.

## 4. mv --after

- [x] 4.1 Add `after: bool` to `run_mv` and `--after` to `mv_cmd`. With it, skip `resolve_dest` and `_do_move`, and validate per the `mv-after` spec (OLD gone, NEW exists, same content-type directory, some manifest has OLD without NEW). Verify with tests in `tests/test_mv.py` for each refusal scenario, checking that nothing on disk changes.
- [x] 4.2 Build the path map from manifest keys under OLD (file or directory) instead of walking OLD on disk, including quiz and question-bank inner renames. Verify with tests for a single file, a directory, and a quiz folder rename.
- [x] 4.3 Per manifest: rekey where OLD exists without NEW, and leave the manifest unchanged with a duplicate notice where both exist. Verify with the two-section test (`ol-3` has both, `ol-4` has only OLD).
- [x] 4.4 Make `compute_file_updates` treat a file at a NEW path as moved from OLD under `after`, and pass a `url_map` to `transform_links` for that file that keeps links resolving from NEW's folder and rebases links that resolve only from OLD's folder. Links to OLD in other files are rewritten as `mv` does. Verify with the two "Links inside the moved file" scenario tests and a test that `modules/week-1.md`'s link to OLD now points at NEW.
- [x] 4.5 Check that `module_order.toml`, `pinned_resources`, `front_page` and `dashboard_image` updates and `--noop`/`--verbose` behave as with plain `mv`. Verify with a test for a module file moved under `--after` and a `--noop` test asserting no file is written.

## 5. Other core subcommands

- [x] 5.1 Confirm that `import` and `publish` need no change: `import` writes no manifest and `publish` never contacts Canvas. Record this in ARCHITECTURE.md (task 6.2). Verify by grepping both modules for manifest use.
- [x] 5.2 Make the `update` stop message and the `mv --after` messages print commands in the form the user types (registered course key or path, and `--config` when the run used a non-default config), so the printed `update --new` targets the same manifest. Verify with a test using a non-default config.

## 6. Documentation

- [x] 6.1 README.md: in the `update` section, document the unrecorded-move stop, the duplicate warning and `--new PATH`. In the `mv` section, document `--after` with the git-move example. In the `prune` section, update the note that a rename orphans the old path to mention the new check. Verify by reading the rendered sections.
- [x] 6.2 ARCHITECTURE.md: describe the pre-flight check (position before phase 0, matching rules, one GET per orphan, `--new` removal and flush), the `mv --after` differences from `mv` (no `resolve_dest`, manifest-derived path map, per-manifest duplicate handling, moved-file link rule), and why `import` and `publish` are unaffected. Verify that the `mv` and `update` sections match the code.
- [x] 6.3 TODO.md: revise "Filesystem watcher for automatic move/rename tracking" to say that `update` now catches unrecorded moves and that a watcher could call `mv --after`. Check BUGS.md for related entries. Verify by reading both files.
- [x] 6.4 Run the full test suite (`uv run pytest`) and confirm it passes.
