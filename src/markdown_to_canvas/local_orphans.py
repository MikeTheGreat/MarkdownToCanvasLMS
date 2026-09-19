"""Find local repo files that nothing else in the course references.

The Canvas-side counterpart lives in `orphans.py` (`find-canvas-orphans`),
which queries the live course. This module never contacts Canvas: it reads the
repo on disk, collects every outbound local reference it can find, and reports
the candidate files with zero inbound references.

Deliberately non-transitive: a file referenced from anywhere counts as
referenced, even if the referrer is itself an orphan. Reachability from the
module roots is a separate (future) question.

The whole scan is biased toward under-reporting — a file that shows up here
should be genuinely unreferenced:

- Course-flag conditionals are NOT applied, so a link inside a currently-false
  ``#if`` branch still counts (same conservative-superset stance as
  ``sync._get_file_refs``).
- ``pinned_resources`` entries count as references, so a pinned resource is
  never reported.
- ``snippets/`` files are never candidates. A snippet is a library file; "no
  page includes it right now" is not a reason to delete it.
- ``modules/``, ``course_settings/`` and ``question_banks/`` are never
  candidates either. The first two are the roots, and nothing in a repo ever
  links *to* them; question banks are independent uploads with no "draw N from
  bank X" reference anywhere in the format (ARCHITECTURE.md, IMSCC notes), so
  every bank would be reported on every run.
- ``quizzes/`` and ``announcements/`` are scanned for the links they contain
  but never reported themselves.
"""

from __future__ import annotations

import contextlib
import io
import re
import subprocess
import tomllib
from collections import defaultdict
from collections.abc import Callable, Iterator
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import click
import yaml

from .convert import (
    expand_frontmatter_snippets,
    markdown_to_html,
    parse_frontmatter,
    preprocess_snippets,
)
from . import repo_format
from .ignore import IgnoreMatcher, load_ignore_matcher
from .link_rewrite import extract_local_refs
from .quiz import split_quiz_body
from .sync import find_pinned_match, load_pinned_resources, parse_module_body

# Folders with a dedicated phase in the sync pipeline; everything else at the
# repo root is a regular content folder. Mirrors the `skip` set in
# sync._phase_content.
_SPECIAL_DIRS = {
    "assets",
    "modules",
    "quizzes",
    "snippets",
    "course_settings",
    "question_banks",
}

# Content folders that are scanned for references but never reported: nobody
# links to an announcement, and a quiz is normally reached from a module or
# taken directly in Canvas, so "unreferenced" is not a deletion signal.
_NEVER_REPORTED_DIRS = {"announcements"}

_TYPE_LABELS = {
    "assets": "Assets",
}

# Hard-wrapped so the note stays readable in a narrow terminal.
# Generous: every well-formed file in a real course repo converts in well under
# a second. This is a backstop against pathological input (see _to_html), not a
# performance budget.
_PANDOC_TIMEOUT_SECONDS = 20.0

_SCOPE_NOTE = (
    "Note: snippets, modules, course settings, question banks, quizzes and\n"
    "announcements are never listed here — they are excluded by design (see\n"
    "README)."
)

_SETTINGS_KEY = "course_settings/course_settings.toml"
_PINNED_LABEL = f"{_SETTINGS_KEY} (pinned_resources)"


@dataclass(frozen=True)
class LocalOrphanReport:
    """orphans and referenced together partition the candidate set.

    ``referenced`` maps a candidate key to the sorted keys of everything that
    refers to it, so the verbose report can show *why* a file is not an orphan.
    Non-candidates (snippets, modules, course settings, question banks) appear
    in neither list — they can never be reported as orphans, so listing them as
    "referenced" would misrepresent what the report covers.

    ``errors`` holds ``(repo-relative key, message)`` for every file that could
    not be scanned. Each one means some outbound links were not followed, so
    the orphan list may name a file that is actually referenced — which is why
    the report prints them last, where they are hardest to miss.
    """

    orphans: list[str]
    referenced: dict[str, list[str]]
    errors: list[tuple[str, str]]


_FRONTMATTER_BLOCK_RE = re.compile(r"\A---\n.*?\n---\n", re.DOTALL)


def _rel(path: Path, repo_root: Path) -> str:
    return path.relative_to(repo_root).as_posix()


def _normalize_key(raw: str) -> str:
    """Normalize a repo-relative path from a config file into a manifest key."""
    key = raw.strip().replace("\\", "/")
    while key.startswith("./"):
        key = key[2:]
    return key.rstrip("/")


