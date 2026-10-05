# Design

## Context

See proposal.md for the motivation and the College 101 incident.

Relevant current behavior:

- `_sync_content_file`, `_sync_quiz`, `_sync_module`, `_walk_assets` and the
  link stub creator (`_make_stub_creator`) each create a Canvas item when the
  path has no manifest entry. A pre-flight check before phase 0 therefore
  covers all creation paths at once. A per-creation-site check would have to be
  repeated in each of them, and the stub creator runs for files other than the
  one being uploaded.
- `run_prune` already defines an orphan: a key whose file is gone, excluding
  `manifest_lib.is_reserved_key` keys and `external_module` entries.
- `pair_manifest.collect_local_items(repo_root)` returns every file `update`
  would sync as `(key, canvas_type, title)`, honoring `.canvasignore`. For
  assets the title is the path below `assets/`.
- `pair_manifest.normalize_title` is the title comparison `fix-manifest` uses.
- `canvas_api._GETTERS` / `_object_key` fetch one Canvas object per manifest
  entry by type (page slug for pages, ID otherwise).
- `mv.run_mv` computes everything from a `path_map` (`build_path_map`) and then
  physically moves. `compute_file_updates` walks the Markdown files on disk and
  calls `links.transform_links`, which takes a `url_map` hook that can decide
  per link.
- `update --check-all` (`check_all=True`) uses an empty manifest, so there are no
  orphans and nothing to compare.

## Goals / Non-Goals

**Goals:**

- No Canvas item is created for a file that is probably an unrecorded move.
- The user can resolve each stop with one command, either recording the move
  or declaring the file new.
- The check costs nothing (no Canvas call) in a repo with no orphans.

**Non-Goals:**

- Repairing duplicates that already exist in Canvas (merging assignments or
  submissions). The check only warns about them.
- Detecting moves through git history. The user chose file name or title
  matching.
- The filesystem watcher in TODO.md.
- Recording moves automatically. `update` never rewrites the manifest on a
  guess.

## Decisions

### Stop before any Canvas change (confirmed by the user)

The check runs in `run_sync` and `run_targeted_sync` right after the manifest
is loaded and before `sync_course_settings`. On any matched pair it prints the
report and returns with errors, before any Canvas write. The alternatives were
an interactive prompt that repairs and continues, and a warning that still
creates the item. Both were rejected: the prompt cannot run unattended and
hides a manifest rewrite inside `update`, and the warning still creates the
duplicate.

### Match on type plus file name or title (confirmed by the user)

A pair matches when the Canvas types are equal and either the file names are
equal or the titles are equal after `normalize_title`. Assets match on file
name only, because their "title" is their path. The alternatives were file
name only, which misses renames such as a renamed quiz folder (whose key
changes from `quizzes/a/a.md` to `quizzes/b/b.md`), and adding git rename
history, which needs a git repo and a base commit to diff against.

### `mv --after OLD NEW` is the repair command (confirmed by the user)

`run_mv` gains an `after` flag. Validation changes: OLD must not exist, NEW
must exist, and some manifest must have OLD (or a key under it) without having
NEW. A manifest holding both is left alone with a duplicate notice, because
one section may already have the duplicate while another does not (proposed;
see the `mv-after` spec). `resolve_dest` is skipped, because NEW names the actual
location, so an existing directory NEW must not be expanded to `NEW/OLD.name`.
`build_path_map` needs a variant that builds the map from manifest keys under
OLD, since OLD no longer exists to walk. The physical move (`_do_move`) is
skipped. Everything else (`compute_all_manifest_updates`,
`compute_module_order_updates`, `compute_course_settings_updates`,
`compute_pinned_resources_updates`, `_describe_changes`, `--noop`) is reused
unchanged.

`compute_file_updates` walks files on disk, so a moved file is found at NEW,
not OLD. With `after`, a file at a NEW path is treated as moved from its OLD
path. Its own links are passed through `transform_links` with a `url_map` that
keeps a link that resolves from NEW's folder and rebases a link that resolves
from OLD's folder only (see the `mv-after` spec). The rule exists because
editors such as VS Code may already have updated the links when the file was
moved.

### Warn about existing duplicates (confirmed by the user)

The same comparison runs between orphans and tracked files. Matches are
printed as warnings and the run continues.

### Read orphan titles one object at a time (confirmed by the user)

Title matching and the "orphan already deleted" rule need each orphan's
Canvas title and existence. The check fetches each orphan with the existing
`_GETTERS` (one GET per orphan; a 404 means the item is gone). The rejected
alternative was `list_course_objects`, which `fix-manifest` uses. It makes one
paginated listing per type plus the folder list, so its cost grows with the
course, not with the number of orphans. College 101's OL-3 manifest has 10
orphans today, so it pays 10 GETs per run until they are cleared.

