"""Move/rename files within a course repo, updating manifest and links."""
from __future__ import annotations

import os
import re
import shutil
import subprocess
import tomllib
import uuid
from pathlib import Path, PurePosixPath
from urllib.parse import unquote

import tomlkit

from . import manifest as manifest_lib
from . import repo_format, toml_write
from .links import transform_links  # re-exported: mv's public API before links.py
from .links import resolve_repo_relative, split_suffix
from .config import find_repo_root  # re-exported: mv's public API since before the move

_CONTENT_TYPE_DIRS = {
    "pages", "assignments", "discussions", "announcements", "quizzes",
    "assets", "snippets", "modules", "question_banks",
    "course_settings",
}


def _content_type_dir(rel_path: str) -> str | None:
    """Return the top-level content directory from a repo-relative path."""
    first = rel_path.split("/")[0]
    return first if first in _CONTENT_TYPE_DIRS else None


def _is_git_repo(path: Path) -> bool:
    try:
        result = subprocess.run(
            ["git", "rev-parse", "--git-dir"],
            cwd=str(path),
            capture_output=True,
            timeout=5,
        )
        return result.returncode == 0
    except (FileNotFoundError, subprocess.TimeoutExpired):
        return False


def _has_tracked_content(repo_root: Path, path: Path) -> bool:
    """True if path (file or directory) contains any git-tracked file.

    `git mv` errors out instead of moving the file when nothing under
    path is tracked yet, so callers must fall back to a plain filesystem
    move in that case.
    """
    try:
        result = subprocess.run(
            ["git", "ls-files", "--error-unmatch", "--", str(path)],
            cwd=str(repo_root),
            capture_output=True,
            timeout=5,
        )
        return result.returncode == 0
    except (FileNotFoundError, subprocess.TimeoutExpired):
        return False


def _is_case_only_rename(src: Path, dest: Path) -> bool:
    """True if src and dest differ only in case (same path on case-insensitive FS)."""
    if str(src).lower() != str(dest).lower():
        return False
    if str(src) == str(dest):
        return False
    try:
        return src.resolve() == dest.resolve()
    except OSError:
        return dest.exists() and src.stat().st_ino == dest.stat().st_ino


def has_trailing_slash(dest: Path | str) -> bool:
    """True if DEST was written with a trailing separator (e.g. "summer/").

    Path() discards the separator, so this must be checked against the raw
    string the user typed, before any Path conversion.
    """
    return isinstance(dest, str) and dest.endswith(("/", os.sep))


def resolve_dest(src: Path, dest: Path, *, must_be_dir: bool = False) -> Path:
    """Expand a directory destination into a full destination path.

    Mirrors normal `mv`: when DEST is an existing directory, SRC is moved
    into it keeping its own name. A case-only rename is left alone, since
    on a case-insensitive filesystem the destination "already exists" as
    the source itself.

    `must_be_dir` (set when DEST had a trailing slash) rejects a
    non-directory destination rather than silently renaming SRC to it,
    again matching normal `mv`.
    """
    if must_be_dir and not dest.is_dir():
        what = "is a file, not a directory" if dest.exists() else "does not exist"
        raise ValueError(
            f"Destination directory {what}: {dest}/\n"
            f"The trailing '/' means DEST must be an existing directory.\n"
            f"Create it first, or drop the trailing '/' to rename {src.name} to {dest.name}."
        )
    if dest.is_dir() and not _is_case_only_rename(src, dest):
        return dest / src.name
    return dest


