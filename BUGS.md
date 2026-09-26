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
