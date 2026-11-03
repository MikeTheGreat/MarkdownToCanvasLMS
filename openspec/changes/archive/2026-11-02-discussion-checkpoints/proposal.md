# Proposal

## Why

Canvas's Discussion Checkpoints split a graded discussion into two graded parts with their own points and due dates: the student's reply to the topic, and a required number of replies to classmates' posts. Cascadia's account has the feature turned on and the user wants to use it, but the tool cannot express, upload or import checkpoints. Today `import` of a checkpointed discussion produces a plain graded discussion with no due date (the parent assignment has none), and `update` would upload exactly that, silently losing both checkpoint dates.

## What Changes

- A discussion's frontmatter MAY contain a `checkpoints:` block with two entries, `reply_to_topic` and `reply_to_others`, each with `points_possible` and `due_at`; `reply_to_others` also has `replies_required` (the number of replies). With `checkpoints:` present, a top-level `points_possible` or `due_at` is an error (the parent's points are the sum, and it has no due date of its own); `unlock_at` and `lock_at` stay top-level and apply to both checkpoints. Without `checkpoints:`, nothing changes.
- `due_dates` entries in `course_settings.toml` gain two keys, `reply_to_topic_due_at` and `reply_to_others_due_at`, used instead of `due_at` for a checkpointed discussion. They accept the same values as `due_at` (a date, `NONE`, `KEEP`, `CREATE_NONE_THEN_KEEP`). A plain `due_at` in the entry of a checkpointed discussion is an error, and so are the checkpoint keys in the entry of a discussion without `checkpoints:`.
- `[relative_due_dates]` items gain `reply_to_topic_offsets`. The item's ordinary `offsets` compute the overall due date (the reply-to-others date); `reply_to_topic_offsets` are applied to that date to give the reply-to-topic date. `generate-due-dates` writes the two checkpoint keys instead of `due_at` for such an item. An `ASSIGNMENT` anchor that names a checkpointed discussion counts from its overall (reply-to-others) date.
- A `replace_date_with` placeholder that selects `due_at` from a checkpointed discussion's entry shows the reply-to-others date.
- `update` uploads checkpoints with Canvas's GraphQL `updateDiscussionTopic` mutation (Canvas has no REST route for them) and stops sending the parent assignment's `points_possible`, `due_at`, `unlock_at` and `lock_at` over REST for a checkpointed discussion, because Canvas accepts those writes and leaves the parent inconsistent with its checkpoints (measured, see design.md). Removing `checkpoints:` from a file turns checkpoints off in Canvas.
- Before uploading any checkpointed discussion, `update` checks that the course's account has the `discussion_checkpoints` feature on. If it is off, `update` prints an error, does not upload that discussion, and suggests commenting out `checkpoints:` and using `points_possible`, `due_at` (the reply-to-others date) and `require_initial_post: true` instead, with the earlier reply-to-topic deadline written into the body with a date placeholder.
- `import` writes the `checkpoints:` block for a checkpointed discussion in an IMSCC export, with a comment above `reply_to_others` saying these are students' replies to other students' posts, and writes the two checkpoint dates into the course's `due_dates` entry, as it already does for `due_at`.
- **BREAKING (format)**: `FORMAT_VERSION` goes from 15 to 16. An older tool would read a file with `checkpoints:` and upload a plain graded discussion with no due date, which is the "older tool misreads a file the new tool writes" case.

### Existing mechanisms this builds on

Nothing in the tool covers checkpoints today (no reference to checkpoints, `sub_assignment` or `reply_to_entry` in the source or docs). The change reuses:

- `canvas_api.graphql()`, already used for the GraphQL-only course post policy.
- The central `due_dates` table, its sentinel values and its override of frontmatter dates (`find_due_date_override`, `_resolve_date_overrides`), and the dates-only pass with its `resolved_dates` cache (`_apply_due_dates_only`).
- `[relative_due_dates]` and `generate-due-dates`, including the `ASSIGNMENT` anchor.
- The graded-discussion rubric code (`_apply_discussion_rubric`); in the sample export the rubric stays on the parent assignment.
- `import`'s pattern of moving dates into `due_dates` and leaving them commented in the frontmatter.

### TODO.md

No existing TODO.md item covers checkpoints. This change adds one: letting a `replace_date_with` placeholder choose a checkpointed discussion's reply-to-topic date.

### Core subcommands

- `update`: affected (validation, flag check, GraphQL upload, dates-only pass, checkpoint removal).
- `import`: affected (writes `checkpoints:` and the two `due_dates` keys).
- `publish`: affected only through date placeholders (a placeholder naming a checkpointed discussion shows the reply-to-others date). It strips frontmatter and never uploads, so the rest of the change does not apply.
- `mv`: not affected. It moves files and rewrites paths; `due_dates` entries match by title, and the new frontmatter and `due_dates` keys move with the file and entry unchanged.

## Capabilities

### New Capabilities
- `discussion-checkpoints`: the `checkpoints:` frontmatter block, its validation, the feature-flag check and its error, uploading, changing and removing checkpoints in Canvas, and importing them from an IMSCC export.

### Modified Capabilities
- `relative-due-dates`: items gain `reply_to_topic_offsets`; an `ASSIGNMENT` anchor naming a checkpointed discussion counts from its reply-to-others date.
- `generate-due-dates-command`: writes `reply_to_topic_due_at` and `reply_to_others_due_at` instead of `due_at` for an item with `reply_to_topic_offsets`, and checks their order.
- `date-placeholders`: `due_at` from a checkpointed discussion's entry resolves to `reply_to_others_due_at`.
- `repo-format-version`: format version 16 and the migration 15 -> 16.

## Impact

- Code: `sync.py` (`_upload_discussion`, `_apply_due_dates_only`, due_dates validation), `canvas_api.py` (GraphQL checkpoint mutations, flag lookup, topic state), `relative_dates.py`, `generate_due_dates.py`, `date_placeholders.py`, `imscc_import.py` (`parse_topic_meta`, `_build_frontmatter` needs nested mappings, `_collect_due_date`), `repo_format.py`.
- Manifest: `resolved_dates` of a checkpointed discussion records the two checkpoint dates instead of `due_at`.
- Canvas API: GraphQL `updateDiscussionTopic` with `checkpoints`/`setCheckpoints`; REST `GET /api/v1/accounts/:id/features/flags/discussion_checkpoints`.
- Docs: README.md (frontmatter, due_dates, relative dates), ARCHITECTURE.md (Canvas behavior measured on 2026-11-02, upload algorithm), TODO.md.
- Tests: unit tests for validation, relative-date arithmetic, import; mocked-API tests for the upload paths.