@contextlib.contextmanager
def _quiet() -> Iterator[None]:
    """Swallow parser chatter during the scan.

    Snippet-resolution errors, module indent warnings and the like are the
    business of `update`, which reports them properly. Repeating them inside a
    read-only report would bury the actual finding.
    """
    with contextlib.redirect_stdout(io.StringIO()):
        yield


# ---------------------------------------------------------------------------
# Discovery
# ---------------------------------------------------------------------------


def _walk_files(
    dir_path: Path,
    repo_root: Path,
    matcher: IgnoreMatcher,
    suffix: str | None = None,
) -> Iterator[Path]:
    """Yield files under dir_path, pruning ignored and hidden directories."""
    for entry in sorted(dir_path.iterdir(), key=lambda p: p.name):
        if entry.name.startswith(".") or matcher.is_ignored(entry, repo_root):
            continue
        if entry.is_dir():
            yield from _walk_files(entry, repo_root, matcher, suffix)
        elif entry.is_file() and (suffix is None or entry.suffix == suffix):
            yield entry


def _content_dirs(repo_root: Path, matcher: IgnoreMatcher) -> list[Path]:
    return sorted(
        d
        for d in repo_root.iterdir()
        if d.is_dir()
        and not d.name.startswith(".")
        and d.name not in _SPECIAL_DIRS
        and not matcher.is_ignored(d, repo_root)
    )


def _unit_folders(
    repo_root: Path, matcher: IgnoreMatcher, folder_name: str, main_suffix: str
) -> list[tuple[Path, Path]]:
    """Return (folder, main_file) for each quiz / question-bank folder.

    A quiz or question bank syncs as a single unit (see ARCHITECTURE's
    `pinned_resources` notes), so the unit is keyed by its main file and its
    inner question files are never candidates in their own right.
    """
    parent = repo_root / folder_name
    if not parent.exists():
        return []
    units: list[tuple[Path, Path]] = []
    for folder in sorted(d for d in parent.iterdir() if d.is_dir()):
        if folder.name.startswith(".") or matcher.is_ignored(folder, repo_root):
            continue
        main = folder / f"{folder.name}{main_suffix}"
        if main.exists():
            units.append((folder, main))
    return units


def collect_candidates(repo_root: Path, matcher: IgnoreMatcher) -> set[str]:
    """Every repo file that could reasonably be reported as unreferenced."""
    candidates: set[str] = set()

    assets_dir = repo_root / "assets"
    if assets_dir.exists():
        for path in _walk_files(assets_dir, repo_root, matcher):
            candidates.add(_rel(path, repo_root))

    for content_dir in _content_dirs(repo_root, matcher):
        if content_dir.name in _NEVER_REPORTED_DIRS:
            continue
        for path in _walk_files(content_dir, repo_root, matcher, suffix=".md"):
            candidates.add(_rel(path, repo_root))

    return candidates


def collect_sources(repo_root: Path, matcher: IgnoreMatcher) -> list[Path]:
    """Every repo file whose contents can reference something else."""
    sources: list[Path] = []

    for content_dir in _content_dirs(repo_root, matcher):
        sources.extend(_walk_files(content_dir, repo_root, matcher, suffix=".md"))

    for name in ("modules", "snippets"):
        d = repo_root / name
        if d.exists():
            sources.extend(_walk_files(d, repo_root, matcher, suffix=".md"))

    syllabus = repo_root / "course_settings" / "syllabus.md"
    if syllabus.exists():
        sources.append(syllabus)

    for _folder, main in _unit_folders(repo_root, matcher, "quizzes", ".md"):
        sources.append(main)
    for _folder, main in _unit_folders(repo_root, matcher, "question_banks", ".toml"):
        sources.append(main)

    return sources


# ---------------------------------------------------------------------------
# Reference extraction
# ---------------------------------------------------------------------------


def _frontmatter_refs(frontmatter: dict[str, Any]) -> set[str]:
    """Repo-relative paths named by frontmatter keys (not by body links)."""
    attachment = frontmatter.get("annotatable_attachment")
    if isinstance(attachment, str) and attachment.strip():
        return {_normalize_key(attachment)}
    return set()


def _read_markdown(
    file_path: Path, snippets_dir: Path
) -> tuple[dict[str, Any], str]:
    """Frontmatter + fully snippet-expanded body, or ({}, "") if unreadable."""
    try:
        text = file_path.read_text()
    except (OSError, UnicodeDecodeError):
        return {}, ""
    try:
        frontmatter, body = parse_frontmatter(text)
    except yaml.YAMLError:
        # Malformed frontmatter — `update` reports it properly. Here, strip the
        # block textually and probe the body anyway, so one bad file does not
        # make everything it links to look unreferenced. The block must be
        # stripped rather than left in place: Pandoc parses a leading --- fence
        # as YAML metadata and dies on the same malformed content.
        frontmatter, body = {}, _FRONTMATTER_BLOCK_RE.sub("", text, count=1)
    frontmatter, body = expand_frontmatter_snippets(
        frontmatter, body, file_path, snippets_dir
    )
    body = preprocess_snippets(body, file_path, snippets_dir)
    return frontmatter, body


