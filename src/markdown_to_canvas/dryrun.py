"""In-memory stand-ins for canvas_api, used by `update --check-as-new-course`
and `update --noop`.

DryRunCanvas implements the same public functions (names, signatures, return
shapes) as canvas_api that the run_sync pipeline calls, so the whole pipeline
runs unchanged against it — every local validation fires, nothing touches the
network. It is lightly stateful (fake-id counter, assignment groups, rubrics)
so that name resolution behaves exactly like a real first sync to an empty
course: settings sync "creates" the groups/rubrics, later phases resolve
content references against them.

Keep this in sync with canvas_api: when the sync pipeline starts calling a new
canvas_api function, add its dry-run twin here (the full-fixture runs in
test_check_as_new_course and test_update_noop catch a missing one as an
AttributeError).

NoopCanvas (`update --noop`) subclasses DryRunCanvas: writes are simulated the
same way, but reads go to the real course and are merged with what the run has
simulated so far. Its fake ids are negative, so they can never name a real
Canvas object, and block_writes() makes any non-GET request fail as a backstop.
"""
from __future__ import annotations

import re
from pathlib import Path
from types import SimpleNamespace
from typing import Any

from . import canvas_api as capi
from .canvas_api import _CANVAS_ITEM_TYPE, GradingStandardSync


def _fake_html_url(canvas_type: str, canvas_id: int) -> str:
    return f"(dry run: {canvas_type} not uploaded, fake id {canvas_id})"


class _AnyModuleName(dict):
    """Name index in which every name resolves to exactly one fake module id.

    module_order.toml may list modules that exist only on Canvas; the simulated
    course is empty, so looking them up for real would report every one of them
    as missing even though the actual course has them.
    """

    def __init__(self, new_id) -> None:
        super().__init__()
        self._new_id = new_id

    def get(self, name, default=None):  # noqa: D102 - dict.get override
        if name not in self:
            self[name] = [self._new_id()]
        return self[name]


def _page_slug(title: str) -> str:
    """Approximate Canvas's title→URL slugification (lowercase, dashes)."""
    slug = re.sub(r"[^a-z0-9]+", "-", title.lower()).strip("-")
    return slug or "page"


class DryRunCourse:
    """Placeholder for the canvasapi Course object during --check-as-new-course.

    All Canvas traffic goes through DryRunCanvas, so it has no methods.
    """

    name = "(check-as-new-course: not contacting Canvas)"
    id = 0


