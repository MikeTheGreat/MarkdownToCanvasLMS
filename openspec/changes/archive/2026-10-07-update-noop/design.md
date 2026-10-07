# Design

## Context

See proposal.md for motivation and specs/update-noop/spec.md for the required
behavior.

`update --check-all` (ARCHITECTURE.md "`--check-all`") already runs the full
`run_sync` pipeline without Canvas. It does so with three mechanisms:

- `SyncContext.api` and the `api=` parameters of the functions outside the ctx
  graph route every Canvas call through one object, the real `canvas_api`
  module or a `dryrun.DryRunCanvas`.
- `manifest_path=None` makes `manifest_lib.flush()` and `record()` skip the disk
  write, so the in-memory manifest can be updated freely during the run.
- `ctx.check_only` changes "Uploading" to "Would upload" (and similar) and
  suppresses `Link:` lines.

Gaps found while reading the code, which `--noop` has to close:

- `run_targeted_sync` (the `-t`/`-s` path) does not pass `api=` to
  `SyncContext` and calls `capi.get_course`, `capi.get_assignment_group_ids`,
  `capi.get_rubric_ids`, `capi.get_orphan_item` and `capi.upload_asset`
  directly. `--check-all` never reaches it, because it rejects `-t`/`-s`.
- `_sync_quiz` calls `course.get_quiz(result["canvas_id"])` on the course
  object (sync.py, near line 3427). With a real course and a fake ID for a new
  quiz this is a GET for a quiz that does not exist.
- `_guard_course` (cli.py) calls `course_guard.check_course`, which records the
  course identity in the manifest or clears the manifest after a prompt.
- `check_unrecorded_moves` flushes the manifest after `--new` forgets entries
  (unrecorded_moves.py, near line 294). It already takes `manifest_path`, so
  passing `None` is enough.
- Several `canvas_api` write functions also read first (for example
  `sync_grading_standards` reads the account's standards, `sync_rubrics` and
  `sync_assignment_groups` read the existing ones). `DryRunCanvas` replaces the
  whole function.

## Goals / Non-Goals

**Goals:**

- Reuse the `--check-all` machinery. One pipeline, one set of "Would ..."
  messages, with only the API object, the starting manifest and the course
  object differing between the three modes.
- Make it impossible, not merely unlikely, for `--noop` to send a write request
  to Canvas.

**Non-Goals:**