def _to_html(
    markdown: str,
    file_path: Path,
    repo_root: Path,
    errors: list[tuple[str, str]],
) -> str:
    """Convert to HTML, degrading to a reported error if Pandoc cannot.

    A report that dies on one bad file is useless; one that silently drops the
    file's links would invent orphans. So: skip it, and name it at the end.

    The timeout matters more than the usual error case. Pandoc parses nested
    bracketed spans by backtracking exponentially, so a run of nine — the kind
    a Canvas export leaves behind — takes minutes on a few hundred bytes.
    Unlike `update`, this command has no staleness gate, so it re-converts
    every file on every run and would stall there every time.
    """
    try:
        return markdown_to_html(markdown, timeout=_PANDOC_TIMEOUT_SECONDS)
    except subprocess.TimeoutExpired:
        errors.append(
            (
                _rel(file_path, repo_root),
                (
                    f"timed out after {_PANDOC_TIMEOUT_SECONDS:.0f}s - check "
                    f"for nested []s"
                ),
            )
        )
        return ""
    except RuntimeError as exc:
        errors.append(
            (
                _rel(file_path, repo_root),
                f"could not convert to HTML - {str(exc).strip().splitlines()[0]}",
            )
        )
        return ""


def _markdown_refs(
    file_path: Path, repo_root: Path, snippets_dir: Path, errors: list[tuple[str, str]]
) -> set[str]:
    frontmatter, body = _read_markdown(file_path, snippets_dir)
    refs = _frontmatter_refs(frontmatter)
    if body.strip():
        html = _to_html(body, file_path, repo_root, errors)
        refs |= extract_local_refs(html, file_path, repo_root)
    return refs


def _module_refs(
    file_path: Path, repo_root: Path, snippets_dir: Path, errors: list[tuple[str, str]]
) -> set[str]:
    _frontmatter, body = _read_markdown(file_path, snippets_dir)
    try:
        items = parse_module_body(body, file_path, repo_root)
    except ValueError:
        # An item pointing outside the repo. Report it rather than silently
        # dropping the module's whole item list, which would manufacture orphans.
        errors.append(
            (
                _rel(file_path, repo_root),
                (
                    "could not resolve every module item - an item points "
                    "outside the repo"
                ),
            )
        )
        return set()
    return {item["local_path"] for item in items if item["type"] == "content"}


def _quiz_refs(
    quiz_md: Path, repo_root: Path, snippets_dir: Path, errors: list[tuple[str, str]]
) -> set[str]:
    frontmatter, body = _read_markdown(quiz_md, snippets_dir)
    description_md, question_files = split_quiz_body(body, quiz_md)
    refs = _frontmatter_refs(frontmatter)
    if description_md.strip():
        html = _to_html(description_md, quiz_md, repo_root, errors)
        refs |= extract_local_refs(html, quiz_md, repo_root)
    for q_path in question_files:
        if q_path.exists():
            refs |= _markdown_refs(q_path, repo_root, snippets_dir, errors)
    return refs


def _question_bank_refs(
    bank_toml: Path, repo_root: Path, snippets_dir: Path, errors: list[tuple[str, str]]
) -> set[str]:
    refs: set[str] = set()
    questions_dir = bank_toml.parent / "questions"
    if questions_dir.exists():
        for q_path in sorted(questions_dir.glob("*.md")):
            refs |= _markdown_refs(q_path, repo_root, snippets_dir, errors)
    return refs


def collect_local_refs(
    file_path: Path,
    repo_root: Path,
    snippets_dir: Path,
    errors: list[tuple[str, str]] | None = None,
) -> set[str]:
    """Return the repo-relative keys referenced by a single source file.

    Overlaps with ``sync._get_file_refs`` on purpose and must not be merged
    with it: that one drives targeted-sync BFS, where quizzes deliberately
    return no refs (see the TODO in sync.py). Here quizzes must be followed, or
    every asset used only inside a quiz would be reported as an orphan.
    """
    if errors is None:
        errors = []
    folder = _rel(file_path, repo_root).split("/")[0]
    if folder == "modules":
        return _module_refs(file_path, repo_root, snippets_dir, errors)
    if folder == "quizzes":
        return _quiz_refs(file_path, repo_root, snippets_dir, errors)
    if folder == "question_banks":
        return _question_bank_refs(file_path, repo_root, snippets_dir, errors)
    if folder == "assets":
        return set()
    return _markdown_refs(file_path, repo_root, snippets_dir, errors)


