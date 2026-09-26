# Spec Delta

## Purpose

Defines how relative links and image paths written inside a block snippet are
resolved, and how every command that pastes, moves, copies or scans snippets
treats them, so a snippet link works from any including file.

## ADDED Requirements

### Requirement: Snippet links are relative to the snippet file

A relative link or image path inside a block snippet (a snippet included with
`[text](path-into-snippets/)`) SHALL be resolved relative to the folder that
holds the snippet file. When the snippet is pasted into an including file, the
tool SHALL rewrite each such path so that, read from the including file's
folder, it names the same file. The rewritten path SHALL be relative (no
leading `/`), SHALL keep any `#fragment` or `?query`, and SHALL keep
percent-encoding when the original used it.

The forms rewritten SHALL be: Markdown links and images `[text](url)` and
`![alt](url)`, including the `<url>` form and a link title; and the `src` of a
raw HTML `<img>` tag and the `href` of a raw HTML `<a>` tag.

#### Scenario: Includer deeper than the snippet
- **WHEN** `snippets/policy.md` contains `![logo](../assets/logo.png)` and `pages/week1/intro.md` includes it
- **THEN** the pasted text in `pages/week1/intro.md` reads `![logo](../../assets/logo.png)` and the uploaded page shows `assets/logo.png`

#### Scenario: Same snippet at two depths
- **WHEN** `snippets/policy.md` links `[syllabus](../pages/syllabus.md)` and is included from both `pages/a.md` and `assignments/unit1/hw.md`
- **THEN** both uploaded items link to the Canvas page for `pages/syllabus.md`

#### Scenario: Includer at the snippet's depth
- **WHEN** `snippets/policy.md` links `../pages/syllabus.md` and `pages/a.md` includes it
- **THEN** the pasted link reads `../pages/syllabus.md`, unchanged

#### Scenario: Snippet in a subfolder
- **WHEN** `snippets/labs/header.md` contains `![](../../assets/lab.png)` and `pages/lab1.md` includes it
- **THEN** the pasted image path is `../assets/lab.png`

#### Scenario: Angle-bracket form and title
- **WHEN** a snippet contains `[notes](<../assets/My Notes.pdf> "Notes")` and an includer one folder deeper than `snippets/` includes it
- **THEN** the pasted link is `[notes](<../../assets/My Notes.pdf> "Notes")`

#### Scenario: Raw HTML image
- **WHEN** a snippet contains `<img src="../assets/a.png" alt="A">` and `pages/week1/x.md` includes it
- **THEN** the pasted tag is `<img src="../../assets/a.png" alt="A">`

#### Scenario: Fragment kept
- **WHEN** a snippet links `../pages/faq.md#late-work`
- **THEN** the pasted link names `pages/faq.md` from the includer's folder and still ends in `#late-work`

### Requirement: Snippets can include snippets

A snippet MAY include other snippets, in block form or inline `$path.md$`
form. A snippet reference inside a snippet SHALL be resolved relative to the
snippet file that contains it, and the included snippet SHALL be expanded
(with its own links rebased onto the snippet that includes it) before the
outer snippet is pasted. Course-flag conditionals SHALL be evaluated in each
snippet at every level. Nesting SHALL be allowed up to 10 levels. A reference
that would make an 11th level SHALL be left unexpanded and SHALL be reported
as an error naming the including file and the chain of snippets; the error
SHALL be handled like other snippet errors. Links that are not file paths
(URLs with a scheme, `#fragment`-only links, paths starting with `/`, links
containing `$`, and link text spanning lines) SHALL NOT be treated as snippet
references and SHALL NOT produce snippet errors. A block snippet reference MAY
carry a link title or use the `<path>` form.

#### Scenario: Block snippet inside a block snippet
- **WHEN** `snippets/outer.md` contains `Outer [Inner](inner.md) text.` and `snippets/inner.md` contains `INNER`, and `pages/notes.md` includes `outer.md`
- **THEN** the pasted text is `Outer INNER text.` and no error is reported

#### Scenario: Links rebased through two levels
- **WHEN** `snippets/block/outer.md` includes `deep/inner.md`, which contains `![logo](../../../assets/logo.png)`, and `pages/week1/x.md` includes `outer.md`
- **THEN** the pasted image path is `../../assets/logo.png`

#### Scenario: Inline snippet inside a block snippet
- **WHEN** `snippets/block/footer.md` contains `[Grades]($../inline/C.md$/grades)` and `snippets/inline/C.md` holds a course URL
- **THEN** a page including the footer shows the Grades link pointing at that course URL plus `/grades`

#### Scenario: A snippet that includes itself
- **WHEN** `snippets/loop.md` contains `again [x](loop.md)` and a page includes it
- **THEN** ten levels are pasted, the eleventh reference is left unexpanded, and an error names the page and the chain `snippets/loop.md -> snippets/loop.md -> ...`

