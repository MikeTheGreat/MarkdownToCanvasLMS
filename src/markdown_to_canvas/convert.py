"""Markdown → HTML conversion and snippet preprocessing."""

from __future__ import annotations

import re
import subprocess
from pathlib import Path
from typing import Any
from urllib.parse import unquote

import pypandoc
import yaml

from .links import (
    is_relative_path_url,
    resolve_repo_relative,
    split_suffix,
    split_url_title,
    transform_links,
)

_SNIPPET_LINK_RE = re.compile(r"\[([^\]]*)\]\(([^)]+)\)")

# Matches $path.md$ — an inline snippet ref embedded anywhere in text, including
# inside Markdown link URLs.  Requiring the .md suffix avoids false positives on
# math expressions ($x^2$) and currency values ($5.99$).
_INLINE_SNIPPET_RE = re.compile(r"\$([^$\n]+\.md)\$")

# Matches a standalone [PASTE_SNIPPET_INTO_FRONTMATTER](path) line — used to
# merge a shared YAML snippet's keys into a file's frontmatter. Must be the
# only thing on the line (surrounding whitespace is allowed).
_FRONTMATTER_SNIPPET_RE = re.compile(
    r"^\[PASTE_SNIPPET_INTO_FRONTMATTER\]\(([^)]+)\)$"
)

_IMG_TAG_RE = re.compile(r"<img\b[^>]*/?>", re.IGNORECASE)
_ALT_ATTR_RE = re.compile(r'\balt="([^"]*)"')
_ROLE_ATTR_RE = re.compile(r'\brole="[^"]*"')
_FENCE_DELIM_RE = re.compile(r"^\s{0,3}(`{3,}|~{3,})(.*)$")


def split_fenced_segments(text: str) -> list[tuple[bool, str]]:
    """Split text into (is_fenced, segment) chunks, in document order.

    A fenced segment runs from its opening ``` / ~~~ line through the matching
    closing line (same fence character, at least as long, nothing else on the
    line); an unclosed fence runs to the end of the text. Fence-lookalikes
    *inside* a fenced segment are plain content, so a block nested in a longer
    outer fence (e.g. a ``` example shown inside a ````markdown block) stays
    part of the outer block.
    """
    segments: list[tuple[bool, str]] = []
    plain: list[str] = []
    fenced: list[str] = []
    close_char, close_len = "", 0
    for line in text.splitlines(keepends=True):
        m = _FENCE_DELIM_RE.match(line)
        if not fenced:
            if m:
                if plain:
                    segments.append((False, "".join(plain)))
                    plain = []
                fenced.append(line)
                close_char, close_len = m.group(1)[0], len(m.group(1))
            else:
                plain.append(line)
        else:
            fenced.append(line)
            if (
                m
                and m.group(1)[0] == close_char
                and len(m.group(1)) >= close_len
                and not m.group(2).strip()
            ):
                segments.append((True, "".join(fenced)))
                fenced = []
    if plain:
        segments.append((False, "".join(plain)))
    if fenced:
        segments.append((True, "".join(fenced)))
    return segments


def iter_lines_with_fence_info(text: str):
    """Yield (line, is_fenced) for each line of text (without newlines).

    Fence delimiter lines count as fenced. Line-based parsers use this so that
    structure-lookalikes inside code blocks (question links, module items,
    ## headings, …) are treated as literal text.
    """
    for is_fenced, seg in split_fenced_segments(text):
        for line in seg.splitlines():
            yield line, is_fenced


def apply_outside_fences(text: str, transform) -> str:
    """Apply transform (str → str) to the text between fenced code blocks,
    leaving the fenced blocks byte-for-byte intact."""
    return "".join(
        seg if is_fenced else transform(seg)
        for is_fenced, seg in split_fenced_segments(text)
    )


def warn(msg: str, errors: list[str] | None) -> None:
    """Print a message with the standard two-space indent and, if an error
    accumulator is provided, record it there as well."""
    print(f"  {msg}")
    if errors is not None:
        errors.append(msg)


