"""Unit + CLI tests: fix-manifest --pair-canvas-with-local / --force-pair."""
from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import pytest
from click.testing import CliRunner

from markdown_to_canvas import manifest as manifest_lib
from markdown_to_canvas.canvas_api import CanvasObject, CourseListing, list_course_objects
from markdown_to_canvas.pair_manifest import (
    LocalItem,
    PairError,
    apply_pairing,
    collect_local_items,
    normalize_title,
    parse_force_pairs,
    plan_pairing,
)

BASE = "https://school.instructure.com"
SYNCED = "2026-01-01T00:00:00+00:00"


def _obj(canvas_type, canvas_id, title, published=True, **kw) -> CanvasObject:
    return CanvasObject(canvas_type, canvas_id, title, published, **kw)


def _listing(*objs: CanvasObject) -> CourseListing:
    items: dict[str, list[CanvasObject]] = {
        t: [] for t in ("page", "assignment", "discussion", "announcement", "quiz", "module", "file")
    }
    for o in objs:
        items[o.canvas_type].append(o)
    ids = {t: {o.canvas_id for o in v} for t, v in items.items()}
    return CourseListing(ids, items)


# ---------------------------------------------------------------------------
# normalize_title
# ---------------------------------------------------------------------------


def test_normalize_title_folds_case_space_quotes_dashes_entities() -> None:
    assert normalize_title("  Lab 3 — “Loops” &amp; Ifs ") == 'lab 3 - "loops" & ifs'
    assert normalize_title("Don’t") == normalize_title("DON'T")


# ---------------------------------------------------------------------------
# collect_local_items
# ---------------------------------------------------------------------------


def _write(root: Path, rel: str, text: str | bytes = "") -> None:
    path = root / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    if isinstance(text, bytes):
        path.write_bytes(text)
    else:
        path.write_text(text)


def test_collect_local_items_covers_every_type_and_applies_ignores(tmp_path) -> None:
    root = tmp_path
    _write(root, "pages/intro.md", "---\ntitle: Intro\n---\nx\n")
    _write(root, "pages/untitled.md", "no frontmatter\n")
    _write(root, "assignments/hw1.md", "---\ntitle: HW 1\n---\n")
    _write(root, "announcements/hello.md", "---\ntitle: Hello\n---\n")
    _write(root, "lectures/wk1.md", "---\ntitle: Week 1 notes\n---\n")
    _write(root, "quizzes/q1/q1.md", "---\ntitle: Quiz 1\n---\n")
    _write(root, "quizzes/q2/q2.md", "---\n---\n")
    _write(root, "quizzes/q1/questions/a.md", "---\ntitle: not a quiz\n---\n")
    _write(root, "modules/m1.md", "---\ntitle: Module 1\n---\n")
    _write(root, "assets/img/a.png", b"12345")
    _write(root, "assets/drafts/b.png", b"1")
    _write(root, "snippets/s.md", "---\ntitle: snippet\n---\n")
    _write(root, "course_settings/syllabus.md", "---\ntitle: Syllabus\n---\n")
    _write(root, "pages/secret.md", "---\ntitle: Secret\n---\n")
    _write(root, "pages/broken.md", "---\ntitle: [unclosed\n---\n")
    _write(root, ".canvasignore", "pages/secret.md\nassets/drafts/\n")

    items, errors = collect_local_items(root)
    got = {i.key: (i.canvas_type, i.title) for i in items}

    assert got == {
        "announcements/hello.md": ("announcement", "Hello"),
        "assignments/hw1.md": ("assignment", "HW 1"),
        "lectures/wk1.md": ("page", "Week 1 notes"),
        "pages/intro.md": ("page", "Intro"),
        "pages/untitled.md": ("page", "untitled"),
        "quizzes/q1/q1.md": ("quiz", "Quiz 1"),
        "quizzes/q2/q2.md": ("quiz", "q2"),
        "modules/m1.md": ("module", "Module 1"),
        "assets/img/a.png": ("file", "img/a.png"),
    }
    assert next(i for i in items if i.key == "assets/img/a.png").size == 5
    assert [key for key, _ in errors] == ["pages/broken.md"]


# ---------------------------------------------------------------------------
# list_course_objects
# ---------------------------------------------------------------------------


