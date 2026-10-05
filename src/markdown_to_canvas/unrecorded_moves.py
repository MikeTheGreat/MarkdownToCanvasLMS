"""Catch course files moved or renamed without `markdown-to-canvas mv`.

A move made with git, a file manager or an editor leaves the manifest entry
under the old path (an *orphan*), so `update` would treat the file at the new
path as new and create a second Canvas item next to the first. `update` runs
``check_unrecorded_moves`` before it changes anything in Canvas: a file with no
manifest entry that matches an orphan stops the run, and a tracked file that
matches one gets a warning (the duplicate already exists).

An orphan and a file match when their Canvas types are equal and their file
names are equal or their titles are equal after ``normalize_title``. The
orphan's title is read from Canvas, one GET per orphan, because the manifest
does not record titles. Assets match by file name only. An orphan whose Canvas
item is gone never matches: no duplicate can result.

Matching (``match_orphans``) is pure; Canvas is reached only through the
``fetch`` callable handed to ``load_orphans``.
"""
from __future__ import annotations

import os
import shlex
from collections import defaultdict
from collections.abc import Callable, Iterable
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import Any

from . import manifest as manifest_lib
from .canvas_api import OrphanItem
from .convert import warn
from .pair_manifest import LocalItem, collect_local_items, normalize_title

#: Manifest types that can be duplicated by an unrecorded move. Others
#: (syllabus, course settings, question banks, ...) have no file of their own
#: that update would create a second Canvas item for.
CHECKED_TYPES = frozenset(
    {"page", "assignment", "discussion", "announcement", "quiz", "module", "file"}
)

SAME_NAME = "same file name"
SAME_TITLE = "same title"


def find_orphans(
    manifest: manifest_lib.ManifestDict, repo_path: Path
) -> list[tuple[str, dict[str, Any]]]:
    """Manifest entries whose local file is gone (shared with `prune`).

    Reserved keys are not repo paths, and Canvas-only modules (module_order.toml
    entries cached under EXTERNAL_MODULE_PREFIX) have no local file by
    definition, so neither is ever an orphan.
    """
    return [
        (key, entry)
        for key, entry in manifest.items()
        if not manifest_lib.is_reserved_key(key, entry)
        and entry.get("canvas_type") != manifest_lib.EXTERNAL_MODULE_TYPE
        and not (repo_path / key).exists()
    ]


@dataclass(frozen=True)
class Orphan:
    key: str
    canvas_type: str
    canvas_id: Any
    title: str | None  # the Canvas item's title; None when it could not be read


@dataclass(frozen=True)
class Match:
    orphan: Orphan
    path: str  # repo-relative path of the matching file
    tracked: bool  # the file has its own manifest entry (the duplicate exists)
    path_id: Any  # the file's own canvas_id when tracked
    reasons: tuple[str, ...]

    @property
    def reason_text(self) -> str:
        return " and ".join(self.reasons)


def load_orphans(
    manifest: manifest_lib.ManifestDict,
    repo_path: Path,
    fetch: Callable[[str, dict[str, Any]], OrphanItem],
) -> list[Orphan]:
    """The orphans that could be duplicated, with their Canvas titles.

    Calls ``fetch`` once per orphan of a checked type and drops orphans whose
    Canvas item is gone. Makes no call when there are no such orphans.
    """
    orphans: list[Orphan] = []
    for key, entry in find_orphans(manifest, repo_path):
        canvas_type = entry.get("canvas_type", "")
        if canvas_type not in CHECKED_TYPES or entry.get("canvas_id") is None:
            continue
        item = fetch(canvas_type, entry)
        if item.exists:
            orphans.append(Orphan(key, canvas_type, entry["canvas_id"], item.title))
    return orphans


def match_orphans(
    orphans: Iterable[Orphan],
    local_items: Iterable[LocalItem],
    manifest: manifest_lib.ManifestDict,
) -> list[Match]:
    """Every (orphan, local file) pair that matches, in orphan then path order."""
    by_type: dict[str, list[LocalItem]] = defaultdict(list)
    for item in local_items:
        by_type[item.canvas_type].append(item)
    matches: list[Match] = []
    for orphan in orphans:
        orphan_name = PurePosixPath(orphan.key).name
        orphan_title = (
            normalize_title(orphan.title)
            if orphan.title is not None and orphan.canvas_type != "file"
            else None
        )
        for item in by_type.get(orphan.canvas_type, ()):
            reasons: list[str] = []
            if PurePosixPath(item.key).name == orphan_name:
                reasons.append(SAME_NAME)
            if orphan_title is not None and normalize_title(item.title) == orphan_title:
                reasons.append(SAME_TITLE)
            if not reasons:
                continue
            entry = manifest.get(item.key)
            matches.append(
                Match(
                    orphan,
                    item.key,
                    tracked=entry is not None,
                    path_id=(entry or {}).get("canvas_id"),
                    reasons=tuple(reasons),
                )
            )
    return matches


# ---------------------------------------------------------------------------
# Printed commands
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class Commands:
    """How to print the commands that resolve a stop or a warning.

    ``course_args`` is the course directory (or registry key) and any
    ``--config`` exactly as the user should type them after the subcommand, so
    a printed `update --new` acts on the same manifest as this run.
    """

    repo_path: Path
    course_args: str = ""

    def shown(self, key: str) -> str:
        """A repo path as the user would type it: relative to the current
        directory when that is inside the repo, absolute otherwise."""
        path = self.repo_path.resolve() / key
        cwd = Path.cwd().resolve()
        if not cwd.is_relative_to(self.repo_path.resolve()):
            return shlex.quote(str(path))
        return shlex.quote(os.path.relpath(path, cwd))

    def _sub(self, name: str) -> str:
        args = f" {self.course_args}" if self.course_args else ""
        return f"markdown-to-canvas {name}{args}"

    def mv_after(self, old: str, new: str) -> str:
        return f"markdown-to-canvas mv --after {self.shown(old)} {self.shown(new)}"

    def update_new(self, path: str) -> str:
        return f"{self._sub('update')} --new {self.shown(path)}"

    def prune(self) -> str:
        return f"{self._sub('prune')} --unpublish (or --delete, or --manifest-only)"


