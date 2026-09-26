# MarkdownToCanvasLMS — Internal Documentation

## Project Intent

A tool for managing Canvas LMS course content through Markdown files stored in a Git repository. The workflow converts Markdown (and supporting assets) into HTML fragments and uploads them to a Canvas LMS instance via the Canvas API.

## Workflow

```text
// Setup:
Git repo (Markdown + assets)
git clone (local)

// This tool:
1. git pull                             (ensure local copy is up-to-date)
2. load .manifest-<config stem>.toml    (into in-memory dict; single source of truth during the run)
2.1. build ignore matcher               (from optional .canvasignore at repo root; .gitignore is NOT consulted;
     any matched file/dir is skipped during discovery in every phase below)
2.5. if course_settings/course_settings.toml exists: apply course metadata to Canvas (name, dates, flags, grading
     standards, assignment groups, late policy, post policy, rubrics)
     → sections are change-detected individually via hashes cached in the manifest
       entry's section_hashes sub-table; only sections whose values changed are
       re-sent (see "Section-level change detection" below)
2.6. if course_settings/syllabus.md exists: convert body to HTML and set as course syllabus body
2.7. load centralized due_dates from course_settings.toml (if present);
     these override any due_at/lock_at/unlock_at in individual file frontmatter
3. upload assets/                       (see processing order below)
     → skip any file whose mtime ≤ manifest last_synced (unless --force-uploads)
4. for each content folder in alphabetical order (excludes assets/, course_settings/, modules/,
   question_banks/, quizzes/, snippets/, hidden dirs):
     check for title collisions across all .md files (including subfolders) → abort if any
     for each .md file in that folder (recursively, including subfolders), alphabetically:
       a. skip if mtime ≤ manifest last_synced (unless --force-uploads); print "Skipping (up-to-date)"
       b. snippet preprocessing: replace any [text](snippets/...) links with snippet file contents
       c. convert Markdown → HTML via Pandoc
          - accessibility post-pass (mark_decorative_images(), part of markdown_to_html()):
            any <img> with a missing or whitespace-only alt attribute gets alt="" and
            role="presentation" so Canvas's accessibility checker treats it as decorative;
            images with real alt text or an existing role attribute are untouched.
            Note: on import, _simplify_pandoc_attrs() drops role="presentation" from
            attribute blocks (id + style only), leaving ![](...) — this pass regenerates
            the decorative markup on upload, so the round trip is lossless.
       d. for each <img> and <a href> that points to a local file:
            - if local file does not exist → print error, remove the tag, skip (do NOT stub)
            - if in manifest → rewrite tag to Canvas URL
            - if NOT in manifest → create empty stub in Canvas (unpublished, title only)
                                   → add to manifest dict AND flush to disk
                                   → rewrite tag to Canvas URL
       e. upload the fully-resolved HTML to Canvas (create or update via manifest)
       f. update manifest dict and flush to disk
4a. if phase 2.5 had to re-create any rubric (Canvas no longer listed it), re-associate
     every assignment that references it by title — including assignments whose own .md
     was up-to-date and therefore skipped in phase 4 (see "Rubric-level change detection")
4b. for each quiz folder in quizzes/ alphabetically:
     → skip if quiz .md AND all question files have mtime ≤ manifest last_synced
     → parse quiz-level .md (frontmatter + ordered question list); numbered
       links inside code fences are literal text, not questions
     → parse each question .md file
     → run rewrite_links() on quiz description HTML and each question_text HTML (same as step 4d)
     → create or update quiz in Canvas (Classic Quizzes API), WITHOUT the publish state
     → delete all existing quiz questions, re-add in order
     → apply the publish state last (finalize_quiz_publish_state); warn if a manual
       "Save It Now" is needed (see "Quiz publish ordering" below)
     → update manifest dict and flush to disk
4c. for each question bank in question_banks/ alphabetically:
     → skip if bank .toml mtime ≤ manifest last_synced (unless --force-uploads)
     → parse bank metadata .toml; parse each question .md in questions/
       (validation only: parse errors are reported as usual)
     → print a WARNING and skip — never uploaded, nothing recorded in the manifest.
       canvasapi has no question-bank methods and Canvas's public REST API for
       assessment question banks is GET-only, so there is no write path. (The
       old canvas_api.sync_question_bank called course.create_question_bank(),
       which doesn't exist, and crashed with AttributeError on a real course;
       it was removed.) Import's default .canvasignore excludes question_banks/**.
4d. if front_page is set in course_settings.toml AND either the front_page value
     changed (its section hash) or the target page's .md was re-synced in this
     run → set_front_page (skipped otherwise, to avoid a redundant API call)
5. sync modules/ alphabetically         (all content IDs now guaranteed in manifest)
     → skip any module whose mtime ≤ manifest last_synced (unless --force-uploads)
6. due_dates pass (every run): for each gradeable item with a due_dates entry,
     compare the entry's symbolic resolution against the resolved_dates cache in
     the item's manifest entry; API calls only for items whose resolution changed
     (see "due_dates resolved-value caching" below)
```

**Processing order:**

Course settings and syllabus are applied first. Then `assets/`. Then regular content folders alphabetically. Then `quizzes/`. Then `question_banks/`. Finally `modules/`. All other content folders (`announcements/`, `assignments/`, `discussions/`, `pages/`, etc.) are processed in alphabetical order, with files within each folder also sorted alphabetically. `course_settings/`, `question_banks/`, `quizzes/`, `snippets/`, and `assets/` are excluded from the regular content pass — each has its own dedicated phase.

**Quiz publish ordering ("Save It Now"):**

Canvas Classic Quizzes keep a snapshot (`quiz_data`) of the questions that students actually see. Editing questions (create/update/delete, via UI or API) only sets `last_edited_at` on the quiz; the snapshot is regenerated when the quiz is *saved through the web UI* or when it *transitions* to published. While `last_edited_at > published_at`, the quiz page shows the "you have unsaved changes… Save It Now" banner and **students keep seeing the old questions**. The REST API has no equivalent of the "Save It Now" button: `PUT /quizzes/:id` with `published=true` on an already-published quiz is a no-op state-wise (Canvas only regenerates on a `workflow_state` *change*), and the unpublish→republish dance is rejected when the quiz has student submissions and re-sends "assignment created" notifications in a published course, so the tool deliberately does not attempt it.

What the tool does instead (`_sync_quiz` in `sync.py` + `finalize_quiz_publish_state` in `canvas_api.py`):

- The initial create/edit call omits `published`, so new quizzes are created unpublished.
- Questions are synced next.
- The publish state from frontmatter is applied **last** (with `notify_of_update: false`). For a quiz being published this run (new, or previously unpublished), the unpublished→published transition regenerates the snapshot — no banner, no manual step.
- If the quiz was **already published and stays published**, nothing programmatic can absorb the question changes: the tool prints a warning (also collected into the end-of-run error summary) with the quiz's `html_url` telling the user to open it and click "Save It Now".

**Fenced code blocks in Markdown input:**

All Markdown-input parsing respects fenced code blocks, built on shared primitives in `convert.py` (`split_fenced_segments`, `iter_lines_with_fence_info`, `apply_outside_fences`):

