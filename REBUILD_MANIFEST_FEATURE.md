# `fix-manifest --pair-canvas-with-local`: design notes

Status: implemented 2026-09-24 (`pair_manifest.py`, `cli.fix_manifest_cmd`);
README.md and ARCHITECTURE.md now hold the maintained description. The command started out
as a separate `rebuild-manifest` subcommand and was folded into `clean-manifest`,
which is renamed `fix-manifest`.

## Motivation

Content imported into a local course repo with `import`, or copied into it
with `cp`, has no entries in the sync manifest (`.manifest-<config>.toml`). The
Canvas items may already exist, but the tool does not know which local file
corresponds to which Canvas item. Running `update` in that state creates a
duplicate in Canvas for every unconnected file.

Typical workflow: `gg cp` content from another course into this one, where a
copy of that content already exists in Canvas (for example because the course
was imported from Canvas), then `gg fix-manifest --pair-canvas-with-local` to
connect the copied files to the existing Canvas items.

A lost or corrupted manifest can be rebuilt the same way.

## Verified current behaviour (before this change)

- `update` does not look up Canvas items by title. With no manifest entry it
  creates the item (`create_or_update_*` with no ID). Canvas gives a duplicate
  page a `-2` URL slug.
- `import` and `cp` do not write manifest entries.
- `clean-manifest` removes entries whose Canvas ID is not in the configured
  course, and marks files that link to them for re-sync. No title matching.
- `update`'s stored-course check (`course_guard.check_course`) already empties
  the manifest when the user confirms a course change, so
  `clean-manifest --no-canvas-check` duplicated what `update` and deleting the
  manifest already do.

## Decisions

### Command shape

- `clean-manifest` is renamed `fix-manifest`. The old name is dropped outright
  (no alias).
- `--clean`: the old `clean-manifest` behaviour.
- `--pair-canvas-with-local`: title matching (below).
- `--force-pair LOCAL_PATH=CANVAS_ID`, repeatable: connect a specific local file
  to a specific Canvas item. Counts as a mode by itself.
- At least one of `--clean`, `--pair-canvas-with-local`, `--force-pair` is
  required. When several are given the order is: clean, then forced pairs, then
  title matching.
- `--apply` makes the changes; without it everything is a report (dry run). In
  a dry run with `--clean` and pairing, pairing is computed against the manifest
  as it would be after the clean, in memory.
- `--yes` stays (skips the course-switch confirmation of `--clean --apply`).
- `--no-canvas-check` is removed. `plan_invalidate_all` stays in the code
  because `course_guard` uses it.
- Pairing (either kind) without `--clean` is refused when the manifest records a
  different course: the user is told to add `--clean`.
- No `repo_format.FORMAT_VERSION` bump: new entries use the existing format.

### What is matched

- Every content type: pages, assignments, discussions, announcements, classic
  quizzes, modules, files.
- Local side: the same files `update` would sync (ignore rules applied).
  - Content folders: every top-level folder except `assets`, `modules`,
    `quizzes`, `snippets`, `course_settings`, `question_banks`; type from the
    folder (`infer_canvas_type`); title from frontmatter `title`, else file stem.
  - `quizzes/<q>/<q>.md`: title from frontmatter, else folder name.
  - `modules/*.md`: title from frontmatter, else stem; matched to module names.
  - `assets/**`: matched by path below `assets/` against the Canvas file's folder
    below `course files/` plus its display name.
- Canvas side: one listing per type. The assignment pool excludes assignments
  that belong to graded discussions or quizzes (`submission_types` contains
  `discussion_topic` or `online_quiz`). Canvas items already referenced by a
  manifest entry (after the clean) are not available for pairing.
- Only local files with no manifest entry are paired automatically.

### Title normalization

HTML entities decoded, Unicode NFKC, curly quotes and dashes folded to ASCII,
whitespace runs collapsed, leading/trailing whitespace stripped, case-insensitive
(`casefold`). Pairs that are equal only after normalization are marked in the
report.

### Duplicates

When one normalized title has several local files and/or several Canvas items of
one type: local files are taken in path order, Canvas items in tie-break order
(published first, then items with submissions, then lowest Canvas ID), and
paired in turn. Every such group is reported with the items not chosen.

### Similar titles

For local files left unpaired, the best unpaired Canvas item of the same type
with a similarity ratio (`difflib.SequenceMatcher` on normalized titles) of at
least 0.6 is suggested; each Canvas item is suggested at most once. Suggestions
are never applied automatically. They are printed as pasteable arguments:

```
--force-pair 'assignments/lab3.md=12345'   # "Lab 3: Loops" ~ "Lab 3 - Loops" (0.91)
```

followed by one complete command containing all of them.

### `--force-pair` rules

- The local path must exist and be a file `update` would sync; the Canvas ID
  must be an item of that file's type in the configured course. Pages take the
  numeric page ID (shown in the report).
- A forced pair replaces an existing entry for that local file; the report says
  so.
- Refused when the Canvas item is already used by another manifest entry, or
  when two `--force-pair` options name the same file or item.
- All problems are reported together and nothing is written.

### Entries written

`canvas_id`, `canvas_type`, plus `canvas_url` for pages (slug) and files
(download URL). No `last_synced`, so the next `update` uploads the local version
over the Canvas item and renders its links with this course's IDs. This
overwrites edits made directly in Canvas; the report says so. Exception: a file
whose local size equals the Canvas file's size gets `last_synced` (now), so
unchanged assets are not re-uploaded.

### Report

- Entries added (local path, Canvas type, Canvas ID, Canvas title), marking the
  normalized-only matches and forced pairs.
- Duplicate-title groups and the choice made.
- Suggested pairs (pasteable), then a complete command.
- Local files with no Canvas match (the next `update` creates them).
- Canvas items with no local match.
- Existing entries whose Canvas title differs from the local title.

After `--apply` the manifest records the configured course, as `--clean` does.
