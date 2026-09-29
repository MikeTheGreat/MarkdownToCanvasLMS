"""Unit tests: HTML link/img rewriting logic."""
from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock

import pytest

from markdown_to_canvas.link_rewrite import (
    canvas_content_url,
    infer_canvas_type,
    rewrite_links,
)

COURSE_ID = 999

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _setup(tmp_path: Path) -> tuple[Path, Path]:
    """Return (course_root, source_file) with fixture files on disk."""
    course_root = tmp_path / "course"
    course_root.mkdir()
    (course_root / "pages").mkdir()
    (course_root / "assignments").mkdir()
    (course_root / "discussions").mkdir()
    (course_root / "assets" / "images").mkdir(parents=True)
    (course_root / "pages" / "syllabus.md").touch()
    (course_root / "assignments" / "week1.md").touch()
    (course_root / "discussions" / "intro.md").touch()
    (course_root / "assets" / "images" / "fig.png").touch()
    source_file = course_root / "pages" / "notes.md"
    return course_root, source_file


def _no_stub(local_path: str, canvas_type: str):
    raise AssertionError(f"stub_creator should not have been called for {local_path!r}")


# ---------------------------------------------------------------------------
# infer_canvas_type
# ---------------------------------------------------------------------------


def test_infer_type_page() -> None:
    assert infer_canvas_type("pages/syllabus.md") == "page"


def test_infer_type_assignment() -> None:
    assert infer_canvas_type("assignments/week1.md") == "assignment"


def test_infer_type_discussion() -> None:
    assert infer_canvas_type("discussions/intro.md") == "discussion"


def test_infer_type_announcement() -> None:
    assert infer_canvas_type("announcements/midterm-reminder.md") == "announcement"


def test_infer_type_file() -> None:
    assert infer_canvas_type("assets/images/fig.png") == "file"


def test_infer_type_module() -> None:
    """A link to a module file must stub a module, not a page — a page stub
    left a page id under the module's manifest key, and module sync/reorder
    then asked Canvas for a module with that id."""
    assert infer_canvas_type("modules/lecture-01.md") == "module"


def test_infer_type_unknown_defaults_to_page() -> None:
    assert infer_canvas_type("other/thing.md") == "page"


# ---------------------------------------------------------------------------
# canvas_content_url
# ---------------------------------------------------------------------------


def test_canvas_url_page() -> None:
    entry = {"canvas_type": "page", "canvas_id": 1, "canvas_url": "syllabus"}
    assert canvas_content_url(entry, COURSE_ID) == f"/courses/{COURSE_ID}/pages/syllabus"


def test_canvas_url_assignment() -> None:
    entry = {"canvas_type": "assignment", "canvas_id": 98765}
    assert canvas_content_url(entry, COURSE_ID) == f"/courses/{COURSE_ID}/assignments/98765"


def test_canvas_url_discussion() -> None:
    entry = {"canvas_type": "discussion", "canvas_id": 55555}
    assert canvas_content_url(entry, COURSE_ID) == f"/courses/{COURSE_ID}/discussion_topics/55555"


def test_canvas_url_announcement() -> None:
    # Announcements are discussion topics in Canvas, so they use the same URL shape.
    entry = {"canvas_type": "announcement", "canvas_id": 55555}
    assert canvas_content_url(entry, COURSE_ID) == f"/courses/{COURSE_ID}/discussion_topics/55555"


def test_canvas_url_file() -> None:
    url = "https://school.instructure.com/files/77777/download"
    entry = {"canvas_type": "file", "canvas_id": 77777, "canvas_url": url}
    assert canvas_content_url(entry, COURSE_ID) == url


def test_canvas_url_unknown_type_raises() -> None:
    with pytest.raises(ValueError, match="Unknown canvas_type"):
        canvas_content_url({"canvas_type": "bogus", "canvas_id": 1}, COURSE_ID)


# ---------------------------------------------------------------------------
# rewrite_links — img tags
# ---------------------------------------------------------------------------