def validate_move(src: Path, dest: Path, repo_root: Path) -> None:
    """Validate the move. Raises ValueError on failure."""
    if not src.exists():
        raise ValueError(f"Source does not exist: {src}")

    case_rename = _is_case_only_rename(src, dest)
    if dest.exists() and not case_rename:
        raise ValueError(f"Destination already exists: {dest}")

    try:
        src_rel = src.resolve().relative_to(repo_root.resolve())
    except ValueError:
        raise ValueError(
            f"Source is outside the course repo ({repo_root}): {src}"
        )
    try:
        dest_rel_parts = dest.resolve().relative_to(repo_root.resolve()) if not case_rename else None
        if case_rename:
            dest_rel = PurePosixPath(
                str(src.resolve().relative_to(repo_root.resolve()).parent)
            ) / dest.name
            if src.resolve().parent != dest.resolve().parent:
                dest_rel = dest.relative_to(repo_root)
        else:
            dest_rel = dest_rel_parts
    except ValueError:
        raise ValueError(
            f"Destination is outside the course repo ({repo_root}): {dest}"
        )

    src_type = _content_type_dir(src_rel.as_posix())
    dest_type = _content_type_dir(dest_rel.as_posix() if hasattr(dest_rel, 'as_posix') else str(dest_rel))
    if src_type != dest_type:
        raise ValueError(
            f"Cannot move across content types: {src_type}/ → {dest_type}/\n"
            f"Both source and destination must be in the same top-level directory."
        )

    dest_parent = dest.parent
    dest_parent_exists = dest_parent.exists()
    if not dest_parent_exists and case_rename:
        dest_parent_exists = dest_parent.resolve() == src.resolve().parent
    if not dest_parent_exists:
        raise ValueError(
            f"Destination parent directory does not exist: {dest_parent}\n"
            f"Create it first, or rename intermediate directories one at a time."
        )


def build_path_map(src: Path, dest: Path, repo_root: Path) -> dict[str, str]:
    """Build old→new repo-relative path mapping for all affected files.

    For quiz/question_bank folder renames, includes the inner file rename.
    """
    src_rel = src.resolve().relative_to(repo_root.resolve()).as_posix()
    case_rename = _is_case_only_rename(src, dest)

    if case_rename:
        dest_rel = _compute_case_rename_dest_rel(src, dest, repo_root)
    else:
        dest_rel = dest.resolve().relative_to(repo_root.resolve()).as_posix()

    path_map: dict[str, str] = {}

    if src.is_file():
        path_map[src_rel] = dest_rel
    elif src.is_dir():
        for child in sorted(src.rglob("*")):
            if child.is_file():
                child_rel = child.resolve().relative_to(repo_root.resolve()).as_posix()
                suffix = child_rel[len(src_rel):]
                path_map[child_rel] = dest_rel + suffix

        _add_quiz_qbank_inner_renames(src, dest, src_rel, dest_rel, path_map)

    return path_map


def _repo_rel(path: Path, repo_root: Path, what: str) -> str:
    try:
        return path.resolve().relative_to(repo_root.resolve()).as_posix()
    except ValueError:
        raise ValueError(f"{what} is outside the course repo ({repo_root}): {path}")


def validate_after(old: Path, new: Path, repo_root: Path) -> None:
    """Validate `mv --after OLD NEW`: the move already happened on disk."""
    if old.exists():
        raise ValueError(
            f"{old} still exists, so there is no move to record.\n"
            "To move it, run mv without --after."
        )
    if not new.exists():
        raise ValueError(
            f"Destination does not exist: {new}\n"
            "With --after, NEW is where the file or folder already is."
        )
    old_type = _content_type_dir(_repo_rel(old, repo_root, "Source"))
    new_type = _content_type_dir(_repo_rel(new, repo_root, "Destination"))
    if old_type != new_type:
        raise ValueError(
            f"Cannot move across content types: {old_type}/ → {new_type}/\n"
            f"Both source and destination must be in the same top-level directory."
        )


def build_after_path_map(old: Path, new: Path, repo_root: Path) -> dict[str, str]:
    """old→new mapping for a move already made on disk.

    OLD is gone, so the map is built from what is at NEW: a file maps to OLD
    itself, a folder maps each file under it to the same path under OLD. A
    renamed quiz/qbank folder whose inner file was renamed with it maps the
    old inner name (OLD/OLD.md) to the new one (NEW/NEW.md).
    """
    old_rel = _repo_rel(old, repo_root, "Source")
    new_rel = _repo_rel(new, repo_root, "Destination")
    if new.is_file():
        return {old_rel: new_rel}
    path_map: dict[str, str] = {}
    for child in sorted(new.rglob("*")):
        if child.is_file():
            child_rel = child.resolve().relative_to(repo_root.resolve()).as_posix()
            path_map[old_rel + child_rel[len(new_rel):]] = child_rel
    parts = old_rel.split("/")
    suffix = _INNER_FILE_SUFFIX.get(parts[0]) if len(parts) >= 2 else None
    if suffix is not None and old.name != new.name:
        new_inner = f"{new_rel}/{new.name}{suffix}"
        if new_inner in path_map.values():
            path_map.pop(f"{old_rel}/{new.name}{suffix}", None)
            path_map[f"{old_rel}/{old.name}{suffix}"] = new_inner
    return path_map


