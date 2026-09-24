"""Copy content from one course repo into another (the `cp` subcommand).

Purely local, like `mv`: nothing here contacts Canvas or touches a manifest.
Each copied file keeps its repo-relative path, so relative links inside it keep
working without being rewritten.

Two phases. `build_copy_plan` works out everything — which files to copy, what
each one already looks like in the destination, rubric blocks to append, the
module_order.toml change, warnings — without writing anything. `run_cp` prints
the plan and, only when there is no unresolved conflict, writes it. So a copy
either happens in full or not at all.
"""
from __future__ import annotations

import re
import shutil
import tomllib
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import tomlkit
import yaml

from . import repo_format
from .conditionals import find_referenced_flags, find_referenced_flags_in_frontmatter
from .config import find_repo_root
from .convert import (
    expand_frontmatter_snippets,
    find_referenced_snippets,
    parse_frontmatter,
)
from .ignore import IgnoreMatcher, load_ignore_matcher
from .local_orphans import _quiet, collect_local_refs
from .quiz import split_quiz_body
from .sync import load_course_flags, load_due_dates

# Top-level folders that are not plain content folders. Anything else at the
# repo root holds content (.md files that become Canvas items).
_SPECIAL_DIRS = {
    "assets", "modules", "quizzes", "snippets", "course_settings", "question_banks",
}
# Folders whose items carry a Canvas title that can collide.
_TITLED_DIRS = ("pages", "assignments", "discussions", "announcements", "quizzes")
_RUBRIC_DIRS = {"assignments", "discussions"}
_GRADED_TYPES = {"assignments": "assignment", "discussions": "discussion", "quizzes": "quiz"}

_RUBRICS_KEY = "course_settings/rubrics.toml"
_MODULE_ORDER_KEY = "course_settings/module_order.toml"
_RUBRICS_HEADER_RE = re.compile(r"^\s*\[\[\s*rubrics\s*\]\]\s*(#.*)?$")
_COURSE_URL_RE = re.compile(r"/courses/(\d+)\b")

# File action statuses.
NEW = "new"
IDENTICAL = "identical"
CONFLICT = "conflict"
SNIPPET_KEPT = "snippet-kept"


class CpError(ValueError):
    """A problem that stops `cp` before anything is written."""


@dataclass
class FileAction:
    rel: str
    status: str


@dataclass
class CopyPlan:
    src_root: Path
    dest_root: Path
    files: list[FileAction] = field(default_factory=list)
    ignored: list[str] = field(default_factory=list)
    # Rubric titles whose source block will be appended to the destination.
    rubric_appends: list[str] = field(default_factory=list)
    # Full new text of the destination's rubrics.toml, when anything is appended.
    rubrics_text: str | None = None
    # Module filenames appended to module_order.toml, and its new text.
    module_order_appends: list[str] = field(default_factory=list)
    module_order_text: str | None = None
    # (referring file, target key, target exists in destination)
    links_not_followed: list[tuple[str, str, bool]] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)

    def by_status(self, status: str) -> list[str]:
        return [f.rel for f in self.files if f.status == status]

    @property
    def conflicts(self) -> list[str]:
        return self.by_status(CONFLICT)


# ---------------------------------------------------------------------------
# Source selection
# ---------------------------------------------------------------------------


def _rel(path: Path, root: Path) -> str:
    return path.resolve().relative_to(root.resolve()).as_posix()


def _visible_files(directory: Path) -> list[Path]:
    """Every file under directory, skipping dot-files and dot-directories."""
    out: list[Path] = []
    for entry in sorted(directory.iterdir(), key=lambda p: p.name):
        if entry.name.startswith("."):
            continue
        if entry.is_dir():
            out.extend(_visible_files(entry))
        elif entry.is_file():
            out.append(entry)
    return out


def _unit_folder(rel: str) -> str | None:
    """`quizzes/<name>` or `question_banks/<name>` for a path inside one."""
    parts = rel.split("/")
    if parts[0] in ("quizzes", "question_banks") and len(parts) >= 2:
        return f"{parts[0]}/{parts[1]}"
    return None


def _find_source_root(srcs: list[Path]) -> Path:
    roots: dict[Path, Path] = {}
    for src in srcs:
        if not src.exists():
            raise CpError(f"No such file or directory: {src}")
        root = find_repo_root(src.absolute())
        if root is None:
            raise CpError(
                f"{src} is not inside a course repo (no "
                f"course_settings/course_settings.toml found above it)."
            )
        roots[root.resolve()] = src
    if len(roots) > 1:
        listed = "\n".join(f"  {r}  (from {s})" for r, s in roots.items())
        raise CpError(f"All SRC paths must be in the same course repo; found:\n{listed}")
    return next(iter(roots))