- **Code fences** are literal text: numbered `[x](y.md)` links inside them are not quiz questions (`quiz.split_quiz_body`, shared by sync and the publish study guide), `- [x](y.md)` / `# heading` lines are not module items (`parse_module_body`), `## Answers`-lookalikes do not split question files (`_split_on_headings`), and numbered lines are not answers. Raw-attribute blocks (```` ```{=html} ```` etc.) are fences like any other; there is no special handling beyond what Pandoc itself does with them. (Content is *excluded* via course-flag conditionals, not via raw-attribute "comment" blocks — that older convention has been removed.)
- **Snippet expansion** (`preprocess_snippets`) and the staleness probe (`find_referenced_snippets`) skip fence content, so `$path.md$` / snippet links in a code block stay literal.
- **publish's Pandoc-syntax cleanup** (`_strip_pandoc_syntax`, `_rewrite_quiz_links`) applies only outside fences, so literal `{#id}` / span / quiz-link examples in code blocks survive staging.
- Fence matching follows CommonMark closely enough for course content: ` ``` ` or `~~~` (3+, up to 3 leading spaces), closed by an equal-or-longer fence of the same character; an unclosed fence runs to end of file; fence-lookalikes inside a longer outer fence (e.g. a ``` ``` ``` example shown inside a ` ````markdown ` block) are content, not fences. Indented (4-space) code blocks and inline backtick spans are *not* considered fences by these parsers.

Not fence-aware by design: `mv`'s link updating (renames also fix example links in code blocks, keeping them valid), orphan detection's "in use" scan (a Canvas URL in a code block still protects content from `prune` — conservative), and `link_rewrite.py` (operates on Pandoc's HTML output, where code content is already escaped).

**Content subfolder support:**

Content folders (`pages/`, `assignments/`, `discussions/`, and any other content directories) support arbitrary subdirectory nesting. Files are discovered recursively (`rglob`) and sorted alphabetically by their full relative path. Canvas itself uses a flat namespace (pages are identified by title/slug, assignments and discussions by title), so the subfolder structure is purely for local organisation — all files are flattened when uploaded to Canvas.

Before any content is uploaded, the tool checks for **title collisions**: two or more `.md` files within the same content type that would resolve to the same Canvas title (from frontmatter `title`, or the filename stem as fallback). If a collision is detected, the sync aborts with an error listing the conflicting files. Titles are scoped per content type — `pages/intro.md` and `assignments/intro.md` sharing the title "Introduction" is fine, but `pages/week1/intro.md` and `pages/week2/intro.md` both titled "Introduction" is an error.

The manifest tracks each file by its full repo-relative path (e.g. `pages/week1/notes.md`), so subfolder files get their own manifest entries and can be targeted with `-t` and `-s`.

The `publish` subcommand discovers content in subfolders the same way, and stages files preserving their subfolder structure (e.g. `docs/pages/week1/notes.md`).

Asset traversal is depth-first with files before subdirectories, both sorted alphabetically:

```text
assets/fig.png          ← files at this level first, alphabetically
assets/logo.png
assets/images/          ← then subdirectories, alphabetically
assets/images/chart.png
assets/images/diagram.png
assets/slides/
assets/slides/week1.pdf
```

**Ignore files:**

An optional `.canvasignore` at the repo root controls which files are uploaded. Patterns use git's `gitwildmatch` syntax (via the [`pathspec`](https://pypi.org/project/pathspec/) library), so negation (`!`), `**`, anchoring, and directory-only patterns (`build/`) all behave as in git. `.gitignore` is deliberately **not** consulted: this lets a repo exclude per-term materials from git while still uploading them to Canvas. Content that should be excluded from both git and Canvas must be listed in both files (the duplication is expected and fine). Matching is applied at every discovery point (assets, content folders, quizzes, question banks, modules), matching repo-root-relative POSIX paths; a matched directory is pruned entirely (its contents are never walked). With no `.canvasignore` present, nothing is matched and every file is processed as before. The tool's own manifests (`.manifest-*.toml`, plus the legacy `.canvas-manifest.toml`) are always excluded. Ignoring a file only stops future uploads — it does **not** prune anything already on Canvas (the file still exists locally and keeps its manifest entry; see the `prune` subcommand for removing content). Implemented in `ignore.py`.

**Asset upload detail:**

The `assets/` folder hierarchy is mirrored into Canvas Files. `assets/images/fig.png` is uploaded into a Canvas folder named `images` (not into the course root). This keeps the Canvas Files area organised and avoids name collisions.

**Post-Pandoc link-rewriting detail:**

- `<img src="../assets/images/x.png">` → look up Canvas file URL from manifest → rewrite src
- `<a href="../pages/foo.md">` → look up or stub-create → rewrite to `/courses/:id/pages/slug`
- `<a href="../assignments/bar.md">` → look up or stub-create → rewrite to `/courses/:id/assignments/:id`
- `<a href="../discussions/baz.md">` → look up or stub-create → rewrite to `/courses/:id/discussion_topics/:id`
- `<a href="../announcements/qux.md">` → look up or stub-create → rewrite to `/courses/:id/discussion_topics/:id` (announcements are discussion topics)
- `<a href="../quizzes/foo/foo.md">` → look up → rewrite to `/courses/:id/quizzes/:id`
- `<a href="../modules/week-1.md">` → look up or stub-create (an empty module) → rewrite to `/courses/:id/modules#module_:id`
- `<a href="https://...">` → leave unchanged
- `<a href="#anchor">` → leave unchanged

**Stub creation:**

When a linked file has no Canvas ID yet, the tool creates a minimal placeholder in Canvas (title only, empty body, unpublished) purely to obtain the Canvas ID. The stub is overwritten with real content when that file is processed in the main loop. Stubs exist for pages, assignments, discussions, announcements, quizzes (title only, unpublished; `_do_quiz()` later edits it by id) and modules. Content type for the stub is derived from the linked file's directory convention or its frontmatter `canvas_type` field.

A stub entry is recorded without `last_synced`, and `_canvas_is_newer()` returns False for any entry lacking `last_synced`. Without that rule the stub's Canvas `updated_at` (seconds old) always beats the local file's mtime, so the file was reported as "Canvas is newer" and the stub was never filled in. Entries without `last_synced` only ever come from this tool (stubs and partially failed uploads recorded with `mark_synced=False`), so there is no Canvas-side edit to protect.

A markdown link with a missing URL (e.g. `[text]( "title")`, produced by a bad or auto-generated reference) becomes an `<a href="">` in the Pandoc output. `_to_local_key()` resolves an empty href to `source_file.parent` itself, i.e. the file's own containing folder (`assignments/`, `pages/`, etc.). `_resolve_entry()` in `link_rewrite.py` therefore treats that folder path as a real, existing, not-yet-synced local file and stub-creates a bogus Canvas item titled after the folder (e.g. an assignment named "Assignments"), landing in whatever assignment group Canvas defaults new assignments into. `_resolve_entry()` now checks `local_file.is_dir()` alongside `local_file.exists()` and treats a directory match the same as a missing file — printing the removing-tag error and dropping the link — rather than stub-creating from it.

`modules/` maps to `"module"` in `link_rewrite._FOLDER_TO_TYPE`. Before that mapping existed, a link to a module file fell through to the `"page"` default and stub-created a Canvas page, leaving a page entry under the module's manifest key; `_reorder_modules()` then called `get_module()` with the page id and crashed with `ResourceDoesNotExist`. For manifests already in that state, `_sync_module()` discards a non-module entry (warning the user to delete the stray page), `_reorder_modules()` treats a non-module entry as not yet synced, and a failed local reposition is reported as an error instead of aborting the run. `create_or_update_module()` re-creates a module that was deleted on Canvas, matching the other content types.

**Exception — assets are uploaded, not stubbed.** `canvas_type = "file"` has no stub form: Canvas offers no placeholder file object, and `capi.create_stub()` raises `ValueError` for it. It does not need one either — unlike a page, a file's content is fully known at reference time, so there is nothing to fill in on a later pass. `_make_stub_creator()` therefore branches on `"file"` and calls `capi.upload_asset()` outright (printing `Uploading referenced asset:` instead of `Stub-creating:`). This matters because the syllabus and content phases both run *before* the asset walk, so a syllabus or page link to a not-yet-uploaded asset always arrives here first; before this branch existed it aborted the whole run. The upload records `last_synced`, so the later asset walk skips the file as already synced. `assets_root` is `<repo>/assets` — safe because `"file"` is only ever inferred from an `assets/` path (`link_rewrite._FOLDER_TO_TYPE`).

**Manifest flushing:**

The manifest is flushed to disk immediately after every write (stub creation, asset upload, content upload) — not batched. This means an interrupted sync can be resumed without re-uploading already-completed items or losing Canvas IDs.

**Console output:**

```text
Uploading asset: assets/images/fig.png
Skipping (up-to-date): assets/slides/week1.pdf
Processing: assignments/week1.md
  Stub-creating: pages/syllabus.md (referenced but not yet synced)
  Uploading: assignments/week1.md
Skipping (up-to-date): discussions/week1-intro.md
Processing: pages/syllabus.md
  Uploading: pages/syllabus.md
Syncing module: modules/week-1.md
```

## `update` Subcommand

```text
Usage: markdown-to-canvas update [OPTIONS] [COURSE_DIR]
```

`COURSE_DIR` is a positional argument (a path or a registry key); there is no `--repo` flag.
It is optional — see [Course-directory resolution](#course-directory-resolution) below.

After `get_course()` and before either `run_sync` or `run_targeted_sync`, the CLI runs
the stored-course check (`cli._guard_course` → `course_guard.check_course`; see
"Stored course (`_canvas_course`)" under the manifest file). `-y/--yes` answers its prompt
(needed with no TTY). `--check-all` skips the check.

Before any of that, `run_sync`, `run_targeted_sync` and `course_guard.check_course` call
`repo_format.check_repo_format()`, which refuses a repo or manifest in a different
format version (see "Repo format version and `upgrade`").

### Course-directory resolution

Every command that acts on an existing course takes `COURSE_DIR` and resolves it the same
way: `update`, `publish`, `prune`, `fix-manifest`, `fix-markdown`, `upgrade`,
`generate-due-dates`, `list-titles`, `find-canvas-orphans`, `find-local-orphans` and
`emit-workflow`. The
argument is declared once, by `cli._course_dir_argument()`, as a plain string (not a
`click.Path`, which would reject a registry key) with `course_registry.complete_course` as
its `shell_complete`. `cli._resolve_course(course_dir, config)` does the resolving, prints
`Course dir: <absolute path>` (plus `  (course KEY)` when a key was used) as the first
line of output, and returns `(directory, config)`:

- **Argument given** — `course_registry.resolve_course()`: if a directory exists at that path
  it is used as typed, with no walking up (a wrong path still fails with the missing
  `course_settings/canvas.toml`, rather than silently acting on some parent directory the
  user did not mean). Otherwise the argument is looked up as a key in the registry. A path
  therefore beats a key. Neither → an error that lists the registered keys; a registered
  directory that is gone → an error naming the key.
- **Argument omitted** — walk up from the current working directory via `find_repo_root()`
  looking for `course_settings/course_settings.toml`, so the command can be run from any
  subdirectory of the course. If no course encloses the cwd, the command exits asking for
  the argument. `prune` is the one exception: its argument is `required=True`, so it is
  never inferred from the cwd (it changes Canvas).
- **Config** — the second return value is `--config` if the command line gave one, else the
  registry entry's `config` (joined to the course directory), else `None`, meaning the
  command's own default `<course dir>/course_settings/canvas.toml`. Only a course named by
  key can get a registry config; a path, or a walk-up, never does. Commands with no
  `--config` (`upgrade`, `generate-due-dates`, `find-local-orphans`, `emit-workflow`)
  discard it. The manifest name derives from the config path (`manifest_path_for`), so a
  registry config selects the section's manifest exactly as `--config` does.

**Click gotcha.** `_course_dir_argument(required=True)` must not pass `default=None`: with
Click 8.4 an explicit `default=None` made a required argument optional, so `prune` fell
through to the walk-up. `tests/test_cli_course_dir.py::test_prune_requires_an_argument_even_inside_a_course`
guards it.

`find_repo_root()` lives in `config.py` because it encodes knowledge of the
`course_settings/` layout. `mv.py` re-exports it (`from .config import find_repo_root`) —
`mv` has always derived its repo root this way, from the source/dest paths rather than the
cwd, and that behavior is unchanged. `mv` has no `COURSE_DIR`, and `update -t/-s` still
resolve relative paths against the cwd; letting them use a registered course is in TODO.md.

`import` deliberately does *not* participate in resolution: its `OUTPUT_DIR` names a repo to be
**created** (it writes `course_settings/` itself and requires an empty or new directory),
so searching for an existing enclosing repo would be backwards. It gains `--register KEY`
instead (below).

### The registry (`course_registry.py`)

Per-user files live under `~/.config/markdown-to-canvas/` (`Path.home()` is looked up on every
call, so tests move `HOME`; `XDG_CONFIG_HOME` is not consulted):

| File | Purpose |
| --- | --- |
| `course_registry.toml` | `[courses]` table: `key = "<path>"` or `key = { path, config }` |
| `terms/<name>.toml` | term files, named on the command line without `.toml` |
| `.env` | fallback for `CANVAS_API_TOKEN` and other variables |

The module imports nothing that reads `CANVAS_API_TOKEN` (no `config`, no `canvas_api`),
because `cli` calls `load_env_files()` before those imports.

- **Lazy reading.** `_read_courses()` is called only when a key must be looked up (and by the
  completion helpers), so a path argument or a walk-up works with a broken or missing
  registry. A whole-file TOML error is a `RegistryError` naming the file; an entry is
  validated only when *that* key is looked up (`_parse_entry`: string or table, keys limited
  to `path`/`config`, a leading `~` expanded, anything else non-absolute rejected), so one bad
  entry does not break the others. `RegistryError` subclasses `Exception`, not `ValueError`,
  so `die()` does not get a "KeyError or ValueError:" prefix.
- **Terms.** `resolve_term(arg)`: an existing file at the path wins, else
  `terms/<arg>.toml`, else an error naming both places and listing the terms. An argument
  ending in `.toml` is never looked up as a name.
- **`.env`.** `load_env_files()` keeps the old call (`find_dotenv(usecwd=True)`, `override=True`,
  so a `.env` from the cwd or a parent beats the shell) and then loads the fallback with
  `override=False`. Precedence: cwd `.env`, then the shell, then the fallback. The fallback load
  is skipped silently when the file is absent.
- **`import --register KEY`.** `check_key_free()` runs before `run_import` (so a taken key
  stops before anything is written); `add_entry()` runs only after the import succeeded. It
  edits the registry with `tomlkit` (comments and other entries survive) and never overwrites a
  key. If registration fails after a successful import, the error says the import itself
  succeeded.
- **Completion.** `complete_course` returns the keys that start with the typed prefix plus a
  `dir` item, and `complete_term` the term names plus a `file` item (Click's shell scripts
  then fall back to directory or file completion when no key matches). Both swallow errors and
  read the registry at Tab time; `install-completion` writes Click's stock script, which calls
  the program on each Tab, so a key added later is offered without reinstalling.
  `tests/test_course_registry.py` drives Click's `bash_complete` protocol in a subprocess.

## CLI Options

### `--force-uploads`

Re-uploads every file regardless of its mtime vs `last_synced`. Bypasses the timestamp check for all file types (assets, content, modules).

### `--force-overwrite`

Skips the Canvas-side timestamp check entirely and always overwrites whatever is in Canvas. Use this when you know the local files are authoritative and want to avoid the extra API calls that the overwrite-protection check requires.

Without this flag, after a file passes the local mtime check, the tool fetches `updated_at` from Canvas for every item that already exists in the manifest. If Canvas has a newer version (i.e. someone edited the item directly in Canvas after the last sync) the upload is skipped and the file is added to a summary list printed at the end of the run — making it easy to review which items diverged before deciding whether to overwrite them.

### `--target-recursively / -t` (BFS selective sync)

Accepts a comma-separated list of local file paths. For each target, the tool:

1. Converts and uploads the file (subject to timestamp check, overridden by `--force-uploads`)
2. Extracts all locally-referenced files from its content:
   - Content files: local `<img src>` and `<a href>` targets found in the Pandoc-converted HTML
   - Module files: all items listed in the module body
3. Adds any unvisited referenced files to a BFS queue
4. Repeats until the queue is empty

Modules encountered during BFS are deferred until all other content in the BFS wave has been processed and has manifest entries, because `add_module_item` requires canvas IDs for all referenced content. This matches the ordering guarantee of the full sync.

The full course sync is skipped when `-t` or `-s` is present.

### `--single-target / -s` (non-recursive selective sync)

Accepts a comma-separated list of local file paths. Each file is converted and uploaded (subject to timestamp check) with no BFS traversal of its references. The full course sync is skipped.

### Combining `-t` and `-s`

`-t` runs first (full BFS). `-s` runs afterwards, independently — it does not consult `-t`'s visited set. Instead, the manifest `last_synced` timestamps written by `-t` prevent `-s` from re-uploading anything that `-t` just processed, because `needs_sync` compares file mtime against the freshly written `last_synced`.

This ordering means: run `-t` on a module to recursively re-sync everything it references, then run `-s` on a few additional targeted files without worrying about overlap.

### Target path resolution

Paths passed to `-t` and `-s` are resolved as follows:

- Absolute paths: used directly, then made relative to `COURSE_DIR`
- Relative paths: resolved relative to the current working directory, then made relative to `COURSE_DIR`

Paths that resolve outside the repo root print a warning and are skipped.

### `--check-all` (offline dry run of a fresh full sync)

Runs the **entire** `run_sync` pipeline as a dry run simulating a first sync
to a brand-new empty Canvas course. Nothing is uploaded, nothing is written,
Canvas is never contacted (no API token required — `config.load()` takes
`require_token=False`). Exits nonzero if any errors/warnings were collected,
so it can gate a deploy script. Rejected in combination with `-t`/`-s`
(check-all always checks everything) and with `--force-uploads`/
`--force-overwrite` (both meaningless: every file is already treated as new
and Canvas timestamps are never consulted).

Mechanism (see `run_sync(check_all=True)` in sync.py and `dryrun.py`):

- **API indirection**: all Canvas traffic in the sync pipeline goes through
  `SyncContext.api` (default: the real `canvas_api` module). Functions outside
  the ctx graph (`sync_course_settings`, `_make_stub_creator`,
  `_canvas_is_newer`, `_reorder_modules`) take an `api=capi` parameter.
  Invariant: **no direct canvasapi calls in sync.py's run_sync graph** — the
  one historical exception (syllabus `course.update(...)`) now goes through
  `capi.update_syllabus_body`. (`course.get_quiz` in `_sync_quiz` is the
  remaining pass-through; `DryRunCourse` implements it.)
- **`dryrun.DryRunCanvas`** mirrors the canvas_api function signatures and
  return shapes with fake ids. It is lightly stateful — assignment groups and
  rubrics "created" by the settings phase are returned by the corresponding
  `get_*_ids` calls — so name resolution (rubric references, assignment-group
  names) behaves exactly like a real first sync. Its `add_module_item`
  replicates the real function's *local* validation (manifest lookup,
  supported-type check) so missing module items still warn. When the pipeline
  grows a new canvas_api call, add its dry-run twin here; test_check_all's
  full-fixture run catches a missing one as an AttributeError.
- **Manifest**: the on-disk manifest is ignored — the run starts from an empty
  in-memory dict, so every file takes the full first-sync path. The in-memory
  manifest is still populated with fake entries during the run (link
  rewriting, `annotatable_attachment` resolution, and module items read it),
  but `manifest_path=None` makes `manifest_lib.flush()`/`record()` skip the
  disk write, so the manifest file is byte-identical afterwards.
- **Output**: a `CHECK MODE` banner, then the normal pipeline output with
  action verbs softened via `ctx.check_only` ("Would upload:" instead of
  "Uploading:", `Link:` lines suppressed — the fake URLs mean nothing).

What it cannot validate: anything only the Canvas server decides (date
rejections outside the term, quizzes needing a manual "Save It Now",
publish-state rejections, permissions). `sync_tab_configuration` is a no-op in
dry-run — tab ids/labels can only be checked against a live course.

## `prune` Subcommand

```text
Usage: markdown-to-canvas prune [OPTIONS] COURSE_DIR

  --delete         Delete the orphaned items from Canvas.
  --unpublish      Unpublish (set published=False) the orphaned items on Canvas.
  --manifest-only  Remove orphaned entries from the local manifest only; never
                   touch Canvas.
  --config PATH    Path to canvas.toml (default: <COURSE_DIR>/course_settings/canvas.toml)
  -y, --yes        Record the course for a manifest that has none without asking
```

`--delete`/`--unpublish` run the stored-course check (`cli._guard_course`, see
"Stored course (`_canvas_course`)" under the manifest file) after connecting;
`--manifest-only` does not, since it never contacts Canvas. `run_prune`'s orphan
scan skips the reserved course entry (its key is not a repo path).

Removes Canvas items whose local source file no longer exists. Because the
manifest is the only record of what the tool created, an entry is treated as an
**orphan** when `COURSE_DIR / <local_key>` is gone from disk — which covers both
deleting a file and renaming one (a rename leaves the old path orphaned while the
new path syncs as a fresh item, per the path-keyed manifest).

Exactly one of `--delete`, `--unpublish`, or `--manifest-only` is required; there
is no default, so the intent is always explicit. Changes are applied immediately
(no preview or confirmation prompt). Pandoc is **not** required for this
subcommand.

`--manifest-only` is a local escape hatch: it drops every orphaned manifest entry
without contacting Canvas at all (no API token or course connection needed). Use
it to clear entries that the Canvas-touching modes leave stranded — items already
deleted on Canvas by hand, unsupported `canvas_type`s, or in-use protected
resources. It ignores the in-use protection and type-support rules below because
it never changes anything on Canvas; it only forgets the local bookkeeping.

When the Canvas object for a `--delete`/`--unpublish` orphan is **already gone**
(deleted manually or by an earlier run), Canvas returns a not-found error. The
desired end state is already reached, so this is treated as success and the stale
manifest entry is dropped rather than failing on every subsequent run.

### How it works

1. Load the manifest and compute the orphan set: every entry whose local file is missing.
2. Query Canvas for the resources it is **actively using** outside of modules — the
   course front page (`course.show_front_page()`) and anything linked from the
   syllabus body (`syllabus_body` scanned for `/courses/.../pages|assignments|...`
   references). These are protected: even when their local file is gone, prune
   keeps them rather than removing content Canvas still relies on.
3. For each orphan, dispatch by `canvas_type`:
   - If the item is covered by a `pinned_resources` entry in
     `course_settings.toml`, skip it (kept, manifest entry retained) — a pin
     means "never touch this on Canvas", and deleting a pinned quiz would
     destroy the student submissions the pin protects. `--manifest-only` is
     exempt (it never contacts Canvas).
   - If the item is in use as the front page or syllabus, skip it (kept, manifest entry retained).
   - `--delete`: fetch the object and call `.delete()`, then drop the manifest key.
   - `--unpublish`: set `published=False` on the object, then drop the manifest key.
   - The Canvas object is addressed by URL slug (`canvas_url`) for pages and by `canvas_id` for everything else — the same identifier rule used by the timestamp check.
4. Flush the manifest after each successful prune, so an interrupted run leaves a consistent file.
5. Print a `N deleted/unpublished, P kept (in use or pinned), M skipped, K errors` summary.

A failure on one item is caught, reported as a warning, and does **not** abort the
run — that entry keeps its manifest key so it can be retried.

### Type support

| `canvas_type` | `--delete` | `--unpublish` |
| --- | --- | --- |
| `page`, `assignment`, `discussion`, `announcement`, `quiz`, `module` | ✅ deleted | ✅ unpublished |
| `file` | ✅ deleted | ⏭️ skipped (Canvas files use a hidden/locked state, not a `published` boolean) |
| `question_bank` | ⏭️ skipped (no reliable delete via `canvasapi`) | ⏭️ skipped (no unpublish concept) |
| `syllabus`, `course_settings`, `module_order` | ⏭️ skipped (bookkeeping / course fields, no standalone object) | ⏭️ skipped |
| `external_module` | n/a — never treated as an orphan (see below) | n/a |

Skipped orphans print a warning and **retain** their manifest entry (nothing is
changed on Canvas), so they can be cleaned up manually if needed.

`external_module` entries (keys under `canvas_modules/`) are filtered out
*before* the orphan scan rather than skipped inside it: they cache the Canvas id
of a module that has no local file by definition, so the "no file on disk"
heuristic would flag every one of them on every prune run.

### Canvas-only modules in `module_order.toml`

`_load_module_order` classifies each `order` entry by whether it ends in `.md`:
a filename resolves through `modules/` and the manifest as before, anything else
is the name of a module that lives only on Canvas. Empty and non-string entries
raise `ValueError` (a whole-run config error, reported via `die()`), which is
what retires the older trick of using `""` to reserve position 1 for a module
the tool could not name.

Positions are the 1-based index into the full list, so Canvas-only entries
occupy real slots; `_local_module_positions` projects out just the file entries
for the per-module `position` passed during a normal content sync.

Name resolution (`_resolve_external_module_id`) matches on
`name.strip().casefold()` against `capi.get_module_ids_by_name(course)`, so a
capitalization change on the Canvas side does not break the file. Canvas allows
duplicate module names, hence the name→**list** of ids; an ambiguous name is an
error rather than a guess. The resolved id is cached as

```toml
["canvas_modules/Getting Started at Cascadia"]
canvas_id = 4213
canvas_type = "external_module"
```

so the happy path costs no `get_modules()` call at all. A cached id that fails
to reposition (module deleted or re-created by whoever owns it) falls back to a
fresh name lookup, which refreshes the cache. The one `get_modules()` call a
reorder pass may need is threaded through the loop as `name_index` so several
unresolved names still cost one request.

Under `--check-all` the simulated course is empty, so `DryRunCanvas`'s
`get_module_ids_by_name` returns an index in which *every* name resolves —
otherwise a check would report the real course's Canvas-only modules as
missing.

As with local modules, Canvas-only modules are repositioned only when
`module_order.toml` itself is stale (or targeted, or `--force-uploads`).
Canvas's insert-and-shift positioning keeps a correctly placed module in place
while other modules are re-synced around it.

## `fix-manifest` Subcommand

```text
Usage: markdown-to-canvas fix-manifest [OPTIONS] [COURSE_DIR]

  --config PATH                   Path to canvas.toml
  --clean                         Remove entries whose Canvas item is not in the course.
  --pair-canvas-with-local        Add entries for unpaired local files by title.
  --force-pair LOCAL_PATH=CANVAS_ID
                                  Pair one file with one Canvas item (repeatable).
  --apply                         Make the changes. Without it, only report.
  -y, --yes                       With --clean --apply, skip the course-switch confirmation.
```

Renamed from `clean-manifest` (2026-09-24; the old name was dropped with no
alias, and so was its `--no-canvas-check` option, which duplicated deleting the
manifest and `update`'s own course-change path; `plan_invalidate_all` stays
because `course_guard` uses it). The CLI wrapper is `cli.fix_manifest_cmd`. It
dies unless at least one of `--clean`, `--pair-canvas-with-local`,
`--force-pair` is given; `--force-pair` values are parsed before anything else,
so a malformed one fails before Canvas is contacted.

Order of work in `fix_manifest_cmd`:

1. Resolve the course, `_ensure_pandoc()` only with `--clean` (the referrer scan
   converts Markdown; pairing does not), `get_course`, then
   `clean_manifest.load_manifest` (repo format check + load).
2. Pairing without `--clean` on a manifest whose `_canvas_course` differs from
   the configured course → `die()`: the entries' IDs belong to the other course
   and would sit next to new ones.
3. `clean_manifest.list_course(course)` → `capi.list_course_objects(course)`,
   one listing for both jobs. Any exception except `ConnectionError` becomes
   `die()` before anything is written.
4. `--clean`: `plan_clean(manifest, listing.ids, ...)`. Pairing then runs on
   `working`, a shallow copy of the manifest without `clean_plan.removals`, so a
   dry run shows the pairs the clean frees up.
5. Pairing: `pair_manifest.collect_local_items(repo)` then
   `pair_manifest.plan_pairing(working, listing, local_items, forced,
   match_titles=pair_titles)`. A `PairError` → `die()`.
6. Without `--apply`: print both reports and stop. With `--apply`: the
   course-switch confirmation (only reachable with `--clean`, because of step
   2), `apply_clean` (flushes and records the course), `apply_pairing` +
   `set_course_identity` (flushes), then the reports.

### `capi.list_course_objects`

Returns `CourseListing(ids, items)`. `ids` is `{canvas_type: set(ids)}` for
`--clean`: pages by `page_id`, all assignments, discussion topics ∪
announcements (used for both `discussion` and `announcement`, since a topic's
announcement flag can change), classic quizzes, modules (also used for
`external_module`), files. `items` holds `CanvasObject` tuples for pairing, per
type. The assignment pool leaves out assignments whose `submission_types`
contains `discussion_topic` or `online_quiz`: those are graded discussions and
quizzes, and pairing an `assignments/` file with one would point it at the
wrong object. For files, `title` is the path below `course files/`, built from
`course.get_folders()` `full_name` plus `display_name` (the name
`upload_asset` uploads under); `published` is `not locked`; `size` is kept for
the re-upload decision. Exceptions propagate on purpose so a failed listing is
never read as "the course has none". This replaced `list_course_object_ids`.

### `--clean`

Implemented in `clean_manifest.py`.
Removes manifest entries whose Canvas object is not in the configured course,
without any title/slug matching (each entry already names its Canvas ID). This is
the repair path for three failure modes `update` cannot see because
`last_synced` says the entry is current: `course_id` changed after a sync, an item
deleted directly in Canvas, and a wrong type recorded by an older version (links to
`modules/*.md` once stub-created pages). It is also a way to switch a
manifest that records one course to another (see the stored-course check).

Canvas is only read. Pandoc is required (the referrer scan converts Markdown).

1. The ids come from `listing.ids` (above).
2. `check_entries(manifest, canvas_ids, config)` is pure:
   - skips the reserved course entry;
   - fixed-type folders (`_FOLDER_TYPES`: `modules/` → module, `assets/` → file,
     `quizzes/` → quiz) remove an entry of any other type. Content folders are not
     type-checked by folder;
   - `syllabus`: its `canvas_id` is the course id (`sync_syllabus` records it that
     way); a mismatch removes it and counts as *foreign evidence*;
   - `COURSE_LEVEL_TYPES` (`course_settings`, `rubrics`, `module_order`) have no
     checkable id (recorded as 0). They are removed only when there is foreign
     evidence (the stored course differs, or the syllabus mismatch above);
     otherwise listed as unchecked. Removing them is equivalent to
     `--force-uploads` for those files (all sections, rubrics and positions are
     re-sent), which the sync code already supports;
   - any type in `canvas_ids`: removed when `int(canvas_id)` is not in the set.
     Pages are compared by `page_id`, never by `canvas_url`, because slugs repeat
     across courses (a Spring and a Fall copy both have `lecture-01`);
   - anything else (e.g. `question_bank`) is listed as unchecked.
3. `plan_clean` runs only when something is removed: `find_referrers` reuses
   `local_orphans.collect_sources` / `collect_local_refs` (snippet-expanded,
   course-flag branches not applied, so the result is a superset) plus the
   `front_page` / `dashboard_image` keys of `course_settings.toml`. Each surviving
   manifest entry that references a removed key goes into `plan.resync`; a
   `course_settings.toml` reference goes into `plan.settings_sections`.
4. `apply_clean` (only with `--apply`) deletes the removed keys, pops
   `last_synced` from each `resync` entry, pops the named section hashes (and
   `last_synced`) from the settings entry, records the configured course with
   `set_course_identity`, and flushes once.

Why re-sync marking drops `last_synced` instead of back-dating it: a back-dated
`last_synced` would make `needs_sync` true, but `_canvas_is_newer` would then
compare Canvas's `updated_at` (set by the previous render) with the local mtime
(older) and skip the file as "Canvas is newer". An entry without `last_synced`
bypasses that check (see "Stub creation"). The cost is that edits made directly in
Canvas to a marked file are overwritten, which is why the report lists them.

With `--apply`, when the manifest records a different course, the CLI prints the
plan and asks for confirmation (`--yes` skips it; no TTY and no `--yes` → `die()`).
Without `--apply` nothing is written, not even the course record.

Not handled: a page renamed on Canvas keeps its old `canvas_url` in the manifest
(checked by id, so the entry is kept); stray Canvas objects are never deleted
(use `find-canvas-orphans`); links already rendered to an object that still exists
but is the wrong one (e.g. a discussion linking to a stray page stub) are not
detected, since the referenced entry itself is valid.

### `--pair-canvas-with-local` and `--force-pair`

Implemented in `pair_manifest.py`. Connects local files that have no entry to
Canvas items that already exist, so `update` does not create duplicates after
`import`, a `cp` into a course that already holds the content, a lost manifest,
or a move to a course copied inside Canvas. Neither `import` nor `cp` writes
manifest entries; `import`'s internal imscc identifiers are not kept in the
local files, so the title is the only thing left to match on.

`collect_local_items(repo)` lists what `update` would sync, with the ignore
matcher applied: `.md` files in content folders (every top-level folder except
`_NON_CONTENT_DIRS`, the same list as `sync._phase_content`), typed by
`infer_canvas_type`; `quizzes/<q>/<q>.md`; `modules/*.md`; and everything under
`assets/` (walked like `sync._walk_assets`, so an ignored folder hides its
contents), whose `title` is the path below `assets/` and which carries its size.
Titles follow `update`: frontmatter `title`, else the stem (the folder name for
a quiz). Frontmatter snippets are not expanded. A YAML error puts the file in
`scan_errors` instead.

`plan_pairing(manifest, listing, local_items, force_pairs, match_titles)` is
pure:

- `_claimed(manifest)` maps (pool, Canvas id) → manifest key. Discussion and
  announcement entries claim both topic pools; `external_module` claims the
  module pool. Claimed items are never paired again.
- Forced pairs are checked first; every problem is collected and raised as one
  `PairError` (file not in `local_items`, no item of the file's type with that
  id, item claimed by another key, a file or item named twice). A forced pair
  may replace the file's own entry (`Pairing.replaced`). Forced items are then
  added to the claimed map.
- Existing entries whose Canvas item's normalized title differs from the local
  one go to `title_mismatches` (report only).
- With `match_titles`, per type: unclaimed Canvas items and entry-less local
  files are grouped by `normalize_title` (`html.unescape`, NFKC, `_QUOTES`
  folding curly quotes and dashes, whitespace collapsed, `casefold`).
  `_pair_group` pairs a group: each local file (path order) first takes a
  candidate whose stripped title is identical, then the rest are zipped with the
  remaining candidates in `_tie_break` order (published, has submissions, lowest
  id). `has_submissions` is `has_submitted_submissions`, which only assignments
  report. Groups with more than one item on either side go to `duplicates`.
- Suggestions: `difflib.SequenceMatcher` ratio of the normalized titles between
  leftover local files and leftover Canvas items of the same type, taken
  greedily from the highest score so each side appears at most once, down to
  `SUGGESTION_THRESHOLD` (0.6). They are only printed.

`apply_pairing` writes `{canvas_id, canvas_type}` with the type from the local
side (so a topic in `announcements/` is recorded as an announcement even when
Canvas lists it as a discussion), plus `canvas_url` for pages (slug) and files
(download URL). There is no `last_synced`, for the same reason `--clean`'s
re-sync marking drops it (see above): the next update must render the file's
links with this course's IDs, and `_canvas_is_newer` must not skip it. Modules
and quizzes get no `canvas_item_ids` / `canvas_question_ids`; their sync clears
and rebuilds the items and questions anyway. Files are the exception: when the
local size equals the Canvas `size`, the entry gets `last_synced = now`
(`file_is_current`), since a file has no links to render and re-uploading
identical bytes only costs time. A same-size file with different bytes is
missed; touching it re-uploads it.

Referrers of newly paired files are not marked for re-sync. A file already
synced that links to an entry-less file would have stub-created that file and
recorded it, so an entry-less file has no synced referrers, except ones the
clean in the same run already marked.

`print_plan` prints suggestions as `--force-pair <shlex-quoted key=id>` with the
titles and score in a shell comment, then one complete command. The command is
built in the CLI (`command_prefix`) from this run's course argument, `--config`,
mode flags and `--force-pair` values, plus `--apply`, so pasting it repeats the
run with the new pairs added.

## `fix-markdown` Subcommand

`cli.fix_markdown_cmd` → `markdown_cleanup.py`. Local only: no config, no Canvas call. `collect_markdown_files(repo)` runs `check_repo_format`, then walks content folders (`local_orphans._content_dirs`), `modules/`, `snippets/`, `quizzes/`, `question_banks/` (all `.md`, including question files) with `local_orphans._walk_files` (hidden and `.canvasignore`d paths pruned), plus `course_settings/syllabus.md`. Top-level files such as `README.md` are not included. `plan_fix_markdown(files)` returns a `FixMarkdownPlan` of `FileFix(path, before, after)`; the CLI prints each file's zero-context unified diff and, with `--apply`, `apply_fix_markdown` writes them. No format-version bump: nothing about how files are read changed.

`clean_markdown_file_text` splits off frontmatter raw (`split_frontmatter_raw`, unparsed, so it round-trips byte for byte) and runs `clean_markdown_body` on the body. Every pass skips fenced code blocks (`apply_outside_fences`) and inline code. The passes, in order:

1. **`repair_swapped_links`**: `[Label][https://url](text)` → `[Label](https://url)text`, unless the URL is a defined reference label.
2. **`remove_stray_brackets`**, per paragraph (split on blank lines). `_structural_brackets` finds brackets that are syntax: a `]` followed by a balanced `(...)` (link/image), by a valid attribute block, or by `[label]` naming a reference definition; a group whose own text is a defined label (shortcut reference); `[^…]` footnotes; task boxes after a list marker; reference definition lines. Each such `]` is paired with its opener by the backward scan. All other unescaped, non-code brackets are stray. They are deleted only if the paragraph has a *seam*: a stray `]` directly followed by `[` where the text between the neighbouring brackets on at least one side contains whitespace. That condition is what separates Word debris (`our ][Finding`, `inven][t][s][ citations`) from prose like `a[i][j]`. This pass runs before the attribute pass on purpose: a trailing `[ ][ ]{.EOP}` still has its block, so the second group is structural and the first forms a seam (`[F][inding] … [ ][ ]{.EOP}` needs this to qualify).
3. **`filter_pandoc_attrs(…, strip_word_attrs)`**: a block containing a Word marker (`is_word_marker`: `.SCXW\d+`, `.BCX\d+`, `.EOP`, `.NormalTextRun`, `.TextRun`, `.OutlineElement`, spelling/grammar/comment/track-change classes, `ccp-*`, `paraid`, `paraeid`) is reduced to id + style; other blocks are returned unchanged, so authored `{class="Button"}` or `{.underline}` survive. Emptied spans and fenced divs are unwrapped as on import.
4. **`repair_prose`**, which import also runs (`_html_to_markdown`, after `_collapse_redundant_spans`). In order:
   - **`shorten_horizontal_rules`**: a line of 4+ dashes (pandoc writes 72 for `<hr>`; VS Code's preview renders that oddly) becomes `---`, keeping up to 3 spaces of indent, when both neighbours are blank, a `:::` fence line, or the text's edge. That condition excludes setext heading underlines (text directly above) and pandoc multiline-table borders (table text on one side).
   - **`flatten_stacked_list_markers`**: a line starting with two or more list markers (`- - - x`, `1.  1.  x`; not a thematic break like `- - -`) keeps only the last; following lines indented at least `indent + removed width` (blank lines included when the next non-blank line qualifies) are dedented by that width. This is how Word's multi-level lists come through pandoc: outer `<li>`s holding only an inner list. The result is less indented than Canvas showed (Canvas presumably hid the outer bullets with `list-style` styles pandoc drops).
   - **`split_empty_break_paragraphs`**: a run of `\`-only lines right after a line ending in a hard break is Word's empty paragraph (two `<br>` = a drawn empty line). List context (the block's first line is a list marker or indented) → the run is deleted, and the previous line's `\` too if the next line is blank or a list marker (then it ends the item); a blank line would make the whole list loose, which pandoc renders as `<li><p>` on every item. Paragraph context → the run becomes one blank line, unless `_inline_open` finds an unclosed `[` or an odd number of `**` runs before it (Word often puts the empty paragraph inside a styled span; splitting there leaves `]{style=…}` as visible text — found on the College 101 repo) or the next line would start another block after a blank line (`_BLOCK_START_RE`: 4-space indent, list marker, heading, quote, fence, table); in those cases it is deleted as in a list.
   - **`drop_final_hard_breaks`**: a trailing `\` is removed only when the next line is blank or the text ends, since pandoc then emits `<br />` right before `</p>`/`</li>`, which browsers do not draw. Kept: breaks mid-paragraph; a `\`-only line whose previous line also ends in a break; and a break after an image alone in its paragraph (`_LONE_IMAGE_RE`, list marker allowed), because removing it turns the paragraph into a pandoc implicit figure with the alt text as a visible caption — found by rendering a real course before and after. A `\`-only line that is removed is deleted, not left blank.
   - **`fix_emphasis_spaces`**: units are paragraphs and list items (split at blank lines and before list-marker lines; emphasis cannot cross either). Unprotected `*` runs (not in code, attribute blocks, link targets, HTML tags, math) are paired in order, `**` first then `*`; runs with whitespace on both sides are skipped (bullets, `5 * 3`). An opener with a space after it abandons the width; a closer with a space before it (`: **In`) gets the space moved after it, or dropped when the closer ends the line. Fixes apply only if the runs pair up; a unit with a `***` run or a `\*` is left alone. The College 101 repo has one item (`**Reflect on Your Career/Industry\**` … `Questions: **`) that stays garbled for that reason.
   - **`unescape_quotes`**: `\'`/`\"` → `'`/`"` except inside inline code, attribute blocks, `](…)` destinations and titles, HTML tags, and `$…$` (where `\'` is a LaTeX accent), and not after an escaped backslash. Because the tool reads `markdown+smart`, straight quotes become curly on the next upload; the README says so.

`_tidy_changed_lines` diffs old and new lines, once after passes 1–3 and once after `repair_prose`. After passes 1–3, lines the passes emptied (a line that held only `[ ]{.EOP}`) are deleted, since an empty line would split a paragraph; after `repair_prose` they are not (`drop_emptied=False`), because its blank lines are deliberate. Both times, trailing whitespace is trimmed on a changed line only if its ending differs from the original's (so an existing two-space hard break survives; the no-break space Word puts in its `[ ]` spans is covered by `[^\S\n]`).

Verified on the College 101 repo (28 of 63 files changed) by rendering each file with pandoc before and after: the text is identical apart from bracket and asterisk characters and quote curling, except where debris had broken parsing (links and bold now render), no figures appear or disappear, and `<li>` counts drop only by the flattened wrapper items.

## `import` Subcommand

Converts an exported Canvas course (`.imscc` file) into a local Markdown repo ready for use with this tool.

```text
markdown-to-canvas import <imscc_path> <output_dir>
```

- `<imscc_path>`: `.imscc` zip file **or** a pre-extracted directory (auto-detected)
- `<output_dir>`: where the course repo is written (fails if non-empty)

**Implementation:** `src/markdown_to_canvas/imscc_import.py`

**Scaffolding written up front, before any content conversion:** every folder in
`TOP_LEVEL_FOLDERS` (`pages`, `assignments`, `discussions`, `announcements`,
`quizzes`, `question_banks`, `modules`, `snippets`, `assets`, `course_settings`)
is created even if the course has nothing to put there, so the repo layout is
always the full shape described in README's "How it works" — an empty
`announcements/` is as informative as a missing one would be confusing. A
default `.gitignore` and `.canvasignore` are also written (see `_DEFAULT_GITIGNORE`
/ `_DEFAULT_CANVASIGNORE`); both are starting points the user is expected to
edit as the course grows, not a fixed policy — `.gitignore` covers OS/editor/
Office junk, `.canvasignore` covers the same junk (so nothing junk-like is
uploaded to Canvas either) plus commented course-specific examples (per-term
material, feedback drafts). `.canvasignore` also actively excludes
`course_definition/**` — the `init_course` skill's convention for instructor
reference material (scope-and-sequence docs, curriculum outcome guides) that
should never reach Canvas, even before that folder exists. Neither lists the
tool's own manifest files — `ignore.py`'s `load_ignore_matcher()` already
excludes those unconditionally.

### IMSCC resource classification

| IMSCC type | href / file location | → category |
| --- | --- | --- |
| `webcontent` | `wiki_content/` | `page` |
| `webcontent` | `web_resources/` | `asset` |
| `imsdt_xmlv1p1` | `gXXX.xml` (topicMeta `<type>` = `topic`) | `discussion` |
| `imsdt_xmlv1p1` | `gXXX.xml` (topicMeta `<type>` = `announcement`) | `announcement` |
| `associatedcontent/...` | `gXXX/*.html` | `assignment` |
| `imswl_xmlv1p1` | `gXXX.xml` | `external_url` |
| `imsqti_xmlv1p2/...` | `gXXX/assessment_meta.xml` (standard) or via `<dependency>` (Canvas export) | `quiz` |
| `imsbasiclti_xmlv1p0/v1p3` | `<file href>` in `lti_resource_links/` or root | `lti` (no local output) |
| `associatedcontent/...` | `non_cc_assessments/*.xml.qti` (objectbank root child) | `question_bank` |
| `associatedcontent/...` | `non_cc_assessments/*.xml.qti` (assessment root child) | skipped (quiz-linked QTI, handled via quiz dependency) |

**Quiz detection — two manifest formats:**

Canvas uses two different manifest layouts for quizzes depending on export version:

- **Standard format**: `imsqti_xmlv1p2/` resource with `href="gXXX/assessment_meta.xml"` and a `<file>` child pointing to the QTI questions file. Both `meta_path` and `qti_path` come directly from this one resource.

- **Canvas export format**: `imsqti_xmlv1p2/` resource with `href=""` (empty) and a `<dependency>` child referencing a companion `associatedcontent/` resource. The companion resource's `href` points to `assessment_meta.xml` and its `<file>` children list both the meta file and a `non_cc_assessments/*.xml.qti` QTI file. The `non_cc_assessments/*.xml.qti` is preferred for question parsing because it uses `question_type` and `points_possible` metadata labels (vs. `cc_profile` labels in the CC format QTI in `gXXX/assessment_qti.xml`).

**LTI resources:** Canvas sets `href=""` on `imsbasiclti_` resource elements; the actual file path is in a `<file href="...">` child. The `imscc_path` is read from this child. LTI 1.3 resources cannot be round-tripped into a usable local format (tool installation is platform-specific), so no local output is written. LTI items in modules are handled separately via the module item's own `url` field.

**Question banks:** `non_cc_assessments/*.xml.qti` files whose root child element is `<objectbank>` (Canvas question pools) are classified as `question_bank` and converted to `question_banks/{slug}/`. Files whose root child is `<assessment>` (quiz-linked QTI) are skipped since the quiz's own dependency chain already handles them.

The `_syllabus` resource (`course_settings/syllabus.html`) → `course_settings/syllabus.md`.

### Processing phases

1. Extract zip to a temp dir if needed; pass directory through unchanged
2. Parse `imsmanifest.xml` → build in-memory resource map (`gXXX → {category, local_path, title, ...}`)
3. Copy `web_resources/` → `assets/`, preserving subdirectory structure
4. **Pages:** strip `<html>/<head>/<body>` wrapper, rewrite internal links, Pandoc HTML→Markdown, write `pages/{stem}.md` with `title` and `published: true` frontmatter
5. **Assignments:** read `gXXX/assignment_settings.xml` for title, points_possible, due_at, lock_at, unlock_at, submission_types, grading_type, workflow_state; convert HTML body; write `assignments/{stem}.md`
6. **Discussions:** parse topic XML body and paired topicMeta for title, published, require_initial_post; if `<attachments>` block present, append a `## Attachments` section with `../assets/{href}` links; write `discussions/{slugify(title)}.md`. (Announcements — topicMeta `<type>` = `announcement` — are routed to phase 6a instead.)
6a. **Announcements:** a discussion topic whose topicMeta `<type>` is `announcement`. Only the announcement body itself is imported — student replies/likes/comments are never present in an IMSCC export, so there is nothing to drop. The body is read exactly like a discussion (shared `_read_topic_body()`, including any `## Attachments`). Frontmatter carries only two active fields: `title` and `published: false` (**always** false on import, regardless of the export's `workflow_state`). Because Canvas has no draft state for announcements, `published: false` means `update` **does not post it yet** — it stays staged in the repo until you set `published: true` (e.g. post the midterm reminder when the midterm is near); see the "Content mapping" announcements entry. Every other topicMeta leaf element (`type`, `workflow_state`, `discussion_type`, `delayed_post_at`, `posted_at`, …) is written as a **commented** frontmatter line (`# key: value`) — the settings Canvas actually accepts (`canvas_api.ANNOUNCEMENT_SETTABLE_FIELDS`) take effect if the user uncomments them, and the rest are reference-only. The topicMeta `<position>` element is **dropped entirely** (not active, not commented): Canvas orders announcements by post date, not position, so exposing it would falsely imply announcement ordering is controllable from the repo. Written to `announcements/{slugify(title)}.md`. See `parse_announcement_meta()` / `convert_announcement()`. On `update`, a `published: false` announcement is skipped (not posted); see the announcements entry under "Content mapping" and `_upload_announcement()` in the sync pipeline.
6b. **Quizzes:** read `gXXX/assessment_meta.xml` for quiz settings; parse QTI 1.2 XML (`gXXX/gXXX.xml`) for questions; write `quizzes/{slug}/{slug}.md` and one file per question under `quizzes/{slug}/questions/`; unsupported question types emit a warning and are skipped

**Assignment group / rubric association:** Assignments, graded discussions, and quizzes each carry an `assignment_group_identifierref` (top-level for assignments/quizzes, nested under `<assignment>` for discussions); assignments and discussions additionally carry `rubric_identifierref` + `rubric_use_for_grading`. `_resolve_assignment_group_and_rubric()` resolves these IMSCC identifiers against identifier→title maps built once in `run_import()` from `assignment_groups.xml`/`rubrics.xml`, writing `assignment_group_id`/`rubric` frontmatter fields by title (matching how `sync.py` resolves them) and `rubric_use_for_grading` → `use_for_grading` (only when a rubric is present). Refs that don't resolve print a warning and are dropped rather than written as unresolvable raw identifiers.
6c. **Question banks:** parse `non_cc_assessments/*.xml.qti` objectbank files; read bank metadata (bank_title, bank_context_uuid, bank_state) from `<qtimetadata>`; parse all `<item>` children as questions (same QTI format as quizzes, plus `original_answer_ids` metadata written as a commented-out frontmatter line); write `question_banks/{slug}/{slug}.toml` and one question file per item under `question_banks/{slug}/questions/`
7. **Modules:** read `course_settings/module_meta.xml`; emit items in position order (see below); write `modules/{slugify(title)}.md`
8. **Course settings:** collect data from all `course_settings/*.xml` files and `imsmanifest.xml` metadata; write:
   - `course_settings/course_settings.toml` — all course-level settings (see below)
   - `course_settings/syllabus.md` — syllabus HTML converted to Markdown
   - `course_settings/events.md` — calendar events (if any exist in `events.xml`)
   - `course_settings/rubrics.toml` — rubric definitions with criteria and ratings (if any exist in `rubrics.xml`)
   - `course_settings/files_meta.toml` — file visibility/lock metadata (from `files_meta.xml`)
   - `course_settings/canvas.toml` — connection config skeleton pre-populated from `context.xml`
   - `media_tracks.xml` and `canvas_export.txt` are skipped (no useful round-trip content)

### Internal link rewriting

Applied to raw HTML before calling Pandoc (phases 4–6):

| Source link | Rewritten to |
| --- | --- |
| `$CANVAS_OBJECT_REFERENCE$/assignments/gXXX` | `../assignments/foo.md` |
| `$CANVAS_OBJECT_REFERENCE$/pages/gXXX` | `../pages/foo.md` |
| `$CANVAS_OBJECT_REFERENCE$/discussion_topics/gXXX` | `../discussions/foo.md` |
| `$CANVAS_OBJECT_REFERENCE$/modules/gXXX` | `../modules/foo.md` (modules are registered in `temp_manifest` before content conversion) |
| `$CANVAS_OBJECT_REFERENCE$/assignments/gYYY` where `gYYY` is a graded quiz's or graded discussion's embedded `<assignment identifier>` | `../quizzes/foo/foo.md` / `../discussions/foo.md` |
| `$WIKI_REFERENCE$/pages/some-slug` (older RCE links name the page by URL slug) | `../pages/some-slug.md`, matched against the `wiki_content/` file stem |
| `$IMS-CC-FILEBASE$/path/to/file` | `../assets/path/to/file` |
| `https://...` | unchanged |

Graded quizzes (`assessment_meta.xml`) and graded discussions (topicMeta) each embed an `<assignment identifier="...">` whose id differs from the quiz/topic resource id and appears nowhere in `imsmanifest.xml`. Canvas's RCE links to those items through that assignment id. `_register_assignment_aliases()` (called at the end of `parse_imsmanifest()`) adds a `TempEntry` with `category="assignment_alias"` for each one, sharing the target's `local_path`. No converter phase selects that category, so the quiz/discussion is still converted once.

An id that resolves to nothing (typically a link copied from an older course whose target was never brought over; Canvas's own `data-api-endpoint` on these points at the old course) → the whole `<a>` is unwrapped, keeping only its inner content, and a warning names the output file and link text. Removing only the href would make pandoc emit `[text]( "title")`, which `update` resolves to the file's own directory and reports as "local path is a directory". The rewriter substitutes the sentinel `_UNRESOLVED_HREF` first and unwraps anchors carrying it with `_UNRESOLVED_ANCHOR_RE`.

### Heading level handling

Canvas LMS silently converts any `<h1>` in page/assignment/discussion content into a styled paragraph, which looks like a heading but is invisible to screen readers (an accessibility regression). To keep imported content H1-free, `_shift_headings_down()` (applied to converted Markdown in phases 4–6 and to the syllabus/events) shifts every ATX heading down one level (H1→H2, H2→H3, …).

This shift is **conditional**: it runs **only when the converted Markdown actually contains an H1**. Canvas itself already prevents H1s in the content it exports, so the common case is that there is nothing to do and headings keep their original levels — an H2 stays an H2 rather than drifting to H3 on every round-trip. The shift kicks in only when an H1 slips through, demoting it (and everything below it) by one. Existing H6 headings cannot be shifted deeper; they are left at H6 with a printed warning.

The complementary check on the **upload** side (`sync.py`) is unconditional: any content whose rendered HTML contains an `<h1>` is rejected with an error so the author fixes the source rather than letting Canvas silently mangle it.

### Pandoc attribute simplification

Pandoc's HTML→Markdown conversion (`_html_to_markdown()`, used by every content type during import) attaches curly-brace attribute blocks to headings, links, images, spans, code, and fenced divs (`::: {...}`) — e.g. `## Heading {#my-id .some-class data-foo="bar" style="color:red"}`. Most of these attributes are Canvas RCE cruft with no meaning outside Canvas. `_simplify_pandoc_attrs()` strips every such block down to just:

- `#id` — kept because in-document anchor links (e.g. a table of contents) may target it
- `style="..."` — kept because it's user-authored formatting

Everything else (classes, `data-*`, `target`, etc.) is dropped. If a block has nothing left after filtering, the `{...}` (and its braces) are removed entirely — including the bare single-class shorthand Pandoc emits for divs with exactly one class and no other attributes (`::: classname`).

The work is done by `markdown_cleanup.filter_pandoc_attrs(markdown, policy)`, shared with `fix-markdown`; `_simplify_pandoc_attrs()` passes the `keep_id_and_style` policy and `skip_code_blocks=False` (import has always processed fence lines too, so a code block's `{.python}` is dropped as before), then strips trailing whitespace. Two details matter:

- **Emptied spans are unwrapped.** When a span's block (`[text]{.cls}`, detected by `]` immediately before `{`) is emptied, its brackets are removed as well (the `[` is found by a backward, balance-counting scan within the paragraph that skips inline code and escaped brackets). Before 2026-09 only the block was removed, leaving `[text]`, which pandoc renders with visible brackets. With Word Online content, where every run of text is its own classed span, that produced `C[heck out our ][Finding Data](url)[ and ]…` — see the `fix-markdown` section. Images (`![…]`) are never unwrapped.
- **Quoted values may contain braces.** `ATTR_BLOCK_RE` matches double-quoted values with backslash escapes as a unit. The earlier `\{[^{}\n]*\}` could not match Word's `ccp-props="{\"134233117\":false}"`, so whole Word blocks survived import untouched.

Fenced divs get one further step: if a div's attribute block ends up empty, the div wrapper itself (both the opening and closing `:::` fence lines) is removed and its content unwrapped, recursively for nested divs. Since Pandoc only ever emits fenced-div syntax for a `<div>` that has at least one attribute (an attribute-less div is passed through as raw HTML instead), fence pairing is done on the pre-simplification text — every opening fence line is guaranteed to have content, and every bare (attribute-less) `:::` line is unambiguously a closing fence.

### Nested span collapsing (`_collapse_redundant_spans`)

Runs immediately after `_simplify_pandoc_attrs()` in `_html_to_markdown()`, and cleans up what that pass leaves behind. Pandoc writes an inline `<span>` (and a `<div>` it cannot express as a fence) as `[content]{#id .class}`. Canvas nests several of these around exported content, so once the meaningless `{.class}` blocks are dropped what remains is a run of bare brackets carrying no formatting:

```text
[[[[[[[[[text]]]]]]]{#module_sequence_footer_container}]]
```

The pass keeps only the pairs that still mean something — the character immediately after the close is `(` (link), `[` (reference link), or `{` (an attribute block that survived) — and deletes the rest, yielding `[text]{#module_sequence_footer_container}`.

**This is a performance fix, not cosmetics.** Pandoc parses nested bracketed spans by backtracking exponentially, measured at roughly 3x per level: 3 levels 0.07s, 5 levels 0.59s, 7 levels 4.9s, 8 levels 14.7s, 9 levels several minutes — on a 691-byte file, on every conversion of it, forever. One such file in a real course repo made a `find-local-orphans` run take 5 minutes instead of 5 seconds (see the orphan-detection section).

Safety rules, in order of how much they matter:

- **Only contiguous runs of two or more `[`.** A lone `[text]` is left alone: it is indistinguishable from prose the author wrote (`the value at position [0]`) and costs nothing to parse. This is the single rule that makes the pass safe to run unconditionally.
- **Fenced code blocks and inline code spans are skipped** (`apply_outside_fences` plus an inline-backtick scan). `a[i][j]` and `m[[0]]` are real content in a programming course.
- **Escaped brackets are skipped.** This is what makes the pass lossless in the import pipeline specifically: pandoc *escapes* author-typed literal brackets when writing Markdown (`<p>literal [[x]]</p>` → `literal \[\[x\]\]`), so an unescaped run is always pandoc's own span markup and never author content. Outside the importer that guarantee would not hold, which is why this lives in `imscc_import.py` rather than `convert.py`.
- **Unbalanced runs are left alone.** `_match_bracket_run()` returns `None` when it cannot pair every open in the run, and the caller skips it rather than guessing. (The mismatched real-world case — 9 opens, 7 closes, an id, then 2 closes — *is* balanced overall and is handled.)

The pass is idempotent, and a run may span a line break (`[[[[[[[[[Thanks!\n--Mike]]]]]]]]]` is one run).

Repos imported before this pass existed can still contain such runs; nothing rewrites them retroactively (`fix-markdown` deliberately does not run this pass: in hand-written Markdown `[[1, 2], [3, 4]]` in prose is not pandoc's markup), but `find-local-orphans` names the offending file and says to check for nested `[]`s.

### Module file generation

- `ContextModuleSubHeader` indent 0 → `## Title` heading
- `ContextModuleSubHeader` indent ≥ 1 → `- Title` plain-text list item (with `(indent-1)*2` leading spaces)
- `WikiPage` / `Assignment` / `Discussion` / `DiscussionTopic` / `Quizzes::Quiz` → `- [display_title](../type/file.md)` (`DiscussionTopic` is the name used in real Canvas IMSCC exports; `Discussion` is the IMS CC name — both are handled)
- `ExternalUrl` → `- [display_title](https://url)` — if the linked webLink resource has `target` or `windowFeatures` attributes on its `<url>` element, they are appended as an HTML comment: `<!-- target="_blank" windowFeatures="width=800" -->`
- `ContextExternalTool` (LTI embedded tool) → `- [display_title](url)` (URL comes from the module item's own `url` field, not the LTI resource XML)
- `Attachment` (Canvas File) → `# SKIPPED: Attachment - "title"` comment line + printed warning (no local file equivalent)
- **Per-item published state:** Items with `workflow_state` != `active` in `module_meta.xml` get `<!-- published="false" -->` appended. During sync, the comment is parsed and the tool attempts to set `published=false` on the Canvas module item via a follow-up PUT (Canvas ignores the flag on the initial create call). **Known Canvas bug:** the API returns 500 for File-type module items, so those cannot be unpublished programmatically — the tool prints a summary of affected items at the end of the run. The `publish` subcommand skips unpublished items entirely (not rendered in the HTML, not followed for reachability — including any assets reachable only through unpublished links).

### Course settings output (`course_settings/course_settings.toml`)

A TOML file written inside the `course_settings/` folder capturing all course-level metadata. `_write_course_settings_toml` writes `format_version = repo_format.FORMAT_VERSION` and `created_by = repo_format.tool_version()` as the first two lines, before every other key and comment (see "Repo format version and `upgrade`"). Sources and content:

| Source file | Fields extracted |
| --- | --- |
| `imsmanifest.xml` (lom metadata) | `last_modified`, `copyright_restrictions`, `copyright_description` |
| `course_settings.xml` | All elements: title, course_code, dates, visibility flags, grading settings, tab configuration, post policy, etc. |
| `grading_standards.xml` | `[[grading_standards]]` — title, data (threshold array), points_based, scaling_factor |
| `assignment_groups.xml` | `[[assignment_groups]]` — title, position, group_weight, rules (drop_lowest etc.) |
| `late_policy.xml` | `[late_policy]` — deduction enablement, deduction amounts, interval |
| `context.xml` | `canvas_domain` → pre-fills `canvas.toml` base_url; `course_id` → pre-fills `canvas.toml` course_id |
| `wiki_content/*.html` (`<meta>`) | `front_page` — see below |

After every other section, `_write_course_settings_toml` adds `[relative_due_dates]` (`_relative_due_dates_section()`): help comments and the shared settings commented out directly under the header (so an uncommented key lands in that section), then an empty `[relative_due_dates.tables.default]` with `items = []`. It goes last because a key uncommented under it must not be captured by a later header. `_write_term_example()` then writes `course_settings/term_dates.toml`, entirely comments, unless the file exists. Tests that check "commented keys precede the first header" cut the text at `[relative_due_dates]` for this reason. See "`generate-due-dates` Subcommand".

### Additional course settings outputs

| Output file | Source | Content |
| --- | --- | --- |
| `course_settings/rubrics.toml` | `rubrics.xml` | `[[rubrics]]` — identifier, title, boolean flags, points_possible, rating_order; nested `[[rubrics.criteria]]` with description, long_description, points; nested `[[rubrics.criteria.ratings]]` with id, description, long_description, points. Fields `sync_rubrics()` never uploads are written commented out — see [Import-only settings are written commented out](#import-only-settings-are-written-commented-out) |
| `course_settings/files_meta.toml` | `files_meta.xml` | `[[folders]]` — path, hidden; `[[files]]` — identifier, locked, hidden, display_name, unlock_at. Entirely import-only; written with a banner saying so |

Boolean fields (`true`/`false`) are stored as TOML booleans. Numeric fields are stored as int or float. Empty elements are omitted. The nested `default_post_policy` element is stored as a TOML inline table.

`_parse_course_settings_full()` is otherwise a straight pass-through of every element in `course_settings.xml`, with one exception: keys in `_COURSE_SETTINGS_DROP` are discarded rather than round-tripped, because the exported value is an artifact of the *source* course. Currently that is just `grading_standard_id` — a Canvas id valid only where it was exported from. `update` resolves the real id by matching `[[grading_standards]]` titles against the target course and its account chain, so the imported value had no legitimate use; worse, being on the `course.update()` allowlist, it would override that resolution on any metadata-only run and silently swap the course's grading scheme. It is now also in `_COURSE_METADATA_SKIP`, so repos imported before this change stop uploading the stale value.

### Front page comes from the page, not from `course_settings.xml`

Canvas does not record *which* page is the home page in any course-settings XML. `course_settings.xml` carries only `default_view` (`wiki` / `modules` / `assignments` / ...); the identity of the wiki home page lives in a `<meta name="front_page" content="true"/>` tag in that page's own `wiki_content/*.html`.

`convert_page()` reads that tag (`_html_meta()`, which searches only the `<head>`, so a page whose *body* quotes the same markup is not mistaken for the home page) and records the page's repo-relative path on `ImportContext.front_page`. The page phase runs before the course-settings phase, so `create_course_settings()` receives it and writes `front_page = "pages/<slug>.md"` next to `default_view`. A cartridge marking two pages keeps the first and warns; `default_view = "wiki"` with no marked page also warns, since the resulting repo cannot say what the home page is.

This was missed until 2026-09: `import` wrote `default_view = "wiki"` and no `front_page`, which left the home page with **no inbound reference anywhere in the repo** — it is in no module, and nothing links to a home page. `find-local-orphans` counts `course_settings.toml`'s `front_page` as a reference (`collect_settings_refs()`), so with the key missing it reported the course's landing page as unreferenced, and `zzRemoveUnusedCanvasFiles.sh` deleted it. Anything reachable only through that page (e.g. an office-hours page) was then orphaned by the next run, cascading. Repos imported before this change need the key added by hand.

### Import-only settings are written commented out

Import is a generic pass-through; upload is an allowlist (`_COURSE_METADATA_KEYS` minus `_COURSE_METADATA_SKIP`, plus the sections `sync_course_settings()` handles by hand). Anything imported but outside the allowlist used to be written as an ordinary-looking key that `update` silently dropped, with nothing in the file to distinguish it from a live setting. Those keys are now written **commented out**.

Four module-level tables in `imscc_import.py` drive this:

| Constant | Applies to | Comment header emitted |
| --- | --- | --- |
| `_COMMENTED_BY_DEFAULT` | `title`, `course_code` | "Optional overrides; uncomment to replace what your school set" |
| `_COMMENTED_ADMIN_ONLY` | `start_at`, `conclude_at`, `restrict_enrollments_to_course_dates`, `is_public`, `is_public_to_auth_users`, `open_enrollment`, `self_enrollment`, `usage_rights_required` | "Usually admin-only; uncomment only if your Canvas role may set them" |
| `_IMPORT_ONLY_READ_ONLY` | `last_modified`, `root_account_uuid` | "Read-only in Canvas; these cannot be changed." (a bare `#` line separates it from the next group) |
| `_IMPORT_ONLY_NOT_UPLOADED` | `copyright_*`, `storage_quota`, the five Canvas feature flags, and the five keys in neither key set (`default_wiki_editing_roles`, `allow_student_organized_groups`, `show_total_grade_as_points`, `filter_speed_grader_by_student_group`, `indexed`) | "Not uploaded by markdown-to-canvas; editing these has no effect." |
| `_RUBRIC_IMPORT_ONLY_KEYS` | rubric `identifier`, `public`, `points_possible`, `hide_score_total`, `free_form_criterion_comments`, `rating_order`; criterion `criterion_id` | file-level header in `rubrics.toml` |

`_COMMENTED_BY_DEFAULT` and `_COMMENTED_ADMIN_ONLY` are the odd ones out: those keys *are* on the upload allowlist and take effect the moment a user uncomments them. `_COMMENTED_BY_DEFAULT` is commented because institutions populate `title`/`course_code` per section (the value carries section number and term), so a sync that re-sent the cartridge's stale value would clobber something useful. `_COMMENTED_ADMIN_ONLY` is commented because Canvas gates those fields on account-level role permissions: which of them a teacher may set varies by school, and Canvas rejects the *entire* `course.update()` with a bare 403 when the body holds one the account may not touch. `update` recovers (see "Permission-gated metadata fields" under course settings), but at the cost of one PUT per field, and the values are institution-owned anyway. A user whose role does have the permission can uncomment them and they upload normally.

Commenting `title` out would have degraded `publish`, which used it for the website title and would otherwise have fallen back to the repo directory name. So `_write_course_settings_toml()` also emits `_PUBLISH_TITLE_KEY` (`title_for_publish_to_website`), **uncommented**, holding the same value. It is a markdown-to-canvas key rather than a Canvas one — it is on no upload path, so editing it cannot reach the course — and it is emitted as a flat key before any section header, like everything else at that level. `publish.load_site_name()` now resolves `title` → `title_for_publish_to_website` → `name` → `course_code` → repo directory name; `name`/`course_code` stay in the chain for hand-written repos that predate this.

The import-only wording is deliberately split. Only the `_IMPORT_ONLY_READ_ONLY` pair is verified un-settable; the feature flags and `storage_quota` are skipped because nobody implemented them, not because Canvas is known to refuse them — hence the weaker "not uploaded by this tool" phrasing for everything else. Do not upgrade that claim without testing against a live course.

Two keys look droppable and are not: `group_weighting_scheme` is absent from `_COURSE_METADATA_KEYS` but `update_course_metadata()` translates it into `apply_assignment_group_weights`, and `dashboard_image` is in `_COURSE_METADATA_SKIP` only because `upload_course_image()` handles it separately. Both stay live. `_COURSE_SETTINGS_DROP` is a different mechanism again — "do not write this key at all" rather than "write it commented".

**Mechanics.** Generated files are built as `tomlkit` documents (see "Generated TOML layout" below). A commented key is a real `tomlkit` comment whose text is `key = value` rendered by `tomlkit` (so escaping stays correct; strings are always single-line), added by `toml_write.add_commented()` for flat keys and, for `rubrics.toml`, by `toml_write.fill_table(..., commented=...)`, which puts the comment where the key would sit. Rating-level `id` is import-only too but sits inside an inline `ratings = [...]` table, so it cannot be commented out on its own; the `rubrics.toml` header says so instead. `files_meta.toml` is 100% import-only and gets a banner rather than a fully commented body.

**Ordering.** The commented block is emitted with the other flat keys, *before* any `[section]` header — a commented line cannot itself break parsing, but a user who uncomments a key below a header would silently nest it. Fixing this ordering also fixed a live bug: `due_dates` (a top-level key) was appended after the `tomli_w` output, which emits `[late_policy]` and `[default_post_policy]` tables at the end — so any course with a late policy produced a file where `due_dates` parsed as `late_policy.due_dates`. `_write_course_settings_toml()` now adds flat keys → commented block → `due_dates` and `tab_configuration` (both top-level inline arrays) → `[late_policy]`/`[default_post_policy]` → arrays-of-tables, in that order because `tomlkit` appends items where they are added.

**Generated TOML layout.** `import` writes `course_settings.toml`, `rubrics.toml`, `files_meta.toml`, question-bank `.toml` files and `module_order.toml` with `tomlkit` through `toml_write.py`, and `mv` rewrites `module_order.toml` with `tomlkit` so comments survive (`_updated_module_order_text()`: a rename keeps the list length, so entries are changed in place and the array's own formatting and comments are untouched). `tomli_w` chose between `[[table]]` blocks and inline `[{...}]` arrays from a 100-character row heuristic the caller could not override, and a `[[table]]` header captures every bare key after it, so a longer row could silently move top-level keys into a table. `toml_write` fixes the layout by key instead: keys in `INLINE_TABLE_ARRAY_KEYS` (`tab_configuration`, `due_dates`, `ratings`, `rules`, `folders`, `files`) are inline arrays of inline tables at any length; any other list of dicts (`grading_standards`, `assignment_groups`, `rubrics`, `criteria`) is a `[[table]]` block array; a list of lists (grading-scale `data`) is a multi-line outer array with each `[name, value]` pair on one line; a list of scalars is one line unless it would exceed 72 characters. `fill_table()` adds every plain key before any sub-table, because `tomlkit` appends and a bare key added after a table header lands inside that table. `tomlkit` writes inline tables as `{a = 1}` (no inner spaces). No `FORMAT_VERSION` bump was needed: the same keys and values are written and files from the old layout parse to the same data. Manifests (`manifest.flush`, `repo_format._write_manifest`) still use `tomli_w`; they are machine-written and hold no arrays of tables whose layout matters.

**Side effect on existing repos.** `compute_settings_section_hashes()` hashes `metadata` as "every top-level key not claimed by another section". Commenting keys out removes them from the parsed dict, so the first `update` after a re-import re-sends the metadata section once. Harmless.

`canvas.toml` is written with `base_url` pre-filled from `context.xml`'s `canvas_domain` (instead of a placeholder). If `context.xml` is absent, the placeholder is used.

### Key behaviours

- **No manifest written** — IMSCC `gXXX` identifiers are not real Canvas numeric IDs; the first `sync` run creates all items and populates the manifest with real IDs.
- **`course_settings/` directory** — `course_settings.toml`, `canvas.toml`, syllabus, events, and any other converted content land here.
- **`course_settings/course_settings.toml`** — all course-wide settings, alongside the rest of the course-settings files.
- **Centralized due dates** — during import, `due_at`/`lock_at`/`unlock_at` fields from assignments, discussions, and quizzes are collected into a `due_dates` inline-table array in `course_settings/course_settings.toml`. The individual `.md` files have these fields commented out (with a note pointing to the centralized file). During `update`/`publish`, centralized `due_dates` entries override any frontmatter dates; matching is by title (with an optional `type` field for disambiguation). Unmatched entries produce a warning. Each date field supports sentinel values (case-insensitive): `"NONE"` actively clears the date on Canvas; `"KEEP"` never sends the field (on create or update); `""` (empty string) behaves like KEEP but prints a warning; `"CREATE_NONE_THEN_KEEP"` sends an empty value (clearing the date) only when the item has no `canvas_id` yet, and acts as KEEP on every later update. The two differ only on first create, so `resolve_dates_symbolic()` and the `resolved_dates` cache map both to `"KEEP"`; both sentinels are kept deliberately. If Canvas rejects due dates (e.g. due_at outside availability window), the tool retries without dates and prints a warning.
- **Graded discussion metadata captured** — `points_possible`, `due_at`, etc. written to frontmatter even if not currently used by sync.
- **Quiz question slugification** — question filenames are derived from the QTI `title` attribute via `_slugify()`. Special characters (e.g. `+`) are stripped, so "What is 2+2?" becomes `what-is-22.md`.
- **Course-navigation tabs humanised** — `course_settings.xml`'s `tab_configuration` (an escaped JSON string of Canvas-internal numeric ids and `context_external_tool_<resource-id>` ids) is rewritten into a readable `tab_configuration` inline array. Numeric ids become string ids (`3` → `id = "assignments"`); external-tool ids are resolved to a human `label` via the tool's BLTI `<blti:title>` (with the original id kept for provenance). See `_convert_tab_configuration()`. `_write_course_settings_toml()` writes `tab_configuration` as an inline array under a plain key, before every `[section]` header, whatever the length of its rows. Under `tomli_w` (before the move to `tomlkit`) that depended on a row-length heuristic, and dumping it separately from the sections (before 2026-09) put `tab_configuration` under `[default_post_policy]`, where `update` ignores it. **Caveat:** Canvas only exports a BLTI resource for tools that ship as course *content*; tools used **only in course navigation** have no resource (and no name) in the cartridge — verified against real Canvas exports. Those tabs are written with an empty `label = ""` fill-in slot plus the id, and one summary warning is printed counting them. Sync skips an unfilled placeholder (it can't match a nameless tool); run `create-tool-aliases` against a Canvas course URL to resolve these labels automatically (see README), or supply them by hand.

### Console output style

```text
Extracting: course.imscc → /tmp/...
Copying asset: assets/Images/logo.png
Converting page: pages/syllabus.md
Converting assignment: assignments/week-1-problem-set.md
Converting discussion: discussions/week-01-forum.md
Converting announcement: announcements/midterm-reminder.md
  Converting question: quizzes/week-1-quiz/questions/what-is-2-plus-2.md
  Converting question: quizzes/week-1-quiz/questions/explain-gravity.md
Converting quiz: quizzes/week-1-quiz/week-1-quiz.md
Generating module: modules/getting-started.md
Done. Wrote course repo to: ./my-course/
```

## Repo format version and `upgrade`

`repo_format.py` owns the format version, the check every repo-reading operation runs, and the migrations behind `upgrade`.

**Where the version lives.** `course_settings/course_settings.toml` has a top-level integer `format_version` (missing file or key = 0); `import` also writes `created_by` (the tool version that ran `import`), and `upgrade` appends one string per version-changing run to `upgraded_by` (`"<tool version> on <date>: <from> -> <to>"`). These are the first keys in the file. Every `.manifest-*.toml` has its own `_repo_format` stamp (see the manifest file section), because manifests are local and can lag behind the committed settings on a second machine. `repo_format.FORMAT_VERSION` is the tool's version (currently 4). `tool_version()` returns `importlib.metadata.version("markdown-to-canvas")`, or `"unknown"`. `pyproject.toml` uses `hatch-vcs` (`dynamic = ["version"]`, `fallback-version = "0.0.0+unknown"`), so the version comes from git tags: `0.2.1.devN+g<hash>` after a `v0.2.0` tag. An editable dev install reports the version from its last install, so `created_by`/`upgraded_by` can be stale there.

**The check.** `check_repo_format(repo) -> None` reads the repo version and every manifest's stamp and raises `RepoFormatError` if any differs from `FORMAT_VERSION`: older says to run `markdown-to-canvas upgrade`, newer says to update the tool, and both versions and any offending manifest are named. It compares versions only; it never edits a file, so a matching version is taken to mean the files were set up correctly (`upgrade` is the one place that repairs `tab_configuration`). `RepoFormatError` subclasses `Exception`, not `ValueError`, so `_handle_cli_errors` does not prefix it with "KeyError or ValueError:". It is called first thing in each library entry point, so no code path reads a repo without it:

| Command | Call site |
| --- | --- |
| `update` | `sync.run_sync`, `sync.run_targeted_sync` |
| `update`, `prune` (guard) | `course_guard.check_course`, repo = `manifest_path.parent` |
| `prune` | `sync.run_prune` |
| `mv` | `mv.run_mv`, right after the repo root is found |
| `publish` | `publish.run_publish` |
| `find-local-orphans` | `local_orphans.find_local_orphans` |
| `fix-manifest` | `clean_manifest.load_manifest` |
| `fix-markdown` | `markdown_cleanup.collect_markdown_files` |
| `list-titles` | `sync.collect_title_items` |
| `generate-due-dates` | `generate_due_dates.plan_generation` |
| `find-canvas-orphans` | `cli.find_canvas_orphans_cmd`, since `orphans.find_orphans(course)` never receives the repo |

`import`, `setup`, `install-completion`, `create-tool-aliases` and `emit-workflow` do not check. The guard checks as well as `run_sync`/`run_prune` because the CLI runs the guard first and the guard can write the manifest. The second check is a few file reads.

**`tab_configuration` placement (upgrade only).** `fix_tab_configuration(doc)` walks every table and every element of every array of tables in a `tomlkit` document. A nested key with no top-level key is deleted from its table and inserted at the top level just before the first table header (above the blank line that separates them), through `tomlkit`'s private `Container._insert_at` (the public `add` only appends, which would land it back under the last table). It returns a notice naming the old location. A key in both places raises `RepoFormatError` naming both. The tool cannot use a nested `tab_configuration`, so `upgrade` fixes it once. Other commands do not look for it, and the old warning in `sync.py` (and `_find_nested_key`) were removed, so a `tab_configuration` nested by hand in a current-version repo is silently not applied.

**`upgrade`.** `run_upgrade(repo, noop)` starts at the minimum of the repo's version and every manifest's version and refuses when any is above `FORMAT_VERSION`. `MIGRATIONS` maps a starting version to a function that edits an `UpgradeState` (the `tomlkit` settings document, the manifest dicts, pending renames, and `pending_writes`, a `{path: new text}` map for any other repo file) and returns human-readable change lines; each step is printed. Unless `--noop`, each step writes in this order: renames, manifests (with `_repo_format` set to `v+1`), the term file, `pending_writes`, then `course_settings.toml` with `format_version = v+1`. Writing the settings last means a failure leaves the repo at the last completed version and a re-run resumes from there; a manifest already past a step is not touched again by it (the settings file only advances if its own version was at or below the step). After the migrations `run_upgrade` runs the placement fix, then appends one `upgraded_by` entry if the settings `format_version` changed during the run (so a manifest-only upgrade adds none), and prints "already current" when nothing changed. A missing `course_settings.toml` is created containing only the version keys. Edits use `tomlkit` (a runtime dependency, added for this), which round-trips comments and layout. Manifests are still written with `tomli_w`.

**Migration 0 -> 1** (`_migrate_0_to_1`): rename `.canvas-manifest.toml` to `.manifest-canvas.toml` when the target does not exist (warn if both exist), and stamp every manifest with version 1.

**Migration 1 -> 2** (`_migrate_1_to_2`): append an empty `[relative_due_dates.tables.default]` (with `items = []`) to the end of `course_settings.toml` by parsing a snippet with `tomlkit` and adding its `relative_due_dates` table to the document (a table header at the end cannot capture existing keys), and stamp every manifest with version 2. It does nothing to the settings when `relative_due_dates` already exists, or when the settings file is already at version 2 (`read_repo_version(repo) >= 2`: a manifest that lags a current settings file must not cause the section to be added, for example when the tab_configuration fix rewrites the file). A repo with no settings file gets one from migration 0 -> 1 before this step, so it gains the section too. The bump was chosen although the change is additive, so that repos match what `import` writes; it does not create a term file.

**Migration 2 -> 3** (`_migrate_2_to_3`): the term file no longer names a table, and the table `generate-due-dates` uses is `--table`, else `default`. Two edits, both only when the settings file's own version is below 3 (same guard as 1 -> 2), and a manifest stamp. (1) `UpgradeState` now also holds the in-repo term file (`course_settings/term_dates.toml`, a `tomlkit` document when it exists, plus a `term_changed` flag that `run_upgrade` writes with the manifests, so `--noop` writes neither); an uncommented `relative_table` key is deleted from it. It never creates the file and cannot reach term files outside the repo. (2) `_migrate_relative_tables` renames the table: a lone table not called `default`, or the one non-empty table when the only other is the empty `default` that 1 -> 2 added (that block is dropped first). Anything else (several real tables, or `default` plus two others) is left alone with a `NOTICE: ... --table NAME` line. The rename is done on the *text* by `_rename_table_headers` / `_drop_table_block`, rewriting only the `[relative_due_dates.tables.NAME...]` and `[[...]]` header lines, because that keeps comments and both item layouts (inline `items = [...]` and `[[...items]]` blocks) byte-identical, which moving a `tomlkit` table under a new key does not guarantee. Comment lines directly above the next header stay with that header when an empty `default` is dropped. Afterwards the result is parsed and compared with the expected data; if it does not match (dotted keys, inline `tables = {...}`, quoted oddities) the file is left unchanged and a "could not rename" notice says to use `--table NAME`. `state.settings_doc` is reassigned to the re-parsed document, which is safe because `run_upgrade` reads the attribute afresh.

**Migration 3 -> 4** (`_migrate_3_to_4`, logic in `snippet_migration.py`): links inside block snippets become relative to the snippet file. Only when the settings file's own version is below 4; always stamps the manifests. `find_includers()` maps each snippet file to the files outside `snippets/` that block-include it (a snippet including a snippet is not an includer here, because before format 4 nested refs were never expanded, so there is no old reading to preserve): every `.md` outside `snippets/` and hidden folders, `.canvasignore`d files included, frontmatter split off textually (no YAML parse, so a malformed block does not hide an includer), refs inside fences, `PASTE_SNIPPET_INTO_FRONTMATTER` refs and inline `$...$` refs ignored. `migrate_snippet_links()` runs `links.transform_links(text, snippet_dir, snippet_dir, {}, url_map=...)` over each snippet outside fences, so it sees exactly the links rebasing sees; the `url_map` callback decides each link; `$...$` inline ref paths and block refs to other snippets are decided the same way (`rewrite_inline_snippets` stays on), since they were written for the includers too. With W the set of includer targets that exist (the readings that worked on Canvas) and S the snippet target: W is one file different from S → rewrite to the path from the snippet folder to it (percent-encoding and fragment/query kept), even if other includers resolved the link to nothing, since those were already broken; W = {S} → unchanged; W empty and S exists → unchanged; otherwise (W has several files, or nothing exists) unchanged with a `NOTICE:` listing each includer's reading. The rule was loosened from "every includer agrees" after a trial on a real course, where a snippet included at two depths had one working and one broken reading and the stricter rule left the working pages broken. A snippet with no includers gets a notice for each link whose S does not exist. New text goes to `state.pending_writes`, so `--noop` writes nothing. Undecodable snippet files are skipped with a notice.

**Adding a migration.** Increase `FORMAT_VERSION`, add the function to `MIGRATIONS` keyed by the previous version, and test it (see `tests/test_repo_format.py`). CLAUDE.md states when a bump is required.

## `generate-due-dates` Subcommand and relative due dates

Computes absolute `unlock_at` / `due_at` / `lock_at` from offsets and writes them into the `due_dates` table of `course_settings.toml`. It never contacts Canvas and never applies `only_if`; `update` sends the dates as it does for hand-written entries (see "due_dates resolved-value caching"). Modules: `relative_dates.py` (loading and arithmetic, no I/O beyond reading two files), `generate_due_dates.py` (plan, render, apply), `cli.generate_due_dates_cmd`.

```text
markdown-to-canvas generate-due-dates TERM_FILE [COURSE_DIR] [--table NAME] [--noop] [--yes]
```

**Settings** live in one top-level `[relative_due_dates]` section (a new top-level key is safe at the end of the file because it is a table). `load_tables(settings)` turns it into `RelativeTable`s: the section's `days_of_week`, `class_on_noninstructional_days`, `unlock_relative_default` and `lock_relative_default` are the shared values, and each `[relative_due_dates.tables.<name>]` table may override any of them, so its `TableSettings` are already resolved. Tables sit under `tables` so a table name can never collide with a setting name. Unknown keys at any level are errors (a typo such as `lock_ofset` would otherwise silently do nothing). Offsets are parsed when loaded, so a bad one is reported before any date is computed. `days_of_week` is stored as a set in week order (the class-day search steps to the next entry of the list). `select_table(tables, cli_name)` picks the table: `--table`, else the one named `default` (`DEFAULT_TABLE`); with no `default` and no `--table` it lists the names and stops, even when there is exactly one other table (migration 2 -> 3 renames the common lone-table case). `sync._NON_METADATA_SETTINGS_KEYS` contains `relative_due_dates`, so editing the section never triggers a course-settings upload. `toml_write.INLINE_TABLE_ARRAY_KEYS` contains `items`, so `import` writes a table's items as inline rows, never as `[[...items]]` blocks.

**Term file** (`load_term`): TOML with `first_day`, `last_day`, `time_zone` (an IANA name, resolved with `zoneinfo`; `tzdata` is a dependency so Windows and slim containers, which have no OS time zone database, work too), `default_due_time`, and `noninstructional_days`; a `relative_table` key is rejected with a message that points at `--table` (it was removed in format version 3). The CLI turns `TERM_FILE` into a path with `course_registry.resolve_term` (a path, else a term name) before `load_term`. Dates and times may be TOML values or strings. `import` writes a fully commented example, `course_settings/term_dates.toml`, only when it does not exist. `course_settings/` is never scanned by `find-local-orphans` and no sync code enumerates it, so the file is not reported or uploaded (tested).

**Arithmetic** (`_Calculator`) is a port of MikesGradingTool's `calculateDueDate` and `apply_offsets_to_due_date` (`Canvas/CanvasHelper.py`), on *naive local* `datetime`s; the zone's UTC offset is attached only when a value is formatted (`isoformat(timespec="seconds")`). The grading tool adds `timedelta` to `pytz`-localized values, which keep the offset of their start date, so an item whose own offsets cross a daylight-saving change ends up an hour early counting forward and an hour late counting backward (23:59 on Oct 31 became 00:59 on Nov 1). Local arithmetic avoids that. Other differences: results are memoized per item (`_due`) and cycles are found with an in-progress list; an item's offsets are never modified (the grading tool inserts `-1 CALENDAR_DAY, +1 CLASS_DAY` into the list for `FIRST_CLASS_OF_QUARTER`, which is safe there only because of its cache; here the two offsets are prepended to a new tuple); `-N CLASS_DAY` looks for the previous class day (the original looks for index+1 in both directions, correct only for one or two class days); an `ASSIGNMENT` anchor to an item with no due date is an error for the whole run (the original reports that one item and continues); an `ASSIGNMENT` anchor counts from the anchor's *date* and restarts at `default_due_time`, as the original does. The class-day search, kept from the original, tracks the index of the next class day, skips a non-instructional day by advancing that index, and starts from the first class day it meets when the start is between class days. It stops with an error after 3,660 steps.

**Lock and unlock** offsets are applied to the item's own due date. Resolution order: the item's `unlock_offset` / `lock_offset`, the table's default, the shared default, then `KEEP`. `NONE` is only valid alone and yields `"NONE"` with no due date needed; any other rule with no due date yields `KEEP` and a warning.

**Plan and apply.** `plan_generation(repo, term_path, table_name)` calls `check_repo_format`, reads `course_settings.toml` once (text and parsed), computes the dates, and compares each item with the entry `_find_entry` matches (same `name`; types must agree when both give one). Values are compared as strings, case-insensitively for sentinels, and as instants when both parse as aware datetimes, so `23:59-07:00` and `06:59Z` the next day are unchanged. The result is a `GenerationPlan` (per-entry `EntryChange` of kind added / changed / unchanged, warnings, notices, and the source text). `render_plan` gives lines flagged as real changes; the CLI prints those with `click.secho(fg="yellow")`, which click strips when the output is not a terminal. `apply_plan` refuses if the file no longer equals the source text (entry indices come from that text), then edits a `tomlkit` document in place: changed entries have their keys assigned, and added entries are appended to the existing array (inline array or `[[due_dates]]` blocks). When there is no `due_dates` key, the array is inserted before the first table header through `repo_format._insert_key`, since appending would put it inside the last table. Confirmation follows `fix-manifest --clean`: no terminal and no `--yes` is an error when there is something to write; nothing to write never prompts; `--noop` stops after printing.

**Warnings** (`title_warnings`) compare the table, `due_dates` and the content titles (`sync.iter_gradeable_content`, frontmatter `title`, else the file stem, the same source as `_check_due_dates_coverage`), report each title once, and name the table(s) responsible. `ignore` titles are skipped in the "no item" warning and the leftover notice. Course flags and `published_if` are not evaluated, since the relative table has no flags; `ignore` covers items that do not exist in a term.

**Not covered.** One `due_dates` array is shared by all Canvas sections of a repo, so a run produces one set of dates. `scripts/harvest_relative_due_dates.py` prints a course of the grading tool's config as a relative table (items keyed by Canvas name; `ASSIGNMENT` anchors rewritten from the grading tool's keys to Canvas names), or with `--term` the term file built from the config's top-level `due_date_info` and `app-wide_config`. `scripts/record_grading_tool_dates.py` extracts the grading tool's date functions with `ast` and records their results in `tests/fixtures/grading_tool_relative_dates.json`; `tests/test_relative_dates_vs_grading_tool.py` compares against it (only the daylight-saving hour may differ).

## `publish` Subcommand

Generates a public [MkDocs](https://www.mkdocs.org/) + [Material](https://squidfunk.github.io/mkdocs-material/)
static website from the local course repo and optionally deploys it to GitHub
Pages. The site mirrors Canvas's left-sidebar navigation model so it feels
familiar, without exposing any student data. This is a read-only export — it
never touches Canvas, the API, or the manifest.

```text
markdown-to-canvas publish [COURSE_DIR] [--output-dir site] [--deploy] [--emit-workflow]
```

- `COURSE_DIR`: the course content directory (a path or a registry key). If omitted, resolved by
  walking up from the current directory — see
  [Course-directory resolution](#course-directory-resolution)
- `--output-dir`: where `mkdocs build` writes the static HTML (default: `site/`)
- `--deploy`: run `mkdocs gh-deploy` (push to the repo's `gh-pages` branch) instead of a local build
- `--emit-workflow`: also write a starter `.github/workflows/publish.yml` into the course repo

**Implementation:** `src/markdown_to_canvas/publish.py`

**Optional dependency:** MkDocs and Material are an opt-in extra so the rest of
the tool installs without them. Install with `uv tool install markdown-to-canvas[publish]`
(or `pip install mkdocs mkdocs-material`). If `mkdocs` is not on `PATH`, the
subcommand exits via `die()` with an install hint. Pandoc is **not** needed for
the publish flow — page/assignment/discussion bodies are staged as Markdown and
MkDocs renders them.

### What it does

1. Determine the site name from `course_settings/course_settings.toml` (`title` / `name` /
   `course_code`), falling back to the course directory name.
2. Build the `nav:` tree from `modules/` (alphabetical, matching the sync
   order). Each module becomes a top-level nav section; the module's own `.md`
   becomes a clickable overview/index page (Material `navigation.indexes`).
   SubHeaders (`## Heading` lines) become nested nav groups; `ExternalUrl`
   items become absolute-URL nav links.
3. Stage a temporary MkDocs tree (`mkdocs.yml` + `docs/` + `overrides/`) and run
   `mkdocs build --site-dir <output-dir>` (or `mkdocs gh-deploy --force` with
   `--deploy`), with the working directory set to `COURSE_DIR` so `gh-deploy`
   finds the course repo's git remote.

### Content selection

**Only content referenced by a module is published** — orphaned pages,
assignments, discussions, and quizzes are excluded. `collect_reachable()` walks
Markdown links from the nav items; for a non-module file it applies the course
flags, then expands block snippets with `preprocess_snippets` (stdout
suppressed; staging reports the errors) before extracting links, so a file
linked only from inside an included snippet is staged. Per-content handling:

| Content | Published as |
| --- | --- |
| Pages / assignments / discussions | Markdown body, frontmatter stripped, snippet includes expanded inline (their links rebased onto the file, like `update`), an H1 prepended if the body has none. Cross-links and asset links are left as-is (the staged `docs/` mirrors the repo layout, so relative links resolve). A snippet error (for example a snippet link that escapes the repo) lands in the staging `errors`, which stops `run_publish` before `mkdocs` runs. |
| Quizzes | A single readable study-guide page (`docs/quizzes/<slug>.md`) with the description and each question's prompt and answer choices; correct choices are marked `**(correct)**`. The `quizzes/<slug>/<slug>.md` folder structure is flattened, and links pointing at it are rewritten. |
| Assets | `assets/` is copied wholesale into `docs/assets/` so every referenced image/file resolves. |

### Canvas-like styling

`docs/stylesheets/extra.css` sets Material's CSS variables to Canvas's charcoal
sidebar (`#2D3B45`) and orange accent (`#E66000`), plus an active-item left
border. `overrides/main.html` extends Material's `base.html` and prepends the
course name to the navigation drawer via the `site_nav` block (a no-op on theme
versions lacking that block, so it never breaks the build).

### Publish console output

```text
Staging site in: /tmp/g2c-publish-xxxx
  Staging module: modules/week-1.md
  Staging content: assignments/week1.md
  Staging content: pages/syllabus.md
Site: Intro to CS  (1 module(s), 3 content file(s))
Running: mkdocs build --site-dir /abs/site -f /tmp/g2c-publish-xxxx/mkdocs.yml
Built static site: /abs/site
```

## `mv` Subcommand

Moves or renames a file or directory within the course repo, updating all
internal references so nothing breaks on the next sync.

```text
markdown-to-canvas mv [--noop/-n] [--verbose/-v] SRC DEST
```

`resolve_dest()` runs first, before validation and before any path map is
built: when DEST is an existing directory, it is expanded to `DEST/SRC.name`
so the command matches normal `mv` (`gg mv pages/week-1.md pages/summer/`
lands at `pages/summer/week-1.md` instead of erroring with "Destination
already exists"). Case-only renames are exempt — on a case-insensitive
filesystem `dest.is_dir()` is true of the source itself, so expanding would
nest a directory inside its own rename. Everything downstream (`validate_move`,
`build_path_map`, link rewriting) sees the fully expanded destination, so a
real collision (`DEST/SRC.name` already exists) still fails the normal
"Destination already exists" check.

A trailing separator on DEST (`pages/summer/`) means "DEST must be an existing
directory", also matching normal `mv`: `resolve_dest(..., must_be_dir=True)`
rejects a missing or non-directory destination instead of silently renaming SRC
to it. Since `Path()` discards the separator, the CLI declares DEST as
`click.Path(path_type=str)` and `run_mv` accepts `Path | str`, calling
`has_trailing_slash()` on the raw value *before* converting to `Path`. Callers
passing a `Path` (all internal callers and most tests) can never trip the
check, which is correct — only typed input carries the intent.

**What it updates:**

1. **Physical move** — uses `git mv` when inside a git repo and the source has
   git-tracked content (falls back to a plain filesystem move otherwise, e.g.
   for files/directories that haven't been `git add`ed yet). Handles
   case-only renames (e.g. `Unit-01` → `unit-01`) via a temporary
   intermediate name.
2. **Every manifest in the repo root** — `find_manifests()` globs
   `.manifest-*.toml` (plus a legacy `.canvas-manifest.toml` if present) and
   `compute_all_manifest_updates()` rewrites each one that changes: top-level
   keys for moved files, and `canvas_item_ids` sub-tables inside module
   entries. `mv` has no `--config` and a rename is a repo-wide fact, so all of
   the repo's courses are updated in one go; the summary line names the files
   when more than one changed. The reserved stored-course entry
   (`_canvas_course`) is carried over unchanged. `mv` never contacts Canvas, so
   it does not run the stored-course check.
3. **All `.md` files in the repo** — rewrites relative Markdown links
   (`[text](path)`, `![alt](path)`), raw HTML `<img src>`/`<a href>`, and
   inline snippet references (`$path.md$`) that point to moved files. Also
   adjusts outbound links inside a moved file when its directory depth
   changes. Each file's links are resolved from that file's own folder, which
   for a snippet is the snippet-relative reading `update` uses (format 4), so
   moving a file that includes a snippet never touches the snippet. The
   rewriting is `links.transform_links`, shared with snippet expansion (see
   [Snippets](#snippets-snippets-directory)). It skips any URL with a scheme
   (`^[A-Za-z][A-Za-z0-9+.-]*:`), `#`-only and `/`-rooted links, empty URLs and
   anything containing `$`, and keeps a `#fragment`/`?query` suffix out of path
   resolution. It does rewrite links inside fenced code blocks (see BUGS.md).
4. **`course_settings/module_order.toml`** — updates filenames in the `order`
   array when a module file is renamed.
5. **`course_settings/course_settings.toml`** — updates the `dashboard_image`
   and `front_page` fields when the file they point to is moved, and rewrites
   `pinned_resources` entries covering the moved path (a stale pin would
   silently unpin the resource, letting the next update re-upload the exact
   thing the pin protects). File pins follow `path_map` (including quiz/qbank
   inner-file renames); folder pins follow the moved directory by prefix.

**Special cases:**

- **Quiz folder renames** — when renaming `quizzes/old-name/` to
  `quizzes/new-name/`, the inner `.md` file that must match the folder name
  is also renamed (`old-name.md` → `new-name.md`).
- **Question bank folder renames** — same as quizzes but for the inner `.toml`
  file.

**Validation (errors before any work is done):**

- Source must exist, destination must not (except for case-only renames).
- Both paths must be within the course repo.
- No cross-content-type moves (e.g. `pages/` → `assignments/`).

**Auto-detects the repo root** by walking up from the source path looking for
`course_settings/course_settings.toml`.

This subcommand is purely local — it never contacts Canvas. Run `update` after
moving files to push the changes.

## `cp` Subcommand

Copies content from one course repo into another, with what it depends on
(`src/markdown_to_canvas/cp.py`). The cross-repo counterpart of `mv`, and like
it purely local: no Canvas calls, no manifest reads or writes, no `git add`.

```text
markdown-to-canvas cp [--noop/-n] [--verbose/-v] [--overwrite] SRC... COURSE_DIR
```

The source repo is found by walking up from each SRC (all must share one);
`COURSE_DIR` goes through `_resolve_course` like every other course argument
and is required. `check_repo_format` runs on both repos before anything is read;
a destination failure is re-raised with the destination path prefixed.

**Files keep their repo-relative paths.** That is what makes the copy work
without link rewriting: a copied file's relative links (`../assets/…`,
`../snippets/…`) resolve in the destination exactly as they did in the source.
There is deliberately no destination sub-path argument.

**Two phases.** `build_copy_plan()` returns a `CopyPlan` and writes nothing;
`run_cp()` prints it and writes only when there is no unresolved conflict (and
not under `--noop`), so a copy happens in full or not at all. Returning `False`
(conflicts, no `--overwrite`) makes the CLI exit 1.

**Dependency walk** (`_Planner.walk`), a worklist over repo-relative keys:

- References come from `local_orphans.collect_local_refs` (run under
  `_quiet()`), the same walker `find-local-orphans` uses, so the two agree on
  what a file references: body links and images after snippet expansion,
  `annotatable_attachment`, module items, quiz description and question files,
  question-bank questions. Conditionals are not applied, so every `#if` branch's
  references are copied. `sync._get_file_refs` is not used because it skips
  quizzes.
- `assets/…` refs are copied. From a module file, every item is followed as a
  copied item (content and asset items alike). Any other content ref is
  recorded in `links_not_followed` with whether the destination already has
  that path, and filtered out at the end if the target got selected anyway.
- Snippets come from `convert.find_referenced_snippets` on the raw text (which
  also catches `PASTE_SNIPPET_INTO_FRONTMATTER`), plus each quiz/bank question
  file.
- Any key inside `quizzes/<name>/` or `question_banks/<name>/` expands to the
  whole folder (a quiz or bank syncs as one unit).
- Files matched by the source `.canvasignore` — directly or through an ignored
  parent directory — are skipped and listed.

**Classification** (`_Planner.classify`): `new`, `identical` (byte compare;
skipped), `conflict`, or `snippet-kept`. A snippet that was pulled in as a
dependency (not named on the command line) and differs in the destination is
kept as the destination's, even with `--overwrite` — course-specific snippets
such as `CANVAS_COURSE_ID` must not be replaced. A snippet named as SRC follows
the normal conflict rule.

**Rubrics** (`_plan_rubrics`), for copied assignments and discussions with a
string `rubric:` (frontmatter snippets expanded first): a title the destination
already has is used as-is, with a warning when criteria/ratings
(`description`, `long_description`, `points`) differ. Otherwise the source's
raw `[[rubrics]]` block — split at top-level `[[rubrics]]` header lines by
`split_rubric_blocks()` and titled by parsing each block alone — is appended as
text, once per title. Raw text rather than `tomlkit`/`toml_write` so the
commented-out import metadata survives. The resulting text is parsed with
`tomllib` before anything is written; invalid TOML or a missing title aborts.
Numeric `rubric:` values only warn. `update` currently attaches rubrics to
assignments only (see TODO "Add discussion rubric support"), so a copied
discussion's rubric lands in `rubrics.toml` but is not associated on Canvas yet.

**`module_order.toml`**: a copied module's name (path under `modules/`) is
appended to `order` with `tomlkit`, keeping comments — only when the file
already exists in the destination and does not list it.

**Warnings** (`_plan_warnings`, never fatal; copied files stay byte-identical):
string `assignment_group_id` not among the destination's `[[assignment_groups]]`
titles; numeric `assignment_group_id` / `group_category_id` / `final_grader_id`;
flags from `find_referenced_flags` / `find_referenced_flags_in_frontmatter` not
defined in the destination (`course_settings.toml` `[course_flags]` plus every
`course_settings/canvas*.toml`); graded items whose title appears in the source's
`due_dates` (`name`) or any `relative_due_dates` table item; same title and
content type as a different destination file; `/courses/<id>/` URLs matching a
`course_id` read with plain `tomllib` from the source's `canvas*.toml` (no token
needed).

**Fresh mtimes.** Files are written with `shutil.copyfile`, not `copy2`. With
`copy2` an overwritten destination file could keep a source mtime older than its
own manifest `last_synced`, and `update` would never upload it.

None of the other core subcommands (`update`, `import`, `mv`, `publish`) changed
for `cp`: it only writes files `update` already reads, and the rest act on one
repo as they find it.

## Orphan detection (`find-local-orphans` / `find-canvas-orphans`)

Two independent implementations of "what does nothing point at?", from opposite
sides. Both are read-only reports and both are **non-transitive**: only zero
inbound references count, so an asset linked from an orphaned page is not
itself an orphan. Reachability from the module roots is future work (TODO.md).

`find-canvas-orphans` (`orphans.py`) queries the live course: it fetches pages,
assignments, discussions and quizzes, regex-scans their HTML for
`/courses/<id>/{pages,assignments,discussion_topics,quizzes,files,modules}/…`
references (`extract_canvas_refs`), adds module item membership, the front page
and the syllabus, and reports every fetched resource not in the referenced set.
Note that Canvas **files** are collected as reference *targets* but never
enumerated as candidates, so an uploaded-but-unlinked Canvas file is not
reported (see TODO.md).

`find-local-orphans` (`local_orphans.py`) never contacts Canvas — no config
file is read beyond `course_settings.toml`, and no API token is needed. It
computes `candidates - referenced` over repo-root-relative keys (the same keys
the manifest uses).

**Candidates** (`collect_candidates`) — what may be reported:

| Source | Key |
| --- | --- |
| `assets/**` | every file, recursively |
| content folders (repo root dirs minus `{assets, modules, quizzes, snippets, course_settings, question_banks, announcements}` and dotdirs) | every `.md`, recursively |

Never candidates, and each for its own reason: `quizzes/` and `announcements/`
(nothing links to an announcement and a quiz is reached from a module or
directly in Canvas, so "unreferenced" is no deletion signal; both remain
reference *sources*, so their links still protect assets — `announcements` is
excluded via `_NEVER_REPORTED_DIRS` in `collect_candidates`, and quizzes simply
have no candidate loop), `snippets/` (a library file;
"unused this term" is not a deletion signal — the user's explicit call),
`modules/` and `course_settings/` (the roots — nothing in a repo links *to*
them), and `question_banks/` (quizzes embed their questions inline; the format
has no "draw N from bank X" reference, so every bank would be reported every
run). Quizzes were candidates (one unit keyed by its main file) until 2026-09-18.

**Reference sources** (`collect_sources` → `collect_local_refs`) — what is
scanned, dispatched on the top-level folder:

| Folder | Extraction |
| --- | --- |
| content, `snippets/`, `course_settings/syllabus.md` | `parse_frontmatter` → `expand_frontmatter_snippets` → `preprocess_snippets` → `markdown_to_html` → `extract_local_refs()`, plus the frontmatter `annotatable_attachment` path |
| `modules/` | `parse_module_body()`, taking `local_path` of every `type == "content"` item |
| `quizzes/` | `split_quiz_body()` for the question list, then the same HTML pass over the description and each question file |
| `question_banks/` | each `questions/*.md` through the content path |
| `assets/` | nothing (binary leaves) |

`course_settings.toml` contributes `front_page` and `dashboard_image` as direct
references, plus `pinned_resources` — returned separately by
`collect_settings_refs` because a pin may name a folder, which needs
`find_pinned_match()`'s prefix rule against each candidate rather than a set
lookup. `due_dates` contributes nothing: those entries match content by title,
not by path.

**`collect_local_refs` overlaps `sync._get_file_refs` deliberately and must not
be merged with it.** `_get_file_refs` drives targeted-sync BFS, where quizzes
intentionally return no refs (see its TODO). Here quizzes *must* be followed —
otherwise every asset used only inside a quiz would be reported as an orphan.
The two have different correctness requirements for the same-looking question.

**Conservative by construction**, in three places:

- Course-flag conditionals are **not** applied, so a link in a currently-false
  `#if` branch still counts — same conservative-superset stance as
  `_get_file_refs` and the `_phase_modules` pre-scan. Turning a flag off never
  makes content look deletable.
- `pinned_resources` entries count as referenced, so a pinned live quiz is
  never reported.
- Parse and conversion failures are **reported** instead of dropping the file's
  links silently. A malformed-frontmatter file has its `---` block stripped
  textually and its body probed anyway (Pandoc parses a leading `---` fence as
  YAML metadata and dies on the same content, so the block must go). A module
  item resolving outside the repo, a Pandoc failure, or a conversion timeout
  appends `(local_key, message)` to `report.errors` rather than manufacturing
  orphans. `_print_errors()` renders that list **last**, after the findings,
  since each entry means the orphan list above may name a file that is really
  referenced.

**Conversion timeout.** `_to_html()` calls `markdown_to_html(..., timeout=_PANDOC_TIMEOUT_SECONDS)`
(20s). Pandoc parses nested bracketed spans by backtracking exponentially —
measured at roughly 3x per level on real hardware: 3 levels 0.07s, 7 levels
4.9s, 9 levels several minutes on a 691-byte file. Runs like that are Canvas
export artifacts (see `_collapse_redundant_spans` below). `update` rarely trips
over one because its mtime staleness gate converts only changed files; this
command has no manifest and re-converts everything every run, so one such file
dominated a whole scan (measured: 5m00s total, ~4.5m of it in one file, 5.4s
after that file was fixed). The timeout turns that into a named error line
(`timed out after 20s - check for nested []s`) instead of a stall.

`_quiet()` (a `redirect_stdout` context manager) swallows parser chatter during
the scan — snippet-resolution errors, module indent warnings. Those belong to
`update`, which reports them properly; repeating them here would bury the
finding.

**`-v` / `--verbose`.** `find_local_orphans()` returns a `LocalOrphanReport`
(`orphans`, `referenced`, `warnings`) rather than a bare orphan list, because
the scan already knows the inbound edges and throwing them away would mean
re-scanning to explain a result. `referenced` maps each referenced candidate to
the sorted keys of everything referring to it, built by accumulating
`referrers[key].add(source_key)` as each source is scanned. `orphans` and
`referenced` **partition the candidate set** — every candidate is in exactly one
— so the two counts always add up to the number of candidates, and
non-candidates (snippets, modules, course settings, question banks) appear in
neither: listing them as "referenced" would imply they could otherwise have been
reported. Settings-derived references are credited to
`course_settings/course_settings.toml`; a pin is credited to that path with a
`(pinned_resources)` suffix, since a pin is not a link but *is* what keeps the
file off the orphan list. `print_report(report, verbose=False)` renders the
referenced section first so the orphan list stays at the bottom of the output,
and always leads with `_SCOPE_NOTE` naming the four folder classes that are
never listed — an empty report otherwise reads as "everything is referenced".

### Bounded Markdown conversion (`markdown_to_html(text, timeout=...)`)

`convert.markdown_to_html()` has two conversion paths. With no `timeout` it
calls `pypandoc.convert_text()` as before — that is what every upload path uses,
since a silent partial result would be worse than a slow one for a file the user
is actively syncing. With a `timeout` it calls pandoc directly via
`subprocess.run` (`_convert_with_timeout`), because pypandoc exposes no timeout,
and raises `subprocess.TimeoutExpired` past the deadline. The pandoc flags live
in `_PANDOC_FROM` / `_PANDOC_TO` / `_PANDOC_EXTRA_ARGS` so both paths share one
definition, and `test_convert.py` asserts both return byte-identical HTML for a
representative document — the two paths must not drift. Only
`find-local-orphans` passes a timeout today.

## Configuration

### Tool config file (`course_settings/canvas.toml`)

Provided once per course repo (in the `course_settings/` folder), checked into git:

```toml
base_url = "https://yourschool.instructure.com"
course_id = 12345

[auth]
# Prefer env var CANVAS_API_TOKEN; this is a fallback for local use only
api_token = ""
```

The API token should be passed via the `CANVAS_API_TOKEN` environment variable rather than committed to the repo. On startup the tool searches for a `.env` file starting from the current working directory (walking up the directory tree) and loads it automatically, so a `.env` in your course repo or any parent directory is picked up without any extra steps.

### Content mapping

Content type is determined by **directory convention** — no explicit config needed for the common case:

```text
pages/          → Canvas Pages
assignments/    → Canvas Assignments
discussions/    → Canvas Discussion Topics
announcements/  → Canvas Announcements (discussion topics with is_announcement)
quizzes/        → Canvas Quizzes (Classic) — nested structure, see below
modules/        → Canvas Modules (special — see below)
```

The directory name maps directly to the Canvas content type. A frontmatter `canvas_type` field can override the default if a file lives outside these directories.

**Announcements** (`_upload_announcement()` → `capi.create_or_update_announcement()`): a Canvas announcement is a discussion topic created with `is_announcement=True`, so it reuses the discussion-topic API, manifest addressing (`discussion_topics/:id`), timestamp check, prune, and link-rewriting — the only differences are the `is_announcement` flag and a distinct `canvas_type = "announcement"` recorded in the manifest. **Canvas has no unpublished/draft state for announcements** — creating one posts it immediately (`create_discussion_topic(..., published=False)` is rejected with *"This topic cannot be set to draft state because it is an announcement"*). So `published` acts as an on/off switch for whether the announcement is sent at all: a `published: false` announcement is **skipped** in `_sync_content_file()` (with a printed warning) — it stays staged in the repo until you set `published: true`, at which point it posts. The skip happens *before* link rewriting, so a not-yet-posted announcement never stub-creates the content it links to. If a `published: false` file already has a manifest entry (it was posted on a previous run), the tool warns that Canvas cannot un-post an announcement and leaves it (use `prune` or delete it in Canvas). Because posting is implicit, `published` itself is never sent to Canvas; a future `delayed_post_at` schedules the post instead of publishing immediately. Announcements cannot be graded, so — unlike discussions — no due-date, assignment-group, or rubric parameters are sent; but any discussion-topic settings in `capi.ANNOUNCEMENT_SETTABLE_FIELDS` (`delayed_post_at`, `lock_at`, `locked`, `discussion_type`, `require_initial_post`, `allow_rating`, `only_graders_can_rate`, `sort_by_rating`, `podcast_enabled`, `pinned`) that appear as active frontmatter are forwarded verbatim. Any other active frontmatter key (other than the handled `title`/`published`/`canvas_type`) is **not** silently dropped: `_upload_announcement()` prints a `WARNING: … ignoring frontmatter field '…'` as it happens and appends `(local_key, field)` to `ctx.ignored_fields`, which `_print_ignored_fields_summary()` lists at the end of the run (alongside the newer-on-Canvas and unpublishable-items summaries). There is no `position` handling — Canvas orders announcements by post date, so it is neither imported nor sent (and an explicit `position:` in a file is reported as ignored). Announcements are **not** valid Canvas module items; if one is referenced from a module the item is skipped with a warning. The `publish` (MkDocs) subcommand does not stage announcements (they are not module content).

### Per-file metadata (YAML frontmatter)

Each Markdown file carries its Canvas-specific metadata in YAML frontmatter. The body of the file (everything after the frontmatter block) is the content that gets converted to HTML.

**Common fields (all types):**

```yaml
---
title: "Week 1 Introduction"
published: true
---
```

**Assignment-specific fields:**

```yaml
---
title: "Week 1 Problem Set"
canvas_type: assignment      # optional if file is in assignments/
points_possible: 50
due_at: "2025-02-01T23:59:00-05:00"
lock_at: "2025-02-08T23:59:00-05:00"
unlock_at: "2025-01-27T00:00:00-05:00"
grading_type: "points"       # points | percent | letter_grade | gpa_scale | pass_fail
submission_types: [online_upload]
published: true
---
```

**Discussion-specific fields:**

```yaml
---
title: "Introduce Yourself"
require_initial_post: true
published: true
---
```

Graded discussions additionally accept these fields, which are passed to Canvas as nested assignment params:

```yaml
---
title: "Week 1 Discussion"
require_initial_post: true
points_possible: 10
due_at: "2025-02-01T23:59:00-05:00"
lock_at: "2025-02-08T23:59:00-05:00"
unlock_at: "2025-01-27T00:00:00-05:00"
assignment_group_id: "Labs"   # same name/numeric-ID resolution as assignments and quizzes
published: true
---
```

**Page-specific fields:**

```yaml
---
title: "Syllabus"
editing_roles: teachers
published: true
---
```

### Quiz file format

Quizzes use a **nested folder structure** — each quiz lives in its own sub-folder under `quizzes/`, named with the slugified quiz title. Questions are stored as individual files in a `questions/` sub-folder.

```text
quizzes/
└── my-quiz/
    ├── my-quiz.md          # quiz-level file (same name as folder)
    └── questions/
        ├── question-one.md # individual question files (human-readable names)
        └── question-two.md
```

**Quiz-level file** (`quizzes/{slug}/{slug}.md`):

The frontmatter holds quiz settings. The body is an optional description shown to students before they begin, followed by a numbered list of links to question files. The link order defines the question order in Canvas.

```yaml
---
title: "Week 1 Quiz"
quiz_type: assignment        # assignment | practice_quiz | graded_survey | survey
points_possible: 6.0
time_limit: 30               # minutes; omit if no time limit
allowed_attempts: 1
shuffle_answers: false
show_correct_answers: true
assignment_group_id: "Labs"   # name (resolved via course_settings.toml) or numeric
                              #   Canvas ID; shared resolution logic with
                              #   assignments and discussions (sync.py:
                              #   _resolve_assignment_group_id). Only affects
                              #   grading when quiz_type is assignment or
                              #   graded_survey.
published: true
---

Read each question carefully before answering.

1. [What is 2+2?](questions/what-is-2-plus-2.md)
2. [Explain gravity](questions/explain-gravity.md)
```

**Multiple choice question** (`question_type: multiple_choice_question`):

`correct` is the 1-based index of the correct answer in the `## Answers` list.

```yaml
---
title: "What is 2+2?"
question_type: multiple_choice_question
points_possible: 1
correct: 2
---

What is the result of adding 2 and 2?

## Answers

1. 3
2. 4
3. 5
```

**True/false question** (`question_type: true_false_question`):

No `## Answers` section — Canvas always provides "True" and "False". `correct` is the boolean value.

```yaml
---
title: "The sky is blue"
question_type: true_false_question
points_possible: 1
correct: true
---

The sky appears blue during the day due to Rayleigh scattering.
```

**Essay question** (`question_type: essay_question`):

No `correct` field or `## Answers` section — manually graded.

```yaml
---
title: "Explain gravity"
question_type: essay_question
points_possible: 5
---

In 3–5 paragraphs, explain the concept of gravity and how it affects objects with different masses.
```

**Multiple-response question** (`question_type: multiple_response_question`):

`correct` is a list of 1-based indices of all correct answers. Answers section is the same format as MCQ.

```yaml
---
title: "Select all prime numbers"
question_type: multiple_response_question
points_possible: 2
correct: [1, 2, 4]
---

Which of the following are prime numbers? Select all that apply.

## Answers

1. 2
1. 3
1. 4
1. 5
```

**Fill-in-blank question** (`question_type: fill_in_blank_question`):

`answers` is a list of all accepted correct strings (case-insensitive exact match). No `## Answers` section.

```yaml
---
title: "Speed of light"
question_type: fill_in_blank_question
points_possible: 1
answers: [300000, 300 000]
---

The speed of light is approximately _____ km/s.
```

**Pattern-match question** (`question_type: pattern_match_question`):

`answers` lists accepted patterns (case-insensitive substring match). `match_type: substring` signals the matching mode.

```yaml
---
title: "Name a language"
question_type: pattern_match_question
points_possible: 1
answers: [python, r language]
match_type: substring
---

Name a programming language used in data science.
```

**Question feedback** (all types): If the QTI item has `<itemfeedback>` elements, a `## Feedback` section is appended after the question text / answers with subsections `### General`, `### Correct`, `### Incorrect`, and `### Per-answer` (only those present in the source). Per-answer feedback lists each answer by 1-based index, written as `- answer N: text` bullets (a following line that isn't itself a `- answer M:` bullet is treated as a continuation paragraph of the same item).

On the sync side, `quiz.parse_question_file()` reads all four subsections: `### General`/`### Correct`/`### Incorrect` become the question's `neutral_comments`/`correct_comments`/`incorrect_comments` (forwarded to Canvas by `canvas_api._build_question_params`), and `### Per-answer` becomes an `answer_comments` key on the matching entry in `answers` (MCQ/multiple-response/true-false only — matched by the same 1-based position used elsewhere for `correct`).

**Essay sample solution**: If the QTI item has `<itemfeedback ident="solution">`, a `## Sample Solution` section is appended after the question text.

**Quiz manifest entry:**

The manifest key is the quiz-level `.md` path. `canvas_question_ids` maps each question file's path (relative to the quiz folder) to its Canvas question ID.

```toml
["quizzes/my-quiz/my-quiz.md"]
canvas_type = "quiz"
canvas_id = 12345
last_synced = "2025-02-01T10:00:00"
canvas_question_ids = {"questions/what-is-2-plus-2.md" = 111, "questions/explain-gravity.md" = 222}
```

**Quiz sync behaviour:**

- The quiz is re-synced if the quiz `.md` file **or any question file** has mtime newer than `last_synced`. A change to a single question triggers a full quiz re-sync.
- On each sync, all existing Canvas questions are deleted and re-created in the order listed in the quiz `.md`. This keeps question order correct and avoids stale questions after edits.
- Canvas module items reference the quiz by `canvas_id` and use module item type `"Quiz"`.
- Quiz description HTML and question text HTML are passed through `rewrite_links()` before upload, so cross-links to other course content resolve to correct Canvas URLs.
- A question file listed in the quiz `.md` but missing on disk is a hard error: the whole quiz upload is skipped (nothing recorded in the manifest, so the quiz is retried next run) and the run's error summary fails the run.

**Supported question types:** `multiple_choice_question`, `true_false_question`, `essay_question`, `multiple_response_question`, `fill_in_blank_question`, `pattern_match_question`. Other types emit a warning and are skipped.

**Effectively required fields per question type** (missing them won't crash the upload, but the question will be ungradable in Canvas):

| Question type | Field | Effect if missing |
| --- | --- | --- |
| `multiple_choice_question` | `correct` (1-based int) | No answer marked correct |
| `multiple_choice_question` | `## Answers` section | No answer choices at all |
| `true_false_question` | `correct` (bool) | Neither True nor False marked correct |
| `multiple_response_question` | `correct` (list of 1-based ints) | No answers marked correct |
| `multiple_response_question` | `## Answers` section | No answer choices at all |
| `fill_in_blank_question` | `answers` (list of strings) | No accepted answers |
| `pattern_match_question` | `answers` (list of patterns) | No accepted patterns |

All other fields across all resource types (`title`, `published`, dates, points, etc.) have safe defaults — nothing will crash or be skipped if they are absent.

### Question bank file format

Canvas question banks (pools) are written to `question_banks/{slug}/`:

```text
question_banks/
└── unfiled-questions/
    ├── unfiled-questions.toml   # bank metadata
    └── questions/
        ├── how-many-exams.md    # one file per question (same format as quiz questions)
        └── ...
```

**Bank metadata TOML** (`question_banks/{slug}/{slug}.toml`):

```toml
bank_title = "Unfiled Questions"
bank_context_uuid = "SRI51UyJjHbdsdzYFn1LYxMYjMYh4GITEORKR38K"
bank_state = "active"
```

**Bank question files** use the same format as quiz question files. Both quiz and bank
questions may carry one extra frontmatter line, written as a comment:

`# original_answer_ids` — the Canvas-internal answer IDs from the original export, kept
as import-only fidelity metadata. Present only on choice-based questions (MCQ,
multiple-response) where Canvas assigned them. It is written commented-out because
nothing consumes it: `update`/`publish`/`sync` never read it, and re-uploading a
question always gets fresh Canvas-assigned answer IDs. Uncomment it manually if you
need to reference the original IDs for some other purpose.

```yaml
---
title: "How many exams?"
question_type: multiple_choice_question
points_possible: 1.0
correct: 3
# original_answer_ids: [8230, 5348, 7678, 5601]
---
```

Note: quizzes that draw from question banks export their questions **inline** in the quiz's own QTI file. There is no "draw N from bank X" reference in the IMSCC output. Question banks and quizzes are independent exports. Deleted banks (`bank_state = "deleted"`) are still imported in deleted state to preserve round-trip fidelity.

**Question bank manifest entry:** None is written, since banks are never uploaded. Older manifests may still contain entries keyed by the bank `.toml` path with `canvas_type = "question_bank"`.

**Import warning and default ignore:** Phase 5c counts converted banks and, if any, prints a `WARNING` that they cannot be re-uploaded to Canvas. `_DEFAULT_CANVASIGNORE` includes `question_banks/**` so a freshly imported repo doesn't print the per-bank skip warning on every `update`.

### Course settings files

These files are never uploaded as Canvas Pages. Each has a dedicated upload path:

| File | Upload behaviour |
| --- | --- |
| `course_settings/course_settings.toml` | Applied via `course.update()` for flat metadata; dedicated API calls for grading standards, assignment groups, late policy, post policy, course-navigation tabs, and rubrics |
| `course_settings/syllabus.md` | Body converted to HTML and set as `course.syllabus_body` via `course.update()` |
| `course_settings/events.md` | Not yet uploaded (future feature) |
| `course_settings/rubrics.toml` | Each rubric created or updated in place (matched by title) via `course.create_rubric()` / `PUT rubrics/:id`; supports `long_description`, `reusable`, `read_only`. Created with a course-level association of `purpose: "bookmark"` (see below — `"grading"` makes Canvas fork the rubric on every edit). Per-rubric change detection via the manifest entry's `rubric_hashes` sub-table; rubrics deleted on Canvas are detected and re-created, and their assignments re-associated (see below) |
| `course_settings/files_meta.toml` | Not yet uploaded (requires matching Canvas file IDs after asset upload) |

**`course_settings/course_settings.toml` upload detail:**

**Permission-gated metadata fields.** Canvas gates individual course fields on account-level role permissions (course visibility, term dates, self-enrollment and similar are commonly withheld from teachers). When the `PUT courses/:id` body contains even one such field, Canvas rejects the *entire* call with a blanket `403 {"status":"unauthorized"}` and no indication of which field caused it — previously an uncaught `canvasapi.exceptions.Forbidden` traceback that killed the run before any content synced. `update_course_metadata()` now catches that 403 and re-sends the fields one at a time, so every field the account *may* set is still applied, and it returns the list of refused API field names. `sync_course_settings()` warns with that list (recorded in `errors`, so the run reports failure) and names the fields so the instructor can comment them out. The section is still marked done: the refusal is a standing account-permission fact, not a transient error, so re-probing on every run would cost one PUT per field forever. If *no* field gets through, the account cannot edit the course at all; the `Forbidden` is re-raised and handled as an ordinary section failure (warned, hash not recorded, retried next run).

The following sections are handled separately from the flat `course.update()` call:

- `[[grading_standards]]` — each entry created via `course.add_grading_standards()` if title not already present; first standard's ID passed as `grading_standard_id` in the course update. **Canvas is asymmetric about scheme values:** reads (and the `data` blob in an IMSCC export, which is what `import` writes into the .toml) give fractions in 0..1, but the *create* endpoint documents `value` as the lower bound on a 0..100 scale and divides by 100 on the way in. `_grading_scheme_entries()` therefore multiplies by 100 when every value is <= 1.0, and passes values through untouched when any exceeds 1.0 (a hand-written file already using 0..100). Uploading 0.95 verbatim meant "0.95%", which silently put every student in the top band.

  **Lookup spans the account chain.** `GET /courses/:id/grading_standards` returns *only* course-owned standards: an account-level scheme the course actually uses is absent from that list, and fetching it by id through the course context 404s (verified against Canvas 2026-09). Matching on that list alone meant a title never matched, so every course got its own clone of the institution's scheme — and, before the 0..100 fix above, a clone with cutoffs 100× too small. `_visible_grading_standards()` therefore also walks `course.account_id` upward via `GET /accounts/:id/grading_standards`, nearest account first, and `sync_grading_standards()` matches titles against the union (course-owned wins a tie). Reuse prints `NOTICE: using account-level standard …`; accounts the token cannot read are skipped rather than fatal, so a teacher without account-read permission still gets a working sync via the create path. A newly created standard prints its id, since nothing in the repo records it.

  **A title match is verified before use.** `_scheme_differences()` compares the live standard against `data` — band count, names, cutoffs (normalized to fractions, so a .toml on either scale compares correctly), and `points_based`/`scaling_factor` when the .toml sets them. On any difference **nothing is changed**: `sync_grading_standards()` returns `standard_id=None` (suppressing the change even for standards that *did* match, since repointing the course at a different standard is itself a silent grade change) plus a `mismatches` list. `sync_course_settings()` prints those, skips `_section_done("grading_standards")`, *and* appends to `section_failures`. Both are required for the error to persist: the missing section hash re-runs the section, and the missing `last_synced` is what makes `needs_sync()` re-examine the file at all when its mtime hasn't changed. The result is an error that repeats every `update` until the instructor reconciles .toml and Canvas — deliberate, because a scheme mismatch silently changes letter grades.

  Note that a standard whose title matches and whose scheme *agrees* is reused as-is, never rewritten — fixing a bad scheme means editing or deleting it on Canvas.
- `[[assignment_groups]]` — each entry created or updated via `course.create_assignment_group()` / `ag.edit()`, matched by name; processed in `position` order. Both calls must pass **flat top-level params** (`name`, `position`, `group_weight`, `rules`): Canvas's assignment-group endpoints `params.permit` only those names and silently drop anything nested under `assignment_group[...]` (unlike most other Canvas endpoints, which expect the nested form). Per-group `group_weight` values only take effect (and only display on the Assignments page) when the course-level `apply_assignment_group_weights` flag is on, so `update_course_metadata()` sets that flag in the `course.update()` call: `group_weighting_scheme = "percent"` (the Canvas IMSCC export name, round-tripped by the importer) maps to `true`, any other value to `false`, and when the key is absent the flag is inferred as `true` if any group has a `group_weight`. When neither the key nor any weight is present the flag is not sent, leaving the course's existing setting alone. **Drop rules deferral:** a group's `rules` (`drop_lowest`/`drop_highest`) are validated by Canvas against the *current* number of assignments in the group ("Drop rules cannot be higher than the number of assignments"). Because course settings are applied in phase 0 — before any assignments exist — a fresh course would reject every drop rule. So `sync_assignment_groups()` catches that specific `BadRequest`, creates/updates the group **without** the rules (warning `Deferring drop rules for assignment group …`), and returns the affected group names; `run_sync()` then re-applies them via `capi.apply_assignment_group_rules()` after the content and quiz phases (phase 2.65), once the groups contain their assignments. A group that still lacks enough assignments at that point is warned about, not fatal.
- `[late_policy]` — applied via `PATCH /api/v1/courses/:id/late_policy` (raw requester call, not wrapped in `canvasapi`). This genuinely is a REST resource, so it stays REST.
- `[default_post_policy]` — applied via the **GraphQL** `setCoursePostPolicy` mutation (`POST /api/graphql`), issued through the shared requester (`canvas_api.graphql()` / `update_post_policy()`). Post policies are GraphQL-only in Canvas; the former `PUT /api/v1/courses/:id/post_policies` REST route does not exist and returned 404.
- `tab_configuration` — controls the **course-navigation sidebar** (the left-hand "Assignments", "Modules", … links). An inline array, one entry per tab, in display order. Each entry is applied via `tab.update(position=…, hidden=…)` against `course.get_tabs()`; `hidden` defaults to false. Positions are assigned in list order **starting at 2**, because Canvas pins **Home** at position 1 and rejects any other tab placed there (`"That tab location is invalid"`).

  Each entry names one tab via `id` **or** `label` — the two are interchangeable (a non-empty `label` is used as the name when present, else `id`). `_resolve_tab_entry()` matches the typed name, **case-insensitively**, against: (1) a built-in tab id (`home`, `syllabus`, `pages`, `assignments`, `modules`, `announcements`, …); then (2) any live tab's **display label**, which covers external tools (`Zoom`, `Panopto Recordings`) and renamed built-ins (Conferences shown as `BigBlueButton`). This means a user can simply type the sidebar name without knowing whether it's a built-in or a tool. An entry may still carry both keys (e.g. the importer writes `label = "Zoom"` plus the original `id = "context_external_tool_g…"` for provenance); the tool id is not used for matching because the cartridge's id never equals a live course's Canvas-assigned tool id.

  Only reordering and hiding are supported — new tabs cannot be created. Entries that don't resolve to any tab in the course (no built-in or installed tool by that name) are **warned about and skipped**, never created. The unmovable `home` and `settings` tabs are silently left alone. Also accepted for backward compatibility: Canvas's internal **numeric** tab ids (`0`=home, `3`=assignments, …; see `NUMERIC_TAB_IDS`) and a single JSON-encoded string, the forms older imports/exports produced.

Read-only or infrastructure fields (`storage_quota`, `root_account_uuid`, `image_identifier_ref`, `last_modified`, `copyright_restrictions`, `copyright_description`, and others) are present in the TOML for round-trip fidelity but are silently ignored by the uploader.

**Section-level change detection** (`DESIGN-settings-caching.md`): the settings file is split into named sections — `metadata` (every top-level key not claimed by another section, so unknown keys conservatively count as metadata), `grading_standards`, `dashboard_image`, `assignment_groups`, `late_policy`, `default_post_policy`, `tab_configuration`, and `front_page` — and each section's canonical-JSON SHA-256 hash (first 16 hex chars; `compute_settings_section_hashes()`) is cached in the manifest entry's `section_hashes` sub-table. When the file's mtime is stale, only sections whose hash differs are re-applied; a comment-only edit re-runs nothing. `due_dates`, `[course_flags]`, and `pinned_resources` are excluded from every section (including metadata): due_dates changes are handled per-item by the dates pass, flag changes per-file via `flags_used`, and `pinned_resources` only gates uploads locally (there is nothing on Canvas to update), so editing any of them re-sends no settings section. Couplings: a `grading_standards` or `assignment_groups` change also forces the `metadata` action (the metadata call carries `grading_standard_id` and the group-weight inference); when only metadata changed, `gs_id` is `None` and the course's existing grading standard is left alone. The dashboard image **file's own mtime** joins the staleness check (via `extra_mtime_paths` against the settings entry's `last_synced`), so editing the image alone re-uploads it — and conversely, unrelated settings edits no longer re-upload it. `front_page` has no action inside `sync_course_settings()`; `run_sync` keys the front-page phase off `"front_page" in changed_sections` (or the page itself having re-synced). **Failure/retry:** a failed section is recorded via `warn(..., errors)` (fails the run) and its hash is *not* updated; the entry is recorded with `mark_synced=False`, so the next run re-parses and retries exactly the failed sections while skipping the succeeded ones. A nested `tab_configuration` is not repaired here: `upgrade` moves it once, and `sync_course_settings()` reads only the top-level key. `format_version`, `created_by` and `upgraded_by` are in `_NON_METADATA_SETTINGS_KEYS`, so `upgrade` does not change the `metadata` hash. Migration: an entry without `section_hashes` (older tool version) re-runs all sections once when stale, then records hashes.

**Rubric-level change detection**: `rubrics.toml` gets the same treatment, one hash per rubric. Each `[[rubrics]]` table's canonical-JSON hash (`_section_hash()`) is cached, keyed by title, in the manifest entry's `rubric_hashes` sub-table. When the file's mtime is stale, only rubrics whose hash differs are sent to `capi.sync_rubrics()`; the rest are skipped (in verbose mode: `Skipping rubric (unchanged): …`). Per rubric, create-vs-update is decided by an exact title match against a live `course.get_rubrics()` fetch — **not** by the manifest — so `Created rubric:` means Canvas didn't list that title at sync time. Updates print `Updated rubric: …`. **Failure/retry:** `sync_rubrics()` catches per-rubric API errors and returns them as `(title, error)` pairs instead of aborting the batch; a failed rubric's hash is not advanced and the entry is recorded with `mark_synced=False`, so the next run retries exactly the failed rubrics. Titles removed from the file drop out of `rubric_hashes` (the Canvas rubric itself is left alone). `--force-uploads` (or a missing `rubric_hashes` sub-table, i.e. older tool version) re-sends every rubric once.

**Rubrics deleted on Canvas — detection and repair.** (Full measured behaviour, including the diagnosis recipes, is in **[todo/RUBRIC_ISSUES.md](todo/RUBRIC_ISSUES.md)**.) Canvas soft-deletes a rubric the moment its **last association is destroyed** (verified 2026-08; the `purpose` of that association is irrelevant, and deleting a rubric from the Manage Rubrics page also destroys its assignment associations). A soft-deleted rubric drops out of `course.get_rubrics()` while assignments that were re-associated with it afterwards keep pointing at it — and the Canvas UI's Rubrics page still lists it, because that page renders the course's rubric *associations*, not the rubric list. The symptom is `rubric 'X' not found on Canvas` for a rubric that is plainly visible in the web UI. Two mechanisms handle this:

- **Detection** (`sync_course_settings`): `rubrics.toml` is loaded on **every** run — even when its mtime is unchanged and the settings phase would otherwise return early — and its titles are compared against the live rubric list. Any title that `rubric_hashes` records as previously synced but Canvas no longer lists is announced (`NOTICE: rubric '…' is in rubrics.toml but no longer on Canvas`) and forced past the hash cache into `stale_rubrics`, so it is re-created in phase 2.5 and `rubric_ids` is correct for the rest of the run. A title Canvas has never seen is *not* treated as deleted — it is simply new (first sync, or `--check-all`, whose simulated course starts empty). Without this the hash cache pinned the broken state in place run after run.
- **Repair** (`_repair_rubric_associations`, phase 4a): creating the same title again does **not** restore the soft-deleted rubric — Canvas mints a new id and leaves the old one deleted but still attached to its assignments — so every assignment referencing a re-created title has to be re-associated. This cannot ride on the normal upload path: an unchanged `.md` returns from `needs_sync` before its frontmatter is ever parsed, so `_apply_rubric` never runs for it. The pass walks `iter_gradeable_content()` (assignments only — rubrics attach nowhere else), skips files already synced this run, and re-associates from the manifest's `canvas_id`, printing `Re-associated rubric '…': …`. Numeric `rubric:` references are left alone: an id names a Canvas rubric directly and there is nothing to re-resolve it to. Run by both `run_sync` and `run_targeted_sync` (repo-wide in both — a re-created rubric strands assignments outside any target set).

**Course-level rubric association uses `purpose: "bookmark"`, not `"grading"`.** Canvas forks a rubric on edit — creating an orphan copy titled `X (1)` and leaving the real rubric's criteria untouched — once the rubric has more than one *grading* association, and a course-level `grading` association counts toward that total. With `"grading"` a rubric attached to even one assignment forked on every sync (the source of long `Class Notes (1) … (11)` runs of junk rubrics in a course); with `"bookmark"` the same edit applies in place. Verified against Canvas 2026-08. The fork still happens for a rubric attached to **2 or more** assignments — see TODO.md.

**due_dates resolved-value caching** (`DESIGN-settings-caching.md`): the dates-only pass (`_apply_due_dates_only`, phase 6) runs on **every** update — not just when settings changed — and each gradeable item's manifest entry caches the **symbolic resolution** of its due_dates entry in a `resolved_dates` sub-table: per date key, a concrete date string (verbatim), `"NONE"` (clear), or `"KEEP"` (leave alone; also what empty values and — for existing items — `CREATE_NONE_THEN_KEEP` resolve to). Computed by `resolve_dates_symbolic()`; comparison is verbatim-string, so reformatting the same instant re-sends once (harmless). Per item: skip if synced this run (the full-sync upload paths record `resolved_dates` themselves, via `extra=` since `record()` rebuilds entries wholesale); if no entry matches but a cache exists, print a one-time `NOTICE` and drop the cache (deleting an entry means "stop managing", never "clear dates"); if the fresh resolution equals the cache, skip with no API call (`--force-uploads` bypasses); otherwise send the changed fields via `update_dates()` and advance the cache — including when there is nothing to send because everything resolved `KEEP` (the cache must advance or the entry re-triggers forever). A Canvas date rejection (`date_warning`) leaves the cache un-written so the item is retried (and re-warned, failing the run) every run until fixed. This structurally fixes the old crash hole where the settings entry was recorded before the dates pass ran, so an interrupted run silently skipped the remaining date updates. Deliberately **not** in scope: the cache never triggers a body re-sync, and frontmatter-only dates are not cached (the dates pass has never applied them). First run after upgrading seeds the cache by applying every matched entry once.

**Pinned resources (`pinned_resources`)**: a top-level array of repo-relative paths (file or folder; a folder entry covers everything under it) whose content is **never uploaded** — the motivating case is a quiz students have started, since `sync_quiz_questions()` deletes and re-creates every question, which disconnects existing submissions. Loaded once per run by `load_pinned_resources(repo_path, settings=None)` in `sync.py` (mirrors `load_course_flags`; non-list, non-string entry, or absolute path raises `ValueError` → `die()`; entries are normalized: trimmed, backslashes → `/`, trailing `/` stripped), threaded through `SyncContext.pinned`. An entry pointing *inside* a `quizzes/<name>/` or `question_banks/<name>/` folder that isn't the folder itself or its main file (`<name>.md` / `<name>.toml`) — e.g. a single question file — is also `ValueError` → `die()`: those sync as one unit, so such a pin could only be silently ineffective (the quiz would still sync and still delete/re-create the "pinned" question). `run_sync` validates pins *before* phase 0 so the hard stop happens before anything is applied to Canvas; `run_targeted_sync` and `run_prune` load (and thus validate) them before processing anything as well. Matching is `find_pinned_match()`: exact key or `entry + "/"` prefix. The check (`_skip_if_pinned()`) sits in every upload path — `_sync_content_file`, `_sync_quiz`, `_sync_module`, `_sync_question_banks`, `sync_syllabus`, `_walk_assets`, and the targeted-sync assets branch — **after** the `needs_sync`/`_quiz_needs_sync` staleness gate (an up-to-date pinned resource stays silent, and no Canvas call is made for a pinned skip) and **before** `_canvas_is_newer`. Placement after the staleness gate means the pin wins over `--force-uploads` and explicit `-t`/`-s` targeting by construction (both merely force the gate open). The skip is a **soft warning**: printed inline and accumulated in `ctx.pinned_skips` for `_print_pinned_summary()`, never appended to `ctx.errors`, so the run still succeeds. `check_pinned_resources_coverage()` warns (never errors) about entries matching nothing on disk. `run_prune` also protects pinned orphans in `delete`/`unpublish` modes (counted as "kept"; `manifest` mode is exempt since it never contacts Canvas), and `mv` rewrites pin entries via `compute_pinned_resources_updates()` + `_replace_toml_quoted_string()` (file pins resolve through `path_map`, which includes quiz/qbank inner-file renames; folder pins by prefix against the moved directory) so a rename can't silently unpin a live quiz. `publish` and `import` are unaffected (neither uploads to Canvas). Not manifest state: the pin list lives only in `course_settings.toml`, so unpinning simply lets the normal mtime staleness check re-upload on the next run.

### Module file format

Module files differ from content files: they don't have a body that becomes HTML. Instead, the frontmatter holds module attributes and the body is a Markdown list of links to local content files. The order of links defines the order of items in the Canvas module.

```markdown
---
title: "Week 1: Introduction"
published: true
unlock_at: 2025-01-20T00:00:00-05:00
require_sequential_progress: false
---

- [Syllabus](../pages/syllabus.md)
- [Week 1 Lecture Notes](../pages/week1-lecture.md)
- [Week 1 Assignment](../assignments/week1.md)
- [Week 1 Discussion](../discussions/week1-intro.md)
```

The link text becomes the display title of the item within the module. The link target is either:

- A relative path to a local content file (page, assignment, discussion, or quiz)
- An absolute URL (`https://...`) — rendered as a Canvas ExternalUrl module item

**External URL items** with a `target="_blank"` attribute (written as an HTML comment on the same line by the importer) open in a new tab in Canvas:

```markdown
- [Course Website](https://example.com) <!-- target="_blank" windowFeatures="width=800" -->
```

The `target` attribute is mapped to Canvas's `new_tab` boolean; `windowFeatures` is discarded (no Canvas equivalent). External URL items default to `new_tab: true` (opens in a new window); add `<!-- target="_self" -->` to embed in an iframe instead.

**Section sub-headers** within a module (Canvas calls these `SubHeader` items) can be written two ways:

1. A `## heading` line becomes a SubHeader at **indent 0**. These stand out visually in both the Markdown source and Canvas.
2. A **plain-text list item** (a bullet with no link) becomes a SubHeader starting at **indent 1**. Nesting with leading spaces increases the indent level (2 spaces per level, same as link items).

```markdown
---
title: "Week 1: Introduction"
published: true
---

## Readings                                         <!-- SubHeader indent 0 -->

- [Week 1 Lecture Notes](../pages/week1-lecture.md)

## Work                                             <!-- SubHeader indent 0 -->

- [Week 1 Assignment](../assignments/week1.md)
- [Week 1 Discussion](../discussions/week1-intro.md)
- Please read the instructions carefully            <!-- SubHeader indent 1 -->
  - And bring your textbook                         <!-- SubHeader indent 2 -->
```

**Item indentation:** Leading spaces on list items control the Canvas module item `indent` parameter (0-5). Every 2 spaces = 1 indent level. `parse_module_body()` captures this from the Markdown and stores it as an `"indent"` key on each item dict. `add_module_item()` passes it through to `module.create_module_item()`. Values exceeding Canvas's maximum of 5 are clamped with a warning. `## headings` always get indent 0; plain-text list items start at indent 1. For the publish website, `render_module_overview()` renders indent-0 SubHeaders as `## headings` and indented SubHeaders as bold `<li>` elements.

**Synchronisation notes:**

- All content files linked from a module must already exist in Canvas (i.e., have entries in the manifest) before the module can be synced. The tool should sync content first, modules second.
- Canvas modules hold a flat ordered list of items. The tool syncs this by comparing the desired item list (derived from the Markdown) against the current Canvas module items and adding, removing, or reordering as needed.
- The manifest tracks both the module's Canvas ID and the Canvas item IDs within it (needed to reorder or delete individual items).
- If any item cannot be added (e.g., its file was never synced so it has no manifest entry), the module's manifest entry is written **without** `last_synced` (`record(..., mark_synced=False)`) — the Canvas ID is kept so the next run updates the same module instead of duplicating it, but the module stays stale and is retried on the next `update`.
- **Module-publish cascade conflict warning:** In Canvas a module's publish state cascades to its contents — `create_or_update_module(..., published=False)` (from a module file's `published: false` frontmatter) unpublishes not just the module but the underlying content of every item in it (pages, assignments, discussions, quizzes). Content is synced *before* modules, so a page uploaded with `published: true` is silently flipped back to unpublished when its module syncs — the module always wins, and the run still reports success. `_warn_module_publish_conflicts(ctx, title, items)` (called from `_sync_module()` only when the module's own `published` is `False`) surfaces this: for each `content` item whose `local_path` ends in `.md` and whose resolved `published` is `True`, it prints an inline `WARNING` and appends `(module_title, item_title, local_key)` to `ctx.publish_conflicts`, which `_print_publish_conflicts_summary()` lists at the end of the run (a **soft** warning like pinned/unpublishable — never added to `ctx.errors`, so the run still succeeds). Only `.md` content is checked: assets (Files) have no `published:` frontmatter to conflict with (their historical module-item default is "published", but there is no stated intent for the module to override), and ExternalUrl/SubHeader items have no underlying content. The check runs on parsed frontmatter, so it fires in `update --check-all` (dry-run) too. Sibling items do **not** affect each other, and links between files do **not** change publish state — the module-level cascade is the only cross-resource publish interaction, so it is the only conflict warned about.

### Manifest file (`.manifest-<config stem>.toml`)

The tool maintains a manifest in the course repo that maps local file paths to their Canvas IDs. The tool reads this file to decide whether to create or update, and writes to it after each successful publish.

**One manifest per `canvas.toml`.** The file name is derived from the config in use (`manifest.manifest_name_for(config_path)`): `course_settings/canvas.toml` → `.manifest-canvas.toml`, `course_settings/canvas-sec-a.toml` → `.manifest-canvas-sec-a.toml`. `Config.config_path` carries the path `config.load()` read, and `run_sync`/`run_targeted_sync`/`run_prune` derive the manifest path from it, so pointing `--config` at a second course (another section, a sandbox) keeps two independent sets of Canvas IDs and `last_synced` times in one repo. `find-canvas-orphans` takes `--config` too but reads no manifest; `publish` and `import` touch none.

**Stored course (`_canvas_course`).** The manifest name tracks the config file, not the course inside it, so editing `course_id` in `canvas.toml` silently keeps every old Canvas ID (observed: 83 assets uploaded to a Spring course kept their Spring ids after `canvas.toml` moved to Fall, so they were never uploaded to Fall and 24 pages kept linking to the Spring copies). The manifest therefore holds a reserved entry `manifest.COURSE_KEY = "_canvas_course"` with `canvas_type = "course_identity"` (`COURSE_TYPE`), `base_url`, `course_id`, `course_name`, `recorded_at`. Helpers in `manifest.py`: `is_reserved_key` (covers this entry and the format stamp below), `get_course_identity`, `set_course_identity` (writes and flushes), `same_course` (base_url compared case-insensitively without trailing slash), `has_content_entries`. Every place that walks the whole manifest skips reserved entries with `is_reserved_key`: `run_prune`, `clean_manifest` (`check_entries`, `plan_invalidate_all`), `pair_manifest._claimed`, `course_guard`, `has_content_entries`, and `mv.compute_manifest_updates` (which passes them through unchanged); `_phase_due_dates` ignores them (no `resolved_dates`).

`course_guard.check_course(manifest_path, config, course_name, assume_yes, confirm, interactive)` is called from `cli._guard_course` after `get_course()` in `update` (full and `-t`/`-s`) and `prune --delete/--unpublish`; not in `update --check-all` or `prune --manifest-only` (no Canvas contact). It lives in the CLI layer, so `run_sync` and friends (and their tests) are unaffected. Outcomes (every prompt defaults to no; the CLI has already printed the repo, course id, base URL and course name, which is what the person is being asked to check):

- same course → return, silently;
- nothing stored → explain (first sync, or a manifest from an older version) and ask before recording. Both cases ask, so a wrong `course_id` on a first sync is caught before anything is uploaded;
- different course stored → print recorded vs requested plus the entry count and the duplicate-content warning, ask, and on yes hand the manifest to `clean_manifest.plan_invalidate_all` + `apply_clean`, which drops every entry and records the new course. The run then continues into the sync, which re-creates the content in the new course. Invalidating without asking Canvas is sound because Canvas object ids are unique per object: nothing in the new course can hold an id recorded against the old one, so a listing could only confirm that every entry is dead.

`assume_yes` answers any of these; with `interactive()` false and no `assume_yes`, `CourseGuardError` names `--yes`. Declining also raises it. The CLI turns `CourseGuardError` into `die()`. `check_course` calls `check_repo_format` on `manifest_path.parent` before loading the manifest, because the guard can write the manifest and must not do so for a repo in the wrong format.

**Format stamp (`_repo_format`).** A second reserved entry, `manifest.FORMAT_KEY = "_repo_format"`, holds `{ format_version = N }`, the repo format version the manifest was written in. `manifest.load()` of a nonexistent path returns a dict that already contains the stamp at `FORMAT_VERSION`, and `manifest.flush()` adds it to any dict that lacks it, so every manifest the tool writes is stamped. A manifest with no stamp is version 0.

**Legacy manifest:** repos written before per-config manifests have a single `.canvas-manifest.toml`. Migration 0 -> 1 (`repo_format._migrate_0_to_1`) renames it to `.manifest-canvas.toml` when that name is free, and warns and leaves it when both exist. Nothing else renames it: `manifest.migrate_legacy_manifest()` was removed and the callers use `manifest_path_for()`. `ignore.py` still ignores both `.manifest-*.toml` and the legacy name, so no manifest is ever treated as uploadable content.

Manifests are local: they record the Canvas IDs of one Canvas course and must never be committed. `import` writes `.manifest-*.toml` into the repo's default `.gitignore`.

```toml
# .manifest-canvas.toml — local; never commit this file

[_repo_format]
format_version = 1

["pages/syllabus.md"]
canvas_id = 11111
canvas_type = "page"
last_synced = "2025-02-01T10:00:00"

["assignments/week1.md"]
canvas_id = 98765
canvas_type = "assignment"
last_synced = "2025-02-01T10:01:00"

# flags_used records the [course_flags] values in effect at this file's last
# successful sync — every flag the file references directly or via any snippet
# it includes. Omitted entirely for files that reference no flags. See
# "Course flags (conditional content)" below.
["assignments/week1.md".flags_used]
in_person_class = true

# resolved_dates caches the symbolic resolution of this item's due_dates entry
# as of its last successful date application (concrete date / "NONE" / "KEEP";
# all three keys always present). Omitted when no due_dates entry matches. The
# every-run dates pass skips items whose fresh resolution equals this cache.
# See "due_dates resolved-value caching" above.
["assignments/week1.md".resolved_dates]
due_at = "2025-02-01T23:59:00-05:00"
unlock_at = "NONE"
lock_at = "KEEP"

# section_hashes (settings entry only) caches each course_settings.toml
# section's content hash as of its last successful application; only sections
# whose hash changed are re-applied. See "Section-level change detection" above.
["course_settings/course_settings.toml"]
canvas_id = 0
canvas_type = "course_settings"
last_synced = "2025-02-01T10:00:30"

["course_settings/course_settings.toml".section_hashes]
metadata = "9f2b4c1a0d3e5f67"
grading_standards = "e3b0c44298fc1c14"
assignment_groups = "a1b2c3d4e5f60718"
late_policy = "0123456789abcdef"
default_post_policy = "fedcba9876543210"
tab_configuration = "00112233445566aa"
dashboard_image = "bb4455667788ccdd"
front_page = "5566778899aabbcc"

# rubric_hashes (rubrics entry only) caches each [[rubrics]] table's content
# hash, keyed by title, as of its last successful upload; only rubrics whose
# hash changed are re-sent. See "Rubric-level change detection" above.
["course_settings/rubrics.toml"]
canvas_id = 0
canvas_type = "rubrics"
last_synced = "2025-02-01T10:00:35"

["course_settings/rubrics.toml".rubric_hashes]
"Essay Rubric" = "1a2b3c4d5e6f7081"
"Lab Rubric" = "8899aabbccddeeff"

["modules/week-1.md"]
canvas_id = 55555
canvas_type = "module"
last_synced = "2025-02-01T10:02:00"
# canvas_item_ids maps each linked file path to its Canvas module item ID
# (needed to reorder or delete individual items within the module)
canvas_item_ids = {"pages/syllabus.md" = 201, "assignments/week1.md" = 202}
```

Source Markdown files stay clean — no tool-written fields mixed in with author-written frontmatter. On first publish the tool creates the item, records the Canvas ID in the manifest, and writes the updated manifest back to disk. On subsequent runs it looks up the Canvas ID from the manifest and updates the existing item.

**Error-retry semantics:** `last_synced` is only stamped on a fully successful upload — every "Skipping upload due to errors" path returns before `manifest.record()`, so an errored file stays stale and is retried on the next `update`. Partial cases use `record(..., mark_synced=False)`, which records the `canvas_id` (so the next run updates rather than duplicates) but omits `last_synced`, leaving the entry stale for retry: a module some of whose items could not be added (`_sync_module()`), and `course_settings.toml` when any settings section failed (the succeeded sections' hashes *are* recorded, so the retry re-runs only the failed ones). Similarly, an item whose due-date update Canvas rejected keeps its `resolved_dates` cache un-advanced, so the dates pass retries it every run until fixed.

## Snippets (`snippets/` directory)

A `snippets/` directory at the repo root holds reusable Markdown fragments. Content files include a snippet using a **normal Markdown link** whose target path resolves into `snippets/`. The preprocessor detects these links and replaces the entire `[text](path)` token with the raw Markdown content of the snippet file, before Pandoc ever runs. Students see the rendered content inline — not a hyperlink.

Example use case: `snippets/office-hours.md` contains your current office hours. Reference it from a dozen pages; update once, re-sync, and the change propagates everywhere.

**Include syntax — standard Markdown links:**

```markdown
[My Office Hours](../snippets/office-hours.md)
```

Any link whose resolved path falls inside the `snippets/` directory triggers inclusion. The link text is discarded and replaced by the snippet's Markdown content.

A snippet containing a single sentence or phrase pastes in cleanly mid-sentence — Markdown treats a single embedded newline as a space. A snippet containing block-level elements (headings, blank lines between paragraphs, lists, code blocks) will break out of any surrounding sentence, so those should be placed as standalone blocks in the including file. The snippet's content determines where it can sensibly be used.

Markdown editors render the include as a normal clickable link, making it easy to navigate to the snippet source to see what will be inlined.

**Behaviour:**

- Substitution happens before Pandoc, so snippet Markdown (headings, lists, etc.) renders naturally as HTML
- Snippet files contain only Markdown body content — no frontmatter
- Snippets are never uploaded to Canvas and have no manifest entries
- **Snippets can include snippets** (format version 4), in block or inline form. `preprocess_snippets` is recursive: `_expand_text(text, file, chain)` expands the refs in `text` relative to `file`; `_load_snippet` reads a snippet, applies the course flags, and calls `_expand_text` on its content with the snippet as `file` before returning it, and `_replace` then rebases the (fully expanded) content onto the file it is pasted into. Rebasing therefore composes level by level: an inner snippet's links are first rebased onto the outer snippet, and the outer snippet's pasted text (inner links included) is then rebased onto the includer. `MAX_SNIPPET_DEPTH = 10`: a reference that would open an 11th level is left unexpanded and reported (naming the top-level file and the chain), which is what stops a snippet that includes itself; the error goes through `errors`, so the includer is not uploaded. A candidate ref is skipped unless `links.is_relative_path_url` accepts it (no scheme, `#`, `/`, `$`, or newline); block refs have their title and `<>` stripped first. The old one-level "nested include not supported" check is gone; it misreported `https:`, `mailto:` and `#anchor` links as nested includes because it resolved every link in the snippet. The newline rule matters for passive probes that run without flags: an inline snippet whose `#if` lines are not evaluated pastes multi-line text into a link, which must not be read as a path.
- **Links inside a snippet are relative to the snippet file** (format version 4). `_replace` in `preprocess_snippets` rebases the pasted text onto the including file with `links.transform_links(content, snippet_dir, includer_dir, {}, rewrite_inline_snippets=False, on_escape=..., url_map=...)`, applied outside fenced code. The forms, and what is skipped (scheme URLs, `#`/`/` links, `$` links), are the ones `mv` rewrites; the shared function lives in `links.py`. The `url_map` callback keeps a link verbatim when it already names the same file from both folders (an includer at the snippet's depth), so such files see no diff. A link that resolves outside the repo from the snippet's folder calls `on_escape`, which records an error through `warn(msg, errors)`: in `sync` that skips the includer's upload (any error added during expansion does), `--check-all` exits 1, and `publish` stops. The includer folder is `source_file.resolve()` relative to `snippets_dir.parent`; an includer outside the repo gets no rebasing. Inline `$...$` content is never rebased (inline refs inside a snippet are expanded relative to that snippet, see the previous bullet). After rebasing, `link_rewrite` (which resolves against the including file) needs no change, and every consumer of `preprocess_snippets` (`sync` content/probes/targeted BFS, `quiz.py`, `publish` staging and reachability, `local_orphans`, `cp`) sees the same links.
- Links inside a snippet that point to content files (pages, assignments, etc.) are then treated normally by the post-Pandoc link-rewriting step — they will be rewritten to Canvas URLs just like any other link
- **Editing a snippet automatically re-syncs files that include it, on the next full `update`/`publish` run.** See [Snippet dependency staleness](#snippet-dependency-staleness) below for how.

### Frontmatter snippets (`PASTE_SNIPPET_INTO_FRONTMATTER`)

The body-content snippet mechanism above can't reach into a file's YAML frontmatter — `parse_frontmatter()` splits the frontmatter block off and parses it before `preprocess_snippets()` ever sees the body, so a `[text](path)` link living inside the YAML block would just be plain text. `expand_frontmatter_snippets()` (`convert.py`) closes that gap with a separate, special-cased mechanism for **merging shared frontmatter values** (e.g. `points_possible`, `rubric` shared by every "worksheet" assignment) rather than reusing body text.

**Syntax:**

```markdown
---
title: "Worksheet 1"
canvas_type: assignment
---
[PASTE_SNIPPET_INTO_FRONTMATTER](../snippets/worksheet-defaults.md)
[PASTE_SNIPPET_INTO_FRONTMATTER](../snippets/another-snippet.md)

Do the worksheet...
```

The link text must be the literal string `PASTE_SNIPPET_INTO_FRONTMATTER` — this is what makes the reference visually distinct from a normal link, and (unlike a bare YAML key) it's clickable in VS Code, since VS Code's Markdown link provider only recognizes `[text](path)` inside the parsed body, never inside frontmatter (the frontmatter block is consumed as a single opaque token before inline parsing runs).

**Resolution algorithm** (`expand_frontmatter_snippets()`):

1. Scan the body line by line from the top. Blank/whitespace-only lines are skipped without stopping the scan.
2. If the first non-blank line isn't a `PASTE_SNIPPET_INTO_FRONTMATTER` link, the body and frontmatter are returned completely unchanged (no marker mode at all — this is a cheap lookahead so ordinary files pay no cost and are never mutated).
3. Otherwise, keep consuming `PASTE_SNIPPET_INTO_FRONTMATTER` lines (and blank lines between them) until hitting the first line that is neither. That line, and everything after it, becomes the returned body.
4. Each referenced file is loaded relative to the *including* file (same convention as body snippets) and validated to resolve inside `snippets_dir` (same path-escape guard as `preprocess_snippets`).
5. Each referenced file's content is parsed with `yaml.safe_load()` — it must be a YAML mapping, not Markdown prose. An error is reported (and that reference skipped) if the path escapes `snippets/`, the file is missing, the YAML is malformed, or it doesn't parse to a mapping.
6. Matched snippets are merged into a `defaults` dict in order — later references override earlier ones for shared keys.
7. The final frontmatter is `{**defaults, **frontmatter}` — the file's own frontmatter always wins over snippet values, so a single file can override one or two fields from a shared default without losing the rest.

**Call sites:** wired in everywhere frontmatter is parsed for actual content sync — `_sync_content_file()` (pages/assignments/discussions) and the module sync path in `sync.py`, plus `parse_quiz_file()` and `parse_question_file()` in `quiz.py` (so quiz-level settings like `time_limit`, or per-question settings like `question_type`/`points_possible`, can be shared across a question bank too). It always runs *before* `preprocess_snippets()`, since the latter only needs to see the real Markdown body.

`publish.py`'s `stage_content_markdown()` (pages/assignments/discussions in the static site) also calls `expand_frontmatter_snippets()` before `preprocess_snippets()`, for the same reason. Skipping it there was a bug: `preprocess_snippets()`'s block-snippet regex (`[text](path)`) matches the `PASTE_SNIPPET_INTO_FRONTMATTER` marker too, so without the frontmatter pass running first, the marker got treated as an ordinary body snippet include and the *raw YAML* of the referenced snippet was spliced straight into the published page body.

**Differences from centralized `due_dates`:** `due_dates` (in `course_settings/course_settings.toml`) is for fields that are mostly *unique per item* but worth reviewing in one place, matched by title. `PASTE_SNIPPET_INTO_FRONTMATTER` is for fields that should be *identical* across many files — edit the snippet once, and every file that references it picks up the change on its next full `update`/`publish` run (see below).

### Snippet dependency staleness

Editing a snippet file (body or frontmatter form) automatically marks every file that references it as stale, without `--force-uploads` or `touch`. No new manifest bookkeeping is involved — `last_synced` is never rewritten, and snippets still have no manifest entries of their own.

**Mechanism:**

- `find_referenced_snippets(text, source_file, snippets_dir)` (`convert.py`) is a passive discovery pass: it reuses `_INLINE_SNIPPET_RE` and `_SNIPPET_LINK_RE` (the same regexes `preprocess_snippets` uses) to resolve every `$path.md$` / `[text](path)` candidate in `text` to an absolute path, keeping the ones that land inside `snippets_dir` and exist, and recursing into each snippet it finds (refs resolved from that snippet's folder, a visited set stopping cycles), so a page is stale when any snippet at any depth below it changes; `_flags_used_for` and `cp` get nested snippets the same way. Since `PASTE_SNIPPET_INTO_FRONTMATTER` is just `[text](path)` syntax, it's caught automatically — no separate handling needed. Unlike `preprocess_snippets`/`expand_frontmatter_snippets`, it never reports errors; it's just a staleness probe.
- `manifest.needs_sync()` gained an optional `extra_mtime_paths: Callable[[], Iterable[Path]] | None` parameter. It's a zero-arg *callable*, not a plain list, so the (file-reading) work of resolving referenced snippets is only done when the file's own mtime didn't already settle the staleness question — most files that need syncing for the usual reason never pay the extra cost.
- `sync.py`'s `_file_referenced_snippets(path, snippets_dir)` reads a file, parses its frontmatter (swallowing `yaml.YAMLError` — if the file does need a real sync, its normal processing path reports the error properly), and delegates to `find_referenced_snippets()` on the body.
- Every staleness check that gates a real sync passes this in: `_sync_content_file()` and `_sync_module()` call `manifest_lib.needs_sync(..., extra_mtime_paths=lambda: _file_referenced_snippets(...))`; `_quiz_needs_sync()` folds snippets referenced by the quiz file *and* every question file into its existing mtime comparison; `_sync_question_banks()` does the same via `_question_files_referenced_snippets()`, unioning snippet references across all question files in a bank.

**Scope:** covers pages, assignments, discussions, modules, quiz-level files, question files, and question banks. **Targeted syncs (`-s`/`-t`) are intentionally excluded** — they only ever call the per-file sync functions for files already in their explicit/BFS-derived target set, so this logic never causes a narrow `-s` run to reach outside the files you named. If a snippet shared by two files changes and you `-s` one of them, only that one re-syncs; the other picks up the change on the next full `update`/`publish`.

**Out of scope:** snippet deletion or rename gets no special handling — a file referencing a now-missing snippet still surfaces the existing "snippet not found" error the next time it's actually processed. `_sync_question_banks()` also still doesn't compare individual question file mtimes against the bank's own `last_synced` for non-snippet edits (a pre-existing gap, unrelated to snippets — see TODO.md).

**Not supported:** nested includes (a frontmatter snippet referencing another snippet) — snippet files are parsed as flat YAML, so there is no recursive expansion to support in the first place.

## Course flags (conditional content)

Boolean flags in the optional `[course_flags]` table of `course_settings.toml` gate regions of Markdown body content via C-preprocessor-style HTML-comment directives (`<!-- #if flag -->` / `#elif` / `#else` / `#endif`, each alone on its own line). Implemented in `conditionals.py`; the original design rationale (including settled decisions and future work) is in `DESIGN-course-flags.md`.

**Per-config overrides (`[course_flags]` in `canvas.toml`):** a `canvas.toml` may carry its own `[course_flags]` table. `config.load()` validates it with `validate_course_flags(table, source)` — the same function `load_course_flags()` uses for `course_settings.toml`, so both files enforce the same name/boolean rules and the error names the offending file — and stores it on `Config.course_flags`. `sync.load_course_flags(repo_path, settings=None, config=None)` then starts from the `course_settings.toml` table and `dict.update()`s the config's on top: same-named flag → the `canvas.toml` value wins, flags in only one file are kept (union). This is what makes `--config` a per-section switch: flags reach `#if`, `published_if` and due_dates `only_if`, so one repo can drive sections that differ in text, publish state and dates while sharing the rest of `course_settings.toml` (course name, grading standards, assignment groups, late policy, tabs — none of which can vary per config). Because each config also has its own manifest, the `flags_used` values recorded per file are per section and flipping between sections never forces a re-sync of the other one. When the config contributes any flags, `load_course_flags()` prints a `Flags:` line naming the file and, if any override changed a value, a second line listing the shadowed names. `publish` and `list-titles` take `--config` for the flags alone: `cli._flags_config()` loads it with `require_token=False, require_course=False` (an explicit `--config` must exist; the default `<repo>/course_settings/canvas.toml` is optional), and `run_publish`/`stage` thread it into `load_course_flags`. `mv` and `find-local-orphans` need no flags.

**Module surface (`conditionals.py`):**

- `apply_conditionals(text, flags, source_desc, errors=None, *, quiet=False) -> str | None` — evaluates directives, returns the filtered text, or `None` if any directive error occurred (caller must skip the file). Errors are reported through the usual `warn(msg, errors)` convention; `quiet=True` suppresses reporting for passive probes (used by `publish.collect_reachable`, which must not double-report errors that staging will report anyway). Directive lines and false-branch lines are removed **entirely** (no blank line left behind — that's what keeps a conditional list item inside one tight list).
- `find_referenced_flags(text) -> set[str]` — lexical probe: every flag name in any directive, any branch, taken or not. Never errors (malformed directives contribute nothing); the flag-usage analogue of `find_referenced_snippets()`.

**Parsing rules:** only a line that is *nothing but* an HTML comment is considered, and only when its content starts with `#` followed by one of the four keywords or the five reserved misspellings (`#ifdef`, `#ifndef`, `#elseif`, `#elsif`, `#fi` — each a hard error with a "did you mean" hint). Everything else (`<!-- #region -->`, `<!-- published:false -->`, ordinary comments, directive-lookalikes not alone on their line) passes through untouched. Conditions are one flag name, optionally preceded by `not`; an undefined flag is a hard error in **any** directive, taken branch or not (the point of hard errors is catching typos *before* the flag flip that would expose them). Nesting is a plain stack; evaluation is standard preprocessor logic (`parent_active` captured at `#if`, `any_taken` across `#elif` arms, at most one `#else`, last).

**Fence-awareness:** processing iterates `split_fenced_segments()` output. Plain segments are scanned line by line; fenced segments are never scanned and are kept/dropped wholesale by the conditional state in force when the fence opened. This also covers raw-attribute blocks such as ```` ```{=html} ```` (a directive inside one is literal; the block as a whole follows the enclosing conditional).

**Pipeline placement:** the pass runs on each body immediately after `parse_frontmatter`/`expand_frontmatter_snippets` and **before** `preprocess_snippets` — so a snippet ref inside a false branch is removed before snippet expansion (a broken snippet path in a dormant branch reports nothing), and before all structural line parsers (module items, quiz question lists, question sections), which is what makes conditional module items / quiz questions work with no parser changes. `preprocess_snippets()` additionally takes a `flags` param and applies the pass to each snippet's content at insertion time (both block and `$inline.md$` forms; a snippet whose directives error contributes an error and the ref is left unexpanded). Consequence: directives must be balanced within each file and within each snippet file independently. Frontmatter is never processed (YAML; no use case). Loaded once per run by `load_course_flags(repo_path, settings=None)` in `sync.py` (mirrors `load_due_dates`; invalid flag name or non-boolean value raises `ValueError` → `die()`), threaded through `SyncContext.flags`.

**Call sites:** `_sync_content_file()` (pages/assignments/discussions/announcements), `_sync_module()`, `sync_syllabus()`, `parse_quiz_file()`/`parse_question_file()` (via `flags`/`source_desc`/`errors` params, covering quizzes and question banks), and in `publish.py`: `stage_content_markdown()`, `render_module_overview()`, `render_quiz_study_guide()`, `collect_reachable()`, `_render_index()`. `publish` uses the **same** flag values as `update` (no per-target overrides in v1). Three passive probes intentionally do *not* apply conditionals and work on the conservative superset instead: the `_phase_modules` pre-scan, `_get_file_refs()` (targeted-sync BFS), and `local_orphans.collect_local_refs()` (`find-local-orphans`) — at worst the first two re-sync/visit a file that active content no longer references, and the third counts a link in a false branch as a real reference so flipping a flag off never makes content look deletable. The real per-file pass reports any errors exactly once.

**Error handling:** every directive problem (undefined flag, misspelled keyword, missing/unexpected/malformed argument, unbalanced structure — see the README's syntax guide or `DESIGN-course-flags.md` §7 for the full table) is a per-file hard error: reported via `warn()` with the repo-relative path and the offending line, the file is skipped (no upload / not staged), the run continues, and the end-of-run summary fails the run. In `publish`, staging errors are collected into the `stage()` info dict and `run_publish()` raises `ValueError` (→ `die()`) before building the site. Fatal whole-run errors (via `ValueError` → `die()`): non-boolean value or invalid name in `[course_flags]`.

**Manifest caching / selective re-sync:** each entry for a file that references flags gains a `flags_used` sub-table recording the flag **values** in effect at its last successful sync — per-file values, not a global snapshot, so a file that errored/was skipped during the run that flipped a flag stays correctly stale. Computed by `_flags_used_for()` as `find_referenced_flags(body) ∪ find_referenced_flags(each referenced snippet's content)` (snippets enumerated with `find_referenced_snippets()`, same as the snippet-mtime path). `manifest.needs_sync()` gained `current_flags`/`verbose` params: after the mtime checks, an entry is stale when any recorded flag is missing from `current_flags` or differs in value (`manifest.flag_change()` finds the first difference; in verbose mode the reason is printed, e.g. ``re-syncing: flag 'in_person_class' changed true → false``). A flag *deleted* from the TOML makes referencing files stale → they re-sync → they hit the undefined-flag hard error (desired loud failure). Snippet-borne flags need no extra machinery: adding a directive to a snippet bumps the snippet's mtime, which the existing `extra_mtime_paths` check catches, and the re-sync refreshes `flags_used`. `_quiz_needs_sync()` folds the flag check in the same way it folds question-file mtimes, and the quiz entry's `flags_used` unions the quiz `.md` and **all** question files (globbed, not just currently-listed ones — a question excluded by a false flag must still make the quiz stale when the flag flips); quiz + questions sync as one unit. Question banks apply conditionals to question content but get no `flags_used` until their pre-existing staleness gap is fixed (see TODO.md). `mv` needs no changes — `flags_used` lives inside the per-file entry, which `mv` re-keys wholesale (covered by a test).

**Unused-flag warning:** after the content pass, `check_course_flags_coverage()` (mirroring `_check_due_dates_coverage()`) scans every `.md` in the repo (including snippets — a flag referenced only inside a snippet counts as used), unions `find_referenced_flags()`, and warns once per defined-but-unreferenced flag. Warning only, never an error (defining a flag before writing the content that uses it is legitimate). Runs in `update` (full and targeted) and `publish`.

**Subcommand matrix:** `update` — full feature; `publish` — same pass, same flag values, same hard errors (file skipped from the site) and unused-flag warning, no manifest/staleness work; `import` — no change (the importer never generates directives); `mv` — no change (entry re-keyed wholesale); `find-canvas-orphans`/`prune` — no change (Canvas-side / manifest/file-presence based); `find-local-orphans` — scans content but deliberately does not apply directives (conservative superset, above).

**Future work** (spec'd in `DESIGN-course-flags.md` §12, tracked in TODO.md): whole-resource exclusion via delete/prune (as opposed to the unpublish-based `published_if` below), `--flag` CLI overrides, richer conditions (`and`/`or`, non-boolean values), and a `list-flags` report.

### `published_if` (frontmatter) and due_dates `only_if`

Structured, per-key evaluation of a flag condition — deliberately narrower than the general `#if` pass above: it computes exactly one value (`published`, or whether a `due_dates` entry applies) instead of filtering arbitrary text, so it sidesteps the call-site-sprawl and per-variant-YAML-breakage risks that ruled out a general `#if` in frontmatter/TOML (see TODO.md).

**`resolve_published_if(frontmatter, flags, source_desc, errors=None, *, quiet=False, forbid=False, forbid_reason="") -> bool | None`** (`conditionals.py`) — resolves the effective `published` boolean for one content file. Absent `published_if`, it's just `frontmatter.get("published", False)`. With `published_if: flag_name` (or `not flag_name`, same grammar as `#if`, via the shared `parse_condition()`/`_parse_condition()` helper), it computes `published` from the flag instead. Returns `None` on any problem (caller skips the file): `published_if` combined with a literal `published` key (ambiguous — hard error), a malformed/missing condition, an undefined flag, or `forbid=True` (set for announcements — Canvas can never un-post one, so the whole feature is disallowed there; message names `forbid_reason`). `quiet=True` suppresses reporting for passive probes, same convention as `apply_conditionals`. `find_referenced_flags_in_frontmatter(frontmatter) -> set[str]` is the frontmatter analogue of `find_referenced_flags()` — the `published_if` flag name if well-formed, else empty; never errors.

**Call sites (loud, primary):** `_sync_content_file()` computes `canvas_type` up front (pure function of `local_key`) so the `forbid=(canvas_type == "announcement")` check runs right after frontmatter/frontmatter-snippet expansion, before body conditionals or HTML conversion — fail fast, and the existing "skip unpublished announcement" block downstream now reads the resolved `published` instead of `frontmatter.get("published", ...)` directly. `_sync_quiz()` resolves it the same way from `parse_quiz_file()`'s (snippet-expanded) frontmatter. Both skip the upload (`Skipping upload due to errors: …`) when resolution returns `None`.

**Call sites (quiet, passive probes):** `_content_default_published()` (module-item default when there's no explicit `{published:...}` override) and `publish.py`'s `_published_title()`/`_item_published()` resolve quietly (`quiet=True`) and default to *not published* on any problem — the referenced file reports the error loudly when it syncs/discovers on its own; these probes must not double-report. `flags` is threaded through the publish call graph that didn't need it before: `_discover_type()`, `_find_syllabus()`, `build_nav()`, `_item_published()`, `_content_default_published()`.

**`flags_used`:** `_flags_used_for()` now expands frontmatter snippets (`expand_frontmatter_snippets()`) before scanning, and unions `find_referenced_flags_in_frontmatter(fm)` with the existing body/snippet scan — so a `published_if` flag (including one delivered via `PASTE_SNIPPET_INTO_FRONTMATTER`) is recorded and a flip re-syncs (and thus unpublishes/republishes) exactly the right files, via the same `manifest.flag_change()` machinery `#if` already uses. `check_course_flags_coverage()` also unions `find_referenced_flags_in_frontmatter()` so a flag used only via `published_if` doesn't spuriously warn as unused.

**`filter_due_dates_by_flags(due_dates, flags) -> list[dict]`** (`sync.py`) — drops `due_dates` entries whose `only_if` (or `not only_if`) condition is unmet, called immediately after `load_due_dates()` in `run_sync`/`run_targeted_sync`/`list-titles` (flags loaded first so they're available). No TOML preprocessing: entries without `only_if` are always kept, so `course_settings.toml` stays valid TOML in every flag configuration. An undefined flag or malformed condition is a whole-run config error — raises `ValueError` → `die()`, same convention as `load_course_flags()`. Filtered-out entries are simply absent from `ctx.due_dates`, so `_apply_due_dates_only()` never sees them (no API call, no cache write) and needs no changes itself.

**Due-dates coverage interaction:** `_check_due_dates_coverage()` gained a `flags` param; for each gradeable content file with a `published_if` key it quietly resolves it, and an item resolving to *not published* (this offering doesn't include it) is treated as expected-to-have-no-`due_dates`-entry — excluded from the "no due_dates entry" warning list. This is orthogonal to `only_if`: an entry dropped by `only_if` still leaves its content file subject to the normal "no entry" warning unless that file is itself `published_if`-excluded.

**Why not a general `#if` in frontmatter/TOML instead:** considered and rejected (2026-07-06) in favor of the narrower structured-key approach above. A full "process `#if` everywhere" design would need conditional YAML to stay valid under *every* flag combination (nothing checks unselected combinations — breakage surfaces a quarter later), would touch dozens of `parse_frontmatter` call sites beyond the handful `apply_conditionals` hits today (title-collision check, due-dates coverage, `list-titles`, `mv`, …) risking silent `update`/`publish` drift if one site is missed, and `<!-- #if flag -->` is invalid YAML/TOML syntax (unlike in a Markdown body), so VSCode would flag conditional frontmatter as broken. `published_if`/`only_if` sidestep all three by computing exactly one value per key, post-parse, from the same settings dict already loaded — no flags-file migration, no per-site drift risk, no invalid-syntax problem.
