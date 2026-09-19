# Design: repo format version and `upgrade`

## Context

See proposal.md for motivation and specs/repo-format-version/spec.md for the
required behavior. Current state that shapes the approach:

- Each repo-reading command in `cli.py` hands off to a library entry point:
  `update` -> `sync.run_sync` / `sync.run_targeted_sync`; `prune` ->
  `sync.run_prune`; `mv` -> `mv.run_mv` (which finds the repo root itself
  from SRC, then DEST, with `find_repo_root()`, `mv.py:723`); `publish` ->
  `publish.run_publish`; `find-local-orphans` ->
  `local_orphans.find_local_orphans`; `clean-manifest` ->
  `clean_manifest.run_plan`, or, with `--no-canvas-check`, an inline
  `manifest_lib.load()` in `cli.py`; `find-canvas-orphans` ->
  `orphans.find_orphans(course)`, which takes no repo at all; `list-titles`
  has its logic inline in `cli.py`.
- Before `run_sync` and `run_prune`, the CLI calls `_guard_course()` ->
  `course_guard.check_course(manifest_path, ...)`, which loads the manifest
  and can write it (recording or switching the course). That happens after
  `get_course()` has read the course from Canvas.
- `course_settings.toml` is written by `import` with `tomli_w` plus
  hand-inserted comments (`imscc_import._write_course_settings_toml`), then
  edited by hand. It is read everywhere with `tomllib`.
- `update` currently detects a nested `tab_configuration`
  (`sync._find_nested_key`, `sync.py:1420`), prints a warning, and skips the
  tabs.
- Manifests are TOML dicts keyed by repo path, loaded through
  `manifest.load()` (seven call sites) and written through `manifest.flush()`.
  One reserved non-path key exists, `_canvas_course`; code that walks entries
  skips it with `manifest.is_course_key()` (six call sites).
- The test fixture course repo (`tests/fixtures/`) has no
  `course_settings.toml`. Most tests call the library entry points directly,
  on the fixture repo or on small repos built in `tmp_path`.
- This change makes no new Canvas API calls and changes no Canvas-facing
  behavior, so no Canvas API behavior needs verifying. The one Canvas-related
  fact it relies on, that `update_course_metadata` makes no API call when
  `course_settings.toml` has no metadata keys, is verified in the code
  (`canvas_api.py`: `if not params: return []`).

## Goals / Non-Goals

**Goals:**
- One place that defines the current format version and the ordered list of
  migrations, so adding a migration is a local change.
- The version check is part of the library: every library entry point that
  reads a repo runs it before reading content files, writing any file, or
  changing anything on Canvas.
- `upgrade` puts `tab_configuration` where the tool can read it.
- `course_settings.toml` edits keep comments and layout.

**Non-Goals:**
- Replacing `tomli_w` in `import` or anywhere else (NEW_FEATURES.md item 2).
  `import` keeps `tomli_w` and emits the version keys as its first lines.
- Adding `.canvasignore` / `.gitignore` entries that newer imports write.
  Those are not breaking changes, so they are not migrations.
- Checking the version inside low-level helpers (`publish.stage`,
  `manifest.load`, `config.load`, ...). The check sits at each command's
  library entry point.
- Downgrading a repo.
- Running the check before `get_course()` reads the course name from Canvas.
  That read changes nothing; the check still runs before any write.

## Decisions

### 1. A new module, `repo_format.py`

It holds:
- `FORMAT_VERSION = 1`
- `RepoFormatError(Exception)` with a user-facing message
- `tool_version()`: the package version, or `"unknown"`
- `read_repo_version(repo)` and `read_manifest_versions(repo)`
- `check_repo_format(repo) -> None`: the core check
  (decision 2)
- `fix_tab_configuration(doc) -> str | None`: the placement check on a
  `tomlkit` document (decision 4)
- the migration registry, an ordered mapping from starting version to a
  migration function, and `run_upgrade(repo, noop)` (decision 6)

