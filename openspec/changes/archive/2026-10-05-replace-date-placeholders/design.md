# Design

## Context

See proposal.md for motivation and specs/ for the required behavior.

Body text goes through the same steps in every upload path (`sync.py` content,
syllabus, quiz description and question files; `publish.render_page_markdown`):
frontmatter snippet expansion, `apply_conditionals`, `preprocess_snippets`
(which also expands the course-reference snippet), then `markdown_to_html`
(Pandoc), except in `publish`, which writes Markdown for MkDocs and strips Pandoc
spans with `_strip_pandoc_syntax`. An error recorded in `ctx.errors` during these
steps makes the caller print `Skipping upload due to errors` and leave the
manifest entry unsynced.

Staleness is decided by `manifest.needs_sync` (file mtime, referenced snippets'
mtimes, and `flags_used` via `flag_change`); quizzes use `sync._quiz_needs_sync`.
`due_dates` changes are applied by `_apply_due_dates_only` through date-only API
calls, which never re-upload a body.

## Goals / Non-Goals

**Goals:**
- One resolver used by `update`, `publish`, `generate-due-dates` and `cp`, so
  they agree on what a placeholder means.
- Re-upload only the bodies whose quoted text actually changed.

**Non-Goals:**
- Dates that are not in `due_dates` (checkpoints, `relative_due_dates` items
  without an entry). The user decided against them: a two-part assignment will
  be split into two Canvas items, each with its own entry.
- Placeholders in frontmatter or module files.
- Time-zone conversion.
- Showing a list of due dates on the MkDocs site (the TODO.md item stays).

## Decisions

All decisions below were confirmed by the user (1-9 in the explore conversation,
10-17 and the related choices noted in them after the proposal was drafted).

1. **Syntax: a Pandoc bracketed span with class `replace_date_with`.** The
   alternatives considered were a Markdown link into `course_settings.toml` with
   the parameter in the link title, and a `$DATE:...$` token beside inline
   snippets. A span gives named attributes instead of a free-text string to
   parse, shows readable fallback text in a preview, and matches the
   `[...]{style=...}` spans imported course files already have. The class
   name was chosen to be unlikely to collide with real CSS classes and to say
   what it does.
2. **Only `due_dates` entries, by `name`.** Matching reuses
   `find_due_date_override` semantics (exact `name`, and `type` when given) on
   the list after `filter_due_dates_by_flags`. A file without `item` uses its own
   entry. Optional `type=` disambiguates; an ambiguous name is an error.
3. **`field` defaults to `due_at`.**
4. **strftime formats, with a course-wide default** stored in
   `course_settings.toml` with a one-line comment directly above it. The
   default includes the time. `import` writes it.
5. **Shown in the time and offset stored in `due_dates`**, not converted via the
   term file.
6. **Unresolved placeholders are errors**, including sentinel values; the file
   is skipped and the rest of the update continues.
7. **The span and its attributes are removed**, leaving plain text.
8. **`publish` expands placeholders too.**
9. **Manifest record for staleness, `generate-due-dates` check, `cp` warning**,
   and **a format version bump (9 -> 10)** even though it is not strictly
   required.