# ---------------------------------------------------------------------------
# Planning
# ---------------------------------------------------------------------------


class _Planner:
    def __init__(self, src_root: Path, dest_root: Path, overwrite: bool) -> None:
        self.src = src_root
        self.dest = dest_root
        self.overwrite = overwrite
        self.snippets_dir = src_root / "snippets"
        self.matcher: IgnoreMatcher = load_ignore_matcher(src_root)
        self.plan = CopyPlan(src_root, dest_root)
        # rel -> True if named (directly or via a folder) on the command line.
        self.selected: dict[str, bool] = {}
        self.processed: set[str] = set()
        self.queue: list[str] = []
        self.modules: list[str] = []

    # -- selection ------------------------------------------------------

    def _ignored(self, rel: str) -> bool:
        path = self.src / rel
        if self.matcher.is_ignored(path, self.src):
            return True
        # A file inside an ignored directory: check each parent directory.
        parent = path.parent
        while parent != self.src and parent.is_relative_to(self.src):
            if self.matcher.is_ignored(parent, self.src):
                return True
            parent = parent.parent
        return False

    def _select(self, rel: str, explicit: bool) -> None:
        if not (self.src / rel).is_file():
            return
        if self._ignored(rel):
            if rel not in self.plan.ignored:
                self.plan.ignored.append(rel)
            return
        if rel in self.selected:
            self.selected[rel] = self.selected[rel] or explicit
            return
        self.selected[rel] = explicit
        self.queue.append(rel)

    def add_src(self, src: Path) -> None:
        rel = _rel(src, self.src)
        if rel == "." or rel == "":
            raise CpError("SRC cannot be the whole course repo; name files or folders in it.")
        top = rel.split("/")[0]
        if top == "course_settings":
            raise CpError(
                f"{rel}: course settings cannot be copied with cp (rubrics and "
                f"module_order entries are merged automatically when needed)."
            )
        if src.is_dir():
            if self._ignored(rel):
                self.plan.ignored.append(rel + "/")
                return
            files = _visible_files(src)
        else:
            files = [src]
        for f in files:
            self._select(_rel(f, self.src), explicit=True)

    # -- dependency walk --------------------------------------------------

    def _add_snippets(self, file_path: Path) -> None:
        try:
            text = file_path.read_text()
        except (OSError, UnicodeDecodeError):
            return
        for snippet in find_referenced_snippets(text, file_path, self.snippets_dir):
            self._select(_rel(snippet, self.src), explicit=False)

    def _add_refs(self, file_path: Path, refs: set[str], follow_content: bool) -> None:
        referrer = _rel(file_path, self.src)
        for key in sorted(refs):
            top = key.split("/")[0]
            if top == "assets":
                if (self.src / key).is_file():
                    self._select(key, explicit=False)
                else:
                    self.plan.warnings.append(
                        f"{referrer}: references {key}, which does not exist in the source"
                    )
            elif follow_content:
                if (self.src / key).exists():
                    self._select(key, explicit=False)
                else:
                    self.plan.warnings.append(
                        f"{referrer}: module item {key} does not exist in the source"
                    )
            elif top not in ("snippets", "course_settings") and key not in self.selected:
                self.plan.links_not_followed.append(
                    (referrer, key, (self.dest / key).exists())
                )

    def _refs(self, file_path: Path) -> set[str]:
        errors: list[tuple[str, str]] = []
        with _quiet():
            refs = collect_local_refs(file_path, self.src, self.snippets_dir, errors)
        for key, message in errors:
            self.plan.warnings.append(f"{key}: {message}; its links may be incomplete")
        return refs

    def _process_unit(self, unit: str) -> None:
        """A quiz or question-bank folder: copy all of it, plus its dependencies."""
        folder = self.src / unit
        for f in _visible_files(folder):
            rel = _rel(f, self.src)
            if self._ignored(rel):
                if rel not in self.plan.ignored:
                    self.plan.ignored.append(rel)
                continue
            self.selected.setdefault(rel, False)
            self.processed.add(rel)
        name = folder.name
        if unit.startswith("quizzes/"):
            main = folder / f"{name}.md"
            if not main.exists():
                return
            self._add_snippets(main)
            try:
                _fm, body = parse_frontmatter(main.read_text())
                _desc, question_files = split_quiz_body(body, main)
            except yaml.YAMLError:
                question_files = []
            for q in question_files:
                if q.exists():
                    self._add_snippets(q)
            self._add_refs(main, self._refs(main), follow_content=False)
        else:
            main = folder / f"{name}.toml"
            questions = folder / "questions"
            if questions.exists():
                for q in sorted(questions.glob("*.md")):
                    self._add_snippets(q)
            if main.exists():
                self._add_refs(main, self._refs(main), follow_content=False)

    def walk(self) -> None:
        while self.queue:
            rel = self.queue.pop(0)
            if rel in self.processed:
                continue
            unit = _unit_folder(rel)
            if unit is not None:
                self._process_unit(unit)
                continue
            self.processed.add(rel)
            path = self.src / rel
            top = rel.split("/")[0]
            if path.suffix != ".md" or top in ("assets", "snippets"):
                continue
            self._add_snippets(path)
            if top == "modules":
                self.modules.append(rel)
                self._add_refs(path, self._refs(path), follow_content=True)
            else:
                self._add_refs(path, self._refs(path), follow_content=False)
        # A link to a file that ended up being copied anyway is not "not followed".
        self.plan.links_not_followed = sorted(
            {entry for entry in self.plan.links_not_followed if entry[1] not in self.selected}
        )

    # -- classification -------------------------------------------------

    def classify(self) -> None:
        for rel in sorted(self.selected):
            dest_path = self.dest / rel
            if not dest_path.exists():
                status = NEW
            elif dest_path.is_dir():
                raise CpError(f"{rel}: the destination has a directory at this path")
            elif dest_path.read_bytes() == (self.src / rel).read_bytes():
                status = IDENTICAL
            elif rel.startswith("snippets/") and not self.selected[rel]:
                status = SNIPPET_KEPT
            else:
                status = CONFLICT
            self.plan.files.append(FileAction(rel, status))

    def copied_md(self) -> list[str]:
        """Copied .md files whose source content lands in the destination."""
        return [
            f.rel for f in self.plan.files
            if f.rel.endswith(".md") and f.status != SNIPPET_KEPT
        ]


