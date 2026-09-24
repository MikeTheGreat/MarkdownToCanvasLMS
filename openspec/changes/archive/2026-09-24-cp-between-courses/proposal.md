# Proposal

## Why

Reusing an assignment, discussion, quiz or whole module from one course in
another is currently a manual job. The user copies the Markdown file, then finds
and copies each image, attachment and snippet it uses, and then copies the
matching `[[rubrics]]` block into the other course's `rubrics.toml`. Any file
that gets missed turns up later as a broken link or a missing rubric. `mv`
cannot help, because it works only inside a single repo.

## Existing mechanisms and how this relates to them

- **`mv`** moves and renames within one repo only. It requires source and
  destination to be in the same repo and the same content-type folder, and it
  rewrites that repo's manifests and links. `cp` is the cross-repo counterpart.
  It does not move anything, and because copied files keep their repo-relative
  paths, their links don't need rewriting, so `mv`'s rewriting code is not
  reused.
- **`import`** builds a whole new repo from a Canvas `.imscc` export. It can
  copy a full course, but it cannot copy selected items into an existing repo.
- **`find-local-orphans`** (`local_orphans.collect_local_refs`) already finds
  every local reference a file makes: body links, image `src`s,
  `annotatable_attachment`, module items, quiz descriptions and question files,
  and links inside snippets. `cp` reuses it to find dependencies.
  `convert.find_referenced_snippets` finds snippet includes, including
  `PASTE_SNIPPET_INTO_FRONTMATTER`.
- **`update -t`** (`sync._get_file_refs`) does a similar reference walk but
  skips quizzes, so `cp` uses the `local_orphans` walker instead.
- **The course registry** (`_resolve_course`) lets `cp` name the destination
  course by key.

## What Changes

- New `cp` subcommand: `markdown-to-canvas cp [-n] [-v] [--overwrite] SRC... COURSE_DIR`.
  It copies the named files or folders from the course repo that contains them
  into the course repo `COURSE_DIR` (a path or registry key), at the same
  repo-relative paths. It is local only and never contacts Canvas. Afterwards
  the user runs `update` on the destination.
- `cp` pulls in each copied item's dependencies:
  - the assets and snippets it references;
  - `annotatable_attachment`;
  - for a quiz, its whole folder;
  - for a module, every item the module lists, with each item's own
    dependencies.
- Links to other pages, assignments, discussions or quizzes, outside a module's
  item list, are not followed. They are left unchanged and listed in the output.
  `update` reports the ones that don't resolve.
- Rubrics: if the destination's `rubrics.toml` already has a rubric with the
  same title, it is used. Otherwise the source's `[[rubrics]]` block is appended
  to it.
- Conflicts: `cp` works out the whole copy first. If any destination file
  exists with different content, it lists them all and writes nothing, unless
  `--overwrite` is given. Identical files are skipped. For a snippet the
  destination already has, the destination's copy is kept and no conflict is
  raised.
- Frontmatter is copied unchanged. `cp` warns about values that won't resolve in
  the destination (assignment group names, course flags, numeric Canvas IDs,
  and dates that live in the source's `due_dates`).
- No breaking changes. No existing file is read differently, so
  `FORMAT_VERSION` is not bumped.

## TODO.md items

- **"Let `-t`, `-s` and `mv` use the course registry"**: this is related but
  not implemented here. `cp` finds its source repo from the SRC paths, as `mv`
  does. A `KEY:path` form for SRC could be added later together with that item.
  `cp` also covers part of that item's open question about `mv` taking two
  different keys, because copying between courses becomes `cp`'s job.
- **"Add discussion rubric support"** (added with this proposal): `cp` copies a
  discussion's `rubric:` like an assignment's, but `update` will not attach it
  on Canvas until that item is done.

## Core subcommands affected

None of `update`, `import`, `mv` or `publish` changes. `cp` only writes files
that `update` already knows how to read, `import` is unrelated, `mv`'s
single-repo behaviour stays as it is, and `publish` builds its site from the
repo as it finds it.

## Capabilities

### New Capabilities
- `copy-between-courses`: the `cp` subcommand. It covers argument handling,
  which dependencies are copied, conflict handling, rubric merging,
  `module_order.toml`, warnings and `--noop` output.

### Modified Capabilities
- `course-registry`: `cp` joins the subcommands that take a `COURSE_DIR`
  argument, and like `prune` it requires that argument.
- `repo-format-version`: `cp` joins the operations that check the format
  version, for both the source and the destination repo.

## Impact

- New module `src/markdown_to_canvas/cp.py` and a `cp` command in `cli.py`.
- Reuses `local_orphans.collect_local_refs`, `convert.find_referenced_snippets`,
  `sync.parse_module_body`, `quiz.split_quiz_body`, `ignore.load_ignore_matcher`,
  `course_registry.resolve_course`, `repo_format.check_repo_format` and
  `config.find_repo_root`.
- Requires Pandoc, because the reference walker converts Markdown to HTML to
  find links.
- New tests in `tests/test_cp.py`, plus updates to the guard lists in
  `test_cli_course_dir.py` and `test_repo_format_enforcement.py`.
- README.md, ARCHITECTURE.md and TESTING.md get new sections.