def parse_frontmatter(text: str) -> tuple[dict[str, Any], str]:
    """Return (frontmatter_dict, body_text). Body excludes the frontmatter block."""
    if not text.startswith("---\n"):
        return {}, text
    try:
        end = text.index("\n---\n", 4)
    except ValueError:
        return {}, text
    return yaml.safe_load(text[4:end]) or {}, text[end + 5 :]


#: How deep snippets may include snippets before expansion stops with an error.
#: A snippet that (directly or indirectly) includes itself hits this limit.
MAX_SNIPPET_DEPTH = 10


def preprocess_snippets(
    text: str,
    source_file: Path,
    snippets_dir: Path,
    errors: list[str] | None = None,
    flags: dict[str, bool] | None = None,
) -> str:
    """Replace snippet references with the snippet file's contents.

    Two forms are supported:

    1. **Inline** — ``$path.md$`` anywhere in text (path relative to source file).
       The content is stripped of leading/trailing whitespace, making it safe
       to embed inside a Markdown link URL::

           [Modules](https://example.com/courses/$../snippets/inline/CANVAS_COURSE_ID.md$/modules)

    2. **Block** — ``[display text](path.md)`` where the path resolves into
       the snippets directory.  The full file content replaces the link.
       Useful for reusable policy paragraphs, office-hour blocks, etc.

    Snippets may include snippets, in either form. A reference inside a
    snippet is relative to that snippet file, and so are its links: a block
    snippet's links are rebased onto the file it is pasted into. Nesting
    deeper than ``MAX_SNIPPET_DEPTH`` is an error and that reference is left
    unexpanded (this is what stops a snippet that includes itself).

    When ``flags`` is given, each snippet's content has its course-flag
    conditionals (#if/#elif/#else/#endif) evaluated before insertion; a
    snippet whose directives error contributes an error and the reference is
    left unexpanded, matching the other snippet-error behaviors.
    """
    # Local import: conditionals.py imports split_fenced_segments/warn from
    # this module, so a top-level import here would be circular.
    from .conditionals import apply_conditionals

    resolved_snippets_dir = snippets_dir.resolve()
    repo_root = resolved_snippets_dir.parent

    try:
        rel_source = source_file.relative_to(snippets_dir.parent)
    except ValueError:
        rel_source = source_file

    def _report_error(msg: str) -> None:
        warn(msg, errors)

    def _desc(path: Path) -> str:
        try:
            return path.relative_to(repo_root).as_posix()
        except ValueError:
            return path.name

    def _dir_of(path: Path) -> str | None:
        """Repo-relative folder of path; None when it is not inside the repo."""
        try:
            return path.resolve().parent.relative_to(repo_root).as_posix()
        except ValueError:
            return None

    def _expand_text(text: str, file: Path, chain: tuple[Path, ...]) -> str:
        """Expand the snippet refs in text, which is the content of ``file``
        (the including file, or a snippet at depth ``len(chain)``)."""
        where = rel_source if not chain else _desc(file)

        def _load_snippet(
            link_target: str, snippet_ref: str, is_inline: bool
        ) -> tuple[str, Path] | None:
            """Resolve link_target to a snippet file and expand it. Returns
            (content, path) or None to leave the reference as written."""
            if not is_relative_path_url(link_target):
                return None
            target_path = (file.parent / link_target).resolve()
            if not target_path.is_relative_to(resolved_snippets_dir):
                if is_inline or "snippets" in Path(link_target).parts:
                    _report_error(
                        f"ERROR: {where}: snippet path {snippet_ref} "
                        f"resolves outside the snippets directory — check that the "
                        f"relative path is correct for the file's current location"
                    )
                return None
            if not target_path.exists():
                _report_error(f"ERROR: snippet not found: {target_path}")
                return None
            if len(chain) >= MAX_SNIPPET_DEPTH:
                path = " -> ".join(_desc(p) for p in (*chain, target_path))
                _report_error(
                    f"ERROR: {rel_source}: snippets nested more than "
                    f"{MAX_SNIPPET_DEPTH} levels deep ({path}) — check for a "
                    f"snippet that includes itself"
                )
                return None
            content = target_path.read_text()
            if flags is not None:
                content = apply_conditionals(content, flags, _desc(target_path), errors)
                if content is None:
                    return None  # directive error reported; leave the ref unexpanded
            content = _expand_text(content, target_path, (*chain, target_path))
            return content, target_path

        def _replace_inline(m: re.Match) -> str:
            """Expand a $path.md$ inline snippet ref (content is stripped)."""
            result = _load_snippet(m.group(1), m.group(0), is_inline=True)
            if result is None:
                return m.group(0)
            content, _ = result
            return content.strip()

        def _replace(m: re.Match) -> str:
            link_target, _title = split_url_title(m.group(2))
            link_target = link_target.strip()
            if link_target.startswith("<") and link_target.endswith(">"):
                link_target = link_target[1:-1]
            result = _load_snippet(link_target, m.group(0), is_inline=False)
            if result is None:
                return m.group(0)
            content, target_path = result
            return _rebase_snippet_links(content, target_path, file)

        def _expand(segment: str) -> str:
            # Pass 1: expand $path.md$ inline snippet refs (stripped, safe for URLs)
            segment = _INLINE_SNIPPET_RE.sub(_replace_inline, segment)
            # Pass 2: expand [text](snippet_path) block snippet links
            return _SNIPPET_LINK_RE.sub(_replace, segment)

        # Snippet refs inside fenced code blocks are literal example text.
        return apply_outside_fences(text, _expand)

    def _rebase_snippet_links(content: str, snippet_path: Path, into: Path) -> str:
        """Re-express the snippet's links (written relative to the snippet
        file) relative to ``into``, the file it is pasted into."""
        includer_dir = _dir_of(into)
        if includer_dir is None:
            return content
        snippet_dir = snippet_path.parent.relative_to(repo_root).as_posix()
        snippet_desc = _desc(snippet_path)

        def _on_escape(url: str) -> None:
            _report_error(
                f"ERROR: {rel_source}: snippet {snippet_desc} links {url}, which "
                f"points outside the course repo from the snippet's folder — "
                f"links in a snippet are relative to the snippet file"
            )

        def _keep_if_same_target(url: str) -> str | None:
            # A link that already names the same file from the includer (an
            # includer at the snippet's depth) is pasted exactly as written.
            path = unquote(split_suffix(url)[0])
            from_snippet = resolve_repo_relative(snippet_dir, path)
            if from_snippet is not None and from_snippet == resolve_repo_relative(
                includer_dir, path
            ):
                return url
            return None

        return apply_outside_fences(
            content,
            lambda seg: transform_links(
                seg, snippet_dir, includer_dir, {},
                rewrite_inline_snippets=False, on_escape=_on_escape,
                url_map=_keep_if_same_target,
            ),
        )

    return _expand_text(text, source_file, ())


