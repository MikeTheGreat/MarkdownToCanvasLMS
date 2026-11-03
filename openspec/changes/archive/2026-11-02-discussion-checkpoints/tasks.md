# Tasks

## 1. Live verification of the unverified Canvas behavior (sandbox course 2758791 only)

- [x] 1.1 Check U2: create a checkpointed discussion with GraphQL, then send `updateDiscussionTopic` with both checkpoints where one `dates` entry has no `dueAt`; record whether that checkpoint's due date is kept or cleared. Verify by recording the result in ARCHITECTURE.md's checkpoint notes, and delete the test topic.
- [x] 1.2 Check U4 and U5: on a checkpointed sandbox discussion, attach a rubric with the existing REST association code (`associate_rubric_with_assignment` on the parent assignment id) and set `group_category_id` over REST; confirm via `GET .../discussion_topics/:id` that `assignment.checkpoints` are unchanged and the rubric is on the parent. Record the result in ARCHITECTURE.md; if either breaks the checkpoints, stop and raise it with the user before task group 5.
- [x] 1.3 Check U1 as far as possible without admin rights: record the flag JSON for the sandbox course's account, and note in ARCHITECTURE.md which states are verified and which come from Canvas's feature-flag semantics.

## 2. Format version

- [x] 2.1 Bump `repo_format.FORMAT_VERSION` to 16 and add `_migrate_15_to_16` to `MIGRATIONS` (stamps version 16 in `course_settings.toml` and every manifest, changes nothing else); verify with tests in `test_repo_format.py` for a version-15 repo, `--noop`, and a lagging manifest, and that `test_repo_format_enforcement.py` still passes.

## 3. Validation (frontmatter and due_dates)

- [x] 3.1 Add parsing and validation of the `checkpoints` block (exact keys, `points_possible`, optional `due_at`, `replies_required` >= 1, unknown keys, block on a non-discussion), and the conflict rule for top-level `points_possible`/`due_at`; verify with unit tests for each scenario in `specs/discussion-checkpoints/spec.md` "The checkpoints frontmatter block" and "Keys that conflict with checkpoints".
- [x] 3.2 Accept `reply_to_topic_due_at` and `reply_to_others_due_at` in `due_dates` entries with the same sentinel handling as `due_at`; add the mismatch errors (a `due_at` key for a checkpointed discussion, checkpoint keys for anything else, either key in a virtual entry) and the reply-to-topic-before-reply-to-others order check; verify with tests in `test_due_dates.py` and the virtual-entry tests.
- [x] 3.3 Make validation failures stop only the affected discussion (no upload, no dates sent) and make the run exit nonzero; verify with a `run_sync` test that other files still upload and the exit status is nonzero.

## 4. Canvas API layer (`canvas_api.py`)

- [x] 4.1 Add `discussion_checkpoints_enabled(course)` (account flag GET; `on`/`allowed_on` true, `off`/`allowed` false, refused lookup -> unknown) and cache the result per run; verify with mocked-HTTP unit tests for each state and for a 403.
- [x] 4.2 Add `set_discussion_checkpoints(course, topic_id, reply_to_topic, reply_to_others, unlock_at, lock_at)` (GraphQL `updateDiscussionTopic` with `assignment: {forCheckpoints: true}`) and `remove_discussion_checkpoints(course, topic_id, points_possible)` (`setCheckpoints: false`); map the flag-disabled and replies-exist GraphQL errors to distinct exceptions; verify with unit tests asserting the exact GraphQL variables and the error mapping.
- [x] 4.3 Extend the discussion create/update result with the fetched topic's `is_checkpointed`, `discussion_subentry_count` and current checkpoint dates, and let `create_or_update_discussion` take a flag that drops `points_possible`, `due_at`, `unlock_at`, `lock_at` from the nested `assignment`; verify with unit tests.
- [x] 4.4 Add the same functions to the dry-run/noop Canvas doubles (`DryRunCanvas`, `NoopCanvas`) so `--noop` and `--check-as-new-course` report checkpoint actions without writing; verify with tests in `test_update_noop.py` and `test_check_as_new_course.py`.

## 5. Upload paths in `update` (`sync.py`)

