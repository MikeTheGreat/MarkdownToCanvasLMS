"""fix-manifest --clean: drop manifest entries whose Canvas object is not in the course.

The manifest trusts its Canvas IDs indefinitely. An ID goes bad when canvas.toml
is pointed at a different course after a sync, when the object is deleted in
Canvas, or when an older tool version recorded the wrong type. `update` then
skips the entry (``last_synced`` says it is current) and keeps rendering links
to the bad ID.

No title or slug matching is involved: every entry already names its local file
and its Canvas ID, so the only question is whether that ID exists, as that
type, in the configured course. Removing an entry does not by itself re-render
the files that link to it, so those are marked for re-sync as well.
"""

from __future__ import annotations

import tomllib
from collections import defaultdict
from dataclasses import dataclass, field
from pathlib import Path

import click

from . import canvas_api as capi
from . import manifest as manifest_lib
from . import repo_format
from .config import Config

SETTINGS_KEY = "course_settings/course_settings.toml"

#: Entries describing the course as a whole. They carry no checkable Canvas ID,
#: so they are reset only when the manifest was demonstrably used with another
#: course (see CleanPlan.foreign_evidence).
COURSE_LEVEL_TYPES = ("course_settings", "rubrics", "module_order")

#: Folders whose files always sync as one Canvas type. Content folders are not
#: listed: their type is not fixed by the folder name.
_FOLDER_TYPES = {"modules": "module", "assets": "file", "quizzes": "quiz"}

#: course_settings.toml keys that name a repo file, and the settings section
#: hash that must be dropped so the section is re-sent.
_SETTINGS_REF_SECTIONS = {"front_page": "front_page", "dashboard_image": "dashboard_image"}


@dataclass
class CleanPlan:
    removals: dict[str, str] = field(default_factory=dict)  # key -> reason
    # referrer key -> removed keys it links to (its last_synced is dropped)
    resync: dict[str, list[str]] = field(default_factory=dict)
    # course_settings.toml section hashes to drop (section -> removed key)
    settings_sections: dict[str, str] = field(default_factory=dict)
    unchecked: list[tuple[str, str]] = field(default_factory=list)
    foreign_evidence: list[str] = field(default_factory=list)
    scan_errors: list[tuple[str, str]] = field(default_factory=list)
    checked: int = 0

    @property
    def has_changes(self) -> bool:
        return bool(self.removals or self.resync or self.settings_sections)


def check_entries(
    manifest: manifest_lib.ManifestDict,
    canvas_ids: dict[str, set[int]],
    config: Config,
) -> CleanPlan:
    """Decide which entries to remove. Pure: no Canvas calls, no file reads."""
    plan = CleanPlan()
    stored = manifest_lib.get_course_identity(manifest)
    if stored is not None and not manifest_lib.same_course(
        stored, config.base_url, config.course_id
    ):
        plan.foreign_evidence.append(
            f"the manifest records course {stored['course_id']} at {stored['base_url']}"
        )

    course_level: list[tuple[str, str]] = []
    for key, entry in manifest.items():
        if manifest_lib.is_reserved_key(key, entry):
            continue
        canvas_type = entry.get("canvas_type", "")
        canvas_id = entry.get("canvas_id")

        expected = _FOLDER_TYPES.get(key.split("/")[0])
        if expected is not None and canvas_type != expected:
            plan.checked += 1
            plan.removals[key] = (
                f"recorded as a Canvas {canvas_type or '(no type)'} "
                f"(id {canvas_id}), but files in {key.split('/')[0]}/ are {expected}s"
            )
            continue

        if canvas_type == "syllabus":
            plan.checked += 1
            if canvas_id is not None and int(canvas_id) != int(config.course_id):
                plan.removals[key] = f"last synced to course {canvas_id}"
                plan.foreign_evidence.append(
                    f"{key} was last synced to course {canvas_id}"
                )
            continue

        if canvas_type in COURSE_LEVEL_TYPES:
            course_level.append((key, canvas_type))
            continue

        ids = canvas_ids.get(canvas_type)
        if ids is None or canvas_id is None:
            plan.unchecked.append((key, canvas_type or "(no type)"))
            continue
        plan.checked += 1
        if int(canvas_id) not in ids:
            plan.removals[key] = f"{canvas_type} {canvas_id} is not in this course"

    for key, canvas_type in course_level:
        if plan.foreign_evidence:
            plan.removals[key] = (
                f"{canvas_type} state belongs to another course; "
                "the next update re-sends all of it"
            )
        else:
            plan.unchecked.append((key, canvas_type))
    return plan


def plan_invalidate_all(manifest: manifest_lib.ManifestDict) -> CleanPlan:
    """Remove every entry, without contacting Canvas.

    For a deliberate course switch. Canvas object ids are unique per object, so
    no object in the new course can hold an id recorded against the old one:
    every entry is invalid by construction and listing the new course would only
    confirm that. Nothing is marked for re-sync either — with the whole manifest
    gone, the next update re-creates everything and re-renders every link.
    """
    plan = CleanPlan()
    for key, entry in manifest.items():
        if manifest_lib.is_reserved_key(key, entry):
            continue
        plan.checked += 1
        plan.removals[key] = "belongs to the previous course"
    return plan


def _normalize_key(raw: str) -> str:
    key = raw.strip().replace("\\", "/")
    while key.startswith("./"):
        key = key[2:]
    return key.rstrip("/")