def _compute_case_rename_dest_rel(src: Path, dest: Path, repo_root: Path) -> str:
    """Compute the dest repo-relative path for a case-only rename."""
    src_resolved = src.resolve()
    repo_resolved = repo_root.resolve()
    src_rel_path = src_resolved.relative_to(repo_resolved)

    dest_str = str(dest.absolute())
    repo_str = str(repo_resolved)

    if dest_str.startswith(repo_str + "/"):
        return dest_str[len(repo_str) + 1:]

    src_rel_str = src_rel_path.as_posix()
    old_name = src.name
    new_name = dest.name
    if src_rel_str.endswith(old_name):
        return src_rel_str[: -len(old_name)] + new_name

    return src_rel_str


# Folders whose <name>/<name>.<ext> inner file must be renamed with the folder.
_INNER_FILE_SUFFIX = {"quizzes": ".md", "question_banks": ".toml"}


def _add_quiz_qbank_inner_renames(
    src: Path, dest: Path,
    src_rel: str, dest_rel: str,
    path_map: dict[str, str],
) -> None:
    """For quiz/qbank folder renames, add inner file renames to path_map."""
    src_name = src.name
    dest_name = dest.name

    if src_name == dest_name:
        return

    parts = src_rel.split("/")
    if len(parts) < 2:
        return

    suffix = _INNER_FILE_SUFFIX.get(parts[0])
    if suffix is None:
        return

    old_inner = f"{src_rel}/{src_name}{suffix}"
    new_inner = f"{dest_rel}/{dest_name}{suffix}"
    if old_inner in path_map:
        path_map[old_inner] = new_inner


def compute_manifest_updates(
    manifest: manifest_lib.ManifestDict,
    path_map: dict[str, str],
) -> manifest_lib.ManifestDict:
    """Return a new manifest dict with updated keys and canvas_item_ids."""
    new_manifest: manifest_lib.ManifestDict = {}
    for key, entry in manifest.items():
        if manifest_lib.is_reserved_key(key, entry):
            new_manifest[key] = entry
            continue
        new_key = path_map.get(key, key)
        new_entry = dict(entry)

        if "canvas_item_ids" in new_entry:
            old_ids = new_entry["canvas_item_ids"]
            new_ids = {}
            for item_path, item_id in old_ids.items():
                new_item_path = path_map.get(item_path, item_path)
                new_ids[new_item_path] = item_id
            new_entry["canvas_item_ids"] = new_ids

        new_manifest[new_key] = new_entry
    return new_manifest


def compute_module_order_updates(
    repo_root: Path,
    path_map: dict[str, str],
) -> list[str] | None:
    """If module files are in path_map, compute new module_order list. Returns None if no changes."""
    order_path = repo_root / "course_settings" / "module_order.toml"
    if not order_path.exists():
        return None

    module_renames: dict[str, str] = {}
    for old, new in path_map.items():
        if old.startswith("modules/"):
            old_name = PurePosixPath(old).name
            new_name = PurePosixPath(new).name
            if old_name != new_name:
                module_renames[old_name] = new_name

    if not module_renames:
        return None

    with order_path.open("rb") as f:
        data = tomllib.load(f)
    order = list(data.get("order", []))

    changed = False
    for i, entry in enumerate(order):
        if isinstance(entry, str) and entry in module_renames:
            order[i] = module_renames[entry]
            changed = True

    return order if changed else None


_COURSE_SETTINGS_PATH_FIELDS = ("dashboard_image", "front_page")