def find_referenced_snippets(text: str, source_file: Path, snippets_dir: Path) -> set[Path]:
    """Return the set of existing snippet files referenced anywhere in text,
    including the snippets those snippets reference (at any depth).

    For staleness checks only: resolves every ``$path.md$`` / ``[text](path)``
    candidate (this also catches ``PASTE_SNIPPET_INTO_FRONTMATTER`` references,
    which use the same ``[text](path)`` syntax) and keeps the ones that land
    inside ``snippets_dir`` and exist; a reference inside a snippet is resolved
    from that snippet's folder. Unlike ``preprocess_snippets`` /
    ``expand_frontmatter_snippets``, this never reports errors — it's a
    passive probe, not part of the expansion pipeline. Refs inside fenced
    code blocks are ignored, matching what expansion does.
    """
    resolved_snippets_dir = snippets_dir.resolve()
    found: set[Path] = set()

    def _scan(text: str, file: Path) -> None:
        def _maybe_add(link_target: str) -> None:
            if not is_relative_path_url(link_target):
                return
            target_path = (file.parent / link_target).resolve()
            if (
                target_path.is_relative_to(resolved_snippets_dir)
                and target_path.is_file()
                and target_path not in found
            ):
                found.add(target_path)
                try:
                    _scan(target_path.read_text(), target_path)
                except (OSError, UnicodeDecodeError):
                    pass

        for is_fenced, seg in split_fenced_segments(text):
            if is_fenced:
                continue
            for m in _INLINE_SNIPPET_RE.finditer(seg):
                _maybe_add(m.group(1))
            for m in _SNIPPET_LINK_RE.finditer(seg):
                target, _title = split_url_title(m.group(2))
                target = target.strip()
                if target.startswith("<") and target.endswith(">"):
                    target = target[1:-1]
                _maybe_add(target)

    _scan(text, source_file)
    return found


