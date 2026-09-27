# Design

## Context

See proposal.md (Why) and specs/group-categories/spec.md for the required behavior.
Relevant current state:

- `_upload_discussion` (`sync.py`) sends only `require_initial_post` plus a nested
  `assignment` dict of grading keys; `canvas_api._do_discussion` forwards any
  kwargs to `course.create_discussion_topic()` / `topic.update()`.
- `_upload_assignment` passes `group_category_id` through unchanged;
  `canvas_api._do_assignment` already fetches the existing assignment before
  `edit()`.
- `assignment_group_id` names are resolved per run from
  `api.get_assignment_group_ids(course)`, held on `SyncContext`; the targeted
  sync (`-t`/`-s`) fetches the same map but does not run the course-settings phase.
- `update --check-all` swaps in `dryrun.DryRunCanvas`, which never contacts Canvas
  and fabricates IDs for things the repo defines.
- Canvas exports name the group set/group category and never give its ID or
  definition (see "Canvas behavior" below).

## Goals / Non-Goals

**Goals:**
- One mechanism (name resolution against a listed set of names) for discussions
  and assignments, in full, targeted and check-only runs.
- Never create a whole-class version of an intended group activity.
- Never change an existing Canvas item's group set/group category in a way that
  could hide student work.

**Non-Goals:**
- Groups inside a group set/group category, group membership, self sign-up,
  group leaders, group limits.
- Deleting or renaming group sets/group categories (`prune` and
  `find-canvas-orphans` are unchanged).
- Converting a group discussion back to a whole-class one.
- Group quizzes and group announcements (Canvas course-level quizzes and
  announcements have no group set/group category setting).

## Decisions

Confirmed with the user:

1. **Key and values.** `group_category_id` in frontmatter, accepting a name
   (documented as the normal form) or a number. The alternative, a separate
   `group_set:` key, was rejected to keep one key for one setting and match the
   existing assignment key. A number is sent unchanged; `cp` warns about it.
2. **Unresolvable name is a hard error for the file**, not a warn-and-skip-field
   (the `assignment_group_id` behavior). Skipping the field would create a
   whole-class discussion or individual assignment that Canvas may not let you
   convert once students have posted or submitted. Applies to discussions and
   assignments.
3. **Every name must be listed** in `course_settings.toml`, even when the group
   set/group category already exists on Canvas. `--check-all` can then check
   names without contacting Canvas, and the repo fully describes the course.
4. **List format:** a top-level inline array of strings,
   `group_categories = ["Project Groups"]`. An array of tables
   (`[[group_categories]]` with `name`) was considered for room to add per-set
   keys later; the user chose the less cluttered form since the list only holds
   names. Adding per-set settings later would need a format change.
5. **`update` creates missing listed group sets/group categories** (empty), so
   `import` + `update` can recreate this part of a course in a new Canvas course.
   The targeted sync (`-t`/`-s`) creates one on demand when a file it uploads
   needs it.
6. **Change safeguard** (described below): omit an unchanged value, add one only
   when there are no replies/submissions, never switch.
7. **Removing `group_category_id` leaves Canvas unchanged**; the README says so
   and says un-grouping is done in Canvas.
8. **Import reads `<group_category>` names** from topic metadata and assignment
   settings and writes both the frontmatter and the `course_settings.toml` list;
   this replaces the dead `<group_category_id>` read.
9. **`cp` adds missing names** to the destination's `group_categories`, the way
   it appends missing rubrics; the numeric-ID warning stays.
10. **Migration 6 -> 7 adds `group_categories = []`** to `course_settings.toml`
    when absent, and records version 7.
11. **Terminology:** "group set/group category" in all docs and comments.
12. **`import` always writes `group_categories`**, as `[]` when the export has
    none, so a freshly imported repo looks the same as an upgraded one.
13. **IDs are not cached in the manifest.** Resolution costs one list request per
    `update` run (only when `group_categories` is non-empty), not one per name or
    per file. A cached ID could go stale if the group set/group category is
    deleted or recreated on Canvas, and the fresh list is needed anyway to
    recreate a deleted one.