def compute_course_settings_updates(
    repo_root: Path,
    path_map: dict[str, str],
) -> dict[str, str] | None:
    """If course_settings.toml's dashboard_image/front_page was moved, return
    {field: new_repo_relative_path} for the changed fields. None if no changes."""
    settings_path = repo_root / "course_settings" / "course_settings.toml"
    if not settings_path.exists():
        return None

    with settings_path.open("rb") as f:
        data = tomllib.load(f)

    updates: dict[str, str] = {}
    for field in _COURSE_SETTINGS_PATH_FIELDS:
        old_value = data.get(field)
        if not old_value:
            continue
        new_value = path_map.get(old_value)
        if new_value is not None and new_value != old_value:
            updates[field] = new_value

    return updates or None


def compute_pinned_resources_updates(
    repo_root: Path,
    path_map: dict[str, str],
    src_rel: str,
    dest_rel: str,
) -> dict[str, str] | None:
    """If pinned_resources entries point at (or under) the moved path, return
    {old_entry_as_written: new_repo_relative_path}. None if no changes.

    A stale pin would silently unpin the resource — the next update would then
    re-upload it (for a quiz: delete and recreate its questions), which is the
    exact thing the pin exists to prevent — so mv rewrites pin paths just like
    it rewrites module_order and front_page/dashboard_image.

    File pins resolve through path_map (which includes quiz/qbank inner-file
    renames); folder pins resolve by prefix against the moved directory.
    """
    settings_path = repo_root / "course_settings" / "course_settings.toml"
    if not settings_path.exists():
        return None

    with settings_path.open("rb") as f:
        data = tomllib.load(f)

    pinned = data.get("pinned_resources", [])
    if not isinstance(pinned, list):
        return None

    updates: dict[str, str] = {}
    for entry in pinned:
        if not isinstance(entry, str):
            continue
        normalized = entry.strip().replace("\\", "/").rstrip("/")
        if normalized in path_map:
            new_value = path_map[normalized]
        elif normalized == src_rel:
            new_value = dest_rel
        elif normalized.startswith(src_rel + "/"):
            new_value = dest_rel + normalized[len(src_rel):]
        else:
            continue
        if new_value != entry:
            updates[entry] = new_value

    return updates or None


def _after_link_keeper(
    repo_root: Path, old_dir: str, new_dir: str, path_map: dict[str, str]
):
    """url_map for a file that was moved before `mv --after` ran.

    Its links may have been written for its old folder or already updated by
    an editor for its new one, and the text alone cannot say which. A link
    that reaches an existing file from the new folder is kept as is; one that
    only reaches an existing file from the old folder is left to the normal
    rebase (returns None); one that reaches nothing from either is kept.
    """

    def exists(rel: str | None) -> bool:
        return rel is not None and (repo_root / rel).exists()

    def url_map(url: str) -> str | None:
        path_part, _ = split_suffix(url)
        if not path_part:
            return url
        decoded = unquote(path_part)
        if exists(resolve_repo_relative(new_dir, decoded)):
            return url
        from_old = resolve_repo_relative(old_dir, decoded)
        if from_old is not None and exists(path_map.get(from_old, from_old)):
            return None
        return url

    return url_map


def compute_file_updates(
    repo_root: Path,
    path_map: dict[str, str],
    after: bool = False,
) -> dict[str, tuple[str, str]]:
    """Compute {new_repo_rel_path: (old_content, new_content)} for files with link changes.

    With ``after`` (``mv --after``) the moved files are already at their new
    paths on disk; their own links go through ``_after_link_keeper``.
    """
    moved_files = set(path_map.keys())
    moved_back = {new: old for old, new in path_map.items()} if after else {}
    updates: dict[str, tuple[str, str]] = {}

    for md_file in sorted(repo_root.rglob("*.md")):
        if md_file.name.startswith("."):
            continue
        try:
            repo_rel = md_file.relative_to(repo_root).as_posix()
        except ValueError:
            continue

        url_map = None
        if repo_rel in moved_back:
            old_dir = str(PurePosixPath(moved_back[repo_rel]).parent)
            new_path = repo_rel
            new_dir = str(PurePosixPath(repo_rel).parent)
            url_map = _after_link_keeper(repo_root, old_dir, new_dir, path_map)
        elif repo_rel in moved_files:
            old_dir = str(PurePosixPath(repo_rel).parent)
            new_path = path_map[repo_rel]
            new_dir = str(PurePosixPath(new_path).parent)
        else:
            old_dir = str(PurePosixPath(repo_rel).parent)
            new_path = repo_rel
            new_dir = old_dir

        try:
            content = md_file.read_text()
        except (OSError, UnicodeDecodeError):
            continue

        new_content = transform_links(content, old_dir, new_dir, path_map, url_map=url_map)
        if new_content != content:
            updates[new_path] = (content, new_content)

    return updates


