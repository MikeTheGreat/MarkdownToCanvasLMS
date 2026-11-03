# Design

## Context

See proposal.md for the motivation and specs/ for the required behavior. Relevant current state:

- `_upload_discussion` (`sync.py`) builds REST params: topic-level settings plus a nested `assignment` dict (`points_possible`, `due_at`, `lock_at`, `unlock_at`, `omit_from_final_grade`, `assignment_group_id`), with dates from a matching `due_dates` entry overriding frontmatter. `canvas_api._do_discussion` GETs an existing topic before `topic.update(...)`, so the topic's current state is already fetched on every update.
- `_apply_due_dates_only` sends changed `due_dates` values for files not uploaded in full this run, through `canvas_api.update_dates`, which for a discussion is a REST `topic.update(assignment=date_fields)`. Its `resolved_dates` cache holds `unlock_at`/`due_at`/`lock_at`.
- `canvas_api.graphql()` already exists (used by `update_post_policy`).
- `import` moves an item's dates into `due_dates` (`_collect_due_date`) and writes them as commented-out frontmatter lines (`_build_frontmatter`, which renders only scalars).
- `relative_dates.py` validates item keys against `_ITEM_KEYS` and computes one due date per item; `generate_due_dates.py` writes `unlock_at`/`due_at`/`lock_at` and checks their order (`_DATE_ORDER`).

### Canvas behavior this design depends on

Verified live on 2026-11-02 in sandbox course 2758791 (Cascadia), with the API token (script kept outside the repo; results also go into ARCHITECTURE.md):

1. GraphQL `createDiscussionTopic` with `assignment: {courseId, forCheckpoints: true}` and two `checkpoints` (`checkpointLabel`, `pointsPossible`, `repliesRequired`, `dates: [{type: "everyone", dueAt, unlockAt, lockAt}]`) creates a checkpointed discussion. Sending `pointsPossible` on the parent is rejected: "Cannot set points_possible in the parent assignment for checkpoints."
2. REST PUT of `title`, `message`, `published` on a checkpointed topic leaves the checkpoints unchanged.
3. REST PUT of `assignment[points_possible]`, `assignment[due_at]`, `assignment[unlock_at]`/`assignment[lock_at]` on a checkpointed topic is accepted (200) and changes only the parent: points no longer equal the sum, the parent gets a due date, and the parent's availability dates differ from the checkpoints'. Canvas does not reject or repair this.
4. GraphQL `updateDiscussionTopic` with `assignment: {forCheckpoints: true}` and two `checkpoints` replaces points, due dates, availability dates and `reply_to_entry_required_count`, and repairs the parent (points = sum, `due_at` null, availability synced).
5. The same mutation on a plain graded discussion created over REST (10 points, a due date, no replies) converts it to a checkpointed one in place (same topic and assignment id).
6. `updateDiscussionTopic` with `setCheckpoints: false, assignment: {forCheckpoints: false, pointsPossible: 7}` removes the checkpoints, leaving a plain graded discussion with 7 points, no due date and `reply_to_entry_required_count` null.
7. The REST topic JSON has `is_checkpointed`, `reply_to_entry_required_count`, `discussion_subentry_count`, and `assignment.has_sub_assignments` and `assignment.checkpoints` (each with `tag`, `points_possible`, `due_at`, `unlock_at`, `lock_at`, `overrides`).
8. `GET /api/v1/accounts/<course.account_id>/features/flags/discussion_checkpoints` returned `{"state": "allowed_on", "context_type": "Account", ...}` for a token whose user is not an account admin (`GET /api/v1/accounts` returns `[]`). The course-level `/courses/:id/features/flags/discussion_checkpoints` returns 404 (the flag is account-level), and the course's `features/enabled` list does not include it.

From Canvas source (instructure/canvas-lms `master`, read 2026-11-02), not measured:

9. With the flag off, the checkpoint services raise "discussion_checkpoints feature flag must be enabled" (`Checkpoints::DiscussionCheckpointCommonService#validate_flag_enabled`), surfaced as a GraphQL error.
10. `updateDiscussionTopic` refuses to enable checkpoints on a topic that has replies: "Checkpoints cannot be enabled after replies have been made."
11. Checkpoints cannot be created when the course has "Restrict Quantitative Data" on.
12. The IMSCC export nests `<sub_assignments><sub_assignment identifier tag>` (full assignment fields) inside the topic's `<assignment>` and writes `<reply_to_entry_required_count>` at the topic level. Confirmed by the sample export `coll101-ol3-12086-f26-college-strategies-export.imscc`.

Unverified, and needed before relying on them (tasks include live checks):

