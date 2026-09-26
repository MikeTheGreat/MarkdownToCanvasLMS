# Spec Delta

## ADDED Requirements

### Requirement: Migration 3 to 4

Migration 3 -> 4 SHALL convert relative links in block snippet files from the
old reading (relative to each including file) to the snippet-relative reading
defined by the `snippet-links` capability, and record format version 4 in
every `.manifest-*.toml`. It SHALL make changes to snippet files only when the
settings file's own format version is below 4.

The migration SHALL consider as includers every `.md` file in the repo outside
`snippets/` and outside hidden folders, including files excluded by
`.canvasignore`, that includes the snippet as a block snippet outside a fenced
code block. `PASTE_SNIPPET_INTO_FRONTMATTER` references and inline `$...$`
references SHALL NOT count as including a snippet. It SHALL examine the same
link forms that `snippet-links` rebases and skip the forms it leaves unchanged.

The migration SHALL also examine the paths of `$path.md$` inline snippet
references inside snippet files, and block snippet references to other
snippets, the same way as links: before format 4 neither was expanded inside a
snippet, and from format 4 both are resolved from the snippet's folder.

For each such link in each included snippet, where an "includer target" is
the repo file the link names when read from an includer's folder, a "working
includer target" is an includer target that exists, and the "snippet target"
is the file the link names when read from the snippet's folder:

1. When all working includer targets are the same file, and it differs from
   the snippet target, the migration SHALL rewrite the link so that, read
   from the snippet's folder, it names that file, and print the change. This
   applies even when some includers resolved the link to nothing: those
   includers were already broken, and the rewrite fixes them too.
2. When all working includer targets are the same file and it equals the
   snippet target, the link SHALL be left unchanged without a message.
3. When there is no working includer target and the snippet target exists,
   the link SHALL be left unchanged without a message.
4. When working includer targets name more than one file, or no target
   exists at all, the link SHALL be left unchanged and the migration SHALL
   print a notice naming the snippet, the link, and each includer with the
   file it resolved to (or that it resolved to nothing).

A snippet that no file includes SHALL be left unchanged; the migration SHALL
print a notice for each of its links whose snippet target does not exist.
These notices SHALL NOT stop the upgrade. The migration SHALL change only the
rewritten link paths in a snippet file and leave all other bytes as they
were. With `--noop` it SHALL print the same changes and notices and write no
file.

#### Scenario: Snippet written for deeper includers
- **WHEN** `snippets/policy.md` contains `![](../../assets/logo.png)` and its only includers are `pages/week1/a.md` and `pages/week2/b.md`
- **THEN** `upgrade` rewrites the image path to `../assets/logo.png`, prints the change, and writes `format_version = 4`

#### Scenario: Includers at the snippet's depth
- **WHEN** `snippets/policy.md` links `../pages/syllabus.md` and every includer is directly under a top-level folder
- **THEN** the snippet file is not modified

#### Scenario: Snippet reading already works
- **WHEN** a snippet links `../assets/x.png` and is included from `pages/a.md` (resolving to `assets/x.png`) and `pages/unit1/b.md` (resolving to `pages/assets/x.png`, which does not exist)
- **THEN** the only working includer target equals the snippet target `assets/x.png`, so the link is left unchanged without a message

#### Scenario: Working includers agree, another includer was broken
- **WHEN** `snippets/block/front.md` links `../instructor_info/office-hours.md`, `pages/week-1/home.md` resolves it to the existing `pages/instructor_info/office-hours.md`, and `pages/landing.md` resolves it to nothing
- **THEN** the link is rewritten to `../../pages/instructor_info/office-hours.md` and no notice is printed

#### Scenario: References to other snippets
- **WHEN** `snippets/block/weekly/front.md` contains `[NAME](../../snippets/inline/name.md)` and `[Syllabus]($../../snippets/inline/C.md$/syllabus)`, written for an includer in `pages/week-1/`
- **THEN** they become `[NAME](../../inline/name.md)` and `[Syllabus]($../../inline/C.md$/syllabus)`, and every includer shows the name and the course URL

#### Scenario: Includers resolve to different existing files
- **WHEN** a snippet links `img/x.png`, `pages/img/x.png` and `pages/unit1/img/x.png` both exist, and the snippet is included from `pages/a.md` and `pages/unit1/b.md`
- **THEN** the link is left unchanged and a notice lists both includers and the file each resolved to

#### Scenario: Includer reading wins over snippet reading
- **WHEN** a snippet links `../assets/x.png`, both `assets/x.png` and `pages/assets/x.png` exist, and the snippet's only includer is `pages/unit1/a.md` (resolving to `pages/assets/x.png`)
- **THEN** the link is rewritten to `../pages/assets/x.png`

#### Scenario: Unused snippet with a broken link
- **WHEN** no file includes `snippets/old.md` and it links `../assets/gone.png`, which does not exist
- **THEN** the file is not modified and a notice names the snippet and the link

#### Scenario: Ignored includer counts
- **WHEN** a `.canvasignore`d draft at a different depth includes a snippet
- **THEN** its reading is considered along with the other includers

#### Scenario: Dry run
- **WHEN** a user runs `upgrade --noop` on a version-3 repo with a snippet link to convert
- **THEN** the rewrite is printed and no file, including the snippet, is written
