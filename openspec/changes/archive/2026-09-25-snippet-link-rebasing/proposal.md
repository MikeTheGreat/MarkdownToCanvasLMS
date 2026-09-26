# Proposal

## Why

A block snippet is pasted into each including file as raw text before Pandoc
runs, so relative links and image paths inside the snippet are resolved from
the including file's folder, not the snippet's. A snippet link works only for
includers at a compatible depth, and a snippet written to work from
`pages/week1/` breaks when included from `pages/`. The rest of the tool
already disagrees with this: `mv` rewrites links inside snippet files as if
they were relative to the snippet, and `find-local-orphans` scans each snippet
file with snippet-relative resolution. `publish` also fails to stage files
linked only from inside a snippet (recorded in BUGS.md).

## What Changes

- **BREAKING** Relative links and image paths in a block snippet are resolved
  relative to the snippet file. When the snippet is pasted, each one is
  rewritten so that it points at the same file from the including file's
  folder. The link forms rebased are the ones `mv` rewrites: Markdown links
  and images (including the `<url>` form and titles) and raw HTML `<img src>`
  and `<a href>`. Absolute URLs (anything with a scheme), `#anchor`-only
  links, paths starting with `/`, links containing `$...$` inline snippet
  refs, and anything inside fenced code blocks are left unchanged.
- Inline `$path.md$` snippets are not rebased; their content is a URL
  fragment, not a link.
- Snippets can include snippets (block and inline), resolved relative to the
  containing snippet, up to 10 levels deep; deeper nesting (including a
  snippet that includes itself) is an error.
- A snippet link that points outside the repo from the snippet's folder is
  an error, handled like other snippet errors: `update` skips uploading the
  including file and `publish` stops before building.
- The repo format version goes from 3 to 4. Migration 3 -> 4 in `upgrade`
  rewrites links inside snippet files from the old includer-relative reading
  to the snippet-relative reading when every includer agrees on the target,
  and lists the links it could not convert.
- `publish` follows links inside included snippets when deciding what to
  stage, fixing the BUGS.md entry.

### Existing mechanisms and how this relates to them

- Workarounds that exist today and keep working: including a snippet only
  from files at one depth; using absolute Canvas URLs; building course URLs
  with `$../snippets/inline/CANVAS_COURSE_REFERENCE.md$`. The change makes the
  first unnecessary and does not affect the other two.
- `mv` (`transform_links`) already treats a snippet's links as relative to
  the snippet and rewrites them when the snippet or its targets move. This
  change makes `update` and `publish` read them the same way. `mv` needs no
  behavior change beyond sharing the absolute-URL check (see design), which
  stops it rewriting `data:` and other scheme URLs as paths.
- `find-local-orphans` already scans snippet files as sources with
  snippet-relative resolution, and also scans each includer's pasted text.
  After the change the two readings agree.
- `cp` finds a snippet's assets through the includer's pasted text; it picks
  up the rebased links without its own change.
- No TODO.md item covers this. The change fixes the one BUGS.md entry.

### Core subcommands affected

- **update**: yes; pastes snippets through the shared expansion step.
- **publish**: yes; staging pastes snippets through the same step, and the
  reachability walk is fixed.
- **mv**: behavior unchanged; it already uses the snippet-relative reading.
  Shares the absolute-URL check with the rebasing code.
- **import**: not affected in behavior. It writes only the inline
  `CANVAS_COURSE_REFERENCE` snippet, which is not rebased, and it records the
  current format version (4) automatically.

## Capabilities

### New Capabilities
- `snippet-links`: how relative links inside a block snippet are resolved and
  rewritten when the snippet is pasted, and how `update`, `publish`, `mv`,
  `cp` and `find-local-orphans` treat them.

### Modified Capabilities
- `repo-format-version`: adds Migration 3 to 4, which converts existing
  snippet links to the snippet-relative convention.

## Impact

- `convert.preprocess_snippets` (the one expansion step every consumer
  calls: sync, quiz, publish staging, local_orphans, cp).
- `publish.collect_reachable`.
- `mv.transform_links` (absolute-URL check, shared with the rebasing code).
- `repo_format.py`: `FORMAT_VERSION = 4`, new migration, and a way for a
  migration to write files other than settings and manifests.
- Every existing course repo must run `markdown-to-canvas upgrade` before
  other commands will run on it.
- Tests for rebasing, migration, publish reachability; README.md,
  ARCHITECTURE.md, BUGS.md updates.
- No Canvas API behavior changes: the HTML sent to Canvas differs only in
  which local file a snippet link points to.
