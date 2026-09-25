"""fix-manifest --pair-canvas-with-local / --force-pair: connect local files to
Canvas items that already exist.

Files brought in with `import` or `cp` have no manifest entry, so `update` would
create a second copy of every one of them in Canvas. Pairing gives each such file
the entry of the Canvas item with the same (normalized) title and type. Only
files with no entry are paired automatically; --force-pair names a pair
explicitly and may replace an entry.

New entries carry no ``last_synced``, so the next update uploads the local
version over the Canvas item and renders its links with this course's IDs. A
file whose size already equals the Canvas copy's is the exception: it is stamped
as synced, since re-uploading identical bytes would only cost time.

Pure planning (plan_pairing) is kept apart from local scanning
(collect_local_items) and writing (apply_pairing) so each can be tested alone.
"""

from __future__ import annotations

import difflib
import html
import re
import shlex
import unicodedata
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import click
import yaml

from . import manifest as manifest_lib
from .canvas_api import CanvasObject, CourseListing
from .convert import parse_frontmatter
from .ignore import load_ignore_matcher
from .link_rewrite import infer_canvas_type

#: Top-level folders that are not content folders (same list as sync._phase_content).
_NON_CONTENT_DIRS = {
    "assets", "modules", "quizzes", "snippets", "course_settings", "question_banks",
}

#: Manifest canvas_type -> the listing pool whose items it can claim. Topics
#: switch between discussion and announcement on Canvas, so both claim both.
_CLAIM_POOLS = {
    "page": ("page",),
    "assignment": ("assignment",),
    "discussion": ("discussion", "announcement"),
    "announcement": ("discussion", "announcement"),
    "quiz": ("quiz",),
    "module": ("module",),
    "external_module": ("module",),
    "file": ("file",),
}

#: Minimum difflib ratio for a similar-title suggestion.
SUGGESTION_THRESHOLD = 0.6

_QUOTES = str.maketrans({
    "‘": "'", "’": "'", "‚": "'", "‛": "'", "′": "'",
    "“": '"', "”": '"', "„": '"', "‟": '"', "″": '"',
    "‐": "-", "‑": "-", "‒": "-", "–": "-", "—": "-",
    "―": "-", "−": "-",
})
_WS_RE = re.compile(r"\s+")


def normalize_title(title: str) -> str:
    """Entities decoded, NFKC, quotes/dashes to ASCII, whitespace collapsed, casefolded."""
    text = unicodedata.normalize("NFKC", html.unescape(str(title)))
    text = text.translate(_QUOTES)
    return _WS_RE.sub(" ", text).strip().casefold()


@dataclass(frozen=True)
class LocalItem:
    key: str  # repo-relative path, the manifest key
    canvas_type: str
    title: str  # for files: the path below assets/
    size: int | None = None


@dataclass
class Pairing:
    local: LocalItem
    canvas: CanvasObject
    how: str  # "exact", "normalized" or "forced"
    replaced: dict[str, Any] | None = None


@dataclass
class DuplicateGroup:
    canvas_type: str
    title: str
    locals: list[str]
    chosen: list[tuple[str, CanvasObject]]
    not_chosen: list[CanvasObject]


@dataclass
class PairPlan:
    added: list[Pairing] = field(default_factory=list)
    duplicates: list[DuplicateGroup] = field(default_factory=list)
    suggestions: list[tuple[LocalItem, CanvasObject, float]] = field(default_factory=list)
    unmatched_local: list[LocalItem] = field(default_factory=list)
    unmatched_canvas: list[CanvasObject] = field(default_factory=list)
    # (local key, local title, Canvas item the existing entry points to)
    title_mismatches: list[tuple[str, str, CanvasObject]] = field(default_factory=list)
    scan_errors: list[tuple[str, str]] = field(default_factory=list)

    @property
    def has_changes(self) -> bool:
        return bool(self.added)


class PairError(Exception):
    """A --force-pair argument cannot be used; the message lists every problem."""


# ---------------------------------------------------------------------------
# Local side
# ---------------------------------------------------------------------------


