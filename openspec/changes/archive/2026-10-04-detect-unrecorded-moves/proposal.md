# Proposal

## Why

When a course file is moved or renamed with git, a file manager or an editor
and not with `markdown-to-canvas mv`, the manifest keeps the old path. The next
`update` treats the file at the new path as new and creates a second Canvas
item, and the old item stays in Canvas because `update` never deletes. In the
College 101 repo, `assignments/make-an-appointment-with-advising-in-class-activity.md`
was moved to `assignments/educational-plan/` with git in commit `1f2c9b6`.
`update` then created assignment 42309815 next to the original 42270446 in
course 2735293 (and 42309822 next to 42270453 in the OL-4 section). Students
submitted to both copies. Canvas has no way to merge assignments, so the
instructor has to reconcile grades by hand.

## What Changes

- `update` checks for unrecorded moves before it changes anything in Canvas.
  A file with no manifest entry is a likely move when an orphaned manifest
  entry (an entry whose local file is gone) has the same content type and
  either the same file name or the same title. The orphan's title comes from
  Canvas, because the manifest does not record titles. When at least one
  likely move is found, `update` stops, lists each `OLD → NEW` pair, and prints
  the command that records the move. Nothing is created in Canvas.
- New option `mv --after OLD NEW`, modeled on `hg mv --after`. It records a
  move that already happened on disk: OLD is gone and NEW exists. It does
  everything `mv` does except move the file: it rekeys every
  `.manifest-*.toml`, rewrites links to OLD in other Markdown files, and
  updates `module_order.toml`, `pinned_resources`, `front_page` and
  `dashboard_image`.
- New option `update --new PATH` (repeatable) for when the matched file
  really is a new item. It removes the manifest entries of the orphans that
  match PATH (Canvas is not changed), prints an inline warning for each one
  saying that the old Canvas item was left in Canvas untracked, and continues
  the run.
- `update` warns, without stopping, about duplicates that already exist: an
  orphaned entry that matches a file that already has its own manifest entry
  (the College 101 state today). The warning repeats on every run until the
  orphan's entry is removed, by `update --new TRACKED`, `prune`, or by hand.

## Existing mechanisms and how this relates to them

- `mv SRC DEST` already does the full repair, but only when it moves the file
  itself. `validate_move` requires SRC to exist. `--after` reuses its
  manifest, link, `module_order.toml` and `course_settings.toml` logic.
- `fix-manifest --pair-canvas-with-local` pairs local files that have no entry
  with Canvas items of the same type and title. It does not catch a move,
  because the orphaned entry still claims the Canvas item, and
  `--force-pair NEW=ID` refuses for the same reason ("already the Canvas item
  for OLD"). Even if it paired the file, it would leave the orphaned entry
  pointing at the same Canvas ID, and a later `prune --delete` would then
  delete the live item. Moves are not routed through it for that reason.
- `prune` and `find-canvas-orphans` act after the duplicate exists. `prune`
  is how the instructor removes the leftover item once a duplicate has
  happened.
- `find-local-orphans` reports unreferenced local files and is unrelated.

## TODO.md

The TODO.md item "Filesystem watcher for automatic move/rename tracking"
addresses the same problem by watching for moves as they happen. This change
does not implement it. It catches moves at the point where they cause harm
(the next `update`), including moves made while no watcher was running,
so it covers the watcher's "missed events are silent failures" caveat.
The TODO item stays, and gets a note that `update` now catches
unrecorded moves and that a watcher could call `mv --after`.

## Core subcommands affected

- `update`: gains the unrecorded-move check (full sync and `-t`/`-s`
  targeted sync, both checking the whole repo), the `--new PATH` option, and
  the existing-duplicate warning. `update --check-all` does not run the check,
  because it ignores the manifest.
- `mv`: gains `--after`.
- `import`: not affected. It builds a repo from a Canvas export and never
  reads or writes a manifest, so it cannot create a duplicate this way.
- `publish`: not affected. It builds a MkDocs site and never contacts Canvas
  or reads a manifest.

## Capabilities

### New Capabilities

- `unrecorded-move-detection`: `update` detects files moved without `mv`,
  stops before creating duplicates, and warns about duplicates that already
  exist.
- `mv-after`: `mv --after OLD NEW` records a move that was already made on
  disk.

### Modified Capabilities

None. No existing spec covers `update`'s pre-flight checks or `mv`.

## Impact

- `src/markdown_to_canvas/sync.py`: a pre-flight check in `run_sync` and
  `run_targeted_sync`, after the course guard and before phase 0.
- New module for the detection logic (matching orphans to files), reusing
  `pair_manifest.collect_local_items` for local titles and types, and
  `canvas_api`'s per-type getters to fetch each orphan's Canvas item.
- `src/markdown_to_canvas/mv.py` and `cli.py`: `mv --after` and
  `update --new`.
- No manifest format change and no `FORMAT_VERSION` bump: nothing new is
  stored, and `mv --after` writes the same manifest shape `mv` writes.
- One Canvas GET per orphaned entry on each `update` run. No Canvas call when
  the manifest has no orphans.
- README.md, ARCHITECTURE.md and TODO.md updates.