#### Scenario: Ten levels
- **WHEN** snippets `s1.md` through `s10.md` each include the next and a page includes `s1.md`
- **THEN** all ten are pasted and no error is reported

#### Scenario: Ordinary links in a snippet
- **WHEN** a snippet contains `[m](https://x.edu/inbox#a)`, `[e](mailto:a@x.edu)`, `[t](#top)` and `[o](../pages/o.md "Office")`
- **THEN** no snippet error is reported for any of them

#### Scenario: Editing a nested snippet
- **WHEN** `snippets/inner.md` changes and a page includes `outer.md`, which includes `inner.md`
- **THEN** the next full `update` treats the page as changed

### Requirement: Links that are not rebased

The tool SHALL paste unchanged: any URL with a scheme (for example `https:`,
`mailto:`, `data:`), a link that is only a `#fragment`, a path starting with
`/`, a link containing a `$...$` inline snippet reference, a link whose text
spans lines, and every link inside a fenced code block. The contents of an inline `$path.md$` snippet
SHALL NOT be rebased.

#### Scenario: Absolute URL
- **WHEN** a snippet links `https://example.edu/help`
- **THEN** the pasted link is `https://example.edu/help`

#### Scenario: Data URI
- **WHEN** a snippet contains `![](data:image/png;base64,iVBOR...)`
- **THEN** the pasted image source is unchanged

#### Scenario: Code block
- **WHEN** a snippet contains a fenced code block showing `![](../assets/x.png)`
- **THEN** the pasted code block is byte-for-byte unchanged

#### Scenario: Inline snippet
- **WHEN** `pages/week1/x.md` contains `$../../snippets/inline/CANVAS_COURSE_REFERENCE.md$`
- **THEN** it is replaced by the snippet's stripped content, with no path rewriting

### Requirement: Snippet link outside the repo is reported

When a relative link in a block snippet resolves outside the course repo from
the snippet's folder, the tool SHALL leave the link unchanged and report an
error naming the including file, the snippet file and the link. The error
SHALL be handled like other snippet errors: `update` SHALL skip uploading the
including file and end with its "please check errors" message,
`update --check-all` SHALL exit non-zero, and `publish` SHALL list the error
and stop without building the site.

#### Scenario: Old-style link after upgrade
- **WHEN** `snippets/policy.md` contains `![](../../assets/x.png)` and `update` syncs a page that includes it
- **THEN** an error names the page, `snippets/policy.md` and `../../assets/x.png`
- **AND** the page is not uploaded, and other files in the run are

#### Scenario: check-all
- **WHEN** `update --check-all` runs on a repo with such a snippet link included from any file
- **THEN** the error is listed and the command exits non-zero

#### Scenario: publish
- **WHEN** `publish` stages a page that includes such a snippet
- **THEN** the error is listed and no site is built

### Requirement: Commands agree on the snippet-relative reading

Every command that reads snippet links SHALL use the snippet-relative reading:
`update` (including `--check-all`, `-s` and `-t`), `publish` (staged page
text and the choice of files to stage), `find-local-orphans`, `cp` (which
assets a copied file needs), and `mv` (which links it rewrites when files
move). `mv` SHALL NOT change links inside a snippet when only an including
file moves.

#### Scenario: find-local-orphans
- **WHEN** an asset is linked only from `snippets/policy.md` with a snippet-relative path, and a page at a different depth includes the snippet
- **THEN** `find-local-orphans` reports the asset as referenced, not as an orphan

#### Scenario: cp
- **WHEN** `cp` copies `pages/week1/intro.md`, which includes a snippet that links `../assets/logo.png`
- **THEN** `assets/logo.png` is copied

#### Scenario: mv of an includer
- **WHEN** `mv pages/a.md pages/unit1/a.md` is run and `pages/a.md` includes `snippets/policy.md`
- **THEN** `snippets/policy.md` is not modified and the moved page still shows the snippet's images after `update`

#### Scenario: mv of a snippet target
- **WHEN** `mv assets/logo.png assets/img/logo.png` is run and `snippets/policy.md` links `../assets/logo.png`
- **THEN** the snippet's link becomes `../assets/img/logo.png`

### Requirement: publish stages files linked from snippets

When `publish` decides which files to stage, it SHALL follow links in the text
of each included block snippet, read with the snippet-relative convention,
after applying course-flag conditionals. A file linked only from inside an
included snippet SHALL be staged.

#### Scenario: Asset linked only from a snippet
- **WHEN** a published page includes `snippets/policy.md`, which is the only file linking `assets/diagram.png`
- **THEN** `publish` stages `assets/diagram.png`, and the staged page's link to it resolves

#### Scenario: Link in a false conditional branch
- **WHEN** the snippet's link to `assets/diagram.png` is inside an `#if` branch that is false for the course flags
- **THEN** `publish` does not stage `assets/diagram.png` on account of that link
