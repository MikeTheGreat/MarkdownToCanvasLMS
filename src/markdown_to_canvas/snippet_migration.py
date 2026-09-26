"""Format migration 3 -> 4: make links inside snippets snippet-relative.

Before format 4 a block snippet was pasted verbatim, so its relative links were
read from each including file's folder. From format 4 they are read from the
snippet's own folder and rebased onto the includer when pasted (see
``convert.preprocess_snippets``). This module rewrites existing snippet files
so each link keeps naming the file it named before, where that is unambiguous,
and reports the links it cannot convert. ``$path.md$`` refs inside a snippet
are converted the same way: before format 4 they were never expanded, and from
format 4 they are resolved from the snippet's folder.
"""
from __future__ import annotations

from pathlib import Path
from urllib.parse import quote, unquote

from .convert import _SNIPPET_LINK_RE, apply_outside_fences, split_fenced_segments
from .links import (
    compute_relative,
    resolve_repo_relative,
    split_suffix,
    transform_links,
)

_FRONTMATTER_MARKER = "PASTE_SNIPPET_INTO_FRONTMATTER"


def _visible_md_files(root: Path, repo: Path) -> list[Path]:
    """Every .md under root, skipping hidden files and folders."""
    return sorted(
        p for p in root.rglob("*.md")
        if p.is_file()
        and not any(part.startswith(".") for part in p.relative_to(repo).parts)
    )


def _body(text: str) -> str:
    """Text after a leading frontmatter block (split textually, not parsed)."""
    if text.startswith("---\n"):
        end = text.find("\n---\n", 4)
        if end != -1:
            return text[end + 5 :]
    return text


def _read(path: Path) -> str | None:
    try:
        return path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError):
        return None


def find_includers(repo: Path) -> dict[Path, list[str]]:
    """Map each block-included snippet file to the repo-relative paths of the
    files that include it.

    Every .md outside snippets/ and hidden folders counts, .canvasignore'd
    files included. Frontmatter-snippet references and inline $...$ refs do
    not count, nor do references inside fenced code.
    """
    snippets_dir = (repo / "snippets").resolve()
    includers: dict[Path, list[str]] = {}
    for md in _visible_md_files(repo, repo):
        if md.resolve().is_relative_to(snippets_dir):
            continue
        text = _read(md)
        if text is None:
            continue
        rel = md.relative_to(repo).as_posix()
        for is_fenced, seg in split_fenced_segments(_body(text)):
            if is_fenced:
                continue
            for m in _SNIPPET_LINK_RE.finditer(seg):
                if m.group(1) == _FRONTMATTER_MARKER:
                    continue
                target = (md.parent / m.group(2)).resolve()
                if target.is_relative_to(snippets_dir) and target.is_file():
                    found = includers.setdefault(target, [])
                    if rel not in found:
                        found.append(rel)
    return includers


def _describe(target: str | None, repo: Path) -> str:
    if target is None or not (repo / target).exists():
        return "(nothing)"
    return target


def migrate_snippet_links(repo: Path) -> tuple[dict[Path, str], list[str]]:
    """Return (new text for each changed snippet file, lines to print)."""
    repo = repo.resolve()
    snippets_root = repo / "snippets"
    if not snippets_root.is_dir():
        return {}, []

    includers = find_includers(repo)
    writes: dict[Path, str] = {}
    lines: list[str] = []

    for snippet in _visible_md_files(snippets_root, repo):
        text = _read(snippet)
        snippet_rel = snippet.relative_to(repo).as_posix()
        if text is None:
            lines.append(f"NOTICE: {snippet_rel}: could not be read as UTF-8; left unchanged")
            continue
        snippet_dir = snippet.parent.relative_to(repo).as_posix()
        users = includers.get(snippet.resolve(), [])
        reported: set[str] = set()

        def _exists(target: str | None) -> bool:
            return target is not None and (repo / target).exists()

        def _decide(url: str) -> str | None:
            path_part, suffix = split_suffix(url)
            if not path_part:
                return None
            decoded = unquote(path_part)
            own = resolve_repo_relative(snippet_dir, decoded)

            if not users:
                if not _exists(own) and url not in reported:
                    reported.add(url)
                    lines.append(
                        f"NOTICE: {snippet_rel} (included by no file): link {url} "
                        f"does not name an existing file; left unchanged"
                    )
                return None

            readings = [
                (user, resolve_repo_relative(str(Path(user).parent.as_posix()), decoded))
                for user in users
            ]
            # Includers whose reading names an existing file: what Canvas
            # showed. Includers that found nothing were already broken.
            working = {t for _, t in readings if _exists(t)}
            if len(working) == 1:
                (only,) = working
                if only == own:
                    return None
                new = compute_relative(snippet_dir, only)
                if "%" in path_part:
                    new = quote(new, safe="/-_.~")
                new += suffix
                lines.append(f"Rewrite link in {snippet_rel}: {url} -> {new}")
                return new
            if not working and _exists(own):
                return None
            if url not in reported:
                reported.add(url)
                detail = "; ".join(
                    f"{user} -> {_describe(t, repo)}" for user, t in readings
                )
                lines.append(
                    f"NOTICE: {snippet_rel}: link {url} left unchanged; it names "
                    f"{_describe(own, repo)} from the snippet, and its includers "
                    f"resolve it as: {detail}"
                )
            return None

        new_text = apply_outside_fences(
            text,
            lambda seg: transform_links(
                seg, snippet_dir, snippet_dir, {}, url_map=_decide,
            ),
        )
        if new_text != text:
            writes[snippet] = new_text

    return writes, lines
