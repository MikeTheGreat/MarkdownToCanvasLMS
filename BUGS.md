# Known bugs

## `publish` doesn't expand inline snippets in module files

A module item whose URL is built from an inline snippet, such as
`- [Syllabus]($../snippets/inline/CANVAS_COURSE_REFERENCE.md$/assignments/syllabus)`
(College 101 `modules/week-1.md`, where the snippet expands to a Canvas course
URL chosen by course flag), works in `update` but not in `publish`. `publish`
prints `WARNING: content not found, skipping:
modules/$../snippets/inline/CANVAS_COURSE_REFERENCE.md$/assignments/syllabus`
and the item is missing from the published site.

`update`'s `_sync_module` runs `preprocess_snippets` on the module body before
`parse_module_body`, so the item becomes an `ExternalUrl`. `publish` calls
`parse_module_body` on the unexpanded body in two places,
`collect_reachable` and `render_module_overview` (src/markdown_to_canvas/publish.py),
so the literal `$...$` text is resolved as a local path under `modules/`.
The sync probes and `local_orphans` already expand snippets first.

The same gap affects date placeholders: `render_module_overview` expands the
placeholders written in a module file, but one that comes from a snippet the
module file includes stays in the staged page as raw span markup, with no error.

Found on 2026-09-26 while staging the College 101 repo for the publish
link-check change; not yet covered by a test.

Likely fix: in both `publish` functions, call `preprocess_snippets(body,
module_md, repo / "snippets", errors, flags=flags)` after the conditionals and
before `parse_module_body` (stdout suppressed in `collect_reachable`, as it
already does for content files), and add a test with a module item whose URL
comes from an inline snippet.

## `mv` rewrites links inside fenced code blocks

`mv` updates relative links in every `.md` file with `links.transform_links`
(src/markdown_to_canvas/links.py), called from `mv.compute_file_updates`. That
function does not skip fenced code blocks, so a link shown as example text
inside a ```` ``` ```` block is rewritten when the file, or the file the link
names, moves. Everything else in the tool treats fenced code as literal text:
snippet expansion, conditionals and the staleness probe all skip it, and
snippet-link rebasing applies `transform_links` only outside fences.

Found by reading the code on 2026-09-25 while adding snippet-link rebasing; not
yet reproduced with a test.

Likely fix: in `mv.compute_file_updates`, call `transform_links` through
`convert.apply_outside_fences`, as `convert.preprocess_snippets` does, and add
a test that a moved file's fenced example link is unchanged.

## A stub-created module can duplicate an existing Canvas module

`update` refuses to create a module when Canvas already has one with the same
name and the manifest doesn't link it (`_sync_module`, the same-name guard).
Two other creation paths skip that check: `canvas_api.create_stub` makes a
module stub when a page or assignment links to a module file that hasn't been
synced yet, and `create_or_update_module` re-creates a module whose manifest id
was deleted on Canvas. Either can leave two modules with the same name.

Found by reading the code on 2026-09-26 while adding the same-name guard; not
reproduced. The stub path also titles the stub from the filename, not the
module's frontmatter `title`, so a name check there would need to read the
module file's frontmatter first.

## Imported dates have no UTC offset, so Canvas may read them in the wrong time zone

Canvas's IMSCC export writes dates in UTC without an offset: in
`coll101-ol3-12086-f26-college-strategies-export.imscc`, a checkpoint with
`<due_at>2026-11-04T07:59:59</due_at>` has `<all_day_date>2026-11-03</all_day_date>`,
so it is due 23:59:59 Pacific on Nov 3. `import` copies such values unchanged
into `due_dates` (and into commented frontmatter lines), for example
`reply_to_others_due_at = "2026-11-04T07:59:59"`.

Measured on 2026-11-02 in sandbox course 2758791: a checkpoint `dueAt` of
`2026-11-12T23:59:00` (no offset) sent through GraphQL `updateDiscussionTopic`
was stored as `2026-11-13T07:59:00Z`, that is, read as Pacific time, not UTC.
So an imported, offset-less checkpoint date is uploaded 7-8 hours later than
the original (07:59 Pacific the next day instead of 23:59).

Not yet measured: whether REST `due_at`/`unlock_at`/`lock_at` (assignments,
plain discussions, quizzes) read offset-less dates the same way. If they do,
every date `import` writes is affected, not only checkpoint dates.

Likely fix: in `import`, treat an offset-less exported date as UTC and write it
with an explicit offset (either `Z`, or converted to the course's
`default_time_zone` from `course_settings.xml` with that zone's offset), and add
a migration note for repos imported before the fix. First measure the REST case
to confirm the scope.