- [x] 5.1 In `_upload_discussion`, for a file with `checkpoints`: run the flag check (feature-off error text from the spec, including the three alternative keys and the placeholder suggestion); resolve checkpoint dates (frontmatter, then `due_dates` overrides, `KEEP` filled from the topic's current checkpoint dates, `CREATE_NONE_THEN_KEEP` per design D12); run REST without the four parent keys when the topic is already checkpointed and with sum/reply-to-others date when it is new or plain; then call `set_discussion_checkpoints`; then the rubric step. Verify with mocked-API tests: new discussion, plain discussion converted, already-checkpointed discussion (assert the four keys are never in the REST call), body-only edit, feature off (no create/update call at all), GraphQL failure after REST (manifest recorded, error reported).
- [x] 5.2 Handle the state transitions of design D10/D11: checkpointed in Canvas and no `checkpoints` in the file -> `remove_discussion_checkpoints` before REST when there are no replies, error when there are; plain in Canvas with replies and `checkpoints` in the file -> error without changes; `--noop` prints "Would turn off checkpoints". Verify with mocked-API tests for each case, including that removal never happens when the file's `checkpoints` key fails validation.
- [x] 5.3 In `_apply_due_dates_only`, route checkpointed discussions to `set_discussion_checkpoints` (points and `replies_required` from the file) and cache `resolved_dates` with `unlock_at`, `reply_to_topic_due_at`, `reply_to_others_due_at`, `lock_at`; verify with tests that a change to one checkpoint date sends one GraphQL call and no REST `update_dates`, and that an unchanged entry sends nothing.
- [x] 5.4 Update `list-titles` and the "Checking due_dates coverage" step so a checkpointed discussion's entry counts as dated and shows its reply-to-others date; verify with the existing `list-titles` tests extended for a checkpointed entry.

## 6. Relative due dates and `generate-due-dates`

- [x] 6.1 Add `reply_to_topic_offsets` to `relative_dates.py` (key validation, not on virtual items or non-discussion types, empty list error, arithmetic from the overall date, ABS_TIME, term-range check, later-than-overall error); `ASSIGNMENT` anchors keep counting from the overall date. Verify with tests in `test_relative_dates.py` for every scenario in `specs/relative-due-dates/spec.md`.
- [x] 6.2 In `generate_due_dates.py`, write `reply_to_topic_due_at`/`reply_to_others_due_at` (removing `due_at`) for such items, remove the checkpoint keys when an item loses `reply_to_topic_offsets`, show both in the plan, apply `dont_reschedule_dates_before` per key, and extend the date-order check; verify with `CliRunner` tests in `test_generate_due_dates.py` including the byte-identical-outside-changed-rows check.

## 7. Date placeholders

- [x] 7.1 Make a `due_at` placeholder resolve to `reply_to_others_due_at` when the entry has it and no `due_at` (same sentinel errors); verify with tests in the date-placeholder test module for the default field, explicit `field=due_at`, and a `KEEP` value.

## 8. Import (`imscc_import.py`)

- [x] 8.1 Parse `sub_assignments` and `reply_to_entry_required_count` in `parse_topic_meta`; extend `_build_frontmatter` to render the nested `checkpoints` mapping with the comment line directly above `reply_to_others:` and each checkpoint's `due_at` commented out inside its mapping; write `reply_to_topic_due_at`/`reply_to_others_due_at` (and the parent's `unlock_at`/`lock_at`, no `due_at`) through `_collect_due_date`; omit top-level `points_possible`. Verify with a test fixture built from the sample export's topicMeta (both sub_assignments, required count 1) asserting the exact frontmatter text and the `due_dates` row, and that the written file parses back to a valid `checkpoints` block.
- [x] 8.2 Round trip: import a fixture with a checkpointed discussion, then run `update` against a mocked Canvas and assert the GraphQL variables carry the exported points, dates and reply-to-others count; verify by that test passing.

## 9. Other core subcommands

- [x] 9.1 `publish`: confirm that staging strips the `checkpoints` block with the rest of the frontmatter and that a placeholder on a checkpointed discussion shows the reply-to-others date; verify with a `test_publish.py` test.
- [x] 9.2 `mv`: confirm moving a checkpointed discussion keeps its frontmatter and `due_dates` entry unchanged; verify with a `test_mv.py` test.
- [x] 9.3 `cp`: confirm a copied checkpointed discussion gets the existing "dates live in the source's course_settings.toml" warning, now naming the checkpoint keys when present; verify with a `test_cp.py` test.

## 10. End-to-end check in the sandbox course

- [x] 10.1 Add a checkpointed discussion (with a rubric and a group set/group category) to `CLAUDE_NOTES/sandbox_course/`, run `update`, and verify through the API that Canvas has the two checkpoints, the sum of points, no parent due date, the reply-to-others count and the rubric; then change one checkpoint date in `due_dates`, rerun, and verify only that date changed; then remove the block, rerun, and verify checkpoints are off. List the new content in the sandbox README.md.

## 11. Documentation

- [x] 11.1 README.md: the `checkpoints` frontmatter block, the two `due_dates` keys, `reply_to_topic_offsets`, the feature-off error and its alternatives, and that placeholders show the reply-to-others date; verify by reading the sections against the specs.
- [x] 11.2 ARCHITECTURE.md: the upload algorithm for checkpointed discussions (REST/GraphQL split, transitions, dates-only pass, `resolved_dates` keys), import of `sub_assignments`, and the results of task group 1 added to the checkpoint notes; verify that no section still says discussions are REST-only.
- [x] 11.3 TODO.md: keep the "placeholder for the reply-to-topic date" item; remove anything this change completes. BUGS.md: check for discussion-related entries this change fixes. Verify by reading both files.