def _updated_module_order_text(text: str, order: list[str]) -> str:
    """module_order.toml text with `order` replaced, keeping comments and layout.

    Entries are changed in place when the list keeps its length (a rename), so
    the array's own formatting and any comments inside it survive too.
    """
    doc = tomlkit.parse(text)
    current = doc.get("order")
    if isinstance(current, list) and len(current) == len(order):
        for i, entry in enumerate(order):
            if current[i] != entry:
                current[i] = entry
    else:
        doc["order"] = toml_write.scalar_array(order, multiline=True)
    return tomlkit.dumps(doc)


def _set_toml_string_value(content: str, key: str, value: str) -> str:
    """Replace a top-level `key = "..."` scalar assignment in raw TOML text.

    Edits the text directly instead of parsing and re-dumping the file, so
    comments and existing array formatting (e.g. due_dates) are left untouched.
    """
    escaped_value = value.replace("\\", "\\\\").replace('"', '\\"')
    pattern = re.compile(rf'^{re.escape(key)}\s*=\s*".*"$', re.MULTILINE)
    new_content, count = pattern.subn(f'{key} = "{escaped_value}"', content, count=1)
    if count == 0:
        raise ValueError(f"Could not find top-level {key!r} assignment in course_settings.toml")
    return new_content


def _replace_toml_quoted_string(content: str, old: str, new: str) -> str:
    """Replace every quoted occurrence of `old` (either quote style) in raw
    TOML text.

    Same rationale as _set_toml_string_value: textual edit to preserve
    comments and formatting. Used for pinned_resources entries, which live in
    an array so there is no `key = "..."` line to anchor on. Matching the
    fully quoted string keeps this from touching prose; the only other places
    a repo-relative path appears quoted in course_settings.toml
    (front_page/dashboard_image) would be rewritten to the same new value
    anyway.
    """
    escaped_new = new.replace("\\", "\\\\").replace('"', '\\"')
    content = content.replace(f'"{old}"', f'"{escaped_new}"')
    return content.replace(f"'{old}'", f'"{escaped_new}"')


def _move_one(src: Path, dest: Path, repo_root: Path, use_git: bool) -> None:
    """Move src → dest. A case-only rename goes via a temp name first, which is
    required on case-insensitive filesystems where src and dest are "the same"."""
    if _is_case_only_rename(src, dest):
        temp = dest.parent / f".mv-tmp-{uuid.uuid4().hex[:8]}"
        if use_git:
            subprocess.run(["git", "mv", str(src), str(temp)], cwd=str(repo_root), check=True)
            subprocess.run(["git", "mv", str(temp), str(dest)], cwd=str(repo_root), check=True)
        else:
            src.rename(temp)
            temp.rename(dest)
    else:
        if use_git:
            subprocess.run(["git", "mv", str(src), str(dest)], cwd=str(repo_root), check=True)
        else:
            shutil.move(str(src), str(dest))


def _do_move(
    src: Path, dest: Path, repo_root: Path, use_git: bool,
    inner_renames: list[tuple[Path, Path]] | None = None,
) -> None:
    """Execute the physical move(s)."""
    _move_one(src, dest, repo_root, use_git)
    for inner_src, inner_dest in inner_renames or []:
        _move_one(inner_src, inner_dest, repo_root, use_git)