- U1. Flag states other than `allowed_on`: whether `off` and `allowed` mean "off" for this course, and `on` means "on". (Canvas's feature-flag semantics say so.)
- U2. Whether a checkpoint `dates` entry without `dueAt` clears that checkpoint's due date or leaves it unchanged. This decides how `KEEP` is implemented; getting it wrong would erase a due date.
- U3. What `setCheckpoints: false` does to checkpoint grades and submissions when students have replied. Not tested; the design refuses that case (see Decisions).
- U4. Whether attaching a rubric to the parent of a checkpointed discussion with the existing REST association code works and leaves the checkpoints alone. The sample export shows a rubric on the parent, made in the UI.
- U5. Whether the REST `group_category_id` update on a checkpointed topic leaves the checkpoints alone. The sample export has a group set/group category with checkpoints, made in the UI.

## Goals / Non-Goals

**Goals:**
- Never leave a checkpointed discussion's parent inconsistent with its checkpoints (fact 3).
- Keep one code path per operation for plain and checkpointed discussions where possible, adding a GraphQL step rather than replacing the REST upload.

**Non-Goals:**
- Per-section or per-student checkpoint date overrides (`dates` entries of type `override`). The tool does not manage overrides for other content either.
- Choosing the reply-to-topic date in a `replace_date_with` placeholder (added to TODO.md).
- Detecting checkpoint changes made by hand in Canvas. As for other content, the file is the source of truth and the next upload overwrites them.

## Decisions

Confirmed with the user in the explore session of 2026-11-02:

- **D1. Frontmatter shape.** `checkpoints: {reply_to_topic: {points_possible, due_at}, reply_to_others: {points_possible, replies_required, due_at}}`, with `unlock_at`/`lock_at` top-level and shared. Keys follow Canvas's tags except that `reply_to_entry` becomes `reply_to_others` (the user chose this name, avoiding "entry"). Shared availability dates match fact 4 (Canvas syncs checkpoint availability to the parent) and the sample export, where all three are identical.
- **D2. `due_dates` keys** `reply_to_topic_due_at` and `reply_to_others_due_at`, replacing `due_at` for a checkpointed discussion. Two separate entries with invented names were rejected because entries match Canvas items by title and the checkpoints have no titles of their own.
- **D3. Relative dates.** The item's ordinary `offsets` give the overall (reply-to-others) date; `reply_to_topic_offsets` count from it. The user thinks of the reply-to-others date as the discussion's due date. An `ASSIGNMENT` anchor uses the overall date, and so does a placeholder's `due_at`.
- **D4. Conflicts are errors**: top-level `points_possible`/`due_at` with `checkpoints`; a `due_at` key in a checkpointed discussion's entry; checkpoint keys in a non-checkpointed discussion's entry.
- **D5. Feature off**: error, discussion not uploaded, with the suggested alternatives (`points_possible`, `due_at`, `require_initial_post: true`, and the earlier deadline in the body via a placeholder).
- **D6. Removing `checkpoints:` turns checkpoints off.** Canvas's refusal to add checkpoints after replies becomes a clear error.
- **D7. Import writes `checkpoints:`**, with a comment above `reply_to_others:` saying these are students' replies to other students' posts.
- **D8. Format version 16**, with a migration that only records the version.

Proposed by this design (not yet confirmed; also listed under Open Questions):

- **D9. Upload order for a checkpointed discussion.** (a) Validate and check the flag. (b) Run the existing REST create/update. When the Canvas topic is already checkpointed, the nested `assignment` omits `points_possible`, `due_at`, `unlock_at` and `lock_at` (fact 3); assignment group, `omit_from_final_grade` and topic settings still go over REST. When the topic is new or still plain, REST sends `points_possible` = the sum and `due_at` = the reply-to-others date, so the topic is created as a graded discussion and is sensible even if step (c) fails; step (c) then converts it (fact 5) and clears the parent due date. (c) Run `updateDiscussionTopic` with `assignment: {forCheckpoints: true}`, both checkpoints, `repliesRequired`, and `dates: [{type: "everyone", dueAt, unlockAt, lockAt}]`. (d) Rubric as today. Alternative: create with `createDiscussionTopic` for new discussions. Rejected because fact 5 shows REST-create-then-convert works, it keeps one creation path for plain and checkpointed discussions, and it covers existing manifest entries with the same code. Risk: if step (c) fails after (b) created the topic, a plain graded discussion exists in Canvas; it is recorded in the manifest so the next run converts it rather than creating a duplicate, and the error is reported.
- **D10. Converting and removing use the topic state already fetched.** `_do_discussion` already GETs an existing topic; its `is_checkpointed` and `discussion_subentry_count` decide: plain + `checkpoints:` + replies → error (fact 10), checkpointed + no `checkpoints:` + replies → error, checkpointed + no `checkpoints:` + no replies → `setCheckpoints: false` (with `forCheckpoints: false` and the file's `points_possible`) *before* the REST update, so REST never writes parent points/dates onto a checkpointed topic.
- **D11. Safeguards for removing checkpoints** (deletes Canvas data): it happens only when the manifest maps the file to that topic (never by title match), the topic reports `is_checkpointed: true`, the file has no `checkpoints` key at all (a parse error or a `checkpoints` key that fails validation stops the file instead), and `discussion_subentry_count` is 0. With replies the tool refuses (U3). `--noop` reports "Would turn off checkpoints". No extra prompt is added: removing the block is an explicit edit, and with no replies there are no student grades on the checkpoints.
- **D12. `KEEP`, `NONE` and `CREATE_NONE_THEN_KEEP`** for checkpoint dates: measured on 2026-11-02 (U2), an omitted `dueAt`/`unlockAt`/`lockAt` in a checkpoint's `dates` entry leaves that value unchanged and an explicit `dueAt: null` clears it. So `KEEP` omits the key, `NONE` sends `null`, and `CREATE_NONE_THEN_KEEP` sends `null` when the topic is being created or converted and omits the key otherwise. (The design first proposed filling `KEEP` from Canvas's current dates; the measurement made that unnecessary.)
- **D13. Dates-only pass.** For a checkpointed discussion, `_apply_due_dates_only` resolves the four keys and sends one `updateDiscussionTopic` (points and `repliesRequired` taken from the file, so a dates-only call does not change them) instead of the REST `update_dates`. `resolved_dates` for such an entry holds `unlock_at`, `reply_to_topic_due_at`, `reply_to_others_due_at`, `lock_at`.
- **D14. Flag lookup** once per run, lazily, the first time a checkpointed discussion is about to be uploaded or have its dates sent: `GET /accounts/<course.account_id>/features/flags/discussion_checkpoints`; `on`/`allowed_on` → on, `off`/`allowed` → off (U1). If the GET fails (401/403/404), treat the state as unknown, proceed, and map the GraphQL error of fact 9 to the same feature-off error. The REST step (b) would already have created or updated the topic in that case; for a new topic, the partial result is a plain graded discussion recorded in the manifest, and the error says so.
- **D15. Import puts checkpoint dates in `due_dates`.** Following the existing pattern (`_collect_due_date` plus commented lines under the "Due dates are managed centrally" note), the two dates go into the entry as `reply_to_topic_due_at`/`reply_to_others_due_at` and each checkpoint's `due_at` is written commented out inside its mapping. `_build_frontmatter` gains support for one level of nested mappings and for a comment line attached to a key.
- **D16. Order check.** A reply-to-topic date after the reply-to-others date is an error in `generate-due-dates` and in `update`'s validation of `due_dates`/frontmatter.
- **D17. Checkpoints on a non-discussion** (an assignment, page or quiz file) is an error.
- **D18. Feature-off and conflict errors** make the run exit nonzero, as other per-file upload errors do.

## Risks / Trade-offs

- [REST writes corrupt the parent silently (fact 3)] → For checkpointed discussions, the four keys are removed from the REST params in one place, and a mocked-API test asserts they are never sent; the GraphQL step always runs after REST and repairs the parent (fact 4).
- [GraphQL step fails after REST succeeded] → Manifest records the topic; next run converts it. The error names the file and says the discussion is currently a plain graded discussion in Canvas.
- [Flag lookup refused at another college] → Fallback to the GraphQL error (D14).
- [Canvas changes the GraphQL schema] → GraphQL errors are reported verbatim with the file name; the mutation and inputs live in one function in `canvas_api.py`.
- [A GraphQL `updateDiscussionTopic` call may also reset settings we don't send] → Fact 4's test sent only `discussionTopicId`, `assignment` and `checkpoints`; title, body, published state and group were unchanged afterwards. The live verification task re-checks group set/group category and rubric (U4, U5).
- [Older tools] → Format bump (D8): an older tool refuses a version-16 repo.

## Migration Plan

- Manifest: no new keys; `resolved_dates` for a checkpointed discussion's entry gets different keys. An existing cache for a discussion that becomes checkpointed no longer equals the new resolution, so its dates are sent once, which is the wanted behavior. Migration 15 -> 16 only stamps version 16 in `course_settings.toml` and every manifest.
- Existing repos without checkpoints behave exactly as before.
- Rollback: an older tool refuses a version-16 repo; reverting the repo's `format_version` and removing `checkpoints:` blocks restores old behavior (checkpointed discussions in Canvas then get the REST parent writes of fact 3 and should be fixed by hand or by turning checkpoints off first).

## Open Questions

Choices made in this design that the user has not confirmed (D9-D18 above). Each can be changed without changing the overall approach:

- D9 REST-then-GraphQL creation rather than GraphQL creation.
- D11 refusing to remove checkpoints when the discussion has replies, rather than trying it.
- D12 `KEEP` omits the date from the mutation (measured to leave it unchanged).
- D14 flag-state mapping and the fallback when the lookup is refused.
- D15 import writing checkpoint dates to `due_dates` (commented out in the frontmatter) rather than live in the frontmatter, matching what import does for `due_at`.
- D16 a reply-to-topic date after the reply-to-others date being an error rather than a warning.
- D17 `checkpoints` on a non-discussion being an error rather than ignored with a warning.
- D18 nonzero exit status for the feature-off error.

Live verification on 2026-11-02 settled U2 (see D12), U4 and U5 (rubric association, group set/group category and publish leave checkpoints alone; a later GraphQL update keeps the rubric and group set/group category). U1 is only partly verified (`allowed_on` observed). U3 is avoided by D11.