def _title_of(path: Path, default: str, errors: list[tuple[str, str]], key: str) -> str | None:
    try:
        fm, _ = parse_frontmatter(path.read_text())
    except (yaml.YAMLError, UnicodeDecodeError) as exc:
        errors.append((key, f"could not read frontmatter: {exc}"))
        return None
    title = fm.get("title", default) if isinstance(fm, dict) else default
    return str(title)


def collect_local_items(repo_root: Path) -> tuple[list[LocalItem], list[tuple[str, str]]]:
    """Every local file `update` would sync as a pairable Canvas item.

    Returns (items, errors). Files whose frontmatter cannot be parsed are
    reported as errors and left out.
    """
    matcher = load_ignore_matcher(repo_root)
    items: list[LocalItem] = []
    errors: list[tuple[str, str]] = []

    def rel(path: Path) -> str:
        return path.relative_to(repo_root).as_posix()

    for folder in sorted(p for p in repo_root.iterdir() if p.is_dir()):
        if (
            folder.name.startswith(".")
            or folder.name in _NON_CONTENT_DIRS
            or matcher.is_ignored(folder, repo_root)
        ):
            continue
        for md in sorted(folder.rglob("*.md")):
            if matcher.is_ignored(md, repo_root):
                continue
            key = rel(md)
            title = _title_of(md, md.stem, errors, key)
            if title is not None:
                items.append(LocalItem(key, infer_canvas_type(key), title))

    quizzes = repo_root / "quizzes"
    if quizzes.is_dir():
        for folder in sorted(d for d in quizzes.iterdir() if d.is_dir()):
            quiz_md = folder / f"{folder.name}.md"
            if matcher.is_ignored(folder, repo_root) or not quiz_md.exists():
                continue
            key = rel(quiz_md)
            title = _title_of(quiz_md, folder.name, errors, key)
            if title is not None:
                items.append(LocalItem(key, "quiz", title))

    modules = repo_root / "modules"
    if modules.is_dir():
        for md in sorted(modules.glob("*.md")):
            if matcher.is_ignored(md, repo_root):
                continue
            key = rel(md)
            title = _title_of(md, md.stem, errors, key)
            if title is not None:
                items.append(LocalItem(key, "module", title))

    assets = repo_root / "assets"

    def walk_assets(folder: Path) -> None:
        # Same walk as sync._walk_assets: an ignored folder hides everything in it.
        for path in sorted(folder.iterdir(), key=lambda p: (p.is_dir(), p.name)):
            if matcher.is_ignored(path, repo_root):
                continue
            if path.is_dir():
                walk_assets(path)
            elif path.is_file():
                items.append(
                    LocalItem(
                        rel(path), "file", path.relative_to(assets).as_posix(),
                        size=path.stat().st_size,
                    )
                )

    if assets.is_dir():
        walk_assets(assets)
    return items, errors


# ---------------------------------------------------------------------------
# Planning (pure)
# ---------------------------------------------------------------------------


def parse_force_pairs(values: tuple[str, ...] | list[str]) -> list[tuple[str, int]]:
    """Parse LOCAL_PATH=CANVAS_ID arguments. Raises PairError listing every bad one."""
    pairs: list[tuple[str, int]] = []
    problems: list[str] = []
    for raw in values:
        local, sep, cid = raw.rpartition("=")
        local = local.strip().replace("\\", "/")
        while local.startswith("./"):
            local = local[2:]
        if not sep or not local or not cid.strip().isdigit():
            problems.append(f"--force-pair '{raw}': expected LOCAL_PATH=CANVAS_ID")
            continue
        pairs.append((local, int(cid.strip())))
    if problems:
        raise PairError("\n".join(problems))
    return pairs


def _claimed(manifest: manifest_lib.ManifestDict) -> dict[tuple[str, int], str]:
    """(pool, Canvas id) -> the manifest key that already uses that Canvas item."""
    claimed: dict[tuple[str, int], str] = {}
    for key, entry in manifest.items():
        if manifest_lib.is_reserved_key(key, entry) or not isinstance(entry, dict):
            continue
        cid = entry.get("canvas_id")
        if cid is None:
            continue
        for pool in _CLAIM_POOLS.get(entry.get("canvas_type", ""), ()):
            claimed[(pool, int(cid))] = key
    return claimed


