# unrecorded-move-detection Specification

## Purpose

Stops `update` from creating a duplicate Canvas item when a course file was
moved or renamed without `markdown-to-canvas mv`, and flags duplicates that an
earlier run already created.

## Requirements

### Requirement: Terms used by the unrecorded-move check

For this capability:

- An **orphan** SHALL be a manifest entry, in the manifest of the config the
  run uses, whose local file does not exist, excluding reserved keys and
  Canvas-only modules from `module_order.toml`.
- A **new file** SHALL be a file that `update` would sync as a Canvas item
  (a content Markdown file, a quiz's main file, a module file, or a file under
  `assets/`), that is not ignored by `.canvasignore`, and that has no entry in
  that manifest.
- A **tracked file** SHALL be such a file that does have an entry.
- An orphan and a file SHALL **match** when both have the same Canvas type and
  at least one of these holds:
  - Their last path components (file names) are equal.
  - The file's title equals the title of the orphan's Canvas item, compared
    the way `fix-manifest --pair-canvas-with-local` compares titles (ignoring
    case, whitespace, curly quotes and dashes). The file's title is its
    frontmatter `title`, or the name `update` falls back to when there is
    none. Files under `assets/` match by file name only.
- An orphan whose Canvas item no longer exists in the course SHALL NOT match
  anything, because no duplicate can result.

#### Scenario: Moved to a subfolder
- **WHEN** the manifest has `assignments/advising.md` (canvas_id 42270446, which exists in the course), that file is gone, and `assignments/educational-plan/advising.md` exists with no entry
- **THEN** the two match by file name

#### Scenario: Renamed with the same title
- **WHEN** the manifest has `pages/old-name.md` whose Canvas page is titled "How to Succeed", that file is gone, and `pages/how-to-succeed.md` with `title: "How to Succeed"` has no entry
- **THEN** the two match by title

#### Scenario: Different type does not match
- **WHEN** an orphan `pages/week-1.md` is a page and the new file `modules/week-1.md` is a module
- **THEN** they do not match

#### Scenario: Orphan already deleted in Canvas
- **WHEN** an orphan's Canvas item no longer exists in the course and a new file has the same file name and type
- **THEN** they do not match and the run is not stopped on their account

### Requirement: update stops before creating a duplicate

Before it makes any change to Canvas, `update` (a full run, and a targeted run
with `-t` or `-s`) SHALL look for new files that match an orphan. When at least
one matching pair exists, `update` SHALL print each pair as `OLD → NEW` with the
reason it matched (file name, title, or both), print for each pair the
`markdown-to-canvas mv --after OLD NEW` command that records the move, print how
to proceed instead when NEW really is a new item, make no change to Canvas or to
the manifest, and exit non-zero. A targeted run SHALL check the whole repo, not
only its targets.

When an orphan matches several new files, or a new file matches several
orphans, every pair SHALL be listed and the run SHALL stop. The tool SHALL NOT
choose among them.

When the check finds no matching pairs, `update` SHALL proceed and print nothing
about it unless `--verbose` is given.

#### Scenario: Unrecorded move stops the run
- **WHEN** `assignments/advising.md` was moved with git to `assignments/educational-plan/advising.md` and `update` is run
- **THEN** `update` prints `assignments/advising.md → assignments/educational-plan/advising.md (same file name)` and `markdown-to-canvas mv --after assignments/advising.md assignments/educational-plan/advising.md`, creates nothing in Canvas, leaves the manifest unchanged, and exits non-zero

#### Scenario: After mv --after the run proceeds
- **WHEN** the user runs the printed `mv --after` command and then `update` again
- **THEN** `update` updates Canvas item 42270446 and creates no new assignment

#### Scenario: Ambiguous match
- **WHEN** an orphan `pages/overview.md` is gone and both `pages/week-1/overview.md` and `pages/week-2/overview.md` are new files
- **THEN** both pairs are listed and the run stops

#### Scenario: Targeted run
- **WHEN** `update -s pages/syllabus-notes.md` is run while an unrecorded move exists elsewhere in the repo
- **THEN** the run stops the same way as a full run

