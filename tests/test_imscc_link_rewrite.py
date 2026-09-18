"""Unit tests: IMSCC $CANVAS_OBJECT_REFERENCE$ and $IMS-CC-FILEBASE$ rewriting."""
from __future__ import annotations

import pytest

from markdown_to_canvas.imscc_import import TempEntry, rewrite_imscc_links


def _manifest(*entries: TempEntry) -> dict[str, TempEntry]:
    return {e.imscc_id: e for e in entries}


def _page(imscc_id: str, local_path: str) -> TempEntry:
    return TempEntry(imscc_id=imscc_id, category="page", imscc_path="", local_path=local_path)


def _assignment(imscc_id: str, local_path: str) -> TempEntry:
    return TempEntry(imscc_id=imscc_id, category="assignment", imscc_path="", local_path=local_path)


def _discussion(imscc_id: str, local_path: str) -> TempEntry:
    return TempEntry(imscc_id=imscc_id, category="discussion", imscc_path="", local_path=local_path)


# ---------------------------------------------------------------------------
# $CANVAS_OBJECT_REFERENCE$ rewrites
# ---------------------------------------------------------------------------


def test_assignment_ref_rewritten() -> None:
    m = _manifest(_assignment("g_a1", "assignments/my-assignment.md"))
    html = '<a href="$CANVAS_OBJECT_REFERENCE$/assignments/g_a1">Link</a>'
    result = rewrite_imscc_links(html, m, "pages/my-page.md")
    assert "../assignments/my-assignment.md" in result
    assert "$CANVAS_OBJECT_REFERENCE$" not in result


def test_page_ref_rewritten() -> None:
    m = _manifest(_page("g_p1", "pages/my-page.md"))
    html = '<a href="$CANVAS_OBJECT_REFERENCE$/pages/g_p1">Page</a>'
    result = rewrite_imscc_links(html, m, "assignments/hw.md")
    assert "../pages/my-page.md" in result


def test_discussion_ref_rewritten() -> None:
    m = _manifest(_discussion("g_d1", "discussions/forum.md"))
    html = '<a href="$CANVAS_OBJECT_REFERENCE$/discussion_topics/g_d1">Forum</a>'
    result = rewrite_imscc_links(html, m, "pages/p.md")
    assert "../discussions/forum.md" in result


def test_wrap_query_param_stripped() -> None:
    m = _manifest(_assignment("g_a1", "assignments/hw.md"))
    html = '<a href="$CANVAS_OBJECT_REFERENCE$/assignments/g_a1?wrap=1">HW</a>'
    result = rewrite_imscc_links(html, m, "pages/p.md")
    assert "?wrap=1" not in result
    assert "../assignments/hw.md" in result


def test_module_ref_resolved_when_in_manifest() -> None:
    m = {"g_mod1": TempEntry(imscc_id="g_mod1", category="module",
                             imscc_path="", local_path="modules/my-module.md")}
    html = '<a href="$CANVAS_OBJECT_REFERENCE$/modules/g_mod1">Module</a>'
    result = rewrite_imscc_links(html, m, "pages/p.md")
    assert "../modules/my-module.md" in result
    assert "$CANVAS_OBJECT_REFERENCE$" not in result


def test_module_ref_unknown_warns_and_removes(capsys: pytest.CaptureFixture) -> None:
    html = '<a href="$CANVAS_OBJECT_REFERENCE$/modules/g_mod1">Module</a>'
    result = rewrite_imscc_links(html, {}, "pages/p.md")
    assert "$CANVAS_OBJECT_REFERENCE$" not in result
    assert "WARNING" in capsys.readouterr().out


def test_unknown_id_warns_and_unwraps_link(capsys: pytest.CaptureFixture) -> None:
    """A link to an object missing from the export keeps its text but loses the <a>.

    An empty href would become `[X]( "title")` in Markdown, which `update`
    resolves to the file's own directory.
    """
    html = ('<p>See <a title="Lecture 07" href="$CANVAS_OBJECT_REFERENCE$/assignments/g_unknown" '
            'data-course-type="assignments"><strong>X</strong></a> now</p>')
    result = rewrite_imscc_links(html, {}, "pages/p.md")
    assert result == "<p>See <strong>X</strong> now</p>"
    out = capsys.readouterr().out
    assert "WARNING" in out
    assert "pages/p.md" in out and "'X'" in out