def _tie_break(item: CanvasObject) -> tuple:
    return (not item.published, not item.has_submissions, item.canvas_id)


def _pair_group(
    locals_: list[LocalItem], candidates: list[CanvasObject]
) -> list[tuple[LocalItem, CanvasObject]]:
    """Pair one normalized-title group: exact titles first, then the rest in order.

    ``locals_`` is in path order and ``candidates`` in tie-break order.
    """
    pairs: list[tuple[LocalItem, CanvasObject]] = []
    free = list(candidates)
    waiting: list[LocalItem] = []
    for loc in locals_:
        exact = next((o for o in free if o.title.strip() == loc.title.strip()), None)
        if exact is None:
            waiting.append(loc)
        else:
            free.remove(exact)
            pairs.append((loc, exact))
    pairs.extend(zip(waiting, free))
    return pairs


def _pairing(local: LocalItem, canvas: CanvasObject, how: str | None = None) -> Pairing:
    if how is None:
        how = "exact" if local.title.strip() == canvas.title.strip() else "normalized"
    return Pairing(local, canvas, how)


def plan_pairing(
    manifest: manifest_lib.ManifestDict,
    listing: CourseListing,
    local_items: list[LocalItem],
    force_pairs: list[tuple[str, int]] = (),
    match_titles: bool = True,
) -> PairPlan:
    """Decide which entries to add. ``manifest`` is the manifest after any clean.

    Raises PairError when a --force-pair cannot be used; nothing is planned then.
    """
    plan = PairPlan()
    by_key = {item.key: item for item in local_items}
    claimed = _claimed(manifest)
    by_id = {
        (pool, obj.canvas_id): obj for pool, objs in listing.items.items() for obj in objs
    }

    # Forced pairs first: they take their items out of the pool.
    problems: list[str] = []
    forced_keys: set[str] = set()
    forced_items: set[tuple[str, int]] = set()
    for key, cid in force_pairs:
        local = by_key.get(key)
        if local is None:
            problems.append(
                f"--force-pair {key}={cid}: {key} is not a file update would sync "
                "(missing, ignored, or not content)"
            )
            continue
        canvas = by_id.get((local.canvas_type, cid))
        if canvas is None:
            problems.append(
                f"--force-pair {key}={cid}: the course has no {local.canvas_type} "
                f"with ID {cid}"
            )
            continue
        owner = claimed.get((local.canvas_type, cid))
        if owner is not None and owner != key:
            problems.append(
                f"--force-pair {key}={cid}: {local.canvas_type} {cid} is already "
                f"the Canvas item for {owner}"
            )
            continue
        if key in forced_keys:
            problems.append(f"--force-pair: {key} is named more than once")
            continue
        if (local.canvas_type, cid) in forced_items:
            problems.append(f"--force-pair: {local.canvas_type} {cid} is named more than once")
            continue
        forced_keys.add(key)
        forced_items.add((local.canvas_type, cid))
        pairing = _pairing(local, canvas, "forced")
        pairing.replaced = manifest.get(key)
        plan.added.append(pairing)
    if problems:
        raise PairError("\n".join(problems))
    for pairing in plan.added:
        for pool in _CLAIM_POOLS[pairing.canvas.canvas_type]:
            claimed[(pool, pairing.canvas.canvas_id)] = pairing.local.key

    # Existing entries whose Canvas title no longer matches the local one.
    for key, entry in manifest.items():
        local = by_key.get(key)
        if local is None or key in forced_keys or not isinstance(entry, dict):
            continue
        cid = entry.get("canvas_id")
        canvas = by_id.get((local.canvas_type, int(cid))) if cid is not None else None
        if canvas is not None and normalize_title(canvas.title) != normalize_title(local.title):
            plan.title_mismatches.append((key, local.title, canvas))

    if not match_titles:
        return plan

    unpaired = [
        item for item in local_items if item.key not in manifest and item.key not in forced_keys
    ]
    by_type: dict[str, list[LocalItem]] = defaultdict(list)
    for item in unpaired:
        by_type[item.canvas_type].append(item)

    for canvas_type, objs in listing.items.items():
        free = [o for o in objs if (canvas_type, o.canvas_id) not in claimed]
        local_groups: dict[str, list[LocalItem]] = defaultdict(list)
        for item in by_type.get(canvas_type, []):
            local_groups[normalize_title(item.title)].append(item)
        canvas_groups: dict[str, list[CanvasObject]] = defaultdict(list)
        for obj in free:
            canvas_groups[normalize_title(obj.title)].append(obj)

        left_local: list[LocalItem] = []
        left_canvas: list[CanvasObject] = []
        for norm, locals_ in sorted(local_groups.items()):
            locals_ = sorted(locals_, key=lambda i: i.key)
            candidates = sorted(canvas_groups.pop(norm, []), key=_tie_break)
            pairs = _pair_group(locals_, candidates)
            plan.added.extend(_pairing(loc, obj) for loc, obj in pairs)
            paired_keys = {loc.key for loc, _ in pairs}
            paired_ids = {obj.canvas_id for _, obj in pairs}
            left_local.extend(loc for loc in locals_ if loc.key not in paired_keys)
            rest = [obj for obj in candidates if obj.canvas_id not in paired_ids]
            left_canvas.extend(rest)
            if pairs and (len(locals_) > 1 or len(candidates) > 1):
                plan.duplicates.append(
                    DuplicateGroup(
                        canvas_type,
                        candidates[0].title,
                        [loc.key for loc in locals_],
                        sorted(((loc.key, obj) for loc, obj in pairs), key=lambda t: t[0]),
                        rest,
                    )
                )
        for objs_left in canvas_groups.values():
            left_canvas.extend(objs_left)

        # Similar titles: best candidate per local file, each Canvas item once.
        scored = sorted(
            (
                (
                    difflib.SequenceMatcher(
                        None, normalize_title(loc.title), normalize_title(obj.title)
                    ).ratio(),
                    loc,
                    obj,
                )
                for loc in left_local
                for obj in left_canvas
            ),
            key=lambda t: (-t[0], t[1].key, t[2].canvas_id),
        )
        used_local: set[str] = set()
        used_canvas: set[int] = set()
        for score, loc, obj in scored:
            if score < SUGGESTION_THRESHOLD:
                break
            if loc.key in used_local or obj.canvas_id in used_canvas:
                continue
            used_local.add(loc.key)
            used_canvas.add(obj.canvas_id)
            plan.suggestions.append((loc, obj, score))
        plan.unmatched_local.extend(left_local)
        plan.unmatched_canvas.extend(left_canvas)

    plan.added.sort(key=lambda p: p.local.key)
    plan.suggestions.sort(key=lambda s: s[0].key)
    plan.unmatched_local.sort(key=lambda i: i.key)
    plan.unmatched_canvas.sort(key=lambda o: (o.canvas_type, normalize_title(o.title)))
    return plan