### `update --new PATH` declares a file new (confirmed by the user)

The user chose `update --new PATH` over a `prune --only PATH` filter. Removal
happens in the pre-flight step, after matching and before phase 0. For each
PATH, the entries of every orphan matching it are deleted from the in-memory
manifest and the manifest is flushed once, so the removal survives a run that
fails later. One inline warning per removed entry is printed at that point.
Matching for `--new` uses the same rules as the check. Because the orphan's
entry is gone, the check has nothing left to match and the run proceeds.
`--new` is validated before anything is removed: an unknown path, a
non-synced file, or a path matching no orphan stops the run with no change.

The old Canvas item is not touched. Once its entry is gone, `prune` no longer
knows it. `find-canvas-orphans` will report it if nothing links to it, and the
warning says so.

### Whole-repo check for targeted runs, none for `--check-all` (confirmed by the user)

`run_targeted_sync` runs the same pre-flight as `run_sync`, so a targeted
run's link stubbing cannot create the duplicate. `update --check-all` skips the
check, and the CLI rejects `--new` together with `--check-all`.

## Canvas API behavior relied on

- Fetching a page by slug and other types by ID, with a 404 for a deleted
  item: verified, existing code (`get_canvas_updated_at` and `prune` use
  `_GETTERS` against live courses).
- Title fields (`title` for pages, discussions, announcements and quizzes;
  `name` for assignments and modules; `display_name` for files): verified,
  used by `fix-manifest` pairing.
- Canvas will not unpublish an assignment with submissions or a discussion
  with replies: verified, existing handling (`_warn_unpublish_refused`,
  `unpublish_refused`). Consequence: for an orphan with student work,
  `prune --unpublish` fails for it, and the warning must not present unpublishing
  as a sure fix.
- Deleting an assignment hides its submissions: not verified live by this
  project. The change adds no delete path: `update --new` only removes a
  manifest entry and never changes Canvas. The duplicate warning still says
  that deleting the orphan with `prune --delete` would also remove the
  submissions made to it, and that `prune` acts on every orphan at once.

## Safeguards against false positives

- A false-positive match costs a stopped run, not lost data. The user clears
  it with `update --new NEW`, which forgets only the matching orphan and
  leaves Canvas unchanged.
- Requiring equal Canvas types prevents cross-type matches (`pages/week-1.md`
  and `modules/week-1.md`).
- An orphan whose Canvas item is gone never matches.
- Ambiguous matches are listed, not resolved.
- `mv --after` never rekeys OLD in a manifest that already has NEW, so it can
  never leave two keys pointing at one Canvas ID. A shared ID would make a later
  `prune --delete` remove the live item.

## Manifest format

No change. The check only reads manifests. `mv --after` writes the same entry
shapes `mv` writes. No `FORMAT_VERSION` bump and no migration.

## Risks / Trade-offs

- [Same file name used for different items, e.g. many `overview.md` under
  `pages/week-N/`] → A deleted one plus a new one stops the run once. Clearing
  it takes one `update --new` run.
- [Repos that keep orphans around get extra Canvas GETs on every `update`] →
  The warning tells the user to prune, and the GET count is bounded by the
  orphan count.
- [The stop blocks unrelated targeted runs (`-s other.md`)] → Accepted so that
  a targeted run's link stubbing cannot create the duplicate either.
- [`update --new` with a mistyped or overly broad PATH forgets the wrong
  orphan] → PATH must match an orphan by the same rules as the check, every
  removal is printed inline, and the removal is undoable with git because the
  manifest is a tracked file. Canvas is never changed.
- [The moved-file link rule guesses] → It only changes a link that is broken
  from NEW's folder and valid from OLD's, so it never breaks a working link.

## Migration Plan

None needed. Existing repos with unrecorded moves will stop on their next
`update` with the repair commands, which is the intended behavior. The
College 101 repo will show duplicate warnings for the advising assignment in
both sections until the orphans are pruned.

### `update --new` also accepts a tracked file (confirmed by the user)

When PATH already has its own manifest entry, `--new` removes the entries of
the orphans that match it, the same way it does for a new file. This is how a
duplicate that already exists stops being warned about without editing the
manifest by hand or pruning every orphan. For example,
`update --new assignments/educational-plan/make-an-appointment-with-advising-in-class-activity.md`
forgets orphan 42270446 and leaves both Canvas assignments untouched.

## Open Questions

1. When one manifest has both OLD and NEW and another has only OLD,
   `mv --after` rekeys the second and leaves the first with a notice
   (proposed), instead of refusing outright. This happens when only one
   section was updated after the move.