def _item(canvas_type: str, canvas_id: Any) -> str:
    return f"{canvas_type} {canvas_id}"


# ---------------------------------------------------------------------------
# The pre-flight check
# ---------------------------------------------------------------------------


def _resolve_new_path(raw: str, repo_path: Path) -> str | None:
    """A --new argument as a repo-relative key: tried from the current
    directory first (like -t/-s), then from the repo root."""
    candidates = [Path(raw)] if Path(raw).is_absolute() else [Path.cwd() / raw, repo_path / raw]
    for candidate in candidates:
        try:
            key = candidate.resolve().relative_to(repo_path.resolve()).as_posix()
        except ValueError:
            continue
        if (repo_path / key).exists():
            return key
    return None


def check_unrecorded_moves(
    repo_path: Path,
    manifest: manifest_lib.ManifestDict,
    manifest_path: Path | None,
    fetch: Callable[[str, dict[str, Any]], OrphanItem],
    errors: list[str],
    new_paths: Iterable[str] = (),
    commands: Commands | None = None,
    verbose: bool = False,
) -> bool:
    """Run update's unrecorded-move check. Returns True when update must stop.

    ``new_paths`` are the ``--new`` arguments: the orphans matching each are
    forgotten (removed from the manifest; Canvas untouched) before the check.
    The manifest is flushed only when the run goes on; a stop leaves it as it
    was on disk.
    """
    commands = commands or Commands(repo_path)
    new_paths = list(new_paths)
    orphans = load_orphans(manifest, repo_path, fetch)
    if not orphans and not new_paths:
        return False

    local_items, _scan_errors = collect_local_items(repo_path)
    matches = match_orphans(orphans, local_items, manifest)

    # --new: validate every argument before forgetting anything.
    synced_keys = {item.key for item in local_items}
    forget: dict[str, list[Match]] = {}
    bad = False
    for raw in new_paths:
        key = _resolve_new_path(raw, repo_path)
        if key is None:
            warn(f"ERROR: --new {raw}: no such file in the course repo", errors)
            bad = True
        elif key not in synced_keys:
            warn(f"ERROR: --new {raw}: not a file that update syncs to Canvas", errors)
            bad = True
        else:
            hits = [m for m in matches if m.path == key]
            if not hits:
                warn(
                    f"ERROR: --new {raw}: matches no orphaned manifest entry (an entry "
                    "whose file is gone and whose Canvas item still exists), so there "
                    "is nothing to forget",
                    errors,
                )
                bad = True
            for m in hits:
                forget.setdefault(m.orphan.key, []).append(m)
    if bad:
        print("\nAborting: nothing was changed in Canvas or the manifest.")
        return True

    for orphan_key, hits in forget.items():
        manifest.pop(orphan_key, None)
        m = hits[0]
        kind = m.orphan.canvas_type.capitalize()
        print(
            f"  WARNING: --new {m.path}: forgot the manifest entry for {orphan_key} "
            f"({_item(m.orphan.canvas_type, m.orphan.canvas_id)}), which matched it "
            f"({m.reason_text}). {kind} {m.orphan.canvas_id} was left in Canvas and "
            "is no longer tracked by markdown-to-canvas; delete it in Canvas if you "
            "don't need it."
        )
    matches = [m for m in matches if m.orphan.key not in forget]

    moves = [m for m in matches if not m.tracked]
    if moves:
        for m in moves:
            item = _item(m.orphan.canvas_type, m.orphan.canvas_id)
            warn(
                f"ERROR: {m.orphan.key} → {m.path} ({m.reason_text}): this looks like a "
                "move made without `markdown-to-canvas mv`. Updating would create a "
                f"second Canvas {m.orphan.canvas_type} next to {item}.",
                errors,
            )
            print(f"      To record the move and keep using {item}:")
            print(f"        {commands.mv_after(m.orphan.key, m.path)}")
            print(
                f"      Or, if {m.path} is a separate item, forget the old entry "
                f"({item} stays in Canvas):"
            )
            print(f"        {commands.update_new(m.path)}")
        print("\nAborting: nothing was changed in Canvas or the manifest.")
        return True

    if forget and manifest_path is not None:
        manifest_lib.flush(manifest_path, manifest)

    for m in matches:
        print(
            f"  WARNING: probable duplicate in Canvas: {m.orphan.key} "
            f"({_item(m.orphan.canvas_type, m.orphan.canvas_id)}) no longer exists "
            f"locally but matches {m.path} ({_item(m.orphan.canvas_type, m.path_id)}) "
            f"({m.reason_text}). Both items are in Canvas."
        )
        print("      To forget the old entry and keep both Canvas items:")
        print(f"        {commands.update_new(m.path)}")
        print(
            "      Or remove orphaned items from Canvas with prune. It acts on every "
            "orphaned entry at once, and deleting an assignment also deletes its "
            "submissions:"
        )
        print(f"        {commands.prune()}")
    if verbose and not matches:
        print(f"Unrecorded-move check: {len(orphans)} orphaned entries, no matches.")
    return False