def collect_settings_refs(repo_root: Path) -> tuple[set[str], list[str]]:
    """Return (referenced keys, pinned_resources entries) from course_settings.toml.

    Pinned entries come back separately because an entry may name a folder,
    which covers everything beneath it — that needs prefix matching against
    each candidate rather than a set lookup.
    """
    settings_path = repo_root / "course_settings" / "course_settings.toml"
    if not settings_path.exists():
        return set(), []
    with settings_path.open("rb") as fh:
        settings = tomllib.load(fh)

    refs: set[str] = set()
    for key in ("front_page", "dashboard_image"):
        value = settings.get(key)
        if isinstance(value, str) and value.strip():
            refs.add(_normalize_key(value))

    # due_dates entries match content by *title*, not by path, so they name
    # nothing on disk and contribute no references.
    return refs, load_pinned_resources(repo_root, settings)


# ---------------------------------------------------------------------------
# Top level
# ---------------------------------------------------------------------------


def find_local_orphans(repo_root: Path) -> LocalOrphanReport:
    """Scan a course repo and return its orphans plus the inbound-reference map."""
    repo_root = repo_root.resolve()
    repo_format.check_repo_format(repo_root)
    matcher = load_ignore_matcher(repo_root)
    snippets_dir = repo_root / "snippets"
    errors: list[tuple[str, str]] = []

    candidates = collect_candidates(repo_root, matcher)
    referrers: dict[str, set[str]] = defaultdict(set)

    settings_refs, pinned = collect_settings_refs(repo_root)
    for key in settings_refs:
        referrers[key].add(_SETTINGS_KEY)

    for source in collect_sources(repo_root, matcher):
        source_key = _rel(source, repo_root)
        with _quiet():
            refs = collect_local_refs(source, repo_root, snippets_dir, errors)
        for key in refs:
            referrers[key].add(source_key)

    # A pin is not a link, but it does mean "leave this alone", so it counts as
    # an inbound reference and is labelled as such in the verbose listing.
    for key in candidates:
        if find_pinned_match(pinned, key) is not None:
            referrers[key].add(_PINNED_LABEL)

    return LocalOrphanReport(
        orphans=sorted(key for key in candidates if key not in referrers),
        referenced={
            key: sorted(referrers[key])
            for key in sorted(candidates)
            if key in referrers
        },
        errors=sorted(errors),
    )


def _group_label(key: str) -> str:
    group = key.split("/")[0]
    return _TYPE_LABELS.get(group, group.replace("_", " ").title())


def _print_grouped(keys: list[str], line: Callable[[str], str]) -> None:
    """Print keys grouped by top-level folder; `line` renders each entry."""
    current_group = None
    for key in keys:
        group = key.split("/")[0]
        if group != current_group:
            current_group = group
            click.secho(f"  {_group_label(key)}:", bold=True)
        click.echo(f"    - {line(key)}")


def print_report(report: LocalOrphanReport, verbose: bool = False) -> None:
    # Up front, so nobody reads an empty report as "everything is referenced".
    click.secho(_SCOPE_NOTE, dim=True)
    click.echo()

    if verbose:
        referenced = report.referenced
        if referenced:
            click.secho(f"Referenced local files ({len(referenced)}):")
            click.echo()
            _print_grouped(
                list(referenced),
                lambda key: f"{key} : {', '.join(referenced[key])}",
            )
        else:
            click.secho("No referenced local files.")
        click.echo()

    if report.orphans:
        click.secho(
            f"Unreferenced local files ({len(report.orphans)}):", fg="yellow"
        )
        click.echo()
        _print_grouped(report.orphans, lambda key: key)
    else:
        click.secho("No unreferenced local files found.", fg="green")

    _print_errors(report.errors)


def _print_errors(errors: list[tuple[str, str]]) -> None:
    """Print the unscannable files last, where they are hardest to miss.

    Each one means some links went unfollowed, so the orphan list above may
    name a file that is really referenced.
    """
    if not errors:
        return
    click.echo()
    click.secho(
        f"Errors ({len(errors)}) — these files could not be scanned, so the "
        f"results above may be incomplete:",
        fg="red",
    )
    click.echo()
    for key, message in errors:
        click.echo(f"    - {key} : {message}")