def test_listing_keeps_graded_topics_and_quizzes_out_of_the_assignment_pool() -> None:
    ns = SimpleNamespace
    course = SimpleNamespace(
        get_pages=lambda: [ns(page_id=1, title="Intro", url="intro", published=True)],
        get_assignments=lambda: [
            ns(id=10, name="HW", published=True, submission_types=["online_upload"],
               has_submitted_submissions=True),
            ns(id=11, name="Talk", published=True, submission_types=["discussion_topic"]),
            ns(id=12, name="Quiz", published=True, submission_types=["online_quiz"]),
        ],
        get_discussion_topics=lambda only_announcements=False: (
            [ns(id=30, title="News", published=True)] if only_announcements
            else [ns(id=20, title="Talk", published=True)]
        ),
        get_quizzes=lambda: [ns(id=40, title="Quiz", published=False)],
        get_modules=lambda: [ns(id=50, name="Week 1", published=True)],
        get_folders=lambda: [ns(id=1, full_name="course files"), ns(id=2, full_name="course files/img")],
        get_files=lambda: [
            ns(id=60, display_name="a.png", folder_id=2, url="https://f/60", size=5, locked=False),
            ns(id=61, display_name="top.pdf", folder_id=1, url="https://f/61", size=9, locked=True),
        ],
    )

    listing = list_course_objects(course)

    assert [a.canvas_id for a in listing.items["assignment"]] == [10]
    assert listing.items["assignment"][0].has_submissions
    assert listing.ids["assignment"] == {10, 11, 12}
    assert listing.ids["discussion"] == listing.ids["announcement"] == {20, 30}
    assert listing.items["page"][0].canvas_url == "intro"
    files = {f.title: f for f in listing.items["file"]}
    assert set(files) == {"img/a.png", "top.pdf"}
    assert files["top.pdf"].published is False
    assert listing.items["module"][0].title == "Week 1"


# ---------------------------------------------------------------------------
# plan_pairing
# ---------------------------------------------------------------------------


def _page(key: str, title: str) -> LocalItem:
    return LocalItem(key, "page", title)


def test_pairs_exact_and_normalized_titles_within_one_type() -> None:
    local = [
        _page("pages/a.md", "Intro"),
        _page("pages/b.md", "Lab 3 – Loops"),
        LocalItem("assignments/c.md", "assignment", "Intro"),
    ]
    listing = _listing(
        _obj("page", 1, "Intro", canvas_url="intro"),
        _obj("page", 2, "lab 3 - loops", canvas_url="lab-3"),
    )

    plan = plan_pairing({}, listing, local)

    assert [(p.local.key, p.canvas.canvas_id, p.how) for p in plan.added] == [
        ("pages/a.md", 1, "exact"),
        ("pages/b.md", 2, "normalized"),
    ]
    assert [i.key for i in plan.unmatched_local] == ["assignments/c.md"]


def test_existing_entries_and_their_items_are_left_alone() -> None:
    local = [_page("pages/a.md", "Intro"), _page("pages/b.md", "Intro")]
    manifest = {"pages/a.md": {"canvas_type": "page", "canvas_id": 1, "canvas_url": "intro"}}
    listing = _listing(_obj("page", 1, "Intro"))

    plan = plan_pairing(manifest, listing, local)

    assert not plan.added
    assert [i.key for i in plan.unmatched_local] == ["pages/b.md"]
    assert not plan.unmatched_canvas


def test_duplicate_titles_use_the_tie_break_and_are_reported() -> None:
    local = [LocalItem("assignments/hw.md", "assignment", "HW")]
    listing = _listing(
        _obj("assignment", 5, "HW", published=False),
        _obj("assignment", 9, "HW", published=True, has_submissions=True),
        _obj("assignment", 7, "HW", published=True),
    )

    plan = plan_pairing({}, listing, local)

    assert plan.added[0].canvas.canvas_id == 9
    (group,) = plan.duplicates
    assert [o.canvas_id for o in group.not_chosen] == [7, 5]
    assert {o.canvas_id for o in plan.unmatched_canvas} == {5, 7}


def test_exact_title_wins_within_a_duplicate_group() -> None:
    local = [_page("pages/a.md", "intro"), _page("pages/b.md", "Intro")]
    listing = _listing(_obj("page", 1, "Intro"), _obj("page", 2, "intro", published=False))

    plan = plan_pairing({}, listing, local)

    assert {(p.local.key, p.canvas.canvas_id, p.how) for p in plan.added} == {
        ("pages/a.md", 2, "exact"),
        ("pages/b.md", 1, "exact"),
    }


def test_similar_titles_are_suggested_not_paired() -> None:
    local = [_page("pages/lab3.md", "Lab 3: Loops"), _page("pages/x.md", "Completely different")]
    listing = _listing(_obj("page", 2, "Lab 3 - Loops"), _obj("page", 3, "Zebra"))

    plan = plan_pairing({}, listing, local)

    assert not plan.added
    assert [(loc.key, obj.canvas_id) for loc, obj, _ in plan.suggestions] == [("pages/lab3.md", 2)]
    assert {i.key for i in plan.unmatched_local} == {"pages/lab3.md", "pages/x.md"}


