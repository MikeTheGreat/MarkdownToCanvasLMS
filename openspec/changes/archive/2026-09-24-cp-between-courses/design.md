# Design

## Context

See proposal.md for the motivation and specs/copy-between-courses/spec.md for the
required behaviour. What matters for the approach:

- **Link style.** Course repos link with relative paths (`../assets/img/x.png`,
  `../snippets/y.md`), resolved against the linking file. `mv` exists mainly to
  keep these links working.
- **Existing reference walker.** `local_orphans.collect_local_refs(file,
  repo_root, snippets_dir)` returns the repo-relative keys that one source file
  references. It covers:
  - content bodies after snippet expansion, so links inside snippets resolve
    against the including file, exactly as `update` resolves them;
  - `annotatable_attachment`;
  - module items, via `parse_module_body`;
  - quiz descriptions and question files, via `split_quiz_body`;
  - question-bank questions.

  It does not apply course-flag conditionals. It does not report which snippets
  were included; `convert.find_referenced_snippets(text, file, snippets_dir)`
  does that.
- **Sync skips old files.** `update` skips a file whose mtime is not newer than
  its manifest `last_synced`.
- **Rubric files.** `rubrics.toml` is written by `import` as `[[rubrics]]` blocks
  with `[[rubrics.criteria]]` sub-tables. The metadata lines are commented out,
  and the ratings are either inline `ratings = [...]` arrays or
  `[[rubrics.criteria.ratings]]` blocks. Rubrics are matched on Canvas by title.
- **Where rubrics apply.** `update` attaches a rubric only to assignments.
  `_apply_rubric` is called from `_upload_assignment` and not from
  `_upload_discussion` (observed in `sync.py`). This is tracked in TODO.md as
  "Add discussion rubric support".

## Goals / Non-Goals

**Goals:**
- The copy either completes in full or writes nothing. Every check runs before
  the first write.
- Reuse the existing reference walker so `cp` and `find-local-orphans` agree on
  what a file references.
- Leave everything in the destination byte-identical except the files `cp`
  creates or (with `--overwrite`) replaces, the appended rubric blocks, and the
  appended `module_order.toml` entry.

**Non-Goals:**
- Copying to a different relative path, and rewriting links. Files keep their
  paths.
- Copying Canvas-side state: manifests, Canvas IDs, group sets, or dates held in
  `course_settings.toml`.
- Copying `course_settings/` files other than individual rubric blocks and the
  `module_order.toml` entry. Assignment groups and course flags are only
  warned about.
- Attaching rubrics to discussions on Canvas. That is the separate TODO item.

## Decisions

These decisions come from the user's answers:

1. **Two phases: plan, then write.** `build_copy_plan()` returns a `CopyPlan`
   holding:
   - the file actions (`new` / `identical` / `conflict` / `snippet-kept` /
     `ignored`);
   - the rubric appends and rubric-difference warnings;
   - the `module_order.toml` change;
   - the links that were not followed;
   - the warnings.

   `run_cp()` prints the plan. It stops if there are conflicts and no
   `--overwrite`, stops after printing under `--noop`, and otherwise writes.
   Nothing is written while the plan is being built.
   The alternative was to copy each file as it is found and roll back on a
   conflict. That was rejected: rolling back is harder to make correct than
   never writing.
2. **Conflict handling.** Files that differ in the destination abort the whole
   run. `--overwrite` replaces them. Identical files are skipped. This is what
   the user chose.
3. **Destination snippets win.** A snippet pulled in as a dependency that
   already exists in the destination is never overwritten, even with
   `--overwrite`. This keeps course-specific snippets such as
   `CANVAS_COURSE_ID` correct. The user chose this.
4. **Links to other content are left unchanged and listed.** The user chose
   this over converting them to plain text. `update` / `--check-all` already
   reports links that don't resolve.
5. **Frontmatter copied byte-identical, with warnings.** The user chose this
   over stripping dates and IDs or copying assignment-group definitions.
6. **Rubric by title.** If the destination has the title, its rubric is used.
   Otherwise the source block is copied. This was in the user's original
   request.

The user also confirmed these, after the first draft of this design:

- **CLI shape.** `cp SRC... COURSE_DIR`, with the destination last and
  required, and the source repo found from the SRC paths as in `mv`. Files land
  at the same relative path, and there is no destination sub-path argument. A
  `KEY:path` source form is left to the TODO item on letting `-t`, `-s` and `mv`
  use the course registry.
- **`module_order.toml`.** A copied module's filename is appended to the
  destination's `module_order.toml`, but only when that file exists.