def test_img_src_rewritten_from_manifest(tmp_path: Path) -> None:
    course_root, source_file = _setup(tmp_path)
    canvas_file_url = "https://school.instructure.com/files/77777/download"
    manifest = {
        "assets/images/fig.png": {
            "canvas_type": "file",
            "canvas_id": 77777,
            "canvas_url": canvas_file_url,
        }
    }
    html = '<p><img src="../assets/images/fig.png" alt="fig" /></p>'
    result = rewrite_links(html, source_file, course_root, manifest, COURSE_ID, _no_stub)
    assert canvas_file_url in result
    assert "../assets" not in result


def test_img_missing_local_file_removed(tmp_path: Path, capsys: pytest.CaptureFixture) -> None:
    course_root, source_file = _setup(tmp_path)
    html = '<p><img src="../assets/images/missing.png" alt="x" /></p>'
    result = rewrite_links(html, source_file, course_root, {}, COURSE_ID, _no_stub)
    assert "<img" not in result
    assert "ERROR" in capsys.readouterr().out


def test_img_src_escaping_repo_removed_and_reported(
    tmp_path: Path, capsys: pytest.CaptureFixture
) -> None:
    """One `../` too many resolves outside the course repo. The tag is removed
    and an error recorded (which makes the caller skip the upload), rather than
    passing the local path through to Canvas."""
    course_root, source_file = _setup(tmp_path)
    html = '<p><img src="../../assets/images/fig.png" alt="" /></p>'
    errors: list[str] = []
    result = rewrite_links(html, source_file, course_root, {}, COURSE_ID, _no_stub, errors)
    assert "<img" not in result
    assert errors == [
        "  pages/notes.md: relative path resolves outside the course repo "
        "(check the number of ../ segments), removing tag: ../../assets/images/fig.png"
    ]
    assert "ERROR" in capsys.readouterr().out


def test_a_href_escaping_repo_removed_and_reported(tmp_path: Path) -> None:
    course_root, source_file = _setup(tmp_path)
    html = '<a href="../../../elsewhere/doc.pdf">Doc</a>'
    errors: list[str] = []
    result = rewrite_links(html, source_file, course_root, {}, COURSE_ID, _no_stub, errors)
    assert "<a " not in result
    assert len(errors) == 1 and "outside the course repo" in errors[0]


@pytest.mark.parametrize(
    "href",
    [
        "/courses/123/files/456/download",  # root-relative Canvas URL
        "//cdn.example.com/x.png",  # protocol-relative
        "data:image/png;base64,AAAA",
        "tel:+15555550100",
    ],
)
def test_non_relative_urls_unchanged_and_not_errors(tmp_path: Path, href: str) -> None:
    """Scheme URLs other than http(s)/mailto used to be resolved as local
    files and removed with "local file not found"."""
    course_root, source_file = _setup(tmp_path)
    html = f'<img src="{href}" alt="" /><a href="{href}">x</a>'
    errors: list[str] = []
    result = rewrite_links(html, source_file, course_root, {}, COURSE_ID, _no_stub, errors)
    assert result == html
    assert errors == []


def test_fragment_kept_on_page_link(tmp_path: Path) -> None:
    """A `#fragment` used to make the path look like a missing file."""
    course_root, source_file = _setup(tmp_path)
    manifest = {
        "pages/syllabus.md": {"canvas_type": "page", "canvas_id": 11111, "canvas_url": "syllabus"}
    }
    html = '<a href="syllabus.md#late-work">Late work</a>'
    errors: list[str] = []
    result = rewrite_links(html, source_file, course_root, manifest, COURSE_ID, _no_stub, errors)
    assert errors == []
    assert f'href="/courses/{COURSE_ID}/pages/syllabus#late-work"' in result


def test_query_and_fragment_dropped_on_file_link(tmp_path: Path) -> None:
    """A file's canvas_url is used verbatim; appending to it could break its own query."""
    course_root, source_file = _setup(tmp_path)
    url = "https://school.instructure.com/files/77777/download?verifier=abc"
    manifest = {
        "assets/images/fig.png": {"canvas_type": "file", "canvas_id": 77777, "canvas_url": url}
    }
    html = '<a href="../assets/images/fig.png?x=1#p2">fig</a>'
    result = rewrite_links(html, source_file, course_root, manifest, COURSE_ID, _no_stub)
    assert f'href="{url}"' in result


