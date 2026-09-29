"""Post-Pandoc HTML link/img rewriting."""

from __future__ import annotations

import re
from pathlib import Path
from typing import TYPE_CHECKING, Any, Callable
from urllib.parse import unquote

from .links import has_url_scheme, is_relative_path_url, split_suffix

if TYPE_CHECKING:
    from .ignore import IgnoreMatcher

ManifestDict = dict[str, dict[str, Any]]

_IMG_RE = re.compile(r"<img\b[^>]*/?>", re.IGNORECASE)
_A_RE = re.compile(r"<a\b[^>]*>", re.IGNORECASE)
_SRC_ATTR_RE = re.compile(r'\bsrc="([^"]*)"')
_HREF_ATTR_RE = re.compile(r'\bhref="([^"]*)"')

_FOLDER_TO_TYPE = {
    "pages": "page",
    "assignments": "assignment",
    "discussions": "discussion",
    "announcements": "announcement",
    "assets": "file",
    "quizzes": "quiz",
    "modules": "module",
}


def infer_canvas_type(local_path: str) -> str:
    folder = local_path.split("/")[0]
    return _FOLDER_TO_TYPE.get(folder, "page")


def canvas_content_url(entry: dict[str, Any], course_id: int) -> str:
    t = entry["canvas_type"]
    if t == "file":
        return entry["canvas_url"]
    if t == "page":
        return f"/courses/{course_id}/pages/{entry['canvas_url']}"
    if t == "assignment":
        return f"/courses/{course_id}/assignments/{entry['canvas_id']}"
    if t in ("discussion", "announcement"):
        # Announcements are discussion topics in Canvas (is_announcement=true).
        return f"/courses/{course_id}/discussion_topics/{entry['canvas_id']}"
    if t == "quiz":
        return f"/courses/{course_id}/quizzes/{entry['canvas_id']}"
    if t == "module":
        return f"/courses/{course_id}/modules#module_{entry['canvas_id']}"
    raise ValueError(f"Unknown canvas_type: {t!r}")


def _to_local_key(href: str, source_file: Path, course_root: Path) -> str | None:
    """Convert a relative href to a course-root-relative key, or None if external/anchor.

    A ``?query``/``#fragment`` suffix is dropped. None also covers any scheme
    URL (``https:``, ``tel:``, ``data:``, ...) and paths outside the repo.
    """
    if href.startswith("#") or has_url_scheme(href):
        return None
    path_part, _suffix = split_suffix(href)
    resolved = (source_file.parent / unquote(path_part)).resolve()
    try:
        return resolved.relative_to(course_root.resolve()).as_posix()
    except ValueError:
        return None


def extract_local_refs(html: str, source_file: Path, course_root: Path) -> set[str]:
    """Return local course-root-relative keys for all local <img src>/<a href> refs in html."""
    keys: set[str] = set()
    for value in _iter_ref_attrs(html):
        key = _to_local_key(value, source_file, course_root)
        if key:
            keys.add(key)
    return keys


_ESCAPES_REPO = (
    "relative path resolves outside the course repo (check the number of ../ segments)"
)
_IS_DIRECTORY = (
    "local path is a directory, not a file (check for a link with a missing URL)"
)
_NOT_FOUND = "local file not found"


def _classify_ref(
    href: str, source_file: Path, course_root: Path
) -> tuple[str | None, str | None]:
    """Return (target, problem) for one <img src>/<a href> value.

    target is None when href is not a local path (external URL, anchor,
    root-relative); otherwise it is the course-root-relative key, or href
    itself when the path escapes the repo. problem is None when target is an
    existing file, else the error reason.
    """
    local_key = _to_local_key(href, source_file, course_root)
    if local_key is None:
        if is_relative_path_url(href):
            # Too many `../` segments. Passing it through would publish a
            # link that cannot resolve.
            return href, _ESCAPES_REPO
        return None, None
    local_file = course_root / local_key
    # A directory match almost always means a markdown link with a
    # blank/missing URL (e.g. `[text]( "title")`), which resolves to the
    # source file's own folder rather than a real target — treat it as an
    # error rather than stub-creating a Canvas item named after the folder.
    if local_file.is_dir():
        return local_key, _IS_DIRECTORY
    if not local_file.exists():
        return local_key, _NOT_FOUND
    return local_key, None


def _source_desc(source_file: Path, course_root: Path) -> Path:
    try:
        return source_file.relative_to(course_root)
    except ValueError:
        return source_file


def _iter_ref_attrs(html: str):
    """Yield the src/href value of every <img>/<a> tag in html."""
    for tag_re, attr_re in ((_IMG_RE, _SRC_ATTR_RE), (_A_RE, _HREF_ATTR_RE)):
        for m in tag_re.finditer(html):
            attr_m = attr_re.search(m.group(0))
            if attr_m:
                yield attr_m.group(1)


def check_local_links(
    html: str, source_file: Path, course_root: Path, errors: list[str]
) -> None:
    """Record an error for each local <img>/<a> ref that is missing or escapes the repo.

    The read-only counterpart of rewrite_links(), for callers that publish the
    source files themselves (``publish``). A message already in ``errors`` is
    not added again, since a file can be staged twice (front page and nav).
    """
    src = _source_desc(source_file, course_root)
    for value in _iter_ref_attrs(html):
        target, problem = _classify_ref(value, source_file, course_root)
        if problem is None:
            continue
        msg = f"  {src}: {problem}: {target}"
        if msg not in errors:
            print(f"  ERROR: {problem}: {target}")
            errors.append(msg)