- Predicting Canvas-side outcomes of writes (rejected dates, quiz "Save It
  Now", rubric copy-on-edit forks). A write that is not sent cannot be
  observed. This is the same limit `--check-all` documents.
- Adding a summary to real `update` runs or to `--check-as-new-course`. The
  counters could serve both later, but only `--noop` prints the summary in this
  change.

## Decisions

These were confirmed by the user in the explore session.

1. **Flag name `--noop`**, matching `mv`, `cp`, `upgrade` and
   `generate-due-dates`.
2. **`--noop` combines with `-t`, `-s`, `--force-uploads`, `--force-overwrite`**
   and reports what that combination would do.
3. **The unrecorded-move check runs and stops the run** as in a real `update`.
4. **The course guard is kept.** How it avoids writing is in Open Questions.
5. **Output** is the normal output with "Would ..." verbs plus an end-of-run
   summary of counts.
6. **Exit status 1** when any error or warning was collected.
7. **`--check-all` is renamed `--check-as-new-course`** with no alias. The
   Python parameter becomes `check_as_new_course`. Internal names in
   `run_sync` (`check_all=`) and `dryrun.py` docstrings and placeholder text
   ("check-all: not contacting Canvas") are renamed to match, so grep for the
   old name finds nothing.

## Open Questions

The following are proposed by this design and were not confirmed by the user.
Each has a recommendation; the specs are written to the recommendation, so
changing one means a small spec edit.

1. **Course guard under `--noop`.** Recommendation (as specified): give
   `check_course` a `noop` mode. Same course: continue. No course recorded:
   print the usual explanation, do not prompt, do not record, continue. A
   different course recorded: print the usual explanation, do not prompt, exit
   1. Alternative for the different-course case: continue as if the user had
   answered yes, with an empty in-memory manifest, which would show a full
   re-creation in the new course. Stopping is recommended because that state
   almost always means `canvas.toml` is wrong.
2. **Short forms.** Recommendation: `-n` for `--noop` (as in `mv` and `cp`);
   `-ca` is dropped, and `--check-as-new-course` has no short form. `-ca` is a
   two-letter short option, which click allows but which reads as `-c a`
   (`-c` is `--config`).
3. **API object: a read-through subclass of `DryRunCanvas`.** Recommendation:
   `dryrun.NoopCanvas(DryRunCanvas)` takes the real course. Read functions
   (`get_canvas_updated_at`, `get_assignment_group_ids`, `get_rubric_ids`,
   `get_group_category_ids`, `get_module_ids_by_name`, `find_module_ids_named`,
   `get_orphan_item`, `get_syllabus_body`, and any other read the pipeline
   calls) forward to `canvas_api`, and the result is merged with what the run
   has simulated so far (for example, an assignment group "created" in phase 0
   is added to the real name -> ID map). Write functions are inherited from
   `DryRunCanvas` unchanged. Alternative considered: wrapping `canvas_api` in a
   generic proxy that forwards everything whose name starts with `get_`. It is
   shorter, but a new write function named `get_or_create_...` would be
   forwarded silently. An explicit list, with the `AttributeError` test that
   `--check-all` already uses for missing twins, is safer.
4. **Fake IDs are negative under `--noop`.** Recommendation: `NoopCanvas`
   hands out IDs from -1 downward, so they cannot equal a real Canvas ID, and
   its read functions return a simulated answer for any negative ID instead of
   asking Canvas (for example, `get_canvas_updated_at` returns `None`).
   `DryRunCanvas` keeps 100001 upward for `--check-as-new-course`, where no ID
   reaches Canvas.
5. **`course.get_quiz` goes through the API object.** Recommendation: add
   `get_quiz(course, quiz_id)` to `canvas_api` and the dry-run classes and call
   `ctx.api.get_quiz` in `_sync_quiz`. `NoopCanvas.get_quiz` returns the
   `SimpleNamespace` placeholder for a negative ID and the real quiz otherwise
   (it is passed only to the simulated `sync_quiz_questions` and
   `finalize_quiz_publish_state`). This also removes the last direct canvasapi
   call noted in ARCHITECTURE.md.
6. **Request-level safety net.** Recommendation: in `--noop` mode, replace the
   course's `canvasapi` requester `request` method with a wrapper that raises
   `NoopWriteError` for any method other than GET, before the run starts. A
   bug in the routing above then fails the run loudly instead of changing the
   course. GraphQL is always POST; the pipeline uses it only for
   `update_post_policy`, a write that `DryRunCanvas` simulates, so no read is
   blocked by this. If a later read needs a GraphQL query, the wrapper will
   have to allow that one query explicitly.
7. **`run_targeted_sync` gets the same indirection.** Recommendation: it takes
   an `api` and passes it to `SyncContext`, and its direct `capi.*` calls go
   through it. This is needed for `--noop -t/-s` regardless of the other
   choices.
8. **Mode parameter.** Recommendation: replace `run_sync(check_all: bool)` with
   `run_sync(mode: Literal["real", "noop", "new_course"])` (and the same on
   `run_targeted_sync`, where `"new_course"` is rejected), because three
   booleans would allow invalid combinations. `ctx.check_only` stays a bool
   (true in both simulated modes), since every message it controls is the same
   in both.
9. **Summary counts.** Recommendation: a small counter object on `SyncContext`,
   incremented where the "Would upload"/"Would create" lines are printed: an
   item whose manifest entry has no `canvas_id` (or no entry) counts as
   *created*, otherwise *updated*; *skipped* is incremented where the
   up-to-date check returns early; *newer on Canvas* is
   `len(newer_on_canvas)`; *problems* is `len(errors)`. Course-settings
   sections, module-order changes and due-date-only updates count as updated.
   Assets count with content items. Example:

   ```
   NOOP SUMMARY (nothing was changed)
     Would create:          1
     Would update:          2
     Up to date (skipped): 37
     Newer on Canvas:       0
     Problems:              0
   ```

## Canvas API behavior this depends on

- `--noop` sends only GET requests that a real `update` already sends (the
  timestamp check, name -> ID lookups, module lookups, orphan lookups). No new
  Canvas behavior is relied on. Verified: these reads run in every real
  `update` today.
- Unverified: that no read in the pipeline is a non-GET request. The safety net
  in Open Question 6 turns a violation into an error. Live verification step:
  run `update --noop` and `update --noop --force-uploads` against the sandbox
  course 2758791 (see CLAUDE_NOTES/CLAUDE-IN-CHROME.md) with request logging
  on, and confirm that every request was a GET and that the course's
  "last activity"/page history shows no edits.

No operation in this change deletes or overwrites Canvas content.

## Manifest format

No manifest format change and no `FORMAT_VERSION` bump. `--noop` reads the
manifest and never writes it. The rename does not touch any repo file.

## Risks / Trade-offs

- [A future `canvas_api` write function is called from the pipeline without a
  dry-run twin] → `NoopCanvas` raises `AttributeError` (the same test pattern
  as `test_check_all`), and the request-level safety net blocks the write if
  the call somehow reaches canvasapi.
- [Simulated writes that also read (grading standards, rubrics, assignment
  groups) skip their read, so `--noop` cannot report what those would find on
  Canvas, for example a grading standard that already exists at the account
  level] → Reported as "Would sync <section>"; the hash caches already limit
  these to sections that changed. Acceptable for a first version.
- [Merging real reads with simulated state can disagree with a real run, for
  example when a real run would rename an existing rubric] → Covered by tests
  that compare the noop output with the actions a mocked real run takes on the
  same fixture.
- [Users' scripts call `--check-all`] → Breaking rename, accepted by the user.
  The README section heading and the option help text name the new flag.

## Migration Plan

No data migration. Users who call `update --check-all` replace it with
`update --check-as-new-course`. Rollback is reverting the code change.
