# Proposal: repo format version and `upgrade`

## Why

The files in a course repo change format as the tool changes. For example,
`import` once nested `tab_configuration` under another section, and the
manifest was once a single `.canvas-manifest.toml`. A repo records no version
for its files, so an older repo can be misread without any error. Today the
tool handles two such cases with one-off code: a warning for the misplaced
`tab_configuration`, and an automatic manifest rename. A recorded format
version lets the tool detect an out-of-date repo, stop, and upgrade it with a
dedicated command, so that a tool update in the middle of a term cannot
silently break a course.

## What Changes

- `course_settings.toml` gains three top-level keys, written first in the
  file: `format_version` (an integer), `created_by` (the tool version that ran
  `import`), and `upgraded_by` (an array with one entry per upgrade run).
  A repo without `format_version` is format version 0.
- Every `.manifest-*.toml` records the format version it was written in. Manifests
  are local and never committed, so they can lag behind the committed
  `course_settings.toml` on a machine that has not run `upgrade`.
- `import` writes `format_version` (the current version) and `created_by`.
- New `upgrade` subcommand: runs each migration from the repo's version to
  the tool's version in order, edits `course_settings.toml` in place with
  `tomlkit` (comments and layout preserved), updates every manifest, prints
  each change, and appends an `upgraded_by` entry. It runs whether or not the
  git working tree is clean.
- Migration 0 -> 1: renames a legacy `.canvas-manifest.toml` to
  `.manifest-canvas.toml` and stamps every manifest.
- **BREAKING**: every command that reads a course repo (`update`, `mv`,
  `publish`, `prune`, `clean-manifest`, `find-local-orphans`,
  `find-canvas-orphans`, `list-titles`) refuses to run when the repo or any
  of its manifests is older than the tool (telling the user to run `upgrade`)
  or newer than the tool (telling the user to update the tool). Every repo
  that exists today is version 0, so each one must be upgraded once. The
  check is a core library function: it runs inside the library operations
  behind these commands (`run_sync`, `run_prune`, `run_mv`, `run_publish`,
  ...), not only in the CLI, so no code path can read a repo without it.
- `upgrade` checks and corrects `tab_configuration` placement, once. The
  tool cannot use `tab_configuration` when it is nested under a section, so
  `upgrade` moves a nested key to the top level (comments and layout
  preserved) and prints a notice; a key present in both places is an error.
  Other commands do not check placement: a matching format version means the
  files were set up correctly. This removes the current warning in `update`,
  so a `tab_configuration` nested by hand after upgrading is silently not
  applied.
- The automatic legacy-manifest rename (`migrate_legacy_manifest()`) is
  removed; migration 0 -> 1 replaces it.
- `format_version`, `created_by` and `upgraded_by` are excluded from the
  `metadata` section hash, so upgrading does not trigger a course-metadata
  API call. They are already never uploaded, because the course-metadata
  upload only sends keys it lists explicitly.
- The package version comes from git through `hatch-vcs` instead of the
  static `version = "0.2.0"`, with a fallback version for builds that have no
  git metadata.
- CLAUDE.md gains a rule: any change that makes the tool read an existing
  file differently must increase the format version and add a migration.
- Documentation stops telling users to commit manifest files. Manifests are
  local and must never be committed (`import`'s default `.gitignore` already
  excludes them).

## Capabilities

### New Capabilities

- `repo-format-version`: how a course repo records its format version and
  provenance, how commands check it, and how `upgrade` migrates a repo and
  its manifests.

### Modified Capabilities

None. The project has no specs yet (`openspec/specs/` is empty).

## Existing mechanisms this builds on

- `manifest.migrate_legacy_manifest()` (`manifest.py:46`) is an ad hoc
  migration that detects a pre-per-config repo by file name and renames the
  manifest on every run of `update`, `prune`, `clean-manifest` and the course
  guard. It moves into migration 0 -> 1.
- `sync.py` warns when `tab_configuration` is nested under a section
  (`_find_nested_key`, used at `sync.py:1420`) but does not fix it, and the
  tabs are not applied. The new placement check replaces that warning with a
  correction.
- The manifest's reserved `_canvas_course` entry (`manifest.COURSE_KEY`) is
  the precedent for a non-path entry in the manifest; the manifest's format
  stamp follows the same pattern.
- The `metadata` section hash (`compute_settings_section_hashes`,
  `_NON_METADATA_SETTINGS_KEYS` in `sync.py`) already excludes keys that are
  not course metadata; the new keys are added to that list.
- No existing command or option records a version. `pyproject.toml` declares
  `version = "0.2.0"`, but nothing in `src/` reads it and it has not been
  bumped.

## Related planning items

- NEW_FEATURES.md item 1 ("Record the tool version that generated or last
  touched the files") is implemented by this change and is removed from
  NEW_FEATURES.md.
- NEW_FEATURES.md item 2 (replace `tomli_w` with `tomlkit`) is started: this
  change adds `tomlkit` and uses it only for `upgrade`'s in-place edits.
  Replacing `tomli_w` in `import` and elsewhere stays a separate, later change.
- No TODO.md item covers this.

## Core subcommands

- `import`: writes `format_version` and `created_by`.
- `update`, `mv`, `publish`: check the format version before doing anything.
  None of them changes the version.
- `upgrade` is new. `setup`, `install-completion`, `create-tool-aliases` and
  `emit-workflow` do not read course files, so they do not check the version.

## Impact

- Code: a new module `repo_format.py` (version check, `tab_configuration`
  placement check, migrations, `upgrade`); the library entry points that call
  the check (`sync.run_sync`, `sync.run_targeted_sync`, `sync.run_prune`,
  `course_guard.check_course`, `mv.run_mv`, `publish.run_publish`,
  `local_orphans.find_local_orphans`, `clean_manifest`, and a new library
  function for `list-titles`); `cli.py` (new `upgrade` command, `die()` for the
  format error, `find-canvas-orphans` calling the check directly because its
  library function never reads the repo); `imscc_import.py` (writes the new
  keys); `manifest.py` (format stamp, reserved-key handling, removal of
  `migrate_legacy_manifest`); `sync.py` (hash exclusion, removal of the
  legacy-manifest calls and of the nested-`tab_configuration` warning).
- Tests: every test that runs a library entry point on a repo without a
  current `course_settings.toml` must give that repo one. Many tests change.
- Dependencies: adds `tomlkit` (runtime) and `hatch-vcs` (build).
- Build: `pyproject.toml` switches to a dynamic version.
- Existing repos: each must run `upgrade` once, on every machine that holds
  a manifest for it.
- Docs: README.md, ARCHITECTURE.md, TESTING.md, CLAUDE.md, NEW_FEATURES.md.