def _get_inner_renames(
    src: Path, dest: Path, src_rel: str, dest_rel: str,
) -> list[tuple[Path, Path]]:
    """Compute inner file renames for quiz/qbank folders after the directory move."""
    renames = []
    src_name = src.name
    dest_name = dest.name

    if src_name == dest_name:
        return renames

    parts = src_rel.split("/")
    if len(parts) < 2:
        return renames

    suffix = _INNER_FILE_SUFFIX.get(parts[0])
    if suffix is None:
        return renames

    old_inner = dest / f"{src_name}{suffix}"
    new_inner = dest / f"{dest_name}{suffix}"
    if old_inner.exists() or (not dest.exists() and (src / f"{src_name}{suffix}").exists()):
        renames.append((old_inner, new_inner))

    return renames


def find_manifests(repo_root: Path) -> list[Path]:
    """Every manifest file in the repo root, one per canvas.toml.

    ``mv`` has no ``--config`` option and a rename affects every course the
    repo drives, so all of them are rewritten — including a pre-per-config
    ``.canvas-manifest.toml`` is not included: ``upgrade`` renames it.
    """
    return sorted(repo_root.glob(manifest_lib.MANIFEST_GLOB))


def compute_all_manifest_updates(
    repo_root: Path, path_map: dict[str, str]
) -> list[tuple[Path, manifest_lib.ManifestDict]]:
    """(path, rewritten manifest) for each manifest the move actually changes."""
    updates: list[tuple[Path, manifest_lib.ManifestDict]] = []
    for path in find_manifests(repo_root):
        manifest = manifest_lib.load(path)
        new_manifest = compute_manifest_updates(manifest, path_map)
        if new_manifest != manifest:
            updates.append((path, new_manifest))
    return updates


def plan_after_manifest_updates(
    repo_root: Path, path_map: dict[str, str]
) -> tuple[
    list[tuple[Path, manifest_lib.ManifestDict]],
    list[tuple[Path, list[tuple[str, str, object, object]]]],
    bool,
]:
    """Manifest rewrites for `mv --after`, one manifest at a time.

    A manifest that already has an entry for a NEW path as well as its OLD path
    is left unchanged (the duplicate already exists in that course) and
    returned in the second list as (manifest, [(old, new, old_id, new_id)]).
    The flag says whether any manifest has an OLD key at all.
    """
    updates: list[tuple[Path, manifest_lib.ManifestDict]] = []
    clashes: list[tuple[Path, list[tuple[str, str, object, object]]]] = []
    any_old = False
    for path in find_manifests(repo_root):
        manifest = manifest_lib.load(path)
        olds = [o for o in path_map if o in manifest]
        any_old = any_old or bool(olds)
        both = [
            (o, path_map[o], manifest[o].get("canvas_id"), manifest[path_map[o]].get("canvas_id"))
            for o in olds
            if path_map[o] in manifest
        ]
        if both:
            clashes.append((path, both))
            continue
        new_manifest = compute_manifest_updates(manifest, path_map)
        if new_manifest != manifest:
            updates.append((path, new_manifest))
    return updates, clashes, any_old


def _config_args_for(manifest_path: Path) -> str:
    """--config for the canvas.toml a manifest belongs to (the usual layout:
    .manifest-<stem>.toml ↔ course_settings/<stem>.toml)."""
    stem = manifest_path.name[len(".manifest-"):-len(".toml")]
    if stem == manifest_lib.DEFAULT_CONFIG_STEM:
        return ""
    return f" --config course_settings/{stem}.toml"


def _describe_clashes(
    repo_root: Path, clashes: list[tuple[Path, list[tuple[str, str, object, object]]]]
) -> None:
    from .unrecorded_moves import Commands

    for path, pairs in clashes:
        for old, new, old_id, new_id in pairs:
            commands = Commands(repo_root)
            course = commands.shown(".") + _config_args_for(path)
            print(
                f"  {path.name}: left unchanged. {old} (Canvas ID {old_id}) and {new} "
                f"(Canvas ID {new_id}) both have entries, so they are probably "
                "duplicate Canvas items. To forget the old entry:\n"
                f"    {Commands(repo_root, course).update_new(new)}"
            )