def test_img_external_src_unchanged(tmp_path: Path) -> None:
    course_root, source_file = _setup(tmp_path)
    html = '<img src="https://example.com/img.png" alt="ext" />'
    result = rewrite_links(html, source_file, course_root, {}, COURSE_ID, _no_stub)
    assert result == html


# ---------------------------------------------------------------------------
# rewrite_links — a href tags
# ---------------------------------------------------------------------------


def test_a_href_page_rewritten_from_manifest(tmp_path: Path) -> None:
    course_root, source_file = _setup(tmp_path)
    manifest = {
        "pages/syllabus.md": {"canvas_type": "page", "canvas_id": 11111, "canvas_url": "syllabus"}
    }
    html = '<a href="../pages/syllabus.md">Syllabus</a>'
    result = rewrite_links(html, source_file, course_root, manifest, COURSE_ID, _no_stub)
    assert f"/courses/{COURSE_ID}/pages/syllabus" in result
    assert "../pages" not in result


def test_a_href_assignment_rewritten_from_manifest(tmp_path: Path) -> None:
    course_root, source_file = _setup(tmp_path)
    manifest = {
        "assignments/week1.md": {"canvas_type": "assignment", "canvas_id": 98765}
    }
    html = '<a href="../assignments/week1.md">Week 1</a>'
    result = rewrite_links(html, source_file, course_root, manifest, COURSE_ID, _no_stub)
    assert f"/courses/{COURSE_ID}/assignments/98765" in result


def test_a_href_discussion_rewritten_from_manifest(tmp_path: Path) -> None:
    course_root, source_file = _setup(tmp_path)
    manifest = {
        "discussions/intro.md": {"canvas_type": "discussion", "canvas_id": 55555}
    }
    html = '<a href="../discussions/intro.md">Intro</a>'
    result = rewrite_links(html, source_file, course_root, manifest, COURSE_ID, _no_stub)
    assert f"/courses/{COURSE_ID}/discussion_topics/55555" in result


def test_a_href_external_unchanged(tmp_path: Path) -> None:
    course_root, source_file = _setup(tmp_path)
    html = '<a href="https://example.com">External</a>'
    result = rewrite_links(html, source_file, course_root, {}, COURSE_ID, _no_stub)
    assert result == html


def test_a_href_anchor_unchanged(tmp_path: Path) -> None:
    course_root, source_file = _setup(tmp_path)
    html = '<a href="#section-1">Jump</a>'
    result = rewrite_links(html, source_file, course_root, {}, COURSE_ID, _no_stub)
    assert result == html


def test_a_href_missing_local_file_removed(tmp_path: Path, capsys: pytest.CaptureFixture) -> None:
    course_root, source_file = _setup(tmp_path)
    html = '<a href="../pages/ghost.md">Ghost</a>'
    result = rewrite_links(html, source_file, course_root, {}, COURSE_ID, _no_stub)
    assert "<a " not in result
    assert "ERROR" in capsys.readouterr().out


def test_a_href_blank_url_resolving_to_directory_removed(
    tmp_path: Path, capsys: pytest.CaptureFixture
) -> None:
    """A markdown link with a missing URL, e.g. `[text]( "title")`, produces
    an empty href that resolves to the source file's own folder. This must
    not be treated as a referenced-but-unsynced file (which would stub-create
    a bogus Canvas item named after the folder) — it should be dropped like
    any other missing-file reference."""
    course_root, source_file = _setup(tmp_path)
    html = '<a href="" title="How would you like to be graded?">How would you like to be graded?</a>'
    result = rewrite_links(html, source_file, course_root, {}, COURSE_ID, _no_stub)
    assert "<a " not in result
    assert "ERROR" in capsys.readouterr().out