def expand_frontmatter_snippets(
    frontmatter: dict[str, Any],
    body: str,
    source_file: Path,
    snippets_dir: Path,
    errors: list[str] | None = None,
) -> tuple[dict[str, Any], str]:
    """Merge PASTE_SNIPPET_INTO_FRONTMATTER references into frontmatter.

    A file may lead its body with one or more lines of the form::

        [PASTE_SNIPPET_INTO_FRONTMATTER](../../snippets/worksheet-defaults.md)
        [PASTE_SNIPPET_INTO_FRONTMATTER](../../snippets/another-snippet.md)

    Blank/whitespace-only lines between or around them are ignored. Each
    referenced file is parsed as a YAML mapping and its keys are merged into
    a copy of ``frontmatter`` (later snippets override earlier ones; the
    file's own frontmatter always wins over snippet values). The marker
    lines are stripped from the returned body. If the body has no such
    leading lines, ``(frontmatter, body)`` is returned unchanged.
    """
    resolved_snippets_dir = snippets_dir.resolve()
    try:
        rel_source = source_file.relative_to(snippets_dir.parent)
    except ValueError:
        rel_source = source_file

    def _report_error(msg: str) -> None:
        warn(msg, errors)

    lines = body.splitlines(keepends=True)

    # Lookahead: only enter "marker mode" if the first non-blank line is a
    # PASTE_SNIPPET_INTO_FRONTMATTER reference, so ordinary files (which may
    # happen to start with blank lines) are left completely untouched.
    i = 0
    while i < len(lines) and lines[i].strip() == "":
        i += 1
    if i >= len(lines) or not _FRONTMATTER_SNIPPET_RE.match(lines[i].strip()):
        return frontmatter, body

    defaults: dict[str, Any] = {}
    while i < len(lines):
        stripped = lines[i].strip()
        if stripped == "":
            i += 1
            continue
        m = _FRONTMATTER_SNIPPET_RE.match(stripped)
        if not m:
            break
        i += 1
        link_target = m.group(1)
        target_path = (source_file.parent / link_target).resolve()
        if not target_path.is_relative_to(resolved_snippets_dir):
            _report_error(
                f"ERROR: {rel_source}: frontmatter snippet path {link_target} "
                f"resolves outside the snippets directory — check that the "
                f"relative path is correct for the file's current location"
            )
            continue
        if not target_path.exists():
            _report_error(f"ERROR: {rel_source}: frontmatter snippet not found: {target_path}")
            continue
        try:
            snippet_data = yaml.safe_load(target_path.read_text()) or {}
        except yaml.YAMLError as exc:
            _report_error(
                f"ERROR: {rel_source}: malformed frontmatter snippet {target_path.name}: {exc}"
            )
            continue
        if not isinstance(snippet_data, dict):
            _report_error(
                f"ERROR: {rel_source}: frontmatter snippet {target_path.name} must contain "
                f"a YAML mapping (got {type(snippet_data).__name__})"
            )
            continue
        defaults.update(snippet_data)

    remaining_body = "".join(lines[i:])
    merged = {**defaults, **frontmatter}
    return merged, remaining_body


