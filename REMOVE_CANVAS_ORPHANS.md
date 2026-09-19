# Plan: `find-canvas-orphans --delete`

Implementation plan for adding optional, confirmed deletion of orphaned
resources to `find-canvas-orphans`, and for extending the command so it also
finds unreferenced Canvas **Files**. Written 2026-09-18 for an implementing
model; read the whole file before starting.

## Decisions already made by the user

- Scope: the command must first learn to report unreferenced Canvas Files (it
  currently never enumerates them), and then deletion covers everything it
  reports: pages, assignments, discussions, quizzes and files.
- Confirmation: per-item prompts by default, with an "all" answer that deletes
  the remaining items. There is no `--yes` flag and no non-interactive mode.

Do not revisit these. If something in this plan seems to conflict with them,
stop and ask the user.

## Read first

- `src/markdown_to_canvas/orphans.py` (the whole module, ~200 lines).
- `src/markdown_to_canvas/cli.py`: `find_canvas_orphans_cmd` (~line 410) and
  `clean_manifest_cmd` (~line 500) for the existing confirm/TTY pattern.
- `src/markdown_to_canvas/canvas_api.py`: `_GETTERS`, `DELETABLE_TYPES`,
  `delete_content()` (~lines 670-810), `get_syllabus_body()`.
- `src/markdown_to_canvas/sync.py`: `run_prune()`, `_in_use_resources()`,
  `_entry_resource_key()` (~lines 1887-2034). Prune is the closest existing
  analogue of this feature.
- `src/markdown_to_canvas/link_rewrite.py`: `canvas_content_url()` (line 33).
- `tests/test_orphans.py` and `tests/conftest.py` (outbound HTTP is blocked in
  tests; everything must be mocked).
- ARCHITECTURE.md section "Orphan detection", and TODO.md items
  "`find-canvas-orphans` never reports unreferenced Canvas files" and
  "Orphan detection: transitive reachability".

## Problems in the current detection that deletion would turn into data loss

The current command is a read-only report, so false positives cost nothing.
With deletion they destroy course content. Fix all of these before wiring up
deletion. Each is a separate step below.

1. **Files uploaded by this tool are linked in a form the scanner does not
   recognise.** `upload_asset()` records `response["url"]` as the file's
   `canvas_url`, and `canvas_content_url()` emits that URL verbatim into page
   HTML. The Canvas upload response URL has the shape
   `https://<host>/files/<id>/download?download_frd=1&verifier=...` — there is
   no `/courses/<id>/` prefix. `_CANVAS_REF_RE` requires `/courses/\d+/`, so
   every asset the tool itself uploaded would be reported as unreferenced.
   Whether Canvas rewrites these links to a course-scoped form when it saves
   the HTML is unverified; handle both forms.
2. **Quiz- and discussion-backed assignments.** Canvas's list-assignments
   endpoint returns an assignment object for every graded classic quiz
   (`quiz_id` set, `submission_types == ["online_quiz"]`) and every graded
   discussion (`discussion_topic` set). The module item for the quiz carries
   the quiz id, not the assignment id, so `ResourceKey("assignment", <id>)` is
   never referenced. The current code does not filter these, so it most likely
   already reports every graded quiz and graded discussion as an orphaned
   assignment. Deleting that assignment deletes the quiz or discussion and its
   grades. Confirm on a live course (see "Live verification"), but implement
   the fix regardless.
3. **Announcements are not scanned.** `course.get_discussion_topics()` excludes
   announcements, so a page or file linked only from an announcement is
   reported as unreferenced.
4. **Other file users outside HTML links**: the course card image
   (`course.image_id`), assignment `annotatable_attachment_id`, and media
   recordings (files with a `media_entry_id`, embedded via
   `/media_attachments_iframe/<file id>` or by media id rather than by a
   `/files/` link).
5. **Places the command cannot see at all**: classic question banks (questions
   not placed in any quiz), New Quizzes (LTI; content not accessible through
   this API), rubrics, calendar events, group content, and content in other
   courses that links into this one. A file used only there will be reported.
   This cannot be fixed; it must be stated in the report and in the delete
   prompt (see step 6).
6. **Orphan does not mean unused for graded items.** An assignment or quiz in
   no module and linked from nowhere is still visible to students on the
   Assignments/Quizzes/Grades pages if published, and may hold student
   submissions. Deleting it deletes those submissions and grades.

## Steps

### Step 1 — Recognise all file reference forms

In `orphans.py`, extend reference extraction so `extract_canvas_refs()` also
returns `ResourceKey("file", id)` for:

- `/files/<id>` with or without a scheme+host prefix, and with any suffix
  (`/download`, `/preview`, `?verifier=...`, `?wrap=1`).
- `/courses/<cid>/files/<id>` (already matched; keep).
- `/media_attachments_iframe/<id>` (the id is the file id).

