"""Read and write the per-config manifest (.manifest-<config stem>.toml)."""
from __future__ import annotations

import tomllib
import tomli_w
from collections.abc import Callable, Iterable
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


ManifestDict = dict[str, dict[str, Any]]


LEGACY_MANIFEST_NAME = ".canvas-manifest.toml"

#: Glob matching every per-config manifest name produced by manifest_name_for().
MANIFEST_GLOB = ".manifest-*.toml"

DEFAULT_CONFIG_STEM = "canvas"

#: Reserved manifest key holding the Canvas course the manifest's IDs belong to.
#: Not a repo path: code that walks every entry must skip it (see is_course_key).
COURSE_KEY = "_canvas_course"
COURSE_TYPE = "course_identity"


def manifest_name_for(config_path: Path | None) -> str:
    """File name of the manifest belonging to ``config_path``.

    The manifest is keyed to the canvas.toml that names the Canvas course, so
    one repo can drive several courses (e.g. one per section) without the runs
    overwriting each other's Canvas IDs: ``course_settings/canvas.toml`` →
    ``.manifest-canvas.toml``, ``course_settings/canvas-sec-a.toml`` →
    ``.manifest-canvas-sec-a.toml``. ``None`` means the default config.
    """
    stem = config_path.stem if config_path is not None else DEFAULT_CONFIG_STEM
    return f".manifest-{stem}.toml"


def manifest_path_for(repo_path: Path, config_path: Path | None) -> Path:
    """Path of the manifest belonging to ``config_path``, inside ``repo_path``."""
    return repo_path / manifest_name_for(config_path)


def migrate_legacy_manifest(repo_path: Path, config_path: Path | None) -> Path:
    """Resolve the manifest path, renaming a pre-per-config manifest into place.

    Repos written by an older version of the tool have a single
    ``.canvas-manifest.toml``. That file belongs to the default config, so it
    is renamed to ``.manifest-canvas.toml`` (once, with a printed notice) and
    only when the run is using the default config and the new name does not
    already exist. A run pointed at some other canvas.toml never adopts it —
    those Canvas IDs belong to a different course.
    """
    path = manifest_path_for(repo_path, config_path)
    legacy = repo_path / LEGACY_MANIFEST_NAME
    if (
        path.name == manifest_name_for(None)
        and not path.exists()
        and legacy.exists()
    ):
        legacy.rename(path)
        print(f"Renamed {LEGACY_MANIFEST_NAME} → {path.name} (one manifest per canvas.toml)")
    return path


def flag_change(
    entry: dict[str, Any], current_flags: dict[str, bool]
) -> tuple[str, bool, bool | None] | None:
    """First recorded course flag whose value no longer matches, if any.

    Compares the entry's ``flags_used`` sub-table (flag values in effect at
    the file's last successful sync) against ``current_flags``. Returns
    ``(name, recorded_value, current_value)`` — current_value is None when
    the flag was deleted from [course_flags] — or None if nothing changed.
    """
    flags_used = entry.get("flags_used") or {}
    for name, recorded in flags_used.items():
        if name not in current_flags:
            return name, bool(recorded), None
        if bool(current_flags[name]) != bool(recorded):
            return name, bool(recorded), bool(current_flags[name])
    return None


def print_flag_change_reason(change: tuple[str, bool, bool | None]) -> None:
    """Verbose-mode explanation for a flag-triggered re-sync."""
    name, recorded, current = change
    if current is None:
        print(f"  re-syncing: flag '{name}' deleted from course_settings.toml")
    else:
        print(
            f"  re-syncing: flag '{name}' changed "
            f"{str(recorded).lower()} → {str(current).lower()}"
        )