def _describe_changes(
    path_map: dict[str, str],
    manifest_names: list[str],
    file_updates: dict[str, tuple[str, str]],
    module_order_updates: list[str] | None,
    course_settings_updates: dict[str, str] | None,
    pinned_updates: dict[str, str] | None,
    noop: bool,
    verbose: bool,
    after: bool = False,
) -> None:
    """Print summary or verbose output of changes."""
    prefix = "Would " if noop else ""
    verb = "record move" if after else "move"

    if verbose or noop:
        for old, new in sorted(path_map.items()):
            print(f"  {prefix}{verb}: {old} → {new}")

    files_moved = len(path_map)
    manifest_entries = sum(1 for o, n in path_map.items() if o != n) if manifest_names else 0

    link_file_count = len(file_updates)
    link_total = 0
    if verbose or noop:
        for fpath, (old_content, new_content) in sorted(file_updates.items()):
            old_lines = old_content.splitlines()
            new_lines = new_content.splitlines()
            for i, (ol, nl) in enumerate(zip(old_lines, new_lines)):
                if ol != nl:
                    link_total += 1
                    if verbose or noop:
                        print(f"  {prefix}update link in {fpath}:{i+1}")
                        print(f"    From: {ol.strip()}")
                        print(f"    To:   {nl.strip()}")
    else:
        for fpath, (old_content, new_content) in file_updates.items():
            old_lines = old_content.splitlines()
            new_lines = new_content.splitlines()
            link_total += sum(1 for o, n in zip(old_lines, new_lines) if o != n)

    parts = []
    if after:
        parts.append(f"{'Would record' if noop else 'Recorded'} the move of {files_moved} file(s)")
    else:
        parts.append(f"{'Would move' if noop else 'Moved'} {files_moved} file(s)")
    if manifest_names:
        where = "" if len(manifest_names) == 1 else f" in {', '.join(manifest_names)}"
        parts.append(f"updated {manifest_entries} manifest entry/entries{where}")
    if link_total:
        parts.append(f"updated {link_total} link(s) across {link_file_count} file(s)")
    if module_order_updates is not None:
        parts.append("updated module_order.toml")
    if course_settings_updates:
        fields = ", ".join(sorted(course_settings_updates))
        parts.append(f"updated {fields} in course_settings.toml")
    if pinned_updates:
        noun = "entry" if len(pinned_updates) == 1 else "entries"
        parts.append(
            f"updated {len(pinned_updates)} pinned_resources {noun} "
            f"in course_settings.toml"
        )

    print(", ".join(parts) + ".")


def run_mv(
    src: Path,
    dest: Path | str,
    noop: bool = False,
    verbose: bool = False,
    after: bool = False,
) -> None:
    """Move/rename a file or directory, updating manifest and all references.

    DEST may be a str so a trailing separator survives to `resolve_dest`.

    ``after`` (``mv --after``) records a move already made on disk: SRC is
    gone and DEST exists. Everything is updated except the files themselves,
    which are not moved. DEST names the actual location, so it is never
    expanded to DEST/SRC.name.
    """
    if after:
        _run_mv_after(src.absolute(), Path(dest).absolute(), noop, verbose)
        return
    must_be_dir = has_trailing_slash(dest)
    src = src.absolute()
    dest = resolve_dest(src, Path(dest).absolute(), must_be_dir=must_be_dir)

    repo_root = find_repo_root(src)
    if repo_root is None:
        repo_root = find_repo_root(dest)
    if repo_root is None:
        raise ValueError(
            "Could not find course repo root.\n"
            "Looked for course_settings/course_settings.toml by walking up from\n"
            f"  {src}\n"
            "Create course_settings/course_settings.toml (it can be empty) to mark the repo root."
        )

    repo_format.check_repo_format(repo_root)

    validate_move(src, dest, repo_root)

    src_rel = src.resolve().relative_to(repo_root.resolve()).as_posix()
    case_rename = _is_case_only_rename(src, dest)
    if case_rename:
        dest_rel = _compute_case_rename_dest_rel(src, dest, repo_root)
    else:
        dest_rel = dest.resolve().relative_to(repo_root.resolve()).as_posix()

    path_map = build_path_map(src, dest, repo_root)

    manifest_updates = compute_all_manifest_updates(repo_root, path_map)
    manifest_names = [path.name for path, _ in manifest_updates]

    file_updates = compute_file_updates(repo_root, path_map)

    module_order_updates = compute_module_order_updates(repo_root, path_map)
    course_settings_updates = compute_course_settings_updates(repo_root, path_map)
    pinned_updates = compute_pinned_resources_updates(
        repo_root, path_map, src_rel, dest_rel
    )

    inner_renames_paths: list[tuple[Path, Path]] = []
    if src.is_dir():
        inner_renames_paths = _get_inner_renames(src, dest, src_rel, dest_rel)

    _describe_changes(
        path_map, manifest_names, file_updates,
        module_order_updates, course_settings_updates, pinned_updates,
        noop, verbose,
    )

    if noop:
        return

    use_git = _is_git_repo(repo_root) and _has_tracked_content(repo_root, src)
    _do_move(src, dest, repo_root, use_git, inner_renames_paths)

    _write_updates(
        repo_root, file_updates, manifest_updates, module_order_updates,
        course_settings_updates, pinned_updates,
    )