It must **not** match `/users/<uid>/files/<id>` (user files are not course
files) or `/assessment_questions/<qid>/files/<id>` (those ids belong to a
question's copy, not a course file — do not credit a course file id from them).
Easiest: add a second regex `_FILE_REF_RE` used alongside `_CANVAS_REF_RE`
rather than bolting another alternative onto the existing one, and anchor it so
the character before `/files/` is a quote, whitespace, `(`, `=`, the host, or
`/courses/<n>`. Write the tests first (step 8 lists them).

Also collect media ids: `data-media-id="m-..."`, `/media_objects_iframe/m-...`,
and `media_comment_m-...`. Store them in a separate `set[str]` returned
alongside the key set (don't overload `ResourceKey`).

`extract_canvas_refs` is also used by `sync._in_use_resources()` (prune's
in-use protection). The extension makes prune more conservative, which is the
correct direction; check `tests/test_sync.py` prune tests still pass and note
the change in ARCHITECTURE.md's prune section.

### Step 2 — Fix assignment aliasing

In `find_orphans()`, when iterating `course.get_assignments()`:

- If the assignment has a truthy `quiz_id`, or `is_quiz_assignment` is true, do
  not add it as a candidate. Record `alias[ResourceKey("assignment", a.id)] =
  ResourceKey("quiz", a.quiz_id)` when `quiz_id` is known.
- If it has a `discussion_topic` (dict with `id`), same treatment, aliasing to
  `ResourceKey("discussion", topic_id)`.
- Still scan its `description` for references.

After the scan, any referenced key that appears in `alias` also marks its
target referenced (a link to `/courses/1/assignments/<quiz's assignment id>`
is a reference to the quiz). New Quizzes assignments (`is_quiz_lti_assignment`)
stay ordinary assignment candidates; their module items use the assignment id.

### Step 3 — Scan announcements

Add a pass over `course.get_discussion_topics(only_announcements=True)`,
scanning `message` for references. Announcements are sources only, never
candidates (the command has never reported them, and deleting old
announcements is not what this feature is for).

### Step 4 — Enumerate Canvas Files as candidates

Add a `course.get_files()` pass after the content passes. For each file build a
`ResourceInfo` with key `ResourceKey("file", f.id)`, title `f.display_name`,
`html_url` built as `/courses/<course.id>/files/<id>` (the file object has
no `html_url`), and `published = not (f.locked or f.hidden)`. Add two fields to
`ResourceInfo` with defaults so existing constructors keep working:

- `detail: str = ""` — for files, the folder path and size, e.g.
  `course files/images · 48 KB`. Folder names come from
  `course.get_folders()` (map `folder_id` → `full_name`), fetched once.
- `risk: str = ""` — filled in step 6.

Mark as referenced (never candidates):

- Every `file` module item's `content_id` (already done by the existing
  module pass).
- The course image. Add `canvas_api.get_course_image_id(course) -> int | None`
  modelled on `get_syllabus_body()`: raw `GET courses/<id>` with
  `include[]=course_image`, returning `image_id` (as int) or None.
- Each assignment's `annotatable_attachment_id`, if present.
- Any file whose `media_entry_id` is set. Do not try to match media ids to
  files precisely in this pass — treat every media-backed file as referenced,
  and count them so the report can say how many were excluded. (Keep the media
  id set from step 1 anyway; it costs nothing and is useful if this is
  tightened later.)

**Fail closed.** The existing code wraps the front page, syllabus and quiz
question passes in `except Exception: pass`. That was acceptable for a report;
for deletion it is not, since a failed syllabus fetch silently turns every
syllabus-linked item into a candidate. Change `find_orphans()` to collect each
swallowed failure into a `warnings: list[str]` instead of passing silently, and
return a small report object:

```python
@dataclass
class CanvasOrphanReport:
    orphans: list[ResourceInfo]
    warnings: list[str]          # failed passes; each one means the list may be wrong
    excluded_media: int          # media-backed files not considered
```

A missing front page (the course has none) is not a failure — distinguish
`ResourceDoesNotExist` from other exceptions there. Update `print_report()` to
take the report object and print warnings **after** the list (same convention
as `local_orphans._print_errors()`), and update the existing tests that assert
`find_orphans(course) == []` to use `.orphans`.

If `report.warnings` is non-empty, `--delete` must refuse to run (print the
warnings and exit via `die()`). Deletion only proceeds from a complete scan.

Add `"file": "Files"` to `_TYPE_LABELS`. Files sort last because the report is
sorted by `canvas_type` string; that's fine.

### Step 5 — Cross-reference the repo manifest and pinned resources

`find-canvas-orphans` currently reads no manifest. For deletion it needs two
things from the repo:

- The manifest for the config in use:
  `manifest_lib.manifest_path_for(repo, cfg.config_path)`, loaded with
  `manifest_lib.load()`. Build `tracked: dict[ResourceKey, str]` mapping each
  entry to its local key, using `sync._entry_resource_key()` (import it; do not
  duplicate it). Only use the manifest if
  `manifest_lib.get_course_identity()` matches `cfg.base_url`/`cfg.course_id`
  (`manifest_lib.same_course`); otherwise print one line saying the manifest
  records a different course and treat `tracked` as empty. Do not use
  `migrate_legacy_manifest` here — it writes files, and without `--delete` this
  command must stay read-only.
- `sync.load_pinned_resources(repo)` and `sync.find_pinned_match()`. An orphan
  whose tracked local key is pinned is shown in the report but never offered
  for deletion (same rule as prune).

In the report, show `tracked: <local key>` under any orphan that has a manifest
entry, plus `(local file missing)` when `repo / local_key` does not exist. This
is useful even without `--delete`: a tracked orphan whose local file still
exists will be re-created or re-uploaded by `update` only if its mtime changes,
and the user should use `find-local-orphans` / `prune` for those instead.

### Step 6 — Risk classification

For each candidate, set `ResourceInfo.risk` to a short reason string, or leave
it empty:

- Assignments: `has_submitted_submissions` is true → `"has student submissions"`.
- Quizzes: fetch the quiz's assignment once via `quiz.assignment_id` only for
  orphaned quizzes (not all quizzes), and use its `has_submitted_submissions`.
  If the lookup fails, set risk to `"could not check for submissions"` rather
  than leaving it empty.
- Discussions: `discussion_subentry_count > 0` → `"has N replies"`.
- Any published assignment, quiz or discussion without one of the above →
  `"published; students can reach it from the Assignments/Quizzes/Discussions page"`.

Items with a non-empty risk are never deleted by the "all" answer (step 7).

### Step 7 — The `--delete` option and the prompt loop

CLI (`cli.py`, `find_canvas_orphans_cmd`):

- Add `--delete` (flag, default False). Help text: "After the report, offer to
  delete the orphans from Canvas, one at a time. Nothing is deleted without
  confirmation."
- Without `--delete` the behaviour is the report only, unchanged apart from
  steps 1-5.
- With `--delete`:
  - If `not sys.stdin.isatty()`: `die("--delete asks for confirmation and needs a terminal.")`.
  - Resolve the repo with `_resolve_repo(repo).resolve()` so manifest paths
    work.
  - If the scan produced warnings: `die()` as described in step 4.
  - If there are no deletable orphans: say so and return.

Put the loop in a new function in `orphans.py`,
`delete_orphans(course, report, tracked, pinned, manifest, manifest_path) -> DeleteSummary`,
so it can be unit-tested with a mocked `click.prompt`. Behaviour:

1. Print a one-paragraph caveat before the first prompt, listing what the scan
   cannot see (item 5 in the problems list: question banks, New Quizzes,
   rubrics, calendar events, other courses) and that a resource only
   referenced by another orphan becomes unreferenced after that orphan is
   deleted, so a second run may find more.
2. Order: content types first (pages, assignments, discussions, quizzes), files
   last. Skip pinned items with a `Kept (pinned via pinned_resources): ...`
   line.
3. For each item print title, type, publish state, URL, `detail`, `tracked`,
   and `risk` (in red if set), then
   `click.prompt("Delete?", type=click.Choice(["y", "n", "a", "q"]), default="n", show_choices=True)`.
   - `y`: delete this one.
   - `n`: keep it.
   - `q`: stop; keep this and every remaining item.
   - `a`: list the remaining items with an empty `risk`, ask one
     `click.confirm(f"Delete these {k} items?", default=False)`, and if
     confirmed delete them without further prompts. Items with a risk are then
     still prompted individually, and `a` is not offered for them (use
     `Choice(["y", "n", "q"])`).
4. Deletion: `capi.delete_content(course, canvas_type, entry)` with a
   synthesised entry — `{"canvas_url": slug}` for pages,
   `{"canvas_id": id}` otherwise. Files need no new API code: `_GETTERS["file"]`
   exists and `DELETABLE_TYPES` includes `"file"`. Catch exceptions per
   item, print a warning, record it, continue.
5. When a deleted item (or one that `delete_content` reports as already gone)
   has a manifest entry, delete that entry and call `manifest_lib.flush()`
   immediately, as `run_prune` does, so a later crash can't leave a manifest
   pointing at a deleted Canvas id. Without this, the next `update` would
   render links to a file id that no longer exists.
6. End with a summary line in `run_prune`'s style:
   `N deleted, M kept, P kept (pinned), E errors.` Return True from the command
   path if there were errors, and print the yellow/green closing line the way
   `prune_cmd` does.

Do not re-scan between deletions. Non-transitivity is intentional and
documented (TODO.md "transitive reachability").

### Step 8 — Tests (`tests/test_orphans.py`)

Extend `_base_course()` so `get_discussion_topics` uses a `side_effect` that
returns announcements when called with `only_announcements=True`, and add
`files`, `folders` and `image_id` parameters. The syllabus and course-image
requests both go through `course._requester.request`; make its `side_effect`
dispatch on the `_kwargs` include value.

Reference extraction:

- `https://host/files/55/download?download_frd=1&verifier=abc` → file 55.
- `/files/55/preview`, `/courses/1/files/55?wrap=1` → file 55.
- `/media_attachments_iframe/55` → file 55.
- `/users/3/files/55` → nothing.
- `/assessment_questions/9/files/55/download` → nothing.
- Media ids are collected from `data-media-id` and `media_objects_iframe`.

Detection:

- An asset linked only via the upload-URL form is not an orphan.
- A quiz-backed and a discussion-backed assignment are never reported when their
  quiz/discussion is in a module, and are not reported as separate candidates
  when the quiz/discussion is orphaned (only the quiz/discussion is).
- A page linked only from an announcement is not an orphan.
- Course image file, annotatable attachment file, file module item, and a
  media-backed file are not orphans; an unlinked plain file is.
- A failing syllabus fetch produces a warning, not a silent pass; a missing
  front page (`ResourceDoesNotExist`) does not.

Deletion (`delete_orphans`, with `click.prompt`/`click.confirm` monkeypatched
and `capi.delete_content` mocked):

- `y`/`n`/`q` behave as specified; `q` deletes nothing further.
- `a` deletes remaining no-risk items after one confirm, still prompts for risky
  items, and does not offer `a` for them.
- Declining the `a` confirm deletes nothing and returns to per-item prompts
  (decide this behaviour and document it; returning to per-item prompting is
  the safer choice).
- Pinned items are never passed to `delete_content`.
- A deleted tracked item's manifest entry is removed and flushed; an untracked
  item leaves the manifest untouched.
- An exception from one delete is recorded and the loop continues.

CLI (`CliRunner`):

- `--delete` with non-TTY stdin exits non-zero and deletes nothing.
- `--delete` with scan warnings exits non-zero and deletes nothing.
- Without `--delete`, no delete call is made and no manifest file is written.

Run the whole suite (`uv run pytest`) and `uv run ruff check`.

### Step 9 — Documentation

- README.md, section `find-canvas-orphans — the live course`: files are now
  reported; describe `--delete`, the prompt answers, what `a` skips, pinned
  items, manifest cleanup, and the list of places the scan cannot see. State
  plainly that an orphaned assignment or quiz may still be reachable by
  students and may hold grades. Update the options table near line 273 if it
  lists per-command flags.
- ARCHITECTURE.md, "Orphan detection": replace the paragraph saying files are
  never enumerated; document the file reference forms, assignment aliasing,
  announcement scanning, fail-closed warnings, `CanvasOrphanReport`, the
  manifest/pin cross-reference and the delete loop. In the prune section, note
  that `_in_use_resources` now recognises the extra file link forms.
- TODO.md: remove "`find-canvas-orphans` never reports unreferenced Canvas
  files". Update item 8 of the code-review list (`orphans.py:136, 158, 170`
  broad excepts) since those are now converted to warnings. Leave the
  transitive-reachability item, but add one sentence noting that with
  `--delete` the cascade it describes can now happen on Canvas too.
