# Spec Delta

## Purpose

Lets the user record a move or rename that was already made on disk without
`markdown-to-canvas mv`, so the manifests, links and settings catch up and
`update` keeps using the existing Canvas items.

## ADDED Requirements

### Requirement: mv --after records a move already made on disk

`markdown-to-canvas mv --after OLD NEW` SHALL make every change that
`mv OLD NEW` would make except moving anything on disk:

- Rename the key OLD to NEW in every `.manifest-*.toml` in the repo, including
  `canvas_item_ids` in module entries, keeping each entry's other fields.
- Rewrite links to OLD in the repo's other Markdown files so they point at NEW.
- Update `module_order.toml`, `pinned_resources`, `front_page` and
  `dashboard_image` where they name OLD.

OLD and NEW SHALL be repo-relative or absolute paths in the same course repo
and the same content-type directory, as for `mv`. `--noop` and `--verbose`
SHALL work as they do for `mv`. A directory OLD SHALL be handled like a
directory move by `mv`: every manifest key and link under OLD maps to the
matching path under NEW.

#### Scenario: Record a git move
- **WHEN** `assignments/advising.md` was moved with git to `assignments/educational-plan/advising.md`, both manifests still have the old key, and `mv --after assignments/advising.md assignments/educational-plan/advising.md` is run
- **THEN** both manifests have the entry under the new key with the same `canvas_id`, no file on disk is moved, and `modules/week-1.md`'s link to the old path now points at the new path

#### Scenario: Directory
- **WHEN** `pages/week-1/` was renamed to `pages/unit-1/` on disk and `mv --after pages/week-1 pages/unit-1` is run
- **THEN** every manifest key under `pages/week-1/` is rekeyed to the same path under `pages/unit-1/`

#### Scenario: Noop
- **WHEN** `mv --after --noop OLD NEW` is run
- **THEN** the changes are printed and no file is written

### Requirement: mv --after validates the paths

`mv --after` SHALL refuse, changing nothing, when OLD exists on disk, when NEW
does not exist, when no manifest in the repo has OLD (or, for a directory, any
key under OLD), or when the paths are in different content-type directories.
A manifest that has entries for both OLD and NEW SHALL be left unchanged, and
`mv --after` SHALL print, for that manifest, both Canvas IDs, that the two are
probably duplicates, and `update --new NEW` (run with that manifest's config) as
the way to forget the old entry. Manifests that have OLD but not NEW SHALL be
rekeyed. When every manifest that has OLD also has NEW, `mv --after` SHALL
refuse, changing nothing (links and settings included), and exit non-zero.

#### Scenario: OLD still exists
- **WHEN** `mv --after pages/a.md pages/b.md` is run and `pages/a.md` exists
- **THEN** it refuses and says to use `mv` without `--after`

#### Scenario: NEW already tracked everywhere
- **WHEN** both manifests already have entries for OLD and NEW, as with the advising assignment today
- **THEN** it refuses, names both Canvas IDs for each manifest, points to `update --new NEW`, and changes nothing

#### Scenario: NEW tracked in one section only
- **WHEN** `.manifest-canvas-ol-3.toml` has OLD and NEW but `.manifest-canvas-ol-4.toml` has only OLD
- **THEN** the OL-4 manifest is rekeyed, the OL-3 manifest is unchanged with a duplicate notice, and links and settings are updated

#### Scenario: OLD not in any manifest
- **WHEN** no manifest has OLD
- **THEN** it refuses and says there is nothing to record

### Requirement: Links inside the moved file

For links inside the moved file itself, `mv --after` SHALL rebase a relative
link from OLD's folder to NEW's folder only when the link resolves to an
existing file from OLD's folder and does not resolve from NEW's folder.
Links that already resolve from NEW's folder SHALL be left as they are,
because an editor may already have updated them.

#### Scenario: Editor already fixed links
- **WHEN** the moved file links to `../../pages/x.md`, which resolves from NEW's folder
- **THEN** the link is unchanged

#### Scenario: Links still written for the old folder
- **WHEN** the moved file links to `../pages/x.md`, which resolves from OLD's folder but not from NEW's folder
- **THEN** the link is rewritten to the path that reaches `pages/x.md` from NEW's folder