- **`.canvasignore`.** Files matched by the source's `.canvasignore` are skipped
  and reported.
- **`course_settings/`.** A SRC inside `course_settings/` is refused.
- **Git.** `cp` runs no `git add`.
- **Extra warnings.** `cp` warns about title collisions and about absolute URLs
  that point at the source course.
- **Snippets named as SRC.** A snippet named explicitly as a SRC follows the
  normal conflict and `--overwrite` rule. Only snippets pulled in as
  dependencies defer to the destination's copy.
- **Discussion rubrics.** A discussion's `rubric:` is merged into `rubrics.toml`
  the same way as an assignment's.

These decisions are technical choices:

7. **Dependency walk.** Starting from the SRC files, `cp` classifies each
   file's references from `collect_local_refs` by top-level folder:
   - `assets/…` is copied;
   - references from a module file are followed as copied items;
   - anything else in a content folder is recorded as a link that was not
     followed.

   Snippets come from `find_referenced_snippets`, run on the raw text of the
   file, and of each question file for quizzes. A quiz or bank SRC expands to
   its whole folder. `collect_local_refs` is run inside `local_orphans._quiet()`,
   so snippet-expansion warnings are not repeated in `cp`'s output.
   `sync._get_file_refs` was not used because it skips quizzes.
8. **Raw-text rubric append.** The source `rubrics.toml` is split into blocks
   at each top-level `[[rubrics]]` header line. Each block is parsed on its own
   with `tomllib` to read its title. The whole matching block's text,
   including its sub-tables and commented metadata, is appended to the
   destination.
   The alternative was re-serialising with `toml_write`/`tomlkit`. That was
   rejected because it would drop the commented-out metadata lines and could
   change the layout.

   After appending, the planned destination text is parsed with `tomllib`
   before anything is written. If it doesn't parse, or the new title is
   missing, `cp` aborts with an error.
   Rubric comparison uses the criteria and ratings (`description`,
   `long_description`, `points`) and ignores every other key.
9. **Fresh mtimes.** Files are written with `shutil.copyfile`, which copies
   content only, not `copy2`. This way a replaced file is newer than any
   `last_synced` and `update` uploads it.
10. **`module_order.toml` append via tomlkit.** The file is edited in place with
    `tomlkit`, so comments survive, as `mv` already does when it edits this file.
11. **Format checks.** `repo_format.check_repo_format` runs on both repos before
    anything else is read, inside `run_cp`, so library callers are covered too.
12. **Warnings reuse existing helpers:**
    - `conditionals.find_referenced_flags` and
      `find_referenced_flags_in_frontmatter` for flags, checked against the
      destination's `load_course_flags`;
    - `load_due_dates` and the `relative_due_dates` tables for dates;
    - the `[[assignment_groups]]` names in the destination's
      `course_settings.toml`;
    - a title scan of the destination's content folders for collisions;
    - `course_id` values read directly from `course_settings/canvas*.toml` in
      the source, for the absolute-URL check. They are read with plain
      `tomllib`, not `config.load`, so no API token is needed.

## Risks / Trade-offs

- **[Risk]** A copied link resolves by accident to an unrelated destination
  file at the same path. → Mitigation: the report of links not followed says
  whether the target already exists in the destination, so the user can check
  it.
- **[Risk]** A snippet the destination keeps may produce different text from
  what the source's snippet produced. → Mitigation: this is intended for
  course-specific snippets. Each kept snippet is reported, so the user can
  compare it.
- **[Risk]** A rubric block split at `[[rubrics]]` lines could include comment
  lines that visually belong to the next rubric. → Mitigation: this is
  cosmetic only. The appended text is validated by parsing it before writing.
- **[Trade-off]** Pandoc is needed to find links, the same as for
  `find-local-orphans`. A regex scan would miss links that only exist in the
  converted HTML (for example, inside raw HTML blocks or reference-style
  links).
- **Canvas behaviour this design depends on:** `cp` makes no Canvas calls. The
  later `update` relies on existing, already-used behaviour: rubric lookup by
  title, and creating new items for paths with no manifest entry. That is
  covered by current tests and `todo/RUBRIC_ISSUES.md`. Nothing new is
  unverified. `cp` deletes nothing on Canvas. `--overwrite` replaces local
  files only. If a replaced file already has a manifest entry, the next
  `update` updates that Canvas item as it would after any local edit, subject
  to the existing overwrite protection that skips items newer on Canvas.
- **Manifests:** `cp` does not read or write any manifest. There is no format
  change and no migration.

## Migration Plan

None needed. This is a new command, with no file-format change and no
`FORMAT_VERSION` bump.
