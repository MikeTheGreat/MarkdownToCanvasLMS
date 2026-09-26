# Design

## Context

See proposal.md for motivation and specs/ for the required behavior.

Current code, as read on 2026-09-25:

- `convert.preprocess_snippets` pastes a block snippet's raw text in `_replace`
  and inline `$...$` snippets in `_replace_inline`. Every consumer calls it:
  `sync.py` (content, syllabus, staleness/ref probes at lines ~1670, ~3135,
  ~3152), `quiz.py` (description and question files), `publish.stage_content_markdown`,
  `local_orphans._read_markdown`, and `cp` through `collect_local_refs`.
- `link_rewrite._to_local_key` resolves every href against the including
  file's folder. It is not changed; after rebasing, the pasted hrefs are
  already correct for that folder.
- `mv.transform_links(content, old_dir, new_dir, path_map)` already
  re-expresses every relative link when `old_dir != new_dir`, resolving from
  `old_dir` and writing a path relative to `new_dir`. It handles `<url>`,
  titles, percent-encoding, raw `<img src>` and `<a href>`, and skips
  `http(s):`, `mailto:`, `#` and anything containing `$`. It does not skip
  other schemes (`data:`, `tel:`) and does not skip fenced code.
- In `sync`, anything `preprocess_snippets` adds to `errors` makes the file
  skip upload (`sync.py:2474-2478`).
- `publish.collect_reachable` extracts refs from each file's raw body (after
  conditionals, before snippet expansion) and skips `snippets/` paths.
- Inline `$...$` refs inside a block snippet are not expanded today; they are
  reported as nested includes (checked by running `preprocess_snippets`).
- `repo_format.UpgradeState` can write only the settings file, manifests and
  the in-repo term file.

## Goals / Non-Goals

**Goals:**
- One rebasing implementation, used by every consumer through
  `preprocess_snippets`, and the same link parser as `mv`.

**Non-Goals:**
- Reference-style link definitions (`[id]: url`). Neither `mv` nor rebasing
  handles them.
- Rebasing `PASTE_SNIPPET_INTO_FRONTMATTER` content. Its values are YAML, and
  its path-valued keys (`annotatable_attachment`) are repo-relative already.
- Links in raw HTML tags other than `<img src>` and `<a href>`.

## Decisions

Decisions confirmed by the user in conversation:

1. Rebase at paste time, snippet-relative convention (option 2).
2. Format bump 3 -> 4 with a migration, not an opt-in setting.
3. Migration leaves ambiguous links unchanged and reports them.
4. When every includer resolves a link to one existing file that differs from
   the snippet-relative reading, the includer reading wins (it is what Canvas
   has been showing).
5. Migration counts every `.md` outside `snippets/` and hidden folders as a
   possible includer, `.canvasignore`d files included (the scope `mv` uses).
6. Rebased link forms are the set `mv` rewrites.
7. A snippet link that escapes the repo from the snippet's folder is left
   unchanged and recorded in `errors`, like other snippet errors: `update`
   skips that includer's upload, `--check-all` exits non-zero, and `publish`
   stops before building.
8. The `publish` reachability fix is part of this change.
9. Rebasing reuses `mv`'s link rewriting. `mv.transform_links` and its
   helpers move to a shared module (for example `links.py`); `mv` imports
   them from there, and `preprocess_snippets` calls
   `transform_links(content, snippet_dir, includer_dir, {})` inside
   `apply_outside_fences`. `transform_links` currently returns links that
   escape the repo unchanged without saying so; the shared version gains an
   optional callback so rebasing can report them (decision 7). Alternative
   rejected: a separate parser in `convert.py`, which could drift from `mv`.
10. The shared function treats any URL matching `^[A-Za-z][A-Za-z0-9+.-]*:`
    as absolute, replacing the `http://`/`https://`/`mailto:` list. This also
    changes `mv`, which today rewrites `data:` and `tel:` URLs as paths when
    a file moves.
11. `mv` keeps rewriting links inside fenced code blocks in this change; that
    behavior is recorded in BUGS.md rather than fixed here.

Added after the College101 trial run (confirmed by the user):

12. Migration rule: when all *working* includer readings (those that name an
    existing file) agree, rewrite the link to that file, even if other
    includers resolved it to nothing; those were already broken. Only
    disagreement between working readings, or no existing target anywhere,
    is left for manual review.
13. Snippets may include snippets (block and inline). `preprocess_snippets`
    expands recursively: a snippet's content is expanded relative to the
    snippet file, then rebased onto the file it is pasted into, so rebasing
    composes level by level. Nesting stops at `MAX_SNIPPET_DEPTH = 10` with
    an error naming the chain; that is what stops a snippet including itself.
    `find_referenced_snippets` follows the same nesting (with a visited set),
    so staleness, `flags_used` and `cp` see nested snippets.
14. Because nested refs were never expanded before format 4, migration 3 -> 4
    also converts `$...$` inline refs and block refs to other snippets inside
    snippet files, by the same rule.
15. Snippet-ref detection skips anything that is not a file path (scheme
    URLs, `#`, `/`, `$`, multi-line text) and strips link titles and `<>`.
    This fixes the old nested-include check, which reported `https:`,
    `mailto:` and `#anchor` links as nested includes, and a multi-line
    "path" that appears when an inline snippet's conditionals are not
    evaluated (the passive probes run without flags).

## Risks / Trade-offs

- [Every repo must run `upgrade` before any other command] → The version
  check already produces a clear message telling the user to run it; this is
  the fourth bump using the same path.
- [A migration notice is easy to miss in the output] → Notices use the
  `NOTICE:` prefix already used by migration 2 -> 3. A link the migration
  leaves pointing outside the repo becomes an `update` error on every run
  until it is fixed.
- [An unfixed snippet blocks every includer's upload] → Intended (decision
  7); the error names the snippet and the link, so one edit clears all of
  them.
- [Rebasing changes the HTML of every item that includes a snippet at a
  non-snippet depth] → Only when the old link was broken for that includer
  (the migration keeps working links pointing at the same files). The staleness
  gate is mtime-based, so migrated snippet files re-sync their includers on
  the next full `update`, which is the desired effect.
- [The shared scheme check changes `mv` output for `data:`/`tel:` URLs in
  files that move] → Today `mv` rewrites such a URL as a relative path, which
  is a bug; the change only stops that.

Canvas API behavior this design depends on: none new. The upload calls and
`rewrite_links` are unchanged; only the local hrefs in the pasted Markdown
differ. No Canvas content is deleted or overwritten beyond the normal
re-upload of changed items.

## Migration Plan

- Manifests: no format change beyond the version stamp; migration 3 -> 4
  stamps every `.manifest-*.toml` with 4, like the earlier migrations.
- `course_settings.toml`: only `format_version` and `upgraded_by` change.
- Snippet files: rewritten in place as described in the
  `repo-format-version` delta. Rollback is `git checkout` of `snippets/` and
  `course_settings/course_settings.toml`, plus an older tool version.

## Open Questions

Implementation details not confirmed in conversation. None of them changes
the specs; the tasks assume the proposed answer.

1. **Migration file writes.** Proposed: add a `pending_writes: dict[Path, str]`
   to `UpgradeState`, written by `run_upgrade` after each step unless
   `--noop`. Snippet files are read as UTF-8; one that cannot be decoded is
   skipped with a notice.
2. **Where the migration's scanner lives.** Proposed: a new module (for
   example `snippet_migration.py`) called from `_migrate_3_to_4`, using the
   shared link module's URL extraction and resolution rather than a second
   parser.
3. **Name of the shared module.** `links.py` is a placeholder.
