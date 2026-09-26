"""Relative-link rewriting shared by `mv` and snippet expansion.

`transform_links` re-expresses the relative links in a Markdown text when the
file (or the text) moves from one folder to another, and/or when the files it
links to move. `mv` uses it to keep links working after a rename; snippet
expansion uses it to rebase a snippet's links, which are written relative to
the snippet file, onto the file that includes it.
"""
from __future__ import annotations

import os
import re
from collections.abc import Callable
from urllib.parse import quote, unquote

# Anchored on "](" rather than the full [text], because link text may contain
# nested brackets (e.g. [[**[x]**]{style=...}](url)). The URL/title group skips
# quoted titles as a unit (so "File(s)" doesn't close the link) and accepts one
# level of balanced parens, which Pandoc allows in paths like "Folder (Old)/x".
MD_LINK_RE = re.compile(
    r'(\])\(((?:[^()"\']|"[^"]*"|\'[^\']*\'|\([^()]*\))*)\)'
)
INLINE_SNIPPET_RE = re.compile(r"\$([^$\n]+\.md)\$")
_HTML_IMG_RE = re.compile(r"<img\b[^>]*/?>", re.IGNORECASE)
_HTML_A_RE = re.compile(r"<a\b[^>]*>", re.IGNORECASE)
_HTML_SRC_ATTR_RE = re.compile(r'\bsrc="([^"]*)"')
_HTML_HREF_ATTR_RE = re.compile(r'\bhref="([^"]*)"')

# Any URL with a scheme (https:, mailto:, data:, tel:, ...) is absolute.
_SCHEME_RE = re.compile(r"^[A-Za-z][A-Za-z0-9+.-]*:")


def is_relative_path_url(url: str) -> bool:
    """True if url is a relative file path that link rewriting should touch.

    Excluded: URLs with a scheme, fragment-only links, root-relative paths,
    empty URLs, anything containing a ``$...$`` inline snippet ref, and
    anything spanning lines (for example the text of an inline snippet whose
    course-flag conditionals have not been evaluated).
    """
    stripped = url.strip()
    if not stripped or stripped.startswith(("#", "/")) or "\n" in stripped:
        return False
    if _SCHEME_RE.match(stripped):
        return False
    return "$" not in stripped


def split_url_title(raw: str) -> tuple[str, str]:
    """Split 'url "title"' into (url, rest_including_space_and_title)."""
    stripped = raw.rstrip()
    for qchar in ('"', "'"):
        if stripped.endswith(qchar):
            start = stripped.rfind(qchar, 0, len(stripped) - 1)
            if start > 0 and stripped[start - 1] == " ":
                return stripped[: start - 1], stripped[start - 1 :]
    return raw, ""


def split_suffix(url: str) -> tuple[str, str]:
    """Split 'path#frag' / 'path?q' into (path, '#frag' / '?q')."""
    m = re.search(r"[?#]", url)
    if m is None:
        return url, ""
    return url[: m.start()], url[m.start() :]


def resolve_repo_relative(base_dir: str, relative_path: str) -> str | None:
    """Resolve a relative path against a repo-relative base directory.

    Returns a normalized repo-relative POSIX path, or None if it escapes the repo.
    """
    if base_dir == ".":
        joined = relative_path
    else:
        joined = base_dir + "/" + relative_path
    normed = os.path.normpath(joined).replace(os.sep, "/")
    if normed.startswith("..") or normed.startswith("/"):
        return None
    return normed


def compute_relative(from_dir: str, to_path: str) -> str:
    """Compute relative path from from_dir to to_path (both repo-relative)."""
    return os.path.relpath(to_path, from_dir).replace(os.sep, "/")