10. **Expand at the Markdown level, after `preprocess_snippets` and before
    Pandoc.** A new `date_placeholders.expand(text, context, errors)` replaces
    each span with the escaped date text, outside fenced code blocks (via
    `apply_outside_fences`) and outside inline code. The alternative was to let
    Pandoc emit `<span class="replace_date_with" data-item=...>` and substitute
    in the HTML. That is more robust about bracket nesting, but `publish` has
    no HTML stage, so it would need a second implementation. At the Markdown
    level one function serves every path, including snippets (expanded first,
    so a placeholder inside a snippet is resolved for the including file). The
    span is matched by a regex on `[TEXT]{ATTRS}` where `TEXT` has no brackets
    and `ATTRS` contains `.replace_date_with`. This is why the spec forbids
    brackets in the fallback text. Safety net: after `markdown_to_html`, any
    remaining `replace_date_with` in the HTML (a span the regex did not match)
    is an error, and in `publish` any remaining `.replace_date_with` in the
    Markdown is an error. The inserted text is Markdown-escaped (`*`, `_`, `[`,
    `]`, `\`, backticks).
11. **Context object.** `DatePlaceholderContext(due_dates, default_format,
    own_title, own_type)`, built once per run (the list and format) and per
    file (own title/type). For a quiz question file, own title/type is the
    quiz's. For pages, announcements, the syllabus and question banks, own is
    `None`, and a placeholder without `item` there is an error. Placeholders are
    expanded in body text of pages, assignments, discussions, announcements,
    the syllabus, quiz descriptions, quiz and question-bank question files, and
    their snippets; not in frontmatter or module files.
12. **No-padding directives are handled by the tool.** Before calling
    `strftime`, `%-d`, `%-m`, `%-H`, `%-I`, `%-M` and `%-j` are replaced with the
    unpadded number. Python passes `%-d` to the platform C library, which
    supports it on Linux and macOS but not on Windows.
13. **Key name `replace_date_with_format`, default `"%A, %B %-d at %-I:%M %p"`**
    ("Tuesday, October 27 at 11:59 PM"). It is placed directly before
    `due_dates` when that key exists (else before the first table header) via
    `toml_write.insert_top_level_key`, and added to
    `sync._NON_METADATA_SETTINGS_KEYS` so editing it does not trigger a
    course-settings upload (the staleness record handles the bodies).
14. **Manifest format: a `dates_used` array of inline tables on the file's
    entry**, `[{item = "HW 1", type = "", field = "due_at", format = "%B %-d", text = "October 27"}]`.
    `item` is the resolved entry name (so an omitted `item` is recorded as the
    own title); `format` is the effective format (so a change to the default
    format changes the result). Staleness recomputes each record against the
    current list and default format: different text, or an error, means stale.
    This is checked in `needs_sync` (a new optional `current_dates` argument
    shaped like `current_flags`) and in `_quiz_needs_sync`. A quiz's records
    cover its description and all its question files. Old manifests have no
    `dates_used`, which means nothing to compare, so they are tolerated without
    migration. An older tool cannot read a version-10 manifest because of the
    format check, so it never drops the record.
15. **`generate-due-dates`.** `plan_generation` builds the post-plan entry list
    (current entries with the changed fields applied, plus added entries) and
    runs the resolver over every placeholder in the files `iter_gradeable_content`
    and the page/syllabus/quiz walks cover (snippets expanded, conditionals not
    applied, so placeholders in every branch are checked). Failures go to
    `GenerationPlan.errors`, which already prints before the prompt and exits
    non-zero after writing.
16. **`cp`.** `_plan_warnings` scans each copied file's text and its referenced
    snippets with a `find_placeholders` helper and checks named items against
    the destination's `load_due_dates`.
17. **Errors in `publish`** follow its existing convention: collected, and
    `run_publish` stops before writing, as it does for broken local links.
    Under that convention one bad placeholder stops the whole publish, unlike
    `update`.

18. **The newer-on-Canvas check compares against the later of the local
    effective mtime and `last_synced`** (confirmed by the user during
    implementation). `_canvas_is_newer` used to compare Canvas's `updated_at`
    only with the local mtime. A re-sync caused by a changed quoted date leaves
    the file older than Canvas's `updated_at`, which the tool's own last upload
    set, so every such re-upload would have been skipped as "Canvas is newer".
    For a locally edited file the mtime is already later than `last_synced`, so
    behavior there is unchanged. The same change fixes course-flag flips,
    which had the same latent problem (their test passed only because the mock
    `updated_at` was unparsable). Alternatives rejected: applying it to
    date-driven re-uploads only (leaves the flag bug), and bypassing the check
    the way `fix-manifest --clean` does (overwrites Canvas edits).

## Canvas API behavior relied on

No new API calls. A placeholder-driven re-upload uses the existing body upload
of each content type (verified: in use by every `update`). Canvas renders the
uploaded text as written. The date in the text does not follow the student's
Canvas time-zone setting, while Canvas's own due-date display does. That
difference is expected and involves no API behavior.

## Overwriting Canvas content

A date change can now re-upload a body nobody edited locally. That upload goes
through the newer-on-Canvas check (`_canvas_is_newer`, decision 18), so an edit
made in Canvas after the last upload is not overwritten without
`--force-overwrite`. Nothing is deleted. False positives and negatives come only
from clock difference: `last_synced` is the local clock, `updated_at` Canvas's.
A local clock behind Canvas's makes a re-upload look blocked (safe: skipped and
listed in the summary); a local clock ahead can let an edit made in Canvas within
that difference of the last upload be overwritten.

## Risks / Trade-offs

- [The regex misses an unusual span (multi-line attributes, brackets in the
  text)] → the post-conversion leftover check turns it into an error instead of
  a silent upload.
- [Renaming an item's title breaks placeholders that name it] → it is an error
  on the next `update` and in `generate-due-dates`. The same rename already
  breaks the `due_dates` match.
- [A large `generate-due-dates` shift re-uploads many bodies in one run] →
  expected; each re-upload is one API call, the same as an edit.
- [Staleness checking costs a re-resolution per file with records] → small:
  records are few and the due_dates list is loaded once per run.

## Migration Plan

`FORMAT_VERSION` becomes 10; `MIGRATIONS[9] = _migrate_9_to_10` adds the
commented key text-level (as 8 -> 9 does) and stamps manifests. Rollback: an
older tool refuses version-10 repos, so going back means using the older tool
on a checkout from before the upgrade.

## Value with no UTC offset

Part of decision 5: a `due_dates` value with no offset is shown as written. The
term file's time zone is not consulted, because `update` does not read the term
file and every value `generate-due-dates` writes carries an offset.