# ---------------------------------------------------------------------------
# rewrite_links — stub creation
# ---------------------------------------------------------------------------


def test_stub_creator_called_for_unknown_file(tmp_path: Path) -> None:
    course_root, source_file = _setup(tmp_path)
    stub_entry = {"canvas_type": "page", "canvas_id": 42, "canvas_url": "syllabus"}
    stub_creator = MagicMock(return_value=stub_entry)
    html = '<a href="../pages/syllabus.md">Syllabus</a>'
    result = rewrite_links(html, source_file, course_root, {}, COURSE_ID, stub_creator)
    stub_creator.assert_called_once_with("pages/syllabus.md", "page")
    assert f"/courses/{COURSE_ID}/pages/syllabus" in result


def test_stub_creator_not_called_when_in_manifest(tmp_path: Path) -> None:
    course_root, source_file = _setup(tmp_path)
    manifest = {
        "pages/syllabus.md": {"canvas_type": "page", "canvas_id": 11111, "canvas_url": "syllabus"}
    }
    stub_creator = MagicMock()
    html = '<a href="../pages/syllabus.md">Syllabus</a>'
    rewrite_links(html, source_file, course_root, manifest, COURSE_ID, stub_creator)
    stub_creator.assert_not_called()


def test_stub_creator_called_once_for_repeated_reference(tmp_path: Path) -> None:
    course_root, source_file = _setup(tmp_path)
    stub_entry = {"canvas_type": "page", "canvas_id": 42, "canvas_url": "syllabus"}
    stub_creator = MagicMock(return_value=stub_entry)
    html = (
        '<a href="../pages/syllabus.md">Link 1</a> '
        '<a href="../pages/syllabus.md">Link 2</a>'
    )
    rewrite_links(html, source_file, course_root, {}, COURSE_ID, stub_creator)
    stub_creator.assert_called_once()  # not twice


def test_link_to_unposted_announcement_is_left_unresolved(
    tmp_path: Path, capsys: pytest.CaptureFixture
) -> None:
    """Canvas has no draft announcements, so no stub is made: the <a> loses its
    href (the text stays) and the target is reported through ``deferred``."""
    course_root, source_file = _setup(tmp_path)
    (course_root / "announcements").mkdir()
    (course_root / "announcements" / "welcome.md").touch()
    html = (
        '<a href="../announcements/welcome.md" title="Hi">Welcome</a> '
        '<a href="../announcements/welcome.md">again</a>'
    )
    deferred: list[str] = []
    errors: list[str] = []
    result = rewrite_links(
        html, source_file, course_root, {}, COURSE_ID, _no_stub, errors,
        deferred=deferred,
    )
    assert result == '<a title="Hi">Welcome</a> <a>again</a>'
    assert deferred == ["announcements/welcome.md"]
    assert errors == []
    assert "not been posted" in capsys.readouterr().out


def test_img_pointing_at_unposted_announcement_removed(tmp_path: Path) -> None:
    course_root, source_file = _setup(tmp_path)
    (course_root / "announcements").mkdir()
    (course_root / "announcements" / "welcome.md").touch()
    html = '<p><img src="../announcements/welcome.md" alt="x"></p>'
    result = rewrite_links(html, source_file, course_root, {}, COURSE_ID, _no_stub)
    assert result == "<p></p>"


def test_link_to_posted_announcement_rewritten(tmp_path: Path) -> None:
    course_root, source_file = _setup(tmp_path)
    (course_root / "announcements").mkdir()
    (course_root / "announcements" / "welcome.md").touch()
    manifest = {
        "announcements/welcome.md": {"canvas_type": "announcement", "canvas_id": 77}
    }
    deferred: list[str] = []
    html = '<a href="../announcements/welcome.md">Welcome</a>'
    result = rewrite_links(
        html, source_file, course_root, manifest, COURSE_ID, _no_stub,
        deferred=deferred,
    )
    assert f'href="/courses/{COURSE_ID}/discussion_topics/77"' in result
    assert deferred == []