Required by project rules (CLAUDE.md):

14. **Format version 6 -> 7.** An older tool would silently drop a named
    `group_category_id` on a discussion (creating a whole-class discussion) and
    send a name where Canvas expects an ID on an assignment, which is the "older
    tool misreads a file the new tool writes" case. Existing content files need no
    rewriting because numeric IDs remain valid.

Implementation approach:

- **canvas_api:** `get_group_category_ids(course) -> dict[str, int]` via
  `course.get_group_categories()`, and `create_group_category(course, name) -> int`
  via `course.create_group_category(name=...)`. `DryRunCanvas` gets both; its
  get returns the IDs it fabricated for listed names.
- **Loading the list:** parse and validate `group_categories` alongside the
  other pre-Canvas config checks (as `load_pinned_resources` does) so a bad list
  stops the run before phase 0. The key is added to `_SETTINGS_SECTION_KEYS` or
  `_NON_METADATA_SETTINGS_KEYS` so it is never treated as course metadata.
- **Creation:** in the full run, right after `sync_course_settings`, if the list
  is non-empty: one GET, create each missing listed name, store `{name: id}` on
  `SyncContext` (new `group_category_ids` field, plus the listed names). This
  runs every full run instead of using the section-hash skip, so a group
  set/group category deleted on Canvas is recreated; the cost is one GET per run,
  and only for repos that list any. The targeted sync fetches the map the same
  way and creates a listed-but-missing name when a file it uploads needs it.
- **Resolution:** `_resolve_group_category_id(ctx, value, local_key)` returns an
  int or records an error. `_upload_discussion` and `_upload_assignment` call it
  before any Canvas write for the file and return early on failure, which gives
  "file not uploaded, error in summary, non-zero exit" through the existing
  `errors` list. A stub created earlier for the same file by link rewriting is
  left as an unpublished empty stub; the next successful run turns it into the
  group item.
- **Sending:** discussions get a top-level `group_category_id` kwarg (not inside
  the nested `assignment` dict). Assignments keep sending it in the assignment
  params.
- **Change safeguard (in `_do_discussion` / `_do_assignment`, which already GET
  the existing item):**
  - Existing item already has the requested group set/group category: omit the
    key from the update, so an unchanged value is never re-sent after students
    have posted.
  - Existing item has no group set/group category: send it only if the
    discussion has no replies (`discussion_subentry_count == 0`) or the
    assignment has no submissions (`has_submitted_submissions` false); otherwise
    fail the file with an error saying to change it in Canvas.
  - Existing item has a different group set/group category: fail the file with
    an error saying to change it in the Canvas UI. The tool never switches one
    group set/group category for another.
- **Announcements:** no code change; `group_category_id` is not in
  `ANNOUNCEMENT_SETTABLE_FIELDS`, so the existing ignored-field warning covers it.
- **Import:** `parse_topic_meta` reads the topic-level `has_group_category` /
  `group_category` (the nested `<assignment>` of a graded discussion carries its
  own `has_group_category`, which is false in the observed export and is
  ignored). The assignment-settings parser reads `group_category` when
  `has_group_category` is true. Names go into an ordered set on the import
  context; the `course_settings.toml` writer always emits the top-level
  `group_categories` array (empty when there are none), before any table, using
  the existing tomlkit writer conventions.
- **Top-level key placement:** the migration and `cp` both insert
  `group_categories` before the first table or array-of-tables header, because a
  TOML key written after a header belongs to that table. One shared helper does
  this for both, preserving the rest of the file with tomlkit.
- **cp:** collects string `group_category_id` values from the copied files,
  appends the ones the destination doesn't list (once each), and reports them;
  `--noop` reports only.