def test_unknown_id_unwrap_leaves_other_links_alone(capsys: pytest.CaptureFixture) -> None:
    m = _manifest(_assignment("g_a1", "assignments/hw.md"))
    html = ('<a href="$CANVAS_OBJECT_REFERENCE$/assignments/g_gone">Gone</a> '
            '<a href="$CANVAS_OBJECT_REFERENCE$/assignments/g_a1">HW</a>')
    result = rewrite_imscc_links(html, m, "pages/p.md")
    assert result == 'Gone <a href="../assignments/hw.md">HW</a>'


def test_wiki_reference_by_page_slug_resolved() -> None:
    m = _manifest(TempEntry(imscc_id="g_p1", category="page",
                            imscc_path="wiki_content/course-orientation.html",
                            local_path="pages/course-orientation.md"))
    html = '<a href="$WIKI_REFERENCE$/pages/course-orientation">Orientation</a>'
    result = rewrite_imscc_links(html, m, "pages/p.md")
    assert result == '<a href="../pages/course-orientation.md">Orientation</a>'


def test_assignment_alias_resolves_to_quiz_file() -> None:
    m = _manifest(TempEntry(imscc_id="g_qa", category="assignment_alias",
                            imscc_path="", local_path="quizzes/q/q.md"))
    html = '<a href="$CANVAS_OBJECT_REFERENCE$/assignments/g_qa">Quiz</a>'
    result = rewrite_imscc_links(html, m, "pages/p.md")
    assert '<a href="../quizzes/q/q.md">Quiz</a>' == result


# ---------------------------------------------------------------------------
# $IMS-CC-FILEBASE$ rewrites
# ---------------------------------------------------------------------------


def test_filebase_image_rewritten() -> None:
    html = '<img src="$IMS-CC-FILEBASE$/images/logo.png" alt="logo"/>'
    result = rewrite_imscc_links(html, {}, "pages/p.md")
    assert "../assets/images/logo.png" in result
    assert "$IMS-CC-FILEBASE$" not in result


def test_filebase_url_decoded() -> None:
    html = '<a href="$IMS-CC-FILEBASE$/My%20Files/doc.pdf">doc</a>'
    result = rewrite_imscc_links(html, {}, "pages/p.md")
    assert "../assets/My Files/doc.pdf" in result


def test_filebase_query_param_stripped() -> None:
    html = '<a href="$IMS-CC-FILEBASE$/doc.pdf?canvas_=1&canvas_qs_wrap=1">doc</a>'
    result = rewrite_imscc_links(html, {}, "pages/p.md")
    assert "canvas_=1" not in result
    assert "../assets/doc.pdf" in result


# ---------------------------------------------------------------------------
# Unchanged cases
# ---------------------------------------------------------------------------


def test_external_https_unchanged() -> None:
    html = '<a href="https://example.com">External</a>'
    result = rewrite_imscc_links(html, {}, "pages/p.md")
    assert result == html


def test_anchor_link_unchanged() -> None:
    html = '<a href="#section-1">Jump</a>'
    result = rewrite_imscc_links(html, {}, "pages/p.md")
    assert result == html


# ---------------------------------------------------------------------------
# Relative depth
# ---------------------------------------------------------------------------


def test_relative_prefix_one_level_deep() -> None:
    """Files in pages/ need exactly one '../'."""
    m = _manifest(_assignment("g_a1", "assignments/hw.md"))
    html = '<a href="$CANVAS_OBJECT_REFERENCE$/assignments/g_a1">HW</a>'
    result = rewrite_imscc_links(html, m, "pages/p.md")
    assert result.count("../") == 1


def test_relative_prefix_two_levels_deep() -> None:
    """Files in a/b/ need '../../'."""
    m = _manifest(_assignment("g_a1", "assignments/hw.md"))
    html = '<a href="$CANVAS_OBJECT_REFERENCE$/assignments/g_a1">HW</a>'
    result = rewrite_imscc_links(html, m, "course_settings/sub/page.md")
    assert "../../assignments/hw.md" in result