- The CLAUDE.md rule about keeping `update`/`import`/`mv`/`publish` in sync does
  not apply: none of them read Canvas orphan state. Say so in the change
  summary rather than editing them.

## Live verification (the user must do this; tests cannot)

Ask the user to run these against a sandbox course, not a live one, before
using `--delete` on real courses:

1. Upload an asset with `update`, link it from a page, then view that page's
   HTML via the API (`GET /api/v1/courses/<id>/pages/<slug>`). Record which
   link form Canvas stored, and confirm the file is not reported.
2. Create a graded classic quiz and a graded discussion, put both in a module,
   and confirm neither they nor their assignments are reported. On the current
   code (before step 2) check whether their assignments *are* reported; if so,
   note in ARCHITECTURE.md that the pre-change report had this false positive.
3. Set a course card image and confirm its file is not reported.
4. Record a media comment or upload a video into a page and confirm it is
   excluded and counted.
5. Run `find-canvas-orphans --delete`, answer `n` to everything, and confirm
   nothing changed. Then delete one unlinked test file with `y` and confirm it
   is gone from Files.

## Out of scope

- Unpublish as an alternative to delete (prune has it; could be added later
  with the same loop).
- Transitive reachability.
- Deleting announcements, modules, rubrics, question banks or folders.
- Emptying now-empty Canvas folders after file deletion.
