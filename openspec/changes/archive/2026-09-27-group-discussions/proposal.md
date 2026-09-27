# Proposal

## Why

Canvas can split a discussion into one private sub-discussion per student group
("group discussion"), but markdown-to-canvas silently drops `group_category_id`
from discussion frontmatter, so a course repo cannot express one. Group
assignments are only half supported: `group_category_id` must be a numeric
Canvas ID, which differs per Canvas course (e.g. OL-3 vs OL-4), and `import`
never picks the setting up from a real Canvas export. The tool also never creates
the group set/group category itself, so `update` into a brand-new course cannot
recreate this part of the course.

## What Changes

- Discussion frontmatter accepts `group_category_id`; `update` sends it to
  Canvas, making the discussion a group discussion.
- `group_category_id` (discussions and assignments) accepts a group set/group
  category **name** as the normal form, resolved per Canvas course at sync time.
  A numeric ID is still accepted and sent as-is.
- `course_settings.toml` gains a top-level list of the course's group sets/group
  categories by name, `group_categories = ["Project Groups"]`. Every name used
  in frontmatter must be listed. `update` creates any listed group set/group category that is missing
  from the Canvas course. It creates only the empty group set/group category;
  students are placed into groups in Canvas. It never renames or deletes one.
- A discussion or assignment whose `group_category_id` name cannot be resolved is
  a hard error for that file: the file is not uploaded (so Canvas never gets a
  whole-class version of a group activity), and the run reports the error.
- `import` reads the group set/group category name that Canvas exports
  (`<group_category>` in discussion `topicMeta` and in `assignment_settings.xml`),
  writes it as `group_category_id: "<name>"` in the discussion's or assignment's
  frontmatter, and writes the distinct names to the `course_settings.toml` list
  (always present, `[]` when there are none).
  This fixes an existing bug: import currently looks for a `<group_category_id>`
  tag that Canvas exports never contain, so group settings are lost on import.
- `cp` adds a copied file's group set/group category name to the destination's
  `group_categories` list when it is missing, the way it appends missing rubrics;
  the existing warning for a numeric `group_category_id` stays.
- Removing `group_category_id` from a file leaves the Canvas item's group setting
  unchanged; the README documents that un-grouping is done in Canvas.
- **BREAKING (repo format)**: an older tool would drop a named
  `group_category_id` on discussions (creating a whole-class discussion) and send
  a name string where Canvas expects an ID on assignments. Per the project's
  format-version rule, `repo_format.FORMAT_VERSION` goes from 6 to 7. The
  migration adds `group_categories = []` to `course_settings.toml` when absent
  and changes no content file (existing numeric values stay valid).

### Existing mechanisms this builds on

- `assignment_group_id` already accepts a name or a number and resolves the name
  against the Canvas course each run (`_resolve_assignment_group_id`); group
  set/group category resolution follows the same pattern.
- `[[assignment_groups]]` in `course_settings.toml` is already created on Canvas
  by `update`'s course-settings phase; the group set/group category list follows
  that model (create-if-missing only).
- `cp` already appends missing rubrics to the destination's `rubrics.toml`; group
  set/group category names are merged the same way.
- `_upload_assignment` already passes `group_category_id` and
  `grade_group_students_individually` through; this change adds name resolution
  and the hard error to it.
- `cp` already warns about numeric `group_category_id`.
- Course flags cannot supply per-course values here: frontmatter is never
  flag-processed. Name resolution makes per-course IDs unnecessary.

### TODO.md

Implements part of the "Group sets and group assignments" item (creating group
sets/group categories and attaching discussions and assignments to them). Group
membership (which students are in which group) stays out of scope; the TODO item
is revised to say so.

### Core subcommands

- **update**: affected (frontmatter handling, name resolution, creation of group
  sets/group categories, hard error).
- **import**: affected (reads the exported names, writes frontmatter and the
  `course_settings.toml` list).
- **mv**: not affected. It moves files and rewrites links and manifest keys; it
  does not interpret `group_category_id`, and group sets/group categories are not
  tracked in the manifest.
- **publish**: not affected. The MkDocs site has no students or groups; a group
  discussion is rendered like any other discussion and `group_category_id` is
  ignored.

## Capabilities

### New Capabilities
- `group-categories`: declaring group sets/group categories in
  `course_settings.toml`, creating them on Canvas, attaching discussions and
  assignments to them by name via `group_category_id`, the unresolved-name hard
  error, and importing all of this from a Canvas export.

### Modified Capabilities
- `copy-between-courses`: `cp` merges group set/group category names into the
  destination's list.
- `repo-format-version`: adds migration 6 -> 7 (adds `group_categories = []`).

## Impact

- `src/markdown_to_canvas/sync.py`: `_upload_discussion`, `_upload_assignment`,
  course-settings phase, `SyncContext`, targeted sync setup.
- `src/markdown_to_canvas/canvas_api.py`: list and create group sets/group
  categories.
- `src/markdown_to_canvas/dryrun.py`: `update --check-all` counterparts.
- `src/markdown_to_canvas/imscc_import.py`: `parse_topic_meta`, assignment
  settings parsing, `course_settings.toml` writer.
- `src/markdown_to_canvas/cp.py`: merging names into the destination.
- `src/markdown_to_canvas/repo_format.py`: version 7 and migration.
- Tests for all of the above (Canvas mocked); README.md, ARCHITECTURE.md, TODO.md.
- Canvas API: `GET/POST /courses/:id/group_categories`, `group_category_id` on
  discussion topics.