def _write_updates(
    repo_root: Path,
    file_updates: dict[str, tuple[str, str]],
    manifest_updates: list[tuple[Path, manifest_lib.ManifestDict]],
    module_order_updates: list[str] | None,
    course_settings_updates: dict[str, str] | None,
    pinned_updates: dict[str, str] | None,
) -> None:
    """Write the link, manifest, module_order and course_settings changes."""
    for file_new_path, (_, new_content) in file_updates.items():
        target = repo_root / file_new_path
        target.write_text(new_content)

    for path, new_manifest in manifest_updates:
        manifest_lib.flush(path, new_manifest)

    if module_order_updates is not None:
        order_path = repo_root / "course_settings" / "module_order.toml"
        order_path.write_text(
            _updated_module_order_text(
                order_path.read_text(encoding="utf-8"), module_order_updates
            ),
            encoding="utf-8",
        )

    if course_settings_updates or pinned_updates:
        settings_path = repo_root / "course_settings" / "course_settings.toml"
        content = settings_path.read_text(encoding="utf-8")
        for field, new_value in (course_settings_updates or {}).items():
            content = _set_toml_string_value(content, field, new_value)
        for old_entry, new_value in (pinned_updates or {}).items():
            content = _replace_toml_quoted_string(content, old_entry, new_value)
        settings_path.write_text(content, encoding="utf-8")


def _run_mv_after(old: Path, new: Path, noop: bool, verbose: bool) -> None:
    """`mv --after OLD NEW`; see run_mv."""
    repo_root = find_repo_root(new) or find_repo_root(old)
    if repo_root is None:
        raise ValueError(
            "Could not find course repo root.\n"
            "Looked for course_settings/course_settings.toml by walking up from\n"
            f"  {new}"
        )
    repo_format.check_repo_format(repo_root)
    validate_after(old, new, repo_root)

    old_rel = _repo_rel(old, repo_root, "Source")
    new_rel = _repo_rel(new, repo_root, "Destination")
    path_map = build_after_path_map(old, new, repo_root)

    manifest_updates, clashes, any_old = plan_after_manifest_updates(repo_root, path_map)
    if not any_old:
        raise ValueError(
            f"No manifest has an entry for {old_rel}"
            f"{' or anything under it' if new.is_dir() else ''}, so there is no "
            "move to record."
        )
    _describe_clashes(repo_root, clashes)
    if not manifest_updates:
        raise ValueError(
            "Every manifest that has the old path also has the new one, so there "
            "is nothing to rekey; nothing was changed."
        )

    file_updates = compute_file_updates(repo_root, path_map, after=True)
    module_order_updates = compute_module_order_updates(repo_root, path_map)
    course_settings_updates = compute_course_settings_updates(repo_root, path_map)
    pinned_updates = compute_pinned_resources_updates(
        repo_root, path_map, old_rel, new_rel
    )
    _describe_changes(
        path_map, [path.name for path, _ in manifest_updates], file_updates,
        module_order_updates, course_settings_updates, pinned_updates,
        noop, verbose, after=True,
    )
    if noop:
        return
    _write_updates(
        repo_root, file_updates, manifest_updates, module_order_updates,
        course_settings_updates, pinned_updates,
    )
