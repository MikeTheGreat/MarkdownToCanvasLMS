# Proposal

## Why

There is no way to see what `update` would do to the real course before running
it. `update --check-all` runs the whole pipeline without contacting Canvas, but
it simulates a first sync to an empty course and ignores the manifest, so every
file is reported as "Would upload" and the output says nothing about which files
are stale, which items are newer on Canvas, or what a targeted `-t`/`-s` run
would touch. The name `--check-all` also does not say that it simulates an empty
course, which is the property that separates it from the new option.

## What Changes

- New `update --noop` (`-n`): runs the same pipeline a real `update` would run
  against the configured course, with the same options, but makes no change to
  Canvas and writes nothing to disk.
  - The manifest is loaded from disk and used as an in-memory copy, so the
    mtime-vs-`last_synced` staleness test, the hash caches for course settings
    and rubrics, and the "newer on Canvas" check decide what is reported exactly
    as they would in a real run. The manifest file is not modified.
  - Canvas reads go to the real course (an API token is required). Every Canvas
    write is simulated; items it would create get fake IDs that are never sent
    to Canvas.
  - Works with `-t`/`--target-recursively`, `-s`/`--single-target`,
    `--force-uploads`, `--force-overwrite`, `--verbose` and `--new`.
  - The unrecorded-move check runs and stops the run as it does in a real
    `update`.
  - The course guard runs as it does in a real `update`. What it does when it
    would otherwise write the manifest is an open question in design.md.
  - Output is the normal `update` output with "Would ..." verbs (the wording
    `--check-all` already uses), followed by a summary of counts at the end.
  - Exits with status 1 when any error or warning was collected, like
    `--check-all`.
- **BREAKING**: `update --check-all` is renamed to `update --check-as-new-course`.
  No deprecated alias is kept; `--check-all` becomes an unknown option. The
  behavior is unchanged.

## Existing mechanisms this relates to

- `update --check-all`: offline simulation of a first sync to an empty course.
  It is kept (renamed). `--noop` reuses its machinery: the `SyncContext.api`
  indirection, `dryrun.DryRunCanvas` for writes, `ctx.check_only` for the
  "Would ..." wording, and `manifest_path=None` so the manifest is never
  flushed.
- `update --verbose`: lists skipped items, but only during a real run.
- `mv --noop`, `cp --noop`, `upgrade --noop`, `generate-due-dates --noop`: the
  flag name and `-n` short form are taken from these.
- `find-canvas-orphans`, `find-local-orphans`, `fix-manifest` without `--clean`:
  read-only reports about orphans and manifest problems; they do not predict what
  `update` uploads.

TODO.md has no item for this feature. No TODO.md item is completed or changed.

## Core subcommands

- `update`: the only command that gains `--noop` and loses `--check-all`.
- `mv`: already has `--noop`; it only edits local files and the manifest, so
  nothing changes.
- `import`: converts an export file to a local repo and never writes to Canvas,
  so a dry run against the course does not apply.
- `publish`: builds a local MkDocs site and never contacts Canvas, so it is not
  affected.

## Capabilities

### New Capabilities

- `update-noop`: `update --noop` (dry run of `update` against the current
  course) and the `--check-all` -> `--check-as-new-course` rename.

### Modified Capabilities

None. The specs `snippet-links`, `unrecorded-move-detection` and
`group-categories` mention `--check-all`; they are historical records and are
not edited. ARCHITECTURE.md and README.md are updated instead.

## Impact

- `src/markdown_to_canvas/cli.py`: `update` options, validation of option
  combinations, the noop path, the summary and exit status.
- `src/markdown_to_canvas/sync.py`: `run_sync` and `run_targeted_sync` take a
  noop mode; `run_targeted_sync` currently calls `capi` directly in places and
  does not pass `api=` to `SyncContext`, so it needs the same API indirection
  `run_sync` has.
- `src/markdown_to_canvas/dryrun.py`: a read-through variant that forwards reads
  to `canvas_api` and simulates writes.
- `src/markdown_to_canvas/course_guard.py` and `unrecorded_moves.py`: must not
  write the manifest under `--noop`.
- Tests: `tests/test_check_all.py` and the other tests that pass `--check-all`
  (`test_group_categories.py`, `test_repo_format_enforcement.py`,
  `test_cli_course_dir.py`, `test_unrecorded_moves.py`, `test_sync.py`); new
  noop tests.
- Docs: README.md, ARCHITECTURE.md, TESTING.md mention `--check-all`.
- Users' own scripts or CI that call `update --check-all` will fail with an
  unknown-option error. The `emit-workflow` template does not use it.