class DryRunCanvas:
    def __init__(self) -> None:
        self._next_id = 100000
        self._assignment_groups: dict[str, int] = {}
        self._rubrics: dict[str, int] = {}
        self._group_categories: dict[str, list[int]] = {}

    def _new_id(self) -> int:
        self._next_id += 1
        return self._next_id

    # -- reads ---------------------------------------------------------------

    def get_canvas_updated_at(self, course, canvas_type, identifier):
        return None  # local always wins; moot anyway with the empty manifest

    def get_assignment_group_ids(self, course) -> dict[str, int]:
        return dict(self._assignment_groups)

    def get_rubric_ids(self, course) -> dict[str, int]:
        return dict(self._rubrics)

    def get_group_category_ids(self, course) -> dict[str, list[int]]:
        return {name: list(ids) for name, ids in self._group_categories.items()}

    # -- course settings -----------------------------------------------------

    def sync_grading_standards(self, course, standards):
        # No live course to compare schemes against, so never a mismatch here.
        return GradingStandardSync(self._new_id() if standards else None, [])

    def update_course_metadata(self, course, settings, grading_standard_id=None) -> list[str]:
        return []

    def upload_course_image(self, course, local_path: Path) -> int:
        return self._new_id()

    def sync_assignment_groups(self, course, groups) -> list[str]:
        for group in groups:
            name = group.get("title", "")
            self._assignment_groups.setdefault(name, self._new_id())
        # No drop rules to defer: apply_assignment_group_rules is a no-op here.
        return []

    def apply_assignment_group_rules(self, course, groups, names=None) -> None:
        pass

    def create_group_category(self, course, name: str) -> int:
        new_id = self._new_id()
        self._group_categories[name] = [new_id]
        return new_id

    def update_late_policy(self, course, late_policy) -> None:
        pass

    def update_post_policy(self, course, post_manually) -> None:
        pass

    def sync_tab_configuration(self, course, tab_config) -> None:
        # Tab ids/labels can only be validated against a live course.
        pass

    def sync_rubrics(
        self, course, rubrics
    ) -> tuple[dict[str, int], list[str], list[str], list[tuple[str, str]]]:
        created: list[str] = []
        for r in rubrics:
            title = r.get("title", "")
            if title not in self._rubrics:
                self._rubrics[title] = self._new_id()
                created.append(title)
        return dict(self._rubrics), created, [], []

    def associate_rubric_with_assignment(
        self, course, rubric_id, assignment_id, use_for_grading=True
    ) -> None:
        pass

    def remove_rubric_from_assignment(self, course, assignment_id, rubric_id) -> bool:
        return False

    def update_syllabus_body(self, course, html: str) -> None:
        pass

    # -- content -------------------------------------------------------------

    def upload_asset(self, course, local_path: Path, assets_root: Path) -> dict[str, Any]:
        canvas_id = self._new_id()
        return {
            "canvas_type": "file",
            "canvas_id": canvas_id,
            "canvas_url": f"/files/{canvas_id}/download",
        }

    def create_or_update_page(
        self, course, canvas_url, title, body, **kwargs
    ) -> dict[str, Any]:
        canvas_id = self._new_id()
        return {
            "canvas_type": "page",
            "canvas_id": canvas_id,
            "canvas_url": canvas_url or _page_slug(title),
            "html_url": _fake_html_url("page", canvas_id),
        }

    def create_or_update_assignment(
        self, course, canvas_id, title, body, **kwargs
    ) -> dict[str, Any]:
        new_id = canvas_id or self._new_id()
        return {
            "canvas_type": "assignment",
            "canvas_id": new_id,
            "html_url": _fake_html_url("assignment", new_id),
            "rubric_settings": None,
        }

    def create_or_update_discussion(
        self, course, canvas_id, title, body, **kwargs
    ) -> dict[str, Any]:
        new_id = canvas_id or self._new_id()
        return {
            "canvas_type": "discussion",
            "canvas_id": new_id,
            "html_url": _fake_html_url("discussion", new_id),
        }

    def create_or_update_announcement(
        self, course, canvas_id, title, body, **kwargs
    ) -> dict[str, Any]:
        new_id = canvas_id or self._new_id()
        return {
            "canvas_type": "announcement",
            "canvas_id": new_id,
            "html_url": _fake_html_url("announcement", new_id),
        }

    def create_stub(self, course, canvas_type: str, title: str) -> dict[str, Any]:
        canvas_id = self._new_id()
        if canvas_type == "page":
            return {
                "canvas_type": "page",
                "canvas_id": canvas_id,
                "canvas_url": _page_slug(title),
            }
        if canvas_type in ("assignment", "discussion", "announcement", "quiz", "module"):
            return {"canvas_type": canvas_type, "canvas_id": canvas_id}
        # Same behavior as the real create_stub, so a dry run reports exactly
        # what a real fresh sync would die on.
        raise ValueError(f"Cannot create stub for canvas_type: {canvas_type!r}")

    def set_front_page(self, course, page_url: str) -> None:
        pass

    def update_dates(self, course, canvas_type, canvas_id, date_fields) -> dict[str, Any]:
        return {"html_url": _fake_html_url(canvas_type, canvas_id)}

    # -- quizzes / question banks ---------------------------------------------

    def create_or_update_quiz(
        self, course, canvas_id, title, description, **kwargs
    ) -> dict[str, Any]:
        new_id = canvas_id or self._new_id()
        return {
            "canvas_type": "quiz",
            "canvas_id": new_id,
            "html_url": _fake_html_url("quiz", new_id),
        }

    def get_quiz(self, course, quiz_id: int):
        # Consumed only by sync_quiz_questions / finalize_quiz_publish_state
        # below, which ignore it.
        return SimpleNamespace(id=quiz_id, published=False)

    def sync_quiz_questions(self, course, quiz, questions) -> dict[str, int]:
        return {q["rel_path"]: self._new_id() for q in questions}

    def finalize_quiz_publish_state(self, quiz, published: bool) -> bool:
        return False  # never "already published" on an empty course

    # -- modules ---------------------------------------------------------------

    def create_or_update_module(self, course, canvas_id, title, **kwargs):
        return SimpleNamespace(id=canvas_id or self._new_id())

    def get_module_ids_by_name(self, course) -> dict[str, list[int]]:
        """Every name resolves, so check-as-new-course does not report a Canvas-only
        module listed in module_order.toml as missing — the simulated course is
        empty, but the real one is where those modules actually live."""
        return _AnyModuleName(self._new_id)

    def find_module_ids_named(self, course, name: str) -> list[int]:
        return []  # the simulated course starts empty, so no name is taken

    def reposition_module(self, course, canvas_id: int, position: int) -> None:
        pass

    def clear_module_items(self, module) -> None:
        pass

    def add_module_item(
        self, module, item: dict[str, Any], manifest: dict
    ) -> tuple[int | None, str | None]:
        """Mirror the real add_module_item's *local* validation (manifest
        lookup, supported-type check, warnings) without the API calls."""
        if item["type"] in ("SubHeader", "ExternalUrl"):
            return self._new_id(), None
        local_path = item["local_path"]
        if local_path not in manifest:
            print(f"  WARNING: module item not in manifest (skipping): {local_path}")
            return None, None
        entry = manifest[local_path]
        if _CANVAS_ITEM_TYPE.get(entry.get("canvas_type", "")) is None:
            print(f"  WARNING: unsupported canvas_type for module item (skipping): {local_path}")
            return None, None
        return self._new_id(), None


class NoopWriteError(RuntimeError):
    """A non-GET request reached Canvas during `update --noop`."""