Alternative: put this in `config.py`, which already knows the
`course_settings/` layout. Rejected because migrations will grow over time and
would swamp the config module; `repo_format.py` imports `find_repo_root` from
`config.py` instead.

### 2. The check is a library function called by each entry point

`check_repo_format(repo)` reads the repo version and every manifest's
version and raises `RepoFormatError` if any differs from `FORMAT_VERSION`
(older: "run `markdown-to-canvas upgrade`"; newer: "update
markdown-to-canvas"; both versions stated; an out-of-date manifest named). It
edits nothing and does not look at `tab_configuration`.

It is called first thing in each entry point:

| Command | Call site |
| --- | --- |
| `update` | `sync.run_sync`, `sync.run_targeted_sync`  |
| `update`, `prune` (course guard) | `course_guard.check_course`, repo = `manifest_path.parent`  |
| `prune` | `sync.run_prune`  |
| `mv` | `mv.run_mv`, right after the repo root is found  |
| `publish` | `publish.run_publish`  |
| `find-local-orphans` | `local_orphans.find_local_orphans`  |
| `clean-manifest` | `clean_manifest.run_plan`, and a new `clean_manifest.load_manifest(repo, config)` that replaces the inline load in `cli.py`'s `--no-canvas-check` branch  |
| `list-titles` | a new library function (for example `sync.collect_title_items(repo, config)`) that takes over the item-collection loop now inline in `cli.py`  |
| `find-canvas-orphans` | `cli.py` calls `repo_format.check_repo_format(repo)` directly, since `orphans.find_orphans(course)` never receives the repo  |

Putting the check in `course_guard.check_course` as well as `run_sync` and
`run_prune` matters: the CLI runs the guard first, and the guard can write
the manifest, so without its own check a version-0 manifest could be written
before `run_sync` refused. When the guard and then `run_sync` both check, the
second check costs a few file reads.

`cli.py` turns `RepoFormatError` into `die()` with its message:
- Add an `except RepoFormatError` branch to `_handle_cli_errors`, which
  `update`, `prune`, `clean-manifest`, `find-canvas-orphans` and
  `find-local-orphans` use. `RepoFormatError` subclasses `Exception`, not
  `ValueError`; otherwise the decorator's existing `ValueError` branch would
  prefix the message with "KeyError or ValueError:".
- `mv` and `publish` already catch `Exception` and call `die(str(e))`, so
  they need no change.
- `list-titles` has neither; add an explicit `except RepoFormatError`.

Import order: `manifest.py` needs `FORMAT_VERSION` to stamp new manifests,
and `repo_format.py` needs `manifest` (for `MANIFEST_GLOB` and the reserved
key name). To avoid a circular import, `repo_format.py` imports `manifest`,
and `manifest.py` does not import `repo_format` at module level: either
define `FORMAT_VERSION` in `manifest.py` and re-export it from
`repo_format.py`, or import it inside `manifest.load()`.

Alternative: check only in the CLI layer. Rejected by the user: format
checking is core library behavior, and a library-only caller must not be able
to read a repo in the wrong format.

### 3. Manifest stamp is a reserved entry

Each manifest gets a reserved top-level entry
`_repo_format = { format_version = N }`, alongside `_canvas_course`.
`manifest.load()` of a path that does not exist returns a dict that already
contains the stamp at `FORMAT_VERSION`, so every newly created manifest is
stamped on its first `flush()`. An existing manifest is loaded as-is; the
format check has already confirmed its stamp is current.

`is_course_key()` is generalized to `is_reserved_key()` covering both
reserved keys, and every place that iterates manifest entries (the six
`is_course_key` callers, `has_content_entries`, `mv`'s key rewriting,
`clean-manifest`, `prune`, orphan detection) is audited to skip it.

Alternatives: a comment line at the top of the manifest (lost on every
`tomli_w` rewrite); a separate `.manifest-*.version` file (doubles the files
`mv` and `prune` must track). The reserved entry reuses an existing pattern.

Why manifests need their own stamp: manifests are never committed, so on a
second machine the committed `course_settings.toml` can say version N while
that machine's manifest is still in an older format. Checking only
`course_settings.toml` would let that manifest be misread.

### 4. `tab_configuration` placement fix (upgrade only)

`fix_tab_configuration(doc)` walks every table and every element of every
array of tables in the `tomlkit` document looking for a `tab_configuration`
key (the same search `sync._find_nested_key` does today on the `tomllib`
dict).
- None nested: return `None`; the file is not touched.
- Nested, none at top level: remove it from the nested table, insert it as a
  top-level key before the first table, and return a notice naming the old
  location (for example `default_post_policy.tab_configuration`).
- Nested and at top level: raise `RepoFormatError` naming both.

Only `upgrade` calls this function, after its migrations. The check runs
once: after that the format version says the files were set up correctly.
The warning block in `sync.py` (around line 1420) is removed.

Why fix instead of warn: the tool cannot apply `tab_configuration` when it is
nested; a warning leaves the course's navigation silently unmanaged. The
cost of not checking on every command is that a key nested by hand after
upgrading is silently not applied again.

### 5. `course_settings.toml` edits use `tomlkit`

All edits to an existing `course_settings.toml` (placement fix, version
keys) parse the file with `tomlkit`, edit the document, and write it back. A
spike on an imported fixture repo confirmed a byte-identical round trip
(including `import`'s hand-inserted comments) and that
`doc.body.insert(0, ...)` places new keys above everything else, where
`tomllib` reads them back as top-level keys.

Setting `format_version`: replace its value if present, else insert it at
position 0. `upgraded_by` is inserted after `format_version`/`created_by` if
absent, and appended to otherwise. A missing `course_settings.toml` is
created by `upgrade` containing only the version keys.

Alternative: targeted line edits. Adequate for the version keys, but moving
a nested `tab_configuration` is a structural edit that `tomlkit` handles
directly.

### 6. Migration mechanics

`run_upgrade` computes the starting version as the minimum of the repo's
version and every manifest's version, and refuses if either is above
`FORMAT_VERSION`. For each step `v -> v+1`:

1. Run the migration function, which edits the in-memory `tomlkit` document
   and manifest dicts and returns a list of human-readable change lines.
   A condition it cannot resolve raises `RepoFormatError`.
2. Print the change lines.
3. Unless `--noop`: write the manifests (with `_repo_format` set to `v+1`),
   then write `course_settings.toml` with `format_version = v+1`.

Writing `format_version` last in each step means a failure leaves the repo
at the last completed version, and re-running `upgrade` resumes from there.
Manifests already past a step are skipped by that step, so a repo whose
`course_settings.toml` is current but whose local manifest is not only
migrates the manifest.

After the migrations, `run_upgrade` runs `fix_tab_configuration` (reporting
only, with `--noop`). If `format_version` in `course_settings.toml` changed
during the run, it appends one `upgraded_by` entry
(`"<tool_version()> on <YYYY-MM-DD>: <start> -> <end>"`). If nothing changed
at all, it prints that the repo is already current.

### 7. Migration 0 -> 1

- Legacy manifest: if `.canvas-manifest.toml` exists and
  `.manifest-canvas.toml` does not, rename it (the rule
  `migrate_legacy_manifest()` applies today). If both exist, print a warning
  that the legacy file is unused.
- Stamp every `.manifest-*.toml` with version 1. No manifest content changes
  in this step.

A nested `tab_configuration` in a version-0 repo is fixed by the placement
check `run_upgrade` runs after the migrations (decision 6).

After this, `migrate_legacy_manifest()` is deleted and its callers use
`manifest_path_for()`. `mv` stops including the legacy manifest in the files
it rewrites (`mv.py:632`).

### 8. Tool version string

`tool_version()` returns `importlib.metadata.version("markdown-to-canvas")`,
or `"unknown"` on `PackageNotFoundError`. `pyproject.toml` switches to
`dynamic = ["version"]` with `[tool.hatch.version] source = "vcs"` and
`fallback-version = "0.0.0+unknown"`, and `hatch-vcs` is added to the build
requirements. Verified in a scratch package: both `uv tool install git+file://`
and `uvx --from git+file://` produce `0.1.devN+g<hash>` with no tags and
`0.2.1.devN+g<hash>` after a `v0.2.0` tag; installing `pypa/hatch` (which uses
the same plugin) from `git+https://github.com/...` produced a tag-derived
version, so GitHub installs see the history and tags as well.

### 9. Hash exclusion

`format_version`, `created_by` and `upgraded_by` are added to
`_NON_METADATA_SETTINGS_KEYS` in `sync.py`. They are already never uploaded:
`update_course_metadata` sends only keys listed in `_COURSE_METADATA_KEYS`.

### 10. Tests

Every test that calls a checked entry point needs a repo at the current
format version. Add a helper in `tests/conftest.py`, for example
`make_current(repo: Path)`, that creates `course_settings/course_settings.toml`
containing `format_version = FORMAT_VERSION`, or prepends the key to an
existing file. Use it in tests that build repos in `tmp_path`.

For the shared fixture repo, add `tests/fixtures/course_settings/course_settings.toml`
containing only `format_version = 1`. Expected side effects, to confirm by
running the suite: the settings phase now runs on the fixture and records a
`course_settings/course_settings.toml` manifest entry, but makes no Canvas
call, since there are no metadata keys and every other section is absent.
Tests that assert exact manifest contents or exact call lists need updating
for that entry and for the `_repo_format` entry (decision 3).

### 11. CLAUDE.md rule

Add a section stating: any change that makes the tool read an existing repo
file (`course_settings/` files, content frontmatter, module or quiz files,
manifests) differently, or that makes an older tool misread a file the new
tool writes, must increase `repo_format.FORMAT_VERSION` by one and add a
migration with tests. Additive changes that older files already satisfy
(a new optional key) do not need a bump.

## Risks / Trade-offs

- [Every existing repo stops working until upgraded] -> The error message
  names the exact command. `upgrade` is quick and `--noop` shows what it
  will do first.
- [A second machine's uncommitted manifest is still old after the repo is
  upgraded elsewhere] -> The per-manifest stamp makes commands refuse on that
  machine until `upgrade` runs there; `upgrade` then migrates only the
  manifest.
- [A `tab_configuration` nested by hand after upgrading is silently not
  applied, since the old warning is removed and no command checks placement]
  -> Accepted by the user: a current version means the files were set up
  correctly. Running `upgrade` again repairs it.
- [A new entry point forgets to call the check] -> The test in task 5.5 runs
  every checked entry point on a version-0 repo and asserts each raises.
- [A breaking format change lands without a version bump] -> The CLAUDE.md
  rule. Nothing enforces it mechanically.
- [`tomlkit` mishandles an unusual hand-edited file] -> Tests cover the
  imported layout, a hand-written file with comments, and the
  `tab_configuration` variants. `--noop` and `git diff` let the user check
  the result.
- [Editable dev installs report a stale version] -> Only affects the
  informational `created_by` / `upgraded_by` strings.
- [Large test churn] -> Accepted by the user. The `make_current` helper and
  the fixture file keep each fix small.

## Migration Plan

1. Tag the current commit `v0.2.0` so hatch-vcs produces readable versions
   (done by the user, who handles all tags and pushes; without a tag the
   version is `0.1.devN+g<hash>`, which still works).
2. Install the new tool version.
3. In each course repo, on each machine that holds a manifest for it, run
   `markdown-to-canvas upgrade`, review with `git diff`, and commit
   `course_settings.toml`.

Rollback: an older tool ignores the new keys in `course_settings.toml`, but
its manifest walkers do not know to skip `_repo_format`. Rolling back means
deleting the `_repo_format` entry from each manifest. This caveat is accepted
rather than engineered around: the tool has one user, and a rollback is
unlikely.