# ---------------------------------------------------------------------------
# Writing
# ---------------------------------------------------------------------------


def _new_entry(pairing: Pairing) -> dict[str, Any]:
    canvas = pairing.canvas
    entry: dict[str, Any] = {
        "canvas_id": canvas.canvas_id,
        # The local folder decides discussion vs announcement, as in update.
        "canvas_type": pairing.local.canvas_type,
    }
    if canvas.canvas_url is not None and canvas.canvas_type in ("page", "file"):
        entry["canvas_url"] = canvas.canvas_url
    if file_is_current(pairing):
        entry["last_synced"] = datetime.now(timezone.utc).isoformat()
    return entry


def file_is_current(pairing: Pairing) -> bool:
    """A file whose Canvas copy has the local size is not re-uploaded."""
    return (
        pairing.canvas.canvas_type == "file"
        and pairing.local.size is not None
        and pairing.canvas.size == pairing.local.size
    )


def apply_pairing(manifest: manifest_lib.ManifestDict, plan: PairPlan) -> None:
    """Write the planned entries into ``manifest`` (in memory; the caller flushes)."""
    for pairing in plan.added:
        manifest[pairing.local.key] = _new_entry(pairing)


# ---------------------------------------------------------------------------
# Report
# ---------------------------------------------------------------------------


def _q(text: str) -> str:
    return '"' + text.replace('"', '\\"') + '"'