def iter_link_urls(content: str):
    """Yield every URL that transform_links would consider, in order.

    Markdown link/image destinations (``<>`` stripped, title removed) and raw
    HTML ``<img src>`` / ``<a href>`` values. Inline ``$...$`` refs are not
    included. Callers filter with ``is_relative_path_url``.
    """
    for m in MD_LINK_RE.finditer(content):
        url, _title = split_url_title(m.group(2))
        stripped = url.strip()
        if stripped.startswith("<") and stripped.endswith(">"):
            yield stripped[1:-1]
        else:
            yield url
    for tag_re, attr_re in (
        (_HTML_IMG_RE, _HTML_SRC_ATTR_RE),
        (_HTML_A_RE, _HTML_HREF_ATTR_RE),
    ):
        for m in tag_re.finditer(content):
            attr_m = attr_re.search(m.group(0))
            if attr_m is not None:
                yield attr_m.group(1)


def transform_links(
    content: str,
    old_dir: str,
    new_dir: str,
    path_map: dict[str, str],
    *,
    rewrite_inline_snippets: bool = True,
    on_escape: Callable[[str], None] | None = None,
    url_map: Callable[[str], str | None] | None = None,
) -> str:
    """Transform relative links in Markdown content.

    old_dir: repo-relative dir of the file before any move
    new_dir: repo-relative dir of the file after move (same as old_dir if not moved)
    path_map: old_repo_relative → new_repo_relative for moved files
    rewrite_inline_snippets: also rewrite the paths of ``$path.md$`` refs
    on_escape: called with each relative link that resolves outside the repo
        from old_dir (and is not otherwise resolvable); the link is left as is
    url_map: if given, called with each relative link first; a non-None
        return value replaces the link verbatim and skips the normal handling
    """
    file_moved = old_dir != new_dir
    reverse_map = {v: k for k, v in path_map.items()}

    def _transform_url(url: str) -> str | None:
        if not is_relative_path_url(url):
            return None
        if url_map is not None:
            mapped = url_map(url)
            if mapped is not None:
                return mapped

        path_part, suffix = split_suffix(url)
        if not path_part:
            return None
        decoded = unquote(path_part)
        has_encoding = "%" in path_part

        target = resolve_repo_relative(old_dir, decoded)
        if target is None:
            target_from_new = (
                resolve_repo_relative(new_dir, decoded) if file_moved else None
            )
            if target_from_new is not None and target_from_new in reverse_map:
                target = reverse_map[target_from_new]
            else:
                if on_escape is not None:
                    on_escape(url)
                return None

        new_target = path_map.get(target, target)
        target_moved = new_target != target

        if not target_moved and not file_moved:
            return None

        new_rel = compute_relative(new_dir, new_target)
        if has_encoding:
            new_rel = quote(new_rel, safe="/-_.~")

        return new_rel + suffix

    def _replace_md_link(m: re.Match) -> str:
        prefix = m.group(1)
        raw_url = m.group(2)

        url, title_suffix = split_url_title(raw_url)
        # Markdown allows <url> syntax (e.g. for filenames with spaces); strip brackets
        stripped = url.strip()
        bracketed = stripped.startswith("<") and stripped.endswith(">")
        inner = stripped[1:-1] if bracketed else url
        new_url = _transform_url(inner)
        if new_url is None:
            return m.group(0)
        if bracketed:
            new_url = f"<{new_url}>"
        return f"{prefix}({new_url}{title_suffix})"

    def _replace_snippet(m: re.Match) -> str:
        path = m.group(1)
        new_path = _transform_url(path)
        if new_path is None:
            return m.group(0)
        return f"${new_path}$"

    def _replace_html_attr(m: re.Match, attr_re: re.Pattern) -> str:
        tag = m.group(0)
        attr_m = attr_re.search(tag)
        if attr_m is None:
            return tag
        new_url = _transform_url(attr_m.group(1))
        if new_url is None:
            return tag
        return tag[: attr_m.start(1)] + new_url + tag[attr_m.end(1) :]

    if rewrite_inline_snippets:
        content = INLINE_SNIPPET_RE.sub(_replace_snippet, content)
    content = MD_LINK_RE.sub(_replace_md_link, content)
    content = _HTML_IMG_RE.sub(lambda m: _replace_html_attr(m, _HTML_SRC_ATTR_RE), content)
    content = _HTML_A_RE.sub(lambda m: _replace_html_attr(m, _HTML_HREF_ATTR_RE), content)
    return content