def _with_fragment(url: str, entry: dict[str, Any], href: str) -> str:
    """Carry a ``#fragment`` from the local href over to the Canvas URL.

    Only for content pages; a file URL may carry its own query, and a module
    URL already ends in ``#module_<id>``.
    """
    _path, suffix = split_suffix(href)
    hash_at = suffix.find("#")
    if hash_at < 0 or entry["canvas_type"] in ("file", "module"):
        return url
    return url + suffix[hash_at:]


# Types create_stub cannot make: a Canvas announcement is posted the moment it
# is created, so there is no unpublished placeholder to link to.
_UNSTUBBABLE_TYPES = frozenset({"announcement"})
# _resolve_entry's marker for a link to an unposted announcement.
_DEFERRED: dict[str, Any] = {}


def rewrite_links(
    html: str,
    source_file: Path,
    course_root: Path,
    manifest: ManifestDict,
    course_id: int,
    stub_creator: Callable[[str, str], dict[str, Any]],
    errors: list[str] | None = None,
    deferred: list[str] | None = None,
    matcher: IgnoreMatcher | None = None,
) -> str:
    """Rewrite local <img src> and <a href> references to Canvas URLs.

    `stub_creator(local_path, canvas_type)` is called when a referenced file
    exists locally but has no manifest entry yet. It must create a Canvas stub,
    update the manifest, flush to disk, and return the new manifest entry.

    An announcement with no manifest entry is the exception: Canvas has no
    draft state for announcements, so a stub would post an empty announcement
    to students. The link is left unresolved instead (the ``<a>`` loses its
    href and renders as plain text; an ``<img>`` is dropped), a warning is
    printed, and the target's key is appended to ``deferred`` so the caller
    can leave the source file stale and retry it once the announcement posts.

    A link to a file that ``matcher`` excludes (.canvasignore) is an error,
    whether or not the file is already on Canvas: nothing is stub-created, and
    the error lands in ``errors`` so the caller skips the upload and leaves the
    source file stale. The error repeats on every update until the link is
    removed or the target is no longer ignored.
    """

    def _resolve_entry(attr_value: str) -> tuple[str | None, dict[str, Any] | None]:
        """Return (local_key, entry), (target, None) for a broken ref,
        (target, _DEFERRED) for an unposted announcement, or (None, None)
        for a non-local URL."""
        local_key, problem = _classify_ref(attr_value, source_file, course_root)
        if local_key is None:
            return None, None
        if problem is not None:
            print(f"  ERROR: {problem}, removing tag: {local_key}")
            if errors is not None:
                src = _source_desc(source_file, course_root)
                errors.append(f"  {src}: {problem}, removing tag: {local_key}")
            return local_key, None  # signals removal
        if matcher is not None and matcher.is_excluded(
            course_root / local_key, course_root
        ):
            src = _source_desc(source_file, course_root)
            msg = (
                f"{src}: links to {local_key}, which .canvasignore excludes; "
                f"{src} will not be uploaded until the link is removed or the "
                "file is no longer ignored"
            )
            print(f"  ERROR: {msg}")
            if errors is not None:
                errors.append(f"  {msg}")
            return local_key, None
        if local_key not in manifest:
            canvas_type = infer_canvas_type(local_key)
            if canvas_type in _UNSTUBBABLE_TYPES:
                print(
                    f"  WARNING: link to {local_key} left unresolved: that "
                    "announcement has not been posted to Canvas yet"
                )
                if deferred is not None and local_key not in deferred:
                    deferred.append(local_key)
                return local_key, _DEFERRED
            entry = stub_creator(local_key, canvas_type)
            manifest[local_key] = entry
        return local_key, manifest[local_key]

    def _replace_img(m: re.Match) -> str:
        tag = m.group(0)
        src_m = _SRC_ATTR_RE.search(tag)
        if src_m is None:
            return tag
        local_key, entry = _resolve_entry(src_m.group(1))
        if local_key is None:
            return tag  # external — unchanged
        if entry is None or entry is _DEFERRED:
            return ""  # local file missing or not on Canvas yet — remove tag
        new_url = _with_fragment(canvas_content_url(entry, course_id), entry, src_m.group(1))
        return tag[: src_m.start(1)] + new_url + tag[src_m.end(1) :]

    def _replace_a(m: re.Match) -> str:
        tag = m.group(0)
        href_m = _HREF_ATTR_RE.search(tag)
        if href_m is None:
            return tag
        local_key, entry = _resolve_entry(href_m.group(1))
        if local_key is None:
            return tag  # external/anchor — unchanged
        if entry is None:
            return ""  # local file missing — remove tag
        if entry is _DEFERRED:
            # Keep the <a> so its </a> still matches; without an href the
            # link text renders as plain text.
            return tag[: href_m.start(0)].rstrip() + tag[href_m.end(0) :]
        new_url = _with_fragment(canvas_content_url(entry, course_id), entry, href_m.group(1))
        return tag[: href_m.start(1)] + new_url + tag[href_m.end(1) :]

    html = _IMG_RE.sub(_replace_img, html)
    html = _A_RE.sub(_replace_a, html)
    return html
