# Tasks

## 1. Repo format

- [x] 1.1 Add a shared helper that inserts a top-level key into a tomlkit `course_settings.toml` document before the first table or array-of-tables header (at the end if there is none), or appends names to an existing array, preserving the rest of the file; verify with unit tests for a file with tables, a file without, and an existing key
- [x] 1.2 Bump `repo_format.FORMAT_VERSION` to 7 and add `_migrate_6_to_7` to `MIGRATIONS`: add `group_categories = []` via the helper when the settings file (at version < 7) has no such key, and record version 7 in the manifests; verify with tests in `test_repo_format.py` that upgrading a version-6 repo with `group_category_id: 12345` adds the key above the first table, keeps an existing `group_categories` line, reports under `--noop` without writing, leaves `.md` files byte-identical, and that the enforcement tests pass at version 7

## 2. Canvas API and dry run

- [x] 2.1 Add `get_group_category_ids(course)` and `create_group_category(course, name)` to `canvas_api.py`; verify with mocked-`canvasapi` unit tests, including a duplicate-name listing that is reported rather than silently picking one
- [x] 2.2 Add the same two methods to `dryrun.DryRunCanvas` (fabricated IDs for created names, no Canvas contact); verify in `test_check_all.py` that a listed name resolves and no HTTP is attempted
- [x] 2.3 Add the change safeguard to `_do_discussion` and `_do_assignment`: omit an unchanged group set/group category, allow adding one only with no replies/submissions (missing count treated as "has replies"), refuse switching; verify with mocked tests for each of the four cases in the spec's safeguard requirement

## 3. update

- [x] 3.1 Parse and validate `group_categories` before phase 0 (non-array value, non-string or empty element, duplicate names are fatal config errors) and keep the key out of course metadata; verify with tests that a bad list stops the run before any Canvas call, that an empty list makes no group set/group category request, and that `update_course_metadata` never receives the key
- [x] 3.2 In the full run, after the course-settings phase, fetch the group set/group category map when the list is non-empty, create each missing listed name (printing a line per creation), and store names and IDs on `SyncContext`; verify with mocked tests: brand-new course creates, existing is not re-created, unlisted Canvas entries untouched, and a run syncing several group discussions and assignments lists group sets/group categories exactly once (no IDs written to the manifest)
- [x] 3.3 Add `_resolve_group_category_id` (name must be listed even if it exists on Canvas; created on demand if listed but missing; integers pass through) and call it from `_upload_discussion` and `_upload_assignment` before any Canvas write, failing the file into `ctx.errors` when unresolved; verify with tests that an unlisted name (including one that exists on Canvas) uploads nothing, the error says to add it to `group_categories`, it is in the error summary and `update` returns failure, while other files still sync
- [x] 3.4 Send the resolved ID as a top-level `group_category_id` on discussions (ungraded and graded, alongside the nested `assignment` dict) and in the assignment params for assignments; verify with tests asserting the kwargs passed to `create_or_update_discussion` / `create_or_update_assignment`, including the OL-3/OL-4 two-config case resolving to different IDs
- [x] 3.5 Wire the same map and resolution into the targeted sync (`-t`/`-s`), including on-demand creation; verify with a targeted-sync test for a group discussion in a course that lacks the group set/group category
- [x] 3.6 Make `update --check-all` report an unlisted name exactly as a real run does; verify in `test_check_all.py`
- [x] 3.7 Confirm an announcement with `group_category_id` produces the existing ignored-field warning and is posted without it; verify with a test

## 4. import

- [x] 4.1 In `parse_topic_meta`, read the topic-level `has_group_category`/`group_category` and write `group_category_id: "<name>"` as active frontmatter in the discussion; verify with a fixture shaped like the real export (graded discussion whose nested `<assignment>` has `has_group_category` false)
- [x] 4.2 In `parse_assignment_settings`, replace the dead `<group_category_id>` read with `<group_category>` (when `has_group_category` is true); update the existing tests that used the fake tag to the real export shape; verify the imported assignment's frontmatter
- [x] 4.3 Collect distinct names in first-seen order and always write the top-level `group_categories` array to the imported `course_settings.toml` (before any table), following the toml-writer style; verify with tests that 15 items using one name produce `group_categories = ["Project Groups"]` and that an export without group sets/group categories writes `group_categories = []`
- [x] 4.4 Round-trip test: import a fixture with a group discussion and a group assignment, then run `update` against a mocked empty course; verify the group set/group category is created and both items are sent with its ID

## 5. Other subcommands

- [x] 5.1 `cp`: append each copied file's string `group_category_id` that the destination's `group_categories` lacks (once per name, creating the key via the 1.1 helper if absent), report each addition, report only under `--noop`, and keep the numeric warning; verify with tests in `test_cp.py` for missing name, present name, absent key, several files sharing a name, `--noop`, and numeric ID
- [x] 5.2 `mv` and `publish`: confirm no change is needed (a moved group discussion keeps its frontmatter; `publish` renders a group discussion like any other); verify with one test each
- [x] 5.3 Run the full test suite (`uv run pytest`) and verify it passes

## 6. Live verification

- [x] 6.1 Ask the user to run the design.md live-verification steps on a scratch Canvas course (or run them with the user's go-ahead), record the results for each "Unverified" row in design.md's Canvas behavior table, and fix anything that differs

## 7. Documentation

- [x] 7.1 README.md: document `group_category_id` on discussions and assignments with a name as the normal form, the `group_categories` list (every name must be listed), creation by `update`, the hard error, the change safeguard, that removing `group_category_id` does not un-group an item on Canvas (do that in Canvas), import behavior, `cp` merging names, and the version-7 upgrade; replace the "tool does not create or manage group sets" note; use "group set/group category" throughout; verify by reading the Discussion, Assignment, course_settings.toml, `cp` and upgrade sections
- [x] 7.2 ARCHITECTURE.md: describe resolution, creation, the safeguard, why IDs are not cached in the manifest, the import parsing, `cp` merging, the top-level-key helper and the format-7 migration; verify the course-settings upload table lists `group_categories`
- [x] 7.3 TODO.md: revise "Group sets and group assignments" to cover only what remains (groups and membership); BUGS.md: confirm no related entry needs removal