def test_link_to_canvasignored_file_is_an_error(tmp_path: Path, capsys) -> None:
    """No stub is made for an ignored target; the link is an error."""
    from markdown_to_canvas.ignore import load_ignore_matcher

    course_root, source_file = _setup(tmp_path)
    (course_root / "pages" / "drafts").mkdir()
    (course_root / "pages" / "drafts" / "plan.md").touch()
    (course_root / ".canvasignore").write_text("drafts/\n")
    errors: list[str] = []
    rewrite_links(
        '<a href="drafts/plan.md">Plan</a>', source_file, course_root, {},
        COURSE_ID, _no_stub, errors, matcher=load_ignore_matcher(course_root),
    )
    assert len(errors) == 1
    assert "pages/drafts/plan.md, which .canvasignore excludes" in errors[0]
    assert "ERROR:" in capsys.readouterr().out


def test_link_to_canvasignored_file_already_on_canvas_is_an_error(
    tmp_path: Path,
) -> None:
    """A manifest entry (uploaded before it was ignored) does not make the link OK."""
    from markdown_to_canvas.ignore import load_ignore_matcher

    course_root, source_file = _setup(tmp_path)
    (course_root / "pages" / "old.md").touch()
    (course_root / ".canvasignore").write_text("old.md\n")
    manifest = {"pages/old.md": {"canvas_type": "page", "canvas_id": 5, "canvas_url": "old"}}
    errors: list[str] = []
    rewrite_links(
        '<a href="old.md">Old</a>', source_file, course_root, manifest,
        COURSE_ID, _no_stub, errors, matcher=load_ignore_matcher(course_root),
    )
    assert len(errors) == 1


# ---------------------------------------------------------------------------
# rewrite_links — mixed content
# ---------------------------------------------------------------------------


def test_url_encoded_href_resolved_to_file_with_spaces(tmp_path: Path) -> None:
    """Percent-encoded hrefs (%20) must resolve to the actual file that has spaces."""
    course_root, source_file = _setup(tmp_path)
    assets_dir = course_root / "assets" / "syllabus"
    assets_dir.mkdir(parents=True)
    (assets_dir / "IT-CS 115 - Panitz - Summer 2026 Syllabus.docx").touch()
    canvas_file_url = "https://school.instructure.com/files/9999/download"
    manifest = {
        "assets/syllabus/IT-CS 115 - Panitz - Summer 2026 Syllabus.docx": {
            "canvas_type": "file",
            "canvas_id": 9999,
            "canvas_url": canvas_file_url,
        }
    }
    html = '<a href="../assets/syllabus/IT-CS%20115%20-%20Panitz%20-%20Summer%202026%20Syllabus.docx">Syllabus</a>'
    result = rewrite_links(html, source_file, course_root, manifest, COURSE_ID, _no_stub)
    assert canvas_file_url in result
    assert "%20" not in result


def test_multiple_different_links_all_rewritten(tmp_path: Path) -> None:
    course_root, source_file = _setup(tmp_path)
    manifest = {
        "pages/syllabus.md": {"canvas_type": "page", "canvas_id": 1, "canvas_url": "syllabus"},
        "assignments/week1.md": {"canvas_type": "assignment", "canvas_id": 2},
        "assets/images/fig.png": {
            "canvas_type": "file",
            "canvas_id": 3,
            "canvas_url": "https://school.instructure.com/files/3/download",
        },
    }
    html = (
        '<img src="../assets/images/fig.png" alt="f" /> '
        '<a href="../pages/syllabus.md">S</a> '
        '<a href="../assignments/week1.md">A</a> '
        '<a href="https://example.com">Ext</a> '
        '<a href="#top">Top</a>'
    )
    result = rewrite_links(html, source_file, course_root, manifest, COURSE_ID, _no_stub)
    assert "https://school.instructure.com/files/3/download" in result
    assert f"/courses/{COURSE_ID}/pages/syllabus" in result
    assert f"/courses/{COURSE_ID}/assignments/2" in result
    assert "https://example.com" in result
    assert "#top" in result
    assert "../" not in result