def test_each_canvas_item_is_suggested_once() -> None:
    local = [_page("pages/a.md", "Lab 3 Loops"), _page("pages/b.md", "Lab 3 Loops!")]
    listing = _listing(_obj("page", 2, "Lab 3: Loops"))
    # Both local files normalize differently from the item, and from each other.
    plan = plan_pairing({}, listing, local)
    assert len(plan.suggestions) == 1


def test_forced_pair_replaces_an_entry_and_takes_the_item_out_of_the_pool() -> None:
    local = [_page("pages/a.md", "Intro"), _page("pages/b.md", "Other")]
    manifest = {"pages/b.md": {"canvas_type": "page", "canvas_id": 99, "canvas_url": "gone"}}
    listing = _listing(_obj("page", 1, "Intro"))

    plan = plan_pairing(manifest, listing, local, force_pairs=[("pages/b.md", 1)])

    (pairing,) = plan.added
    assert (pairing.local.key, pairing.how) == ("pages/b.md", "forced")
    assert pairing.replaced == manifest["pages/b.md"]
    assert [i.key for i in plan.unmatched_local] == ["pages/a.md"]


def test_forced_pair_only_mode_does_no_title_matching() -> None:
    local = [_page("pages/a.md", "Intro"), _page("pages/b.md", "Other")]
    listing = _listing(_obj("page", 1, "Intro"), _obj("page", 2, "Other"))

    plan = plan_pairing({}, listing, local, force_pairs=[("pages/b.md", 1)], match_titles=False)

    assert [(p.local.key, p.canvas.canvas_id) for p in plan.added] == [("pages/b.md", 1)]


def test_forced_pair_problems_are_all_reported() -> None:
    local = [_page("pages/a.md", "A"), _page("pages/b.md", "B"), _page("pages/c.md", "C")]
    manifest = {"pages/c.md": {"canvas_type": "page", "canvas_id": 3}}
    listing = _listing(_obj("page", 1, "A"), _obj("page", 3, "C"), _obj("assignment", 4, "X"))

    with pytest.raises(PairError) as exc:
        plan_pairing(
            manifest, listing, local,
            force_pairs=[
                ("pages/missing.md", 1),
                ("pages/a.md", 4),  # an assignment, not a page
                ("pages/b.md", 3),  # already pages/c.md's item
            ],
        )
    message = str(exc.value)
    assert "pages/missing.md is not a file update would sync" in message
    assert "no page with ID 4" in message
    assert "already the Canvas item for pages/c.md" in message

    with pytest.raises(PairError, match="named more than once"):
        plan_pairing({}, listing, local, force_pairs=[("pages/a.md", 1), ("pages/b.md", 1)])


def test_parse_force_pairs() -> None:
    assert parse_force_pairs(["./pages/a=b.md=12"]) == [("pages/a=b.md", 12)]
    with pytest.raises(PairError, match="expected LOCAL_PATH=CANVAS_ID"):
        parse_force_pairs(["pages/a.md", "pages/b.md=x"])


def test_title_mismatch_of_existing_entry_is_reported() -> None:
    local = [_page("pages/a.md", "Intro")]
    manifest = {"pages/a.md": {"canvas_type": "page", "canvas_id": 1}}
    plan = plan_pairing(manifest, _listing(_obj("page", 1, "Welcome")), local)
    assert [(k, o.title) for k, _, o in plan.title_mismatches] == [("pages/a.md", "Welcome")]


def test_apply_writes_entries_in_the_existing_format() -> None:
    local = [
        _page("pages/a.md", "Intro"),
        LocalItem("announcements/n.md", "announcement", "News"),
        LocalItem("assets/a.png", "file", "a.png", size=5),
        LocalItem("assets/b.png", "file", "b.png", size=5),
    ]
    listing = _listing(
        _obj("page", 1, "Intro", canvas_url="intro"),
        _obj("announcement", 2, "News"),
        _obj("file", 3, "a.png", canvas_url="https://f/3", size=5),
        _obj("file", 4, "b.png", canvas_url="https://f/4", size=6),
    )
    manifest: dict = {}
    apply_pairing(manifest, plan_pairing(manifest, listing, local))

    assert manifest["pages/a.md"] == {"canvas_id": 1, "canvas_type": "page", "canvas_url": "intro"}
    assert manifest["announcements/n.md"] == {"canvas_id": 2, "canvas_type": "announcement"}
    assert "last_synced" in manifest["assets/a.png"]  # same size: not re-uploaded
    assert manifest["assets/b.png"] == {
        "canvas_id": 4, "canvas_type": "file", "canvas_url": "https://f/4",
    }


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def _repo(tmp_path: Path) -> Path:
    root = tmp_path / "course"
    _write(root, "course_settings/course_settings.toml", "format_version = 4\n")
    _write(root, "course_settings/canvas.toml", f'base_url = "{BASE}"\ncourse_id = 200\n')
    _write(root, "pages/intro.md", "---\ntitle: Intro\n---\n")
    _write(root, "pages/lab3.md", "---\ntitle: 'Lab 3: Loops'\n---\n")
    _write(root, "pages/stale.md", "---\ntitle: Stale\n---\n")
    return root


