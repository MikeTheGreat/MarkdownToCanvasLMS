# Known bugs

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