- **Manifest:** unchanged. Group sets/group categories are matched by name each
  run, not tracked in the manifest, so `mv`, `prune` and `find-canvas-orphans`
  never see them. Canvas has no lookup-by-name for group sets/group categories;
  the tool lists them all (one request, the same way assignment groups are
  fetched each run) and matches names locally.

## Canvas behavior this depends on

| Behavior | Status |
| --- | --- |
| Exports name the group set/group category (`<has_group_category>true</has_group_category>`, `<group_category>Project Groups</group_category>`) in discussion topic metadata and `assignment_settings.xml`, never its ID | Verified: Kelly Leahy master export (2026-07-15), 15 files |
| Exports contain no group set/group category definitions or groups | Verified: same export, `course_settings/` and manifest resource types |
| `GET /courses/:id/group_categories` lists name and id | Verified: OL-3 course (2735293), 2026-09-27, `update` resolved `Project Groups` |
| `POST /courses/:id/group_categories` with only `name` creates an empty group set/group category | Verified: same course, 2026-09-27 (a newly listed name was created by `update`) |
| Discussion create accepts `group_category_id`; the topic object reports it back (`group_category_id = 286609`) along with `discussion_subentry_count` and `can_unpublish` | Verified: same course, 2026-09-27, ungraded and graded test discussions |
| A graded group discussion can be created in one call with `group_category_id` and the nested `assignment` | Verified: same course, 2026-09-27. The group set/group category lives on the topic only: its assignment reports `group_category_id = None` |
| A group assignment can be created by name and re-synced after a submission without re-sending the group set/group category | Verified: same course, 2026-09-27 (View As Student submission) |
| Canvas refuses to unpublish an assignment with a submission (`Can't unpublish if there are student submissions`) | Verified: same course, 2026-09-27; `update` now keeps it published and reports an error |
| `published: false` unpublishes a graded (group) discussion with no replies | Verified: same course, 2026-09-27 |
| Updating an existing (stub) discussion to add `group_category_id` works when there are no replies | Verified: same course, 2026-09-27 (discussion stub-created by a page link, then synced as a group discussion) |
| Canvas rejects changing the group set/group category after replies or submissions | Unverified; the design does not rely on it, because the safeguard refuses first. Verified on the same course, 2026-09-27: the safeguard refuses a switch, a group discussion re-synced after a Test Student reply keeps the reply, and `published: false` on a discussion with a reply leaves it published with an error |
| Group set/group category names are unique within a course | Unverified; if the GET returns two with the same name, resolution fails the file with an error listing both IDs |
| The student-organized "Student Groups" group set/group category appears in the list | Unverified; harmless unless a repo lists that name |

Live verification (scratch Canvas course, before release): create a listed group
set/group category; create a group discussion, a graded group discussion and a
group assignment by name; re-sync each unchanged after a test student posts or
submits (must succeed with no group change); edit the frontmatter to a different
name and re-sync (must fail with the safeguard error, student post still
visible); check a stub-then-group discussion. The re-sync-after-posts and
change-after-posts steps cover the data-loss risk.

## Risks / Trade-offs

- [Canvas rejects or mishandles group_category_id on topic update] → the live
  verification runs before release; the stub case falls back to deleting the
  unpublished stub and creating the topic if the update path fails.
- [Requiring every name to be listed adds a step for hand-written repos] → the
  error names the missing entry; `import` writes the list automatically.
- [Safeguard reads of reply/submission counts may be stale or absent on some
  Canvas versions] → treat a missing field as "has replies" and refuse.
- [A group set/group category deleted on Canvas is recreated empty, and
  previously grouped items lose their groups] → the creation line in the output
  makes it visible; the tool cannot restore membership.

## Migration Plan

`upgrade` adds `group_categories = []` and stamps version 7; no content file
changes. Repos with numeric `group_category_id` values keep working; to switch a
file to a name, the user adds the name to `group_categories` and edits the value.
Rollback: an older tool refuses the version-7 repo, so rollback means using the
new tool or reverting `format_version` by hand (safe only if no names are used;
the extra `group_categories` key is ignored by older tools).