def _cli(mocker, monkeypatch, listing: CourseListing):
    from markdown_to_canvas.cli import main

    monkeypatch.setenv("CANVAS_API_TOKEN", "tok")
    mocker.patch("markdown_to_canvas.cli._ensure_pandoc")
    mocker.patch("markdown_to_canvas.cli.get_course", return_value=SimpleNamespace(name="Fall"))
    mocker.patch("markdown_to_canvas.canvas_api.list_course_objects", return_value=listing)
    return lambda *args: CliRunner().invoke(main, ["fix-manifest", *args])


LISTING = _listing(
    _obj("page", 1, "Intro", canvas_url="intro"),
    _obj("page", 2, "Lab 3 - Loops", canvas_url="lab-3"),
    _obj("page", 3, "Stale", canvas_url="stale"),
)


def test_cli_dry_run_reports_and_prints_pasteable_force_pairs(tmp_path, mocker, monkeypatch) -> None:
    root = _repo(tmp_path)
    run = _cli(mocker, monkeypatch, LISTING)
    path = root / ".manifest-canvas.toml"

    result = run(str(root), "--pair-canvas-with-local")

    assert result.exit_code == 0, result.output
    assert not path.exists()
    assert "Would add 2 entries" in result.output
    assert "--force-pair pages/lab3.md=2   #" in result.output
    assert (
        f"markdown-to-canvas fix-manifest {root} --pair-canvas-with-local --apply \\\n"
        "  --force-pair pages/lab3.md=2"
    ) in result.output


def test_cli_apply_writes_pairs_and_records_the_course(tmp_path, mocker, monkeypatch) -> None:
    root = _repo(tmp_path)
    run = _cli(mocker, monkeypatch, LISTING)

    result = run(str(root), "--pair-canvas-with-local", "--force-pair", "pages/lab3.md=2", "--apply")

    assert result.exit_code == 0, result.output
    loaded = manifest_lib.load(root / ".manifest-canvas.toml")
    assert loaded["pages/intro.md"]["canvas_id"] == 1
    assert loaded["pages/lab3.md"]["canvas_url"] == "lab-3"
    assert loaded["pages/stale.md"]["canvas_id"] == 3
    assert manifest_lib.get_course_identity(loaded)["course_id"] == 200


def test_cli_clean_then_pair_reconnects_a_removed_entry_in_the_dry_run(tmp_path, mocker, monkeypatch) -> None:
    root = _repo(tmp_path)
    path = root / ".manifest-canvas.toml"
    manifest_lib.flush(path, {
        "pages/stale.md": {"canvas_type": "page", "canvas_id": 77, "canvas_url": "stale", "last_synced": SYNCED},
    })
    before = path.read_bytes()
    run = _cli(mocker, monkeypatch, LISTING)

    result = run(str(root), "--clean", "--pair-canvas-with-local")
    assert result.exit_code == 0, result.output
    assert "Would remove 1 entries" in result.output
    assert "pages/stale.md -> page 3" in result.output
    assert path.read_bytes() == before

    result = run(str(root), "--clean", "--pair-canvas-with-local", "--apply")
    assert result.exit_code == 0, result.output
    assert manifest_lib.load(path)["pages/stale.md"]["canvas_id"] == 3


def test_cli_pairing_on_another_courses_manifest_needs_clean(tmp_path, mocker, monkeypatch) -> None:
    root = _repo(tmp_path)
    path = root / ".manifest-canvas.toml"
    manifest: dict = {}
    manifest_lib.set_course_identity(manifest, path, BASE, 100, "Spring")
    before = path.read_bytes()
    run = _cli(mocker, monkeypatch, LISTING)

    result = run(str(root), "--pair-canvas-with-local", "--apply")

    assert result.exit_code == 1
    assert "Add --clean" in result.output
    assert path.read_bytes() == before


def test_cli_bad_force_pair_changes_nothing(tmp_path, mocker, monkeypatch) -> None:
    root = _repo(tmp_path)
    run = _cli(mocker, monkeypatch, LISTING)

    result = run(str(root), "--force-pair", "pages/intro.md=999", "--apply")

    assert result.exit_code == 1
    assert "no page with ID 999" in result.output
    assert not (root / ".manifest-canvas.toml").exists()