def find_referrers(
    repo_root: Path, targets: set[str]
) -> tuple[dict[str, set[str]], list[tuple[str, str]]]:
    """Map each repo file that links to any of ``targets`` to the targets it names.

    Reuses find-local-orphans' scan, so snippets are already expanded into the
    files that include them and course-flag branches are not applied (a link in
    an inactive branch still counts — marking one extra file costs a re-upload).
    course_settings.toml references come back under SETTINGS_KEY.
    """
    from .ignore import load_ignore_matcher
    from .local_orphans import _quiet, collect_local_refs, collect_sources

    matcher = load_ignore_matcher(repo_root)
    snippets_dir = repo_root / "snippets"
    errors: list[tuple[str, str]] = []
    referrers: dict[str, set[str]] = defaultdict(set)
    for source in collect_sources(repo_root, matcher):
        source_key = source.relative_to(repo_root).as_posix()
        with _quiet():
            refs = collect_local_refs(source, repo_root, snippets_dir, errors)
        for ref in refs & targets:
            referrers[source_key].add(ref)

    settings_path = repo_root / SETTINGS_KEY
    if settings_path.exists():
        with settings_path.open("rb") as fh:
            settings = tomllib.load(fh)
        for name in _SETTINGS_REF_SECTIONS:
            value = settings.get(name)
            if isinstance(value, str) and _normalize_key(value) in targets:
                referrers[SETTINGS_KEY].add(_normalize_key(value))
    return referrers, errors


def _settings_sections_for(repo_root: Path, removed: set[str]) -> dict[str, str]:
    settings_path = repo_root / SETTINGS_KEY
    if not settings_path.exists():
        return {}
    with settings_path.open("rb") as fh:
        settings = tomllib.load(fh)
    sections: dict[str, str] = {}
    for name, section in _SETTINGS_REF_SECTIONS.items():
        value = settings.get(name)
        if isinstance(value, str) and _normalize_key(value) in removed:
            sections[section] = _normalize_key(value)
    return sections


def plan_clean(
    manifest: manifest_lib.ManifestDict,
    canvas_ids: dict[str, set[int]],
    config: Config,
    repo_root: Path,
) -> CleanPlan:
    plan = check_entries(manifest, canvas_ids, config)
    if not plan.removals:
        return plan
    removed = set(plan.removals)
    referrers, plan.scan_errors = find_referrers(repo_root, removed)
    for referrer, keys in sorted(referrers.items()):
        if referrer in removed or referrer not in manifest:
            continue
        if referrer == SETTINGS_KEY:
            plan.settings_sections = _settings_sections_for(repo_root, removed)
            continue
        plan.resync[referrer] = sorted(keys)
    return plan


def apply_clean(
    manifest: manifest_lib.ManifestDict,
    manifest_path: Path,
    plan: CleanPlan,
    config: Config,
    course_name: str,
) -> None:
    """Apply the plan and record the configured course; one flush at the end."""
    for key in plan.removals:
        manifest.pop(key, None)
    for key in plan.resync:
        entry = manifest.get(key)
        if entry is not None:
            entry.pop("last_synced", None)
    if plan.settings_sections and SETTINGS_KEY in manifest:
        entry = manifest[SETTINGS_KEY]
        hashes = entry.get("section_hashes") or {}
        for section in plan.settings_sections:
            hashes.pop(section, None)
        entry.pop("last_synced", None)
    manifest_lib.set_course_identity(
        manifest, manifest_path, config.base_url, config.course_id, course_name
    )


def load_manifest(
    repo_root: Path, config: Config
) -> tuple[manifest_lib.ManifestDict, Path]:
    """Check the repo's format, then load the manifest belonging to ``config``."""
    repo_format.check_repo_format(repo_root)
    manifest_path = manifest_lib.manifest_path_for(repo_root, config.config_path)
    return manifest_lib.load(manifest_path), manifest_path


def list_course(course) -> capi.CourseListing:
    click.echo("Listing the course's pages, assignments, discussions, quizzes, modules and files...")
    return capi.list_course_objects(course)


def print_plan(plan: CleanPlan, applied: bool) -> None:
    click.echo()
    click.echo(f"Checked {plan.checked} manifest entries against Canvas.")
    if plan.foreign_evidence:
        click.secho("This manifest was used with a different course:", fg="yellow")
        for reason in plan.foreign_evidence:
            click.echo(f"  - {reason}")

    verb = "Removed" if applied else "Would remove"
    if plan.removals:
        click.echo()
        click.secho(f"{verb} {len(plan.removals)} entries:", fg="yellow")
        for key, reason in sorted(plan.removals.items()):
            click.echo(f"  - {key} : {reason}")
    else:
        click.echo()
        click.secho("Every checked entry is in this course.", fg="green")

    if plan.resync or plan.settings_sections:
        verb = "Marked" if applied else "Would mark"
        count = len(plan.resync) + (1 if plan.settings_sections else 0)
        click.echo()
        click.secho(
            f"{verb} {count} files for re-sync because they link to a removed entry. "
            "The next update re-renders them, overwriting any edits made to them "
            "directly in Canvas:",
            fg="yellow",
        )
        for key, targets in plan.resync.items():
            click.echo(f"  - {key} : links to {', '.join(targets)}")
        for section, target in sorted(plan.settings_sections.items()):
            click.echo(f"  - {SETTINGS_KEY} [{section}] : names {target}")

    if plan.unchecked:
        click.echo()
        click.secho(
            f"Not checked ({len(plan.unchecked)}) — no Canvas ID that can be looked up:",
            dim=True,
        )
        for key, canvas_type in sorted(plan.unchecked):
            click.secho(f"  - {key} ({canvas_type})", dim=True)

    if plan.scan_errors:
        click.echo()
        click.secho(
            f"Errors ({len(plan.scan_errors)}) — these files could not be scanned for "
            "links, so files that link to a removed entry may be missing above:",
            fg="red",
        )
        for key, message in plan.scan_errors:
            click.echo(f"  - {key} : {message}")