def print_plan(plan: PairPlan, applied: bool, command_prefix: list[str]) -> None:
    """Print the pairing report. ``command_prefix`` starts the suggested command."""
    click.echo()
    verb = "Added" if applied else "Would add"
    if plan.added:
        click.secho(f"{verb} {len(plan.added)} entries:", fg="yellow")
        for p in plan.added:
            note = {
                "exact": "",
                "normalized": f"  (title matched after normalizing: {_q(p.local.title)})",
                "forced": "  (--force-pair"
                + (", replaces the existing entry" if p.replaced else "")
                + ")",
            }[p.how]
            click.echo(
                f"  - {p.local.key} -> {p.canvas.canvas_type} {p.canvas.canvas_id} "
                f"{_q(p.canvas.title)}{note}"
            )
        resync = [p for p in plan.added if not file_is_current(p)]
        if resync:
            click.echo()
            click.secho(
                f"The next update uploads {len(resync)} of these over the Canvas "
                "item, overwriting any edits made directly in Canvas. Files whose "
                "size matches the Canvas copy are marked as synced and not re-uploaded.",
                fg="yellow",
            )
    else:
        click.secho("No entries to add.", fg="green")

    if plan.duplicates:
        click.echo()
        click.secho(f"Titles shared by several items ({len(plan.duplicates)}):", fg="yellow")
        for group in plan.duplicates:
            click.echo(f"  - {group.canvas_type} {_q(group.title)}:")
            for key, obj in group.chosen:
                state = "published" if obj.published else "unpublished"
                click.echo(f"      {key} -> {obj.canvas_id} ({state})")
            for obj in group.not_chosen:
                state = "published" if obj.published else "unpublished"
                click.echo(f"      not used: {obj.canvas_id} ({state})")
            chosen_keys = {key for key, _ in group.chosen}
            for key in (k for k in group.locals if k not in chosen_keys):
                click.echo(f"      no Canvas item left for {key}")

    if plan.suggestions:
        click.echo()
        click.secho(
            f"Similar titles ({len(plan.suggestions)}). These are not paired. "
            "To pair one, pass its line to fix-manifest:",
            fg="yellow",
        )
        args: list[str] = []
        for loc, obj, score in plan.suggestions:
            arg = shlex.quote(f"{loc.key}={obj.canvas_id}")
            args.append(arg)
            click.echo(
                f"  --force-pair {arg}   # {obj.canvas_type} {_q(loc.title)} ~ "
                f"{_q(obj.title)} ({score:.2f})"
            )
        click.echo()
        click.echo("Or all of them at once (delete the lines you do not want):")
        lines = [" ".join(command_prefix)] + [f"  --force-pair {a}" for a in args]
        click.echo(" \\\n".join(lines))

    if plan.unmatched_local:
        click.echo()
        click.secho(
            f"Local files with no Canvas item ({len(plan.unmatched_local)}); "
            "the next update creates them:",
            dim=True,
        )
        for item in plan.unmatched_local:
            click.secho(f"  - {item.key} ({item.canvas_type} {_q(item.title)})", dim=True)

    if plan.unmatched_canvas:
        click.echo()
        click.secho(
            f"Canvas items with no local file ({len(plan.unmatched_canvas)}):", dim=True
        )
        for obj in plan.unmatched_canvas:
            click.secho(f"  - {obj.canvas_type} {obj.canvas_id} {_q(obj.title)}", dim=True)

    if plan.title_mismatches:
        click.echo()
        click.secho(
            f"Existing entries whose Canvas title differs from the local title "
            f"({len(plan.title_mismatches)}):",
            dim=True,
        )
        for key, title, obj in plan.title_mismatches:
            click.secho(
                f"  - {key}: local {_q(title)}, Canvas {obj.canvas_type} "
                f"{obj.canvas_id} {_q(obj.title)}",
                dim=True,
            )

    if plan.scan_errors:
        click.echo()
        click.secho(
            f"Errors ({len(plan.scan_errors)}) — these files could not be read and "
            "were not paired:",
            fg="red",
        )
        for key, message in plan.scan_errors:
            click.echo(f"  - {key} : {message}")