def mark_decorative_images(html: str) -> str:
    """Mark alt-less images as decorative for the Canvas accessibility checker.

    Pandoc drops the alt attribute entirely for ``![](image.png)``, and the
    Canvas accessibility checker flags such images as missing alt text. An
    ``<img>`` whose alt is missing or whitespace-only is treated as
    decorative: it gets ``alt=""`` plus ``role="presentation"`` — the same
    markup the Canvas editor writes when an image is marked decorative.
    Images with real alt text, or with an explicit role attribute already
    set, are left untouched.
    """

    def _fix(m: re.Match) -> str:
        tag = m.group(0)
        alt_m = _ALT_ATTR_RE.search(tag)
        if alt_m is not None and alt_m.group(1).strip():
            return tag  # real alt text — not decorative
        if alt_m is not None and alt_m.group(1):
            # whitespace-only alt — normalize to alt=""
            tag = tag[: alt_m.start(1)] + tag[alt_m.end(1) :]
        additions = []
        if alt_m is None:
            additions.append('alt=""')
        if _ROLE_ATTR_RE.search(tag) is None:
            additions.append('role="presentation"')
        if not additions:
            return tag
        if tag.endswith("/>"):
            head, close = tag[:-2].rstrip(), " />"
        else:
            head, close = tag[:-1].rstrip(), ">"
        return f"{head} {' '.join(additions)}{close}"

    return _IMG_TAG_RE.sub(_fix, html)


# Kept in one place because markdown_to_html() has two conversion paths that
# must produce identical output — see _convert_with_timeout().
_PANDOC_FROM = "markdown+smart"
_PANDOC_TO = "html5"
_PANDOC_EXTRA_ARGS = ["--mathml"]


def _convert_with_timeout(text: str, timeout: float) -> str:
    """`pypandoc.convert_text` equivalent, bounded by a wall-clock timeout.

    pypandoc exposes no timeout, so this drives pandoc directly. The flags must
    stay in step with the pypandoc call in markdown_to_html(); a test asserts
    both paths return the same HTML.

    Raises subprocess.TimeoutExpired if pandoc outruns `timeout`. That is a
    real risk on imported content: pandoc parses nested bracketed spans by
    backtracking exponentially, so a run like `[[[[[[[[[x]]]]]]]]]` left behind
    by a Canvas export takes minutes on a file of a few hundred bytes.
    """
    result = subprocess.run(
        [
            pypandoc.get_pandoc_path(),
            f"--from={_PANDOC_FROM}",
            f"--to={_PANDOC_TO}",
            *_PANDOC_EXTRA_ARGS,
        ],
        input=text.encode("utf-8"),
        capture_output=True,
        timeout=timeout,
        check=False,
    )
    if result.returncode != 0:
        stderr = result.stderr.decode("utf-8", errors="replace")
        raise RuntimeError(
            f'Pandoc died with exitcode "{result.returncode}" during '
            f"conversion: {stderr}"
        )
    return result.stdout.decode("utf-8")


def markdown_to_html(text: str, timeout: float | None = None) -> str:
    """Convert Markdown to a Canvas-ready HTML fragment.

    `timeout` bounds the conversion in seconds, for callers that convert every
    file in a repo and must not stall on one pathological document. It is off
    by default: the upload paths convert files the user is actively syncing,
    where a silent partial result would be worse than a slow one.
    """
    if timeout is None:
        html = pypandoc.convert_text(
            text,
            to=_PANDOC_TO,
            format=_PANDOC_FROM,
            extra_args=_PANDOC_EXTRA_ARGS,
        )
    else:
        html = _convert_with_timeout(text, timeout)
    return mark_decorative_images(html)