# ---------------------------------------------------------------------------
# Frontmatter helpers
# ---------------------------------------------------------------------------


def _frontmatter(path: Path, snippets_dir: Path) -> dict[str, Any] | None:
    try:
        text = path.read_text()
        fm, body = parse_frontmatter(text)
    except (OSError, UnicodeDecodeError, yaml.YAMLError):
        return None
    with _quiet():
        fm, _ = expand_frontmatter_snippets(fm, body, path, snippets_dir)
    return fm if isinstance(fm, dict) else None


def _item_title(rel: str, fm: dict[str, Any] | None) -> str:
    if fm and fm.get("title"):
        return str(fm["title"])
    return Path(rel).stem


def _is_quiz_main(rel: str) -> bool:
    parts = rel.split("/")
    return len(parts) == 3 and parts[0] == "quizzes" and parts[2] == f"{parts[1]}.md"


def _titled_type(rel: str) -> str | None:
    """The content type a file's title belongs to, or None if it has no Canvas title."""
    top = rel.split("/")[0]
    if top == "quizzes":
        return "quizzes" if _is_quiz_main(rel) else None
    if top in _TITLED_DIRS:
        return top
    return None


def _load_toml(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    try:
        with path.open("rb") as fh:
            return tomllib.load(fh)
    except tomllib.TOMLDecodeError as e:
        raise CpError(f"{path}: invalid TOML: {e}") from e


# ---------------------------------------------------------------------------
# Rubrics
# ---------------------------------------------------------------------------


def split_rubric_blocks(text: str) -> dict[str, str]:
    """Map each rubric title to the raw text of its `[[rubrics]]` block.

    A block runs from its `[[rubrics]]` header line to the next one (or the end
    of the file) and so includes its criteria, ratings and comment lines.
    """
    lines = text.splitlines(keepends=True)
    starts = [i for i, line in enumerate(lines) if _RUBRICS_HEADER_RE.match(line)]
    blocks: dict[str, str] = {}
    for n, start in enumerate(starts):
        end = starts[n + 1] if n + 1 < len(starts) else len(lines)
        block = "".join(lines[start:end])
        try:
            parsed = tomllib.loads(block)
        except tomllib.TOMLDecodeError:
            continue
        rubrics = parsed.get("rubrics") or [{}]
        title = rubrics[0].get("title")
        if isinstance(title, str) and title not in blocks:
            blocks[title] = block
    return blocks


def _rubric_shape(rubric: dict[str, Any]) -> list[tuple]:
    """The parts of a rubric that matter for comparison: criteria and ratings."""
    shape = []
    for c in rubric.get("criteria", []) or []:
        ratings = tuple(
            (r.get("description"), r.get("long_description") or "", r.get("points"))
            for r in c.get("ratings", []) or []
        )
        shape.append(
            (c.get("description"), c.get("long_description") or "", c.get("points"), ratings)
        )
    return shape


def _plan_rubrics(planner: _Planner) -> None:
    plan = planner.plan
    src_path = planner.src / _RUBRICS_KEY
    dest_path = planner.dest / _RUBRICS_KEY
    src_rubrics = {
        r.get("title"): r for r in _load_toml(src_path).get("rubrics", []) if isinstance(r, dict)
    }
    dest_rubrics = {
        r.get("title"): r for r in _load_toml(dest_path).get("rubrics", []) if isinstance(r, dict)
    }
    src_blocks = split_rubric_blocks(src_path.read_text()) if src_path.exists() else {}

    wanted: dict[str, list[str]] = {}
    for rel in planner.copied_md():
        if rel.split("/")[0] not in _RUBRIC_DIRS:
            continue
        fm = _frontmatter(planner.src / rel, planner.snippets_dir)
        if not fm or fm.get("rubric") is None:
            continue
        ref = fm["rubric"]
        if not isinstance(ref, str):
            plan.warnings.append(
                f"{rel}: rubric {ref!r} is a numeric Canvas ID from the source course; "
                f"it will not resolve in the destination. Use the rubric's title instead."
            )
            continue
        wanted.setdefault(ref, []).append(rel)

    for title, users in sorted(wanted.items()):
        if title in dest_rubrics:
            if title in src_rubrics and (
                _rubric_shape(src_rubrics[title]) != _rubric_shape(dest_rubrics[title])
            ):
                plan.warnings.append(
                    f"rubric '{title}' differs between the two courses; the destination's "
                    f"version will be used (by {', '.join(users)})"
                )
            continue
        if title not in src_blocks:
            plan.warnings.append(
                f"rubric '{title}' (used by {', '.join(users)}) is not in the source's "
                f"{_RUBRICS_KEY}; nothing to copy"
            )
            continue
        plan.rubric_appends.append(title)

    if not plan.rubric_appends:
        return
    text = dest_path.read_text() if dest_path.exists() else ""
    for title in plan.rubric_appends:
        if text and not text.endswith("\n"):
            text += "\n"
        if text:
            text += "\n"
        text += src_blocks[title].rstrip("\n") + "\n"
    try:
        titles = {r.get("title") for r in tomllib.loads(text).get("rubrics", [])}
    except tomllib.TOMLDecodeError as e:
        raise CpError(
            f"Appending rubrics to the destination's {_RUBRICS_KEY} would produce "
            f"invalid TOML ({e}); nothing was written."
        ) from e
    missing = [t for t in plan.rubric_appends if t not in titles]
    if missing:
        raise CpError(
            f"Appending rubrics to the destination's {_RUBRICS_KEY} did not add "
            f"{', '.join(missing)}; nothing was written."
        )
    plan.rubrics_text = text


# ---------------------------------------------------------------------------
# module_order.toml
# ---------------------------------------------------------------------------


def _plan_module_order(planner: _Planner) -> None:
    path = planner.dest / _MODULE_ORDER_KEY
    if not planner.modules or not path.exists():
        return
    doc = tomlkit.parse(path.read_text())
    order = doc.get("order")
    if order is None:
        order = tomlkit.array()
        order.multiline(True)
        doc["order"] = order
    existing = {str(e) for e in order}
    for rel in planner.modules:
        name = rel.split("/", 1)[1]
        if name not in existing:
            order.append(name)
            existing.add(name)
            planner.plan.module_order_appends.append(name)
    if planner.plan.module_order_appends:
        planner.plan.module_order_text = tomlkit.dumps(doc)


# ---------------------------------------------------------------------------
# Warnings about course-specific values
# ---------------------------------------------------------------------------


def _dest_flags(dest: Path) -> set[str]:
    flags = set(load_course_flags(dest).keys())
    for cfg in (dest / "course_settings").glob("canvas*.toml"):
        table = _load_toml(cfg).get("course_flags", {})
        if isinstance(table, dict):
            flags |= set(table)
    return flags


def _source_course_ids(src: Path) -> set[str]:
    ids: set[str] = set()
    for cfg in (src / "course_settings").glob("canvas*.toml"):
        value = _load_toml(cfg).get("course_id")
        if value is not None:
            ids.add(str(value))
    return ids


def _dest_titles(dest: Path) -> dict[tuple[str, str], list[str]]:
    titles: dict[tuple[str, str], list[str]] = {}
    for top in _TITLED_DIRS:
        folder = dest / top
        if not folder.exists():
            continue
        for md in sorted(folder.rglob("*.md")):
            rel = _rel(md, dest)
            ctype = _titled_type(rel)
            if ctype is None:
                continue
            fm = _frontmatter(md, dest / "snippets")
            titles.setdefault((ctype, _item_title(rel, fm)), []).append(rel)
    return titles


def _relative_names(settings: dict[str, Any]) -> set[str]:
    names: set[str] = set()
    section = settings.get("relative_due_dates")
    tables = section.get("tables", {}) if isinstance(section, dict) else {}
    if not isinstance(tables, dict):
        return names
    for table in tables.values():
        items = table.get("items", []) if isinstance(table, dict) else []
        for item in items if isinstance(items, list) else []:
            if isinstance(item, dict) and isinstance(item.get("name"), str):
                names.add(item["name"].strip())
    return names


def _plan_warnings(planner: _Planner) -> None:
    plan = planner.plan
    src_settings = _load_toml(planner.src / "course_settings" / "course_settings.toml")
    dest_settings = _load_toml(planner.dest / "course_settings" / "course_settings.toml")
    dest_groups = {
        g.get("title") for g in dest_settings.get("assignment_groups", []) if isinstance(g, dict)
    }
    dest_flags = _dest_flags(planner.dest)
    due_names = {e.get("name") for e in load_due_dates(planner.src, src_settings)}
    relative_names = _relative_names(src_settings)
    dest_titles = _dest_titles(planner.dest)
    course_ids = _source_course_ids(planner.src)

    for rel in planner.copied_md():
        path = planner.src / rel
        try:
            text = path.read_text()
        except (OSError, UnicodeDecodeError):
            continue
        fm = _frontmatter(path, planner.snippets_dir) or {}
        top = rel.split("/")[0]

        group = fm.get("assignment_group_id")
        if isinstance(group, str):
            if group not in dest_groups:
                plan.warnings.append(
                    f"{rel}: assignment_group_id '{group}' is not defined in the "
                    f"destination's course_settings.toml"
                )
        elif group is not None:
            plan.warnings.append(
                f"{rel}: assignment_group_id {group!r} is a numeric Canvas ID from the "
                f"source course"
            )
        for key in ("group_category_id", "final_grader_id"):
            if fm.get(key) is not None:
                plan.warnings.append(
                    f"{rel}: {key} {fm[key]!r} is a Canvas ID from the source course"
                )

        flags = find_referenced_flags(text) | find_referenced_flags_in_frontmatter(fm)
        undefined = sorted(flags - dest_flags)
        if undefined:
            plan.warnings.append(
                f"{rel}: uses course flag(s) {', '.join(undefined)} not defined in the "
                f"destination"
            )

        ctype = _titled_type(rel)
        if ctype is not None:
            title = _item_title(rel, fm)
            if top in _GRADED_TYPES:
                where = []
                if title in due_names:
                    where.append("due_dates")
                if title in relative_names:
                    where.append("relative_due_dates")
                if where:
                    plan.warnings.append(
                        f"{rel}: dates for '{title}' live in the source's "
                        f"course_settings.toml ({' and '.join(where)}) and were not copied"
                    )
            others = [o for o in dest_titles.get((ctype, title), []) if o != rel]
            if others:
                plan.warnings.append(
                    f"{rel}: the destination already has a {ctype[:-1]} titled "
                    f"'{title}' ({', '.join(others)})"
                )

        if course_ids:
            found = sorted({m.group(1) for m in _COURSE_URL_RE.finditer(text)} & course_ids)
            if found:
                plan.warnings.append(
                    f"{rel}: contains absolute Canvas URL(s) to the source course "
                    f"(/courses/{', '.join(found)}/...)"
                )


# ---------------------------------------------------------------------------
# Entry points
# ---------------------------------------------------------------------------


def build_copy_plan(srcs: list[Path], dest_root: Path, overwrite: bool = False) -> CopyPlan:
    """Work out everything `cp` would do. Writes nothing."""
    if not srcs:
        raise CpError("Nothing to copy: give at least one SRC.")
    src_root = _find_source_root(srcs)
    dest_root = dest_root.resolve()
    if src_root == dest_root:
        raise CpError(
            "Source and destination are the same course repo; use "
            "`markdown-to-canvas mv` to move or rename within a course."
        )
    if not (dest_root / "course_settings" / "course_settings.toml").exists():
        raise CpError(
            f"{dest_root} is not a course repo (no course_settings/course_settings.toml)."
        )
    repo_format.check_repo_format(src_root)
    try:
        repo_format.check_repo_format(dest_root)
    except repo_format.RepoFormatError as e:
        raise repo_format.RepoFormatError(f"Destination course {dest_root}: {e}") from e

    planner = _Planner(src_root, dest_root, overwrite)
    for src in srcs:
        planner.add_src(src.absolute())
    planner.walk()
    planner.classify()
    _plan_rubrics(planner)
    _plan_module_order(planner)
    _plan_warnings(planner)
    return planner.plan


def _print_plan(plan: CopyPlan, noop: bool, verbose: bool, overwrite: bool) -> None:
    will = "Would copy" if noop else "Copying"
    print(f"Source:    {plan.src_root}")
    new = plan.by_status(NEW)
    replaced = plan.conflicts if overwrite else []
    for rel in new:
        print(f"  {will}: {rel}")
    for rel in replaced:
        print(f"  {'Would overwrite' if noop else 'Overwriting'}: {rel}")
    identical = plan.by_status(IDENTICAL)
    if identical:
        if verbose:
            for rel in identical:
                print(f"  Identical in destination, skipped: {rel}")
        else:
            print(f"  {len(identical)} file(s) already identical in the destination, skipped")
    for rel in plan.by_status(SNIPPET_KEPT):
        print(f"  Keeping the destination's own snippet: {rel}")
    for rel in plan.ignored:
        print(f"  Skipped (matched by the source's .canvasignore): {rel}")
    for title in plan.rubric_appends:
        verb = "Would append" if noop else "Appending"
        print(f"  {verb} rubric '{title}' to {_RUBRICS_KEY}")
    for name in plan.module_order_appends:
        verb = "Would add" if noop else "Adding"
        print(f"  {verb} {name} to {_MODULE_ORDER_KEY}")
    if plan.links_not_followed:
        print("\nLinks to content that was not copied (left unchanged):")
        for referrer, key, exists in plan.links_not_followed:
            state = "exists in destination" if exists else "MISSING in destination"
            print(f"  {referrer} -> {key}  ({state})")
    if plan.warnings:
        print("\nWarnings:")
        for w in plan.warnings:
            print(f"  WARNING: {w}")


def _write(plan: CopyPlan, overwrite: bool) -> int:
    count = 0
    for action in plan.files:
        if action.status == NEW or (action.status == CONFLICT and overwrite):
            target = plan.dest_root / action.rel
            target.parent.mkdir(parents=True, exist_ok=True)
            # copyfile, not copy2: the copy must get a fresh mtime so `update`
            # sees it as changed even if the destination synced this path later
            # than the source file was last edited.
            shutil.copyfile(plan.src_root / action.rel, target)
            count += 1
    if plan.rubrics_text is not None:
        path = plan.dest_root / _RUBRICS_KEY
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(plan.rubrics_text)
    if plan.module_order_text is not None:
        (plan.dest_root / _MODULE_ORDER_KEY).write_text(plan.module_order_text)
    return count


def run_cp(
    srcs: list[Path],
    dest_root: Path,
    *,
    noop: bool = False,
    verbose: bool = False,
    overwrite: bool = False,
) -> bool:
    """Copy srcs (and their dependencies) into dest_root. Returns success.

    Returns False without writing anything when the destination has files that
    differ and `overwrite` is not set. Raises CpError / RepoFormatError for
    problems found before planning completes.
    """
    plan = build_copy_plan(srcs, dest_root, overwrite)
    _print_plan(plan, noop, verbose, overwrite)

    if plan.conflicts and not overwrite:
        print(
            "\nThese files already exist in the destination with different content:"
        )
        for rel in plan.conflicts:
            print(f"  {rel}")
        print("Nothing was copied. Re-run with --overwrite to replace them.")
        return False
    if noop:
        print("\n(noop: nothing was written)")
        return True
    count = _write(plan, overwrite)
    print(
        f"\nCopied {count} file(s). Run `markdown-to-canvas update` on the "
        f"destination course to upload them."
    )
    return True
