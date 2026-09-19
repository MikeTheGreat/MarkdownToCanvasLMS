"""Confirm the Canvas course a manifest's IDs belong to before using them.

The manifest is named after the canvas.toml file, not after the course inside
it, so editing ``course_id`` keeps the same manifest — and every recorded Canvas
ID keeps pointing into the old course. The manifest therefore stores the course
it belongs to (manifest.COURSE_KEY), and every command that uses those IDs
against Canvas calls check_course() first.

The caller has already printed the repo, course id, base URL and course name, so
the person answering the prompt can see which course is about to be written to.
"""

from __future__ import annotations

import sys
from collections.abc import Callable
from pathlib import Path

import click

from . import clean_manifest
from . import manifest as manifest_lib
from . import repo_format
from .config import Config


class CourseGuardError(Exception):
    """The run must stop; the message says why and what to do."""


def _describe(base_url: str, course_id: int, name: str | None) -> str:
    label = f"course {course_id} at {base_url}"
    return f"{label} ('{name}')" if name else label


def _interactive() -> bool:
    return sys.stdin.isatty()


def check_course(
    manifest_path: Path,
    config: Config,
    course_name: str,
    assume_yes: bool = False,
    confirm: Callable[[str], bool] | None = None,
    interactive: Callable[[], bool] = _interactive,
) -> None:
    """Verify (and if needed record) the course the manifest belongs to.

    - Same course stored: nothing to do.
    - Nothing stored: ask, then record. Covers both a first sync and a manifest
      written before this check existed.
    - A different course stored: ask, and on yes empty the manifest (every ID in
      it belongs to the other course) and record the new one.
    """
    if confirm is None:
        confirm = lambda prompt: click.confirm(prompt, default=False)  # noqa: E731
    repo_format.check_repo_format(manifest_path.parent)
    manifest = manifest_lib.load(manifest_path)
    configured = _describe(config.base_url, config.course_id, course_name)
    stored = manifest_lib.get_course_identity(manifest)

    def ask(question: str) -> None:
        if assume_yes:
            return
        if not interactive():
            raise CourseGuardError(
                "There is no terminal to ask, so nothing was changed. Re-run with "
                "--yes to answer yes to: " + question
            )
        if not confirm(question):
            raise CourseGuardError("Stopped; nothing was changed.")

    if stored is not None:
        if manifest_lib.same_course(stored, config.base_url, config.course_id):
            return
        previous = _describe(
            stored["base_url"], stored["course_id"], stored.get("course_name")
        )
        count = sum(
            1 for k, v in manifest.items() if not manifest_lib.is_reserved_key(k, v)
        )
        print(
            f"\n{manifest_path.name} belongs to a different course:\n"
            f"  Recorded:  {previous}\n"
            f"  Requested: {configured}\n"
            f"All {count} Canvas IDs in {manifest_path.name} belong to the recorded "
            "course, so they cannot be used here. Changing the course empties the "
            "manifest, and the next update re-creates this repo's content in the "
            "requested course.\n"
            "  - If the requested course already holds a copy of this content "
            "(for example, it was copied from the recorded course in Canvas), that "
            "will leave duplicates.\n"
            "  - If canvas.toml is wrong instead, answer no and fix "
            "course_id/base_url."
        )
        ask(f"Change {manifest_path.name} to {configured} and clear its {count} Canvas IDs?")
        plan = clean_manifest.plan_invalidate_all(manifest)
        clean_manifest.apply_clean(manifest, manifest_path, plan, config, course_name)
        print(
            f"Cleared {len(plan.removals)} entries from {manifest_path.name}; "
            f"it now records {configured}."
        )
        return

    if manifest_lib.has_content_entries(manifest):
        print(
            f"\n{manifest_path.name} does not record which course its Canvas IDs "
            "belong to (it was written by an older version of markdown-to-canvas).\n"
            "Check the course named above. If this manifest may have been used with "
            "a different course (for example, course_id in canvas.toml was changed "
            "after an update), answer no and run `markdown-to-canvas clean-manifest` "
            "first."
        )
    else:
        print(
            f"\n{manifest_path.name} is new, so this is the first sync to Canvas "
            "from this repo and config. Check the course named above before "
            "uploading to it."
        )
    ask(f"Record {configured} as this manifest's course and continue?")
    manifest_lib.set_course_identity(
        manifest, manifest_path, config.base_url, config.course_id, course_name
    )
    print(f"Recorded {configured} as the course for {manifest_path.name}")