def needs_sync(
    manifest: ManifestDict,
    local_key: str,
    file_path: Path,
    force: bool = False,
    extra_mtime_paths: Callable[[], Iterable[Path]] | None = None,
    current_flags: dict[str, bool] | None = None,
    verbose: bool = False,
) -> bool:
    """Return True if the file should be synced to Canvas.

    True when: force=True, no manifest entry, no last_synced, file mtime is newer
    than last_synced, or (if file_path alone isn't newer) any path returned by
    extra_mtime_paths() is newer than last_synced. When ``current_flags`` is
    given, also True when any course flag recorded in the entry's
    ``flags_used`` sub-table is missing from current_flags or differs in value
    (in verbose mode the changed flag is printed as the reason).

    extra_mtime_paths is a zero-arg callable rather than a plain iterable so
    callers can defer the (potentially file-reading) work of computing it —
    it's only invoked when file_path's own mtime didn't already settle the
    question, e.g. to check whether a referenced snippet changed.
    """
    if force:
        return True
    entry = manifest.get(local_key)
    if entry is None or "last_synced" not in entry:
        return True
    last_synced = datetime.fromisoformat(entry["last_synced"])
    file_mtime = datetime.fromtimestamp(file_path.stat().st_mtime, tz=timezone.utc)
    if file_mtime > last_synced:
        return True
    if extra_mtime_paths is not None and any(
        datetime.fromtimestamp(p.stat().st_mtime, tz=timezone.utc) > last_synced
        for p in extra_mtime_paths()
    ):
        return True
    if current_flags is not None:
        change = flag_change(entry, current_flags)
        if change is not None:
            if verbose:
                print_flag_change_reason(change)
            return True
    return False


def load(path: Path) -> ManifestDict:
    if not path.exists():
        return {}
    with open(path, "rb") as f:
        return dict(tomllib.load(f))


def flush(path: Path | None, manifest: ManifestDict) -> None:
    """Write the manifest to disk. path=None means in-memory only (used by
    `update --check-all`, which must never touch the manifest file)."""
    if path is None:
        return
    with open(path, "wb") as f:
        tomli_w.dump(manifest, f)


def record(
    manifest: ManifestDict,
    manifest_path: Path | None,
    local_path: str,
    canvas_id: int,
    canvas_type: str,
    extra: dict[str, Any] | None = None,
    mark_synced: bool = True,
) -> None:
    """Update an entry and immediately flush to disk (unless manifest_path is
    None — see flush()).

    mark_synced=False records the Canvas object (so a later run updates it
    instead of creating a duplicate) but omits ``last_synced``, leaving the
    entry stale so needs_sync() retries it on the next run — used when the
    upload partially failed.
    """
    entry: dict[str, Any] = {
        "canvas_id": canvas_id,
        "canvas_type": canvas_type,
    }
    if mark_synced:
        entry["last_synced"] = datetime.now(timezone.utc).isoformat()
    if extra:
        entry.update(extra)
    manifest[local_path] = entry
    flush(manifest_path, manifest)


def is_course_key(key: str, entry: dict[str, Any] | None = None) -> bool:
    """True for the reserved stored-course entry (not a repo file)."""
    return key == COURSE_KEY or (entry or {}).get("canvas_type") == COURSE_TYPE


def get_course_identity(manifest: ManifestDict) -> dict[str, Any] | None:
    """The stored course (base_url, course_id, course_name), or None if unrecorded."""
    entry = manifest.get(COURSE_KEY)
    if not entry or "course_id" not in entry or "base_url" not in entry:
        return None
    return entry


def set_course_identity(
    manifest: ManifestDict,
    manifest_path: Path | None,
    base_url: str,
    course_id: int,
    course_name: str,
) -> None:
    """Record which Canvas course the manifest's IDs belong to, and flush."""
    manifest[COURSE_KEY] = {
        "canvas_type": COURSE_TYPE,
        "base_url": base_url.rstrip("/"),
        "course_id": int(course_id),
        "course_name": course_name,
        "recorded_at": datetime.now(timezone.utc).isoformat(),
    }
    flush(manifest_path, manifest)


def same_course(identity: dict[str, Any], base_url: str, course_id: int) -> bool:
    return (
        str(identity.get("base_url", "")).rstrip("/").lower()
        == base_url.rstrip("/").lower()
        and int(identity.get("course_id", -1)) == int(course_id)
    )


def has_content_entries(manifest: ManifestDict) -> bool:
    """True if the manifest holds any entry other than the stored course."""
    return any(not is_course_key(k, v) for k, v in manifest.items())