def block_writes(course) -> None:
    """Make every non-GET request through ``course``'s requester raise.

    canvasapi objects fetched from a course share its requester, so this covers
    them too. It is a backstop: NoopCanvas already simulates every write, and a
    request that gets here means a write function was called without going
    through it.
    """
    requester = course._requester
    real_request = requester.request

    def guarded(method, endpoint=None, *args, **kwargs):
        if str(method).upper() != "GET":
            raise NoopWriteError(
                f"--noop stopped a {method} request to Canvas ({endpoint}). "
                "Nothing was changed; this is a bug in markdown-to-canvas."
            )
        return real_request(method, endpoint, *args, **kwargs)

    requester.request = guarded


class NoopCanvas(DryRunCanvas):
    """canvas_api stand-in for `update --noop`: real reads, simulated writes.

    Reads are forwarded to canvas_api and merged with the objects this run has
    "created", so name resolution sees both the real course and the run's own
    additions. Fake ids count down from -1; a read asked about a fake id is
    answered here without contacting Canvas. Live name maps are fetched once,
    since nothing changes them during a noop run.
    """

    def __init__(self) -> None:
        super().__init__()
        self._next_id = 0
        self._fake_page_urls: set[str] = set()
        self._modules: dict[str, list[int]] = {}
        self._live_ag: dict[str, int] | None = None
        self._live_rubric_ids: dict[str, int] | None = None
        self._live_group_categories: dict[str, list[int]] | None = None
        self._live_module_ids: dict[str, list[int]] | None = None

    def _new_id(self) -> int:
        self._next_id -= 1
        return self._next_id

    def _new_page_url(self, canvas_id: int) -> str:
        url = f"noop-new-page{canvas_id}"
        self._fake_page_urls.add(url)
        return url

    def _is_fake(self, identifier) -> bool:
        if isinstance(identifier, int):
            return identifier < 0
        return identifier in self._fake_page_urls

    # -- reads ---------------------------------------------------------------

    def get_canvas_updated_at(self, course, canvas_type, identifier):
        if self._is_fake(identifier):
            return None
        return capi.get_canvas_updated_at(course, canvas_type, identifier)

    def get_orphan_item(self, course, canvas_type, entry):
        return capi.get_orphan_item(course, canvas_type, entry)

    def get_assignment_group_ids(self, course) -> dict[str, int]:
        if self._live_ag is None:
            self._live_ag = capi.get_assignment_group_ids(course)
        return {**self._live_ag, **self._assignment_groups}

    def get_rubric_ids(self, course) -> dict[str, int]:
        if self._live_rubric_ids is None:
            self._live_rubric_ids = capi.get_rubric_ids(course)
        return {**self._live_rubric_ids, **self._rubrics}

    def get_group_category_ids(self, course) -> dict[str, list[int]]:
        if self._live_group_categories is None:
            self._live_group_categories = capi.get_group_category_ids(course)
        merged = {name: list(ids) for name, ids in self._live_group_categories.items()}
        for name, ids in self._group_categories.items():
            merged.setdefault(name, []).extend(ids)
        return merged

    def get_module_ids_by_name(self, course) -> dict[str, list[int]]:
        if self._live_module_ids is None:
            self._live_module_ids = capi.get_module_ids_by_name(course)
        merged = {name: list(ids) for name, ids in self._live_module_ids.items()}
        for name, ids in self._modules.items():
            merged.setdefault(name, []).extend(ids)
        return merged

    def find_module_ids_named(self, course, name: str) -> list[int]:
        return self.get_module_ids_by_name(course).get(name.strip().casefold(), [])

    # -- writes that depend on what the course already has --------------------

    def sync_assignment_groups(self, course, groups) -> list[str]:
        existing = self.get_assignment_group_ids(course)
        for group in groups:
            name = group.get("title", "")
            if name not in existing:
                self._assignment_groups[name] = self._new_id()
        return []

    def sync_rubrics(
        self, course, rubrics
    ) -> tuple[dict[str, int], list[str], list[str], list[tuple[str, str]]]:
        existing = self.get_rubric_ids(course)
        created: list[str] = []
        updated: list[str] = []
        for r in rubrics:
            title = r.get("title", "")
            if title in existing:
                updated.append(title)
            else:
                self._rubrics[title] = self._new_id()
                created.append(title)
        return self.get_rubric_ids(course), created, updated, []

    def create_or_update_page(
        self, course, canvas_url, title, body, **kwargs
    ) -> dict[str, Any]:
        canvas_id = self._new_id()
        return {
            "canvas_type": "page",
            "canvas_id": canvas_id,
            "canvas_url": canvas_url or self._new_page_url(canvas_id),
            "html_url": _fake_html_url("page", canvas_id),
        }

    def create_stub(self, course, canvas_type: str, title: str) -> dict[str, Any]:
        entry = super().create_stub(course, canvas_type, title)
        if canvas_type == "page":
            entry["canvas_url"] = self._new_page_url(entry["canvas_id"])
        return entry

    def create_or_update_module(self, course, canvas_id, title, **kwargs):
        if canvas_id is None:
            canvas_id = self._new_id()
            self._modules.setdefault(title.strip().casefold(), []).append(canvas_id)
        return SimpleNamespace(id=canvas_id)