#### Scenario: Check-all mode is unaffected
- **WHEN** `update --check-all` is run
- **THEN** no unrecorded-move check is made, because check mode ignores the manifest

### Requirement: update --new declares a matched file to be a new item

`update` SHALL accept a repeatable `--new PATH` option, where PATH is a
repo-relative path to a file that `update` syncs. For each PATH, every orphan
that matches it SHALL have its manifest entry removed before any Canvas change,
and for each removed entry `update` SHALL print an inline warning at that point
in the output naming the orphan's path, its Canvas type and ID, the PATH it
matched, and saying that the old Canvas item was left in Canvas and is no
longer tracked by the tool. The run SHALL then continue, and a new file at
PATH SHALL be created in Canvas as usual. Canvas SHALL NOT be changed by
removing the entry.

PATH may also be a tracked file. In that case the matching orphans' entries are
removed in the same way, which is how a duplicate that already exists stops
being warned about.

When a PATH does not exist, is not a file `update` syncs, or matches no
orphan, `update` SHALL report it as an error and stop before any Canvas or
manifest change. The stop message described in "update stops before creating a
duplicate" SHALL name `update --new NEW` as the alternative to `mv --after`.

`--new` SHALL NOT be accepted together with `--check-all`.

#### Scenario: Declare a file new
- **WHEN** the orphan `pages/overview.md` (page 555) matches the new file `pages/week-2/overview.md` and `update --new pages/week-2/overview.md` is run
- **THEN** the `pages/overview.md` entry is removed from the manifest, a warning names `pages/overview.md`, page 555 and `pages/week-2/overview.md` and says page 555 was left in Canvas untracked, and `pages/week-2/overview.md` is created as a new Canvas page

#### Scenario: Other orphans are kept
- **WHEN** `update --new pages/week-2/overview.md` is run and the manifest has other orphans that do not match it
- **THEN** their entries are unchanged

#### Scenario: PATH matches no orphan
- **WHEN** `update --new pages/unique.md` is run and no orphan matches `pages/unique.md`
- **THEN** `update` reports an error, changes nothing in Canvas or the manifest, and exits non-zero

#### Scenario: Clearing an existing duplicate warning
- **WHEN** `update --new assignments/educational-plan/make-an-appointment-with-advising-in-class-activity.md` is run while the orphan `assignments/make-an-appointment-with-advising-in-class-activity.md` (42270446) matches it
- **THEN** the orphan's entry is removed with the inline warning, assignment 42270446 stays in Canvas, and later runs print no duplicate warning for the pair

### Requirement: update warns about duplicates that already exist

When an orphan matches a tracked file (not a new one), `update` SHALL print a
warning naming the orphan, its Canvas ID, the tracked file and its Canvas ID,
saying that the two are probably duplicates in Canvas, and naming
`update --new TRACKED` (forget the orphan, keep both Canvas items) and `prune`
as ways to clear it. The warning SHALL NOT stop the run. It SHALL be printed on
every run until the orphan's entry is gone.

#### Scenario: Advising duplicate
- **WHEN** the manifest has the orphan `assignments/make-an-appointment-with-advising-in-class-activity.md` (42270446) and the tracked file `assignments/educational-plan/make-an-appointment-with-advising-in-class-activity.md` (42309815), and `update` is run
- **THEN** `update` prints a warning naming both paths and both IDs and continues the sync

#### Scenario: Warning goes away once the entry is gone
- **WHEN** the orphan's entry is removed (by `update --new`, `prune`, or by hand) and `update` is run again
- **THEN** no duplicate warning is printed for that pair

### Requirement: Canvas is only read by the check

The check SHALL only read from Canvas. It SHALL read Canvas only when the
manifest has at least one orphan, fetching each orphan's Canvas item
individually. When there are no orphans it SHALL make no Canvas call.

#### Scenario: No orphans, no Canvas call
- **WHEN** every manifest entry's file exists
- **THEN** the check makes no Canvas request
