"""Tests for the `publish` subcommand (MkDocs static-site generation).

Most assertions target the pure-Python staging/nav/render helpers, which need
no MkDocs install.  One test exercises ``run_publish`` end-to-end with the
``mkdocs`` subprocess mocked out.
"""
from __future__ import annotations

import sys
from pathlib import Path

import yaml

from markdown_to_canvas import publish

FIXTURES = Path(__file__).parent / "fixtures"


# ---------------------------------------------------------------------------
# Path mapping + site name
# ---------------------------------------------------------------------------

def test_staged_path_flattens_quiz():
    assert publish.staged_path("quizzes/a-quiz/a-quiz.md") == "quizzes/a-quiz.md"
    assert publish.staged_path("pages/syllabus.md") == "pages/syllabus.md"


def test_load_site_name_falls_back_to_repo_dir():
    assert publish.load_site_name(FIXTURES) == FIXTURES.name


def test_load_site_name_reads_course_settings(tmp_path):
    cs_dir = tmp_path / "course_settings"
    cs_dir.mkdir()
    (cs_dir / "course_settings.toml").write_text('title = "Intro to CS"\n')
    assert publish.load_site_name(tmp_path) == "Intro to CS"


def test_load_site_name_uses_publish_title_when_title_commented_out(tmp_path):
    """An imported repo ships `title` commented out; the publish-only key stands in."""
    cs_dir = tmp_path / "course_settings"
    cs_dir.mkdir()
    (cs_dir / "course_settings.toml").write_text(
        'title_for_publish_to_website = "Intro to CS"\n'
        '# title = "IT-CS142 OL1 6563 - SU26"\n'
    )
    assert publish.load_site_name(tmp_path) == "Intro to CS"


def test_load_site_name_prefers_title_over_publish_title(tmp_path):
    """Uncommenting `title` makes it win over the publish-only fallback."""
    cs_dir = tmp_path / "course_settings"
    cs_dir.mkdir()
    (cs_dir / "course_settings.toml").write_text(
        'title = "Uncommented Title"\n'
        'title_for_publish_to_website = "Stale Import Title"\n'
    )
    assert publish.load_site_name(tmp_path) == "Uncommented Title"


# ---------------------------------------------------------------------------
# Content discovery
# ---------------------------------------------------------------------------

def test_discover_published_fixture():
    published = publish.discover_published(FIXTURES)
    assert "Assignments" in published
    assert "Discussions" in published
    assert "Modules" in published
    assert "Pages" in published
    assert "Quizzes" not in published

    assert ("Week 1 Problem Set", "assignments/week1.md") in published["Assignments"]
    assert ("Introduce Yourself", "discussions/week1-intro.md") in published["Discussions"]
    assert ("Week 1: Introduction", "modules/week-1.md") in published["Modules"]
    assert ("Syllabus", "pages/syllabus.md") in published["Pages"]


def test_discover_published_skips_unpublished(tmp_path):
    (tmp_path / "pages").mkdir()
    (tmp_path / "pages" / "draft.md").write_text(
        "---\ntitle: Draft\npublished: false\n---\nDraft content\n"
    )
    (tmp_path / "pages" / "live.md").write_text(
        "---\ntitle: Live\npublished: true\n---\nLive content\n"
    )
    published = publish.discover_published(tmp_path)
    titles = [t for t, _ in published.get("Pages", [])]
    assert "Live" in titles
    assert "Draft" not in titles


def test_find_syllabus_fixture():
    result = publish._find_syllabus(FIXTURES)
    assert result == ("Syllabus", "pages/syllabus.md")


def test_find_syllabus_in_course_settings(tmp_path):
    cs = tmp_path / "course_settings"
    cs.mkdir()
    (cs / "syllabus.md").write_text(
        "---\ntitle: Course Syllabus\npublished: true\n---\nContent\n"
    )
    result = publish._find_syllabus(tmp_path)
    assert result == ("Course Syllabus", "course_settings/syllabus.md")


def test_find_syllabus_missing(tmp_path):
    assert publish._find_syllabus(tmp_path) is None


# ---------------------------------------------------------------------------
# Reachability
# ---------------------------------------------------------------------------

def test_extract_local_refs(tmp_path):
    page = tmp_path / "pages" / "a.md"
    (tmp_path / "pages").mkdir()
    (tmp_path / "pages" / "b.md").write_text("other")
    (tmp_path / "assets" / "img.png").parent.mkdir(parents=True)
    (tmp_path / "assets" / "img.png").write_text("")
    page.write_text("See [B](b.md) and ![img](../assets/img.png)\n")
    refs = publish.extract_local_refs(page.read_text(), page, tmp_path)
    assert "pages/b.md" in refs
    assert "assets/img.png" in refs


def test_extract_local_refs_skips_external():
    from pathlib import Path
    text = "[link](https://example.com) and [anchor](#top)"
    refs = publish.extract_local_refs(text, Path("/fake/file.md"), Path("/fake"))
    assert len(refs) == 0


def test_collect_reachable_excludes_quizzes(tmp_path):
    (tmp_path / "modules").mkdir()
    (tmp_path / "modules" / "m.md").write_text(
        "---\ntitle: M\npublished: true\n---\n"
        "- [Quiz](../quizzes/q/q.md)\n"
        "- [Page](../pages/p.md)\n"
    )
    (tmp_path / "quizzes" / "q").mkdir(parents=True)
    (tmp_path / "quizzes" / "q" / "q.md").write_text(
        "---\ntitle: Q\npublished: true\n---\nQuiz\n"
    )
    (tmp_path / "pages").mkdir()
    (tmp_path / "pages" / "p.md").write_text(
        "---\ntitle: P\npublished: true\n---\nPage\n"
    )
    reachable = publish.collect_reachable(tmp_path, {"modules/m.md"})
    assert "modules/m.md" in reachable
    assert "pages/p.md" in reachable
    assert "quizzes/q/q.md" not in reachable


def test_collect_reachable_follows_chains(tmp_path):
    (tmp_path / "pages").mkdir()
    (tmp_path / "pages" / "a.md").write_text(
        "---\ntitle: A\n---\nSee [B](b.md)\n"
    )
    (tmp_path / "pages" / "b.md").write_text(
        "---\ntitle: B\n---\nSee [C](c.md)\n"
    )
    (tmp_path / "pages" / "c.md").write_text(
        "---\ntitle: C\n---\nEnd\n"
    )
    reachable = publish.collect_reachable(tmp_path, {"pages/a.md"})
    assert reachable == {"pages/a.md", "pages/b.md", "pages/c.md"}


# ---------------------------------------------------------------------------
# Navigation
# ---------------------------------------------------------------------------

def test_build_nav_syllabus_assignments_modules():
    nav = publish.build_nav(FIXTURES)

    assert nav[0] == {"Home": "index.md"}
    assert nav[1] == {"Syllabus": [{"Syllabus": "pages/syllabus.md"}]}

    labels = [list(entry.keys())[0] for entry in nav[2:]]
    assert "Assignments" in labels
    assert "Modules" in labels
    assert "Discussions" not in labels
    assert "Pages" not in labels
    assert "Quizzes" not in labels

    # Assignments section contains the published assignment.
    assignments = next(entry for entry in nav if "Assignments" in entry)
    assert {"Week 1 Problem Set": "assignments/week1.md"} in assignments["Assignments"]

    # Modules section lists the module overview page.
    modules = next(entry for entry in nav if "Modules" in entry)
    assert {"Week 1: Introduction": "modules/week-1.md"} in modules["Modules"]


def test_build_nav_skips_unpublished(tmp_path):
    (tmp_path / "pages").mkdir()
    (tmp_path / "pages" / "draft.md").write_text(
        "---\ntitle: Draft\npublished: false\n---\nContent\n"
    )
    nav = publish.build_nav(tmp_path)
    assert len(nav) == 1  # only Home


# ---------------------------------------------------------------------------
# Content staging
# ---------------------------------------------------------------------------

def test_stage_content_strips_frontmatter_and_keeps_existing_h1():
    md = publish.stage_content_markdown(FIXTURES / "pages" / "syllabus.md", FIXTURES)
    assert not md.startswith("---")
    assert "# Course Syllabus" in md
    # Snippet include is expanded inline (link text discarded).
    assert "office-hours.md" not in md
    # Cross-link to the assignment is preserved as a Markdown link.
    assert "../assignments/week1.md" in md


def test_stage_content_prepends_h1_when_missing():
    md = publish.stage_content_markdown(FIXTURES / "discussions" / "week1-intro.md", FIXTURES)
    assert md.startswith("# Introduce Yourself")


def test_stage_content_strips_frontmatter_snippet_marker(tmp_path):
    (tmp_path / "snippets").mkdir()
    (tmp_path / "snippets" / "defaults.md").write_text(
        "due_at: 2026-01-01\npoints_possible: 10\n"
    )
    (tmp_path / "assignments").mkdir()
    assignment = tmp_path / "assignments" / "hw1.md"
    assignment.write_text(
        "---\ntitle: HW1\npublished: true\n---\n"
        "[PASTE_SNIPPET_INTO_FRONTMATTER](../snippets/defaults.md)\n\n"
        "Do the thing.\n"
    )
    md = publish.stage_content_markdown(assignment, tmp_path)
    assert "due_at" not in md
    assert "points_possible" not in md
    assert md == "# HW1\n\nDo the thing.\n"


def test_stage_content_rewrites_quiz_links(tmp_path):
    (tmp_path / "snippets").mkdir()
    page = tmp_path / "page.md"
    page.write_text("---\ntitle: P\n---\n\nSee [the quiz](../quizzes/a-quiz/a-quiz.md).\n")
    md = publish.stage_content_markdown(page, tmp_path)
    assert "../quiz-not-published.md" in md
    assert "a-quiz/a-quiz.md" not in md


# ---------------------------------------------------------------------------
# Pandoc syntax normalisation
# ---------------------------------------------------------------------------

def test_strip_pandoc_attrs_heading():
    text = '## What is this? {#what-is-this heading="Overview of course"}\n'
    result = publish._strip_pandoc_syntax(text)
    assert result == "## What is this? \n"


def test_strip_pandoc_attrs_image():
    text = '![alt](img.png){#239821515 role="presentation" width="776" height="284"}\n'
    result = publish._strip_pandoc_syntax(text)
    assert result == "![alt](img.png)\n"


def test_strip_pandoc_attrs_link_target():
    text = '[Click here](https://example.com){.external target="_blank"}\n'
    result = publish._strip_pandoc_syntax(text)
    assert result == "[Click here](https://example.com)\n"


def test_strip_pandoc_attrs_span():
    text = '[bold text]{style="background-color: #fff500;"}\n'
    result = publish._strip_pandoc_syntax(text)
    assert result == "bold text\n"


def test_strip_pandoc_span_with_nested_link():
    text = (
        '[Please [watch the video here]'
        '(https://example.com/video))]{style="font-size: 18pt;"}\n'
    )
    result = publish._strip_pandoc_syntax(text)
    assert result == "Please [watch the video here](https://example.com/video))\n"


def test_strip_pandoc_attrs_preserves_code_fences():
    text = '```\n{#id .class key="val"}\n```\n'
    result = publish._strip_pandoc_syntax(text)
    assert result == text


def test_strip_pandoc_attrs_ignores_plain_braces():
    text = "x = {1, 2, 3}\n"
    result = publish._strip_pandoc_syntax(text)
    assert result == text


def test_strip_pandoc_attrs_raw_html_block():
    text = "before\n\n```{=html}\n<!-- comment -->\n```\n\nafter\n"
    result = publish._strip_pandoc_syntax(text)
    assert "```" not in result
    assert "<!-- comment -->" in result
    assert "before" in result
    assert "after" in result


def test_strip_pandoc_escapes_apostrophe():
    result = publish._strip_pandoc_syntax("you\\'ll need this\n")
    assert result == "you'll need this\n"


def test_strip_pandoc_escapes_double_quote():
    result = publish._strip_pandoc_syntax('mentions of \\"hybrid format\\"\n')
    assert result == 'mentions of "hybrid format"\n'


def test_strip_pandoc_trailing_backslash():
    result = publish._strip_pandoc_syntax("end of line\\\nmore text\n")
    assert result == "end of line  \nmore text\n"


def test_strip_pandoc_trailing_backslash_with_spaces():
    result = publish._strip_pandoc_syntax("end of line\\  \nmore text\n")
    assert result == "end of line  \nmore text\n"


def test_strip_pandoc_escapes_preserved_in_code_fence():
    text = "```\nyou\\'ll see \\\" here\\\n```\n"
    result = publish._strip_pandoc_syntax(text)
    assert result == text


# ---------------------------------------------------------------------------
# Quiz study guide
# ---------------------------------------------------------------------------

def test_render_quiz_study_guide():
    guide = publish.render_quiz_study_guide(FIXTURES / "quizzes" / "a-quiz")
    assert guide.startswith("# A Quiz")
    assert "Answer each question carefully." in guide
    assert "## Question 1: What is 2+2?" in guide
    # MCQ choices listed; the correct one (index 2 → "4") is marked.
    assert "- 4 **(correct)**" in guide
    assert "- 3\n" in guide
    # Essay question has a prompt but no answer choices.
    assert "## Question 2: Explain something" in guide


# ---------------------------------------------------------------------------
# Module overview page
# ---------------------------------------------------------------------------

def test_render_module_overview():
    md = publish.render_module_overview(FIXTURES / "modules" / "week-1.md", FIXTURES)
    assert md.startswith("# Week 1: Introduction")
    assert "## Readings" in md
    assert "## Work" in md
    assert "<ul>" in md
    assert "</ul>" in md
    # Non-indented item has no style attribute.
    assert '<li><a href="../pages/syllabus.md">Syllabus</a></li>' in md
    # Indented items under "Work" get margin-left styling.
    assert '<li style="margin-left: 2em"><a href="../assignments/week1.md">Week 1 Assignment</a></li>' in md
    assert '<li style="margin-left: 2em"><a href="../discussions/week1-intro.md">Week 1 Discussion</a></li>' in md


def test_render_module_overview_redirects_quiz_links(tmp_path):
    """Quiz items in a module overview link to the not-published placeholder."""
    mod = tmp_path / "modules" / "m.md"
    mod.parent.mkdir(parents=True)
    (tmp_path / "quizzes" / "q").mkdir(parents=True)
    (tmp_path / "quizzes" / "q" / "q.md").write_text(
        "---\ntitle: Q\npublished: true\n---\nQuiz\n"
    )
    (tmp_path / "pages").mkdir()
    (tmp_path / "pages" / "p.md").write_text("---\ntitle: P\npublished: true\n---\nPage\n")
    mod.write_text(
        "---\ntitle: Test\npublished: true\n---\n"
        "- [My Quiz](../quizzes/q/q.md)\n"
        "- [My Page](../pages/p.md)\n"
    )
    html = publish.render_module_overview(mod, tmp_path)
    assert "../../quiz-not-published/" in html
    assert "quizzes/q" not in html
    assert '<a href="../pages/p.md">My Page</a>' in html


def test_render_module_overview_indentation(tmp_path):
    """render_module_overview renders multi-level indentation as HTML with margin-left."""
    mod = tmp_path / "modules" / "m.md"
    mod.parent.mkdir(parents=True)
    (tmp_path / "pages").mkdir()
    mod.write_text(
        "---\ntitle: Indented Module\n---\n\n"
        "## Section\n"
        "- [Top](../pages/a.md)\n"
        "  - [One](../pages/b.md)\n"
        "    - [Two](../pages/c.md)\n"
    )
    md = publish.render_module_overview(mod, tmp_path)
    assert '<li><a href="../pages/a.md">Top</a></li>' in md
    assert '<li style="margin-left: 2em"><a href="../pages/b.md">One</a></li>' in md
    assert '<li style="margin-left: 4em"><a href="../pages/c.md">Two</a></li>' in md


# ---------------------------------------------------------------------------
# mkdocs.yml
# ---------------------------------------------------------------------------

def test_render_mkdocs_yml_roundtrips():
    nav = publish.build_nav(FIXTURES)
    text = publish.render_mkdocs_yml("My Course", nav)
    parsed = yaml.safe_load(text)
    assert parsed["site_name"] == "My Course"
    assert parsed["theme"]["name"] == "material"
    assert parsed["theme"]["custom_dir"] == "overrides"
    assert "navigation.indexes" in parsed["theme"]["features"]
    assert parsed["extra_css"] == ["stylesheets/extra.css"]
    assert parsed["nav"][0] == {"Home": "index.md"}


# ---------------------------------------------------------------------------
# Full staging tree
# ---------------------------------------------------------------------------

def test_stage_writes_full_tree(tmp_path):
    info = publish.stage(FIXTURES, tmp_path)

    assert (tmp_path / "mkdocs.yml").exists()
    assert (tmp_path / "overrides" / "main.html").exists()
    assert (tmp_path / "docs" / "index.md").exists()
    assert (tmp_path / "docs" / "stylesheets" / "extra.css").exists()
    assert (tmp_path / "docs" / "assets" / "images" / "fig.png").exists()
    # Nav seeds (syllabus, assignments, modules) are staged.
    assert (tmp_path / "docs" / "modules" / "week-1.md").exists()
    assert (tmp_path / "docs" / "pages" / "syllabus.md").exists()
    assert (tmp_path / "docs" / "assignments" / "week1.md").exists()
    # Discussion is reachable from the module → staged but not in nav.
    assert (tmp_path / "docs" / "discussions" / "week1-intro.md").exists()
    assert not (tmp_path / "docs" / "quizzes").exists()
    # Placeholder page for quiz links exists.
    assert (tmp_path / "docs" / "quiz-not-published.md").exists()

    assert info["site_name"] == FIXTURES.name
    assert info["module_count"] == 1
    assert set(info["staged_files"]) == {
        "assets/images/fig.png",
        "assignments/week1.md",
        "discussions/week1-intro.md",
        "modules/week-1.md",
        "pages/syllabus.md",
    }


def test_stage_excludes_unreachable_content(tmp_path):
    repo = tmp_path / "repo"
    (repo / "pages").mkdir(parents=True)
    (repo / "pages" / "private-notes.md").write_text(
        "---\ntitle: Private Notes\npublished: true\n---\nSecret\n"
    )
    (repo / "pages" / "syllabus.md").write_text(
        "---\ntitle: Syllabus\npublished: true\n---\nWelcome\n"
    )
    staging = tmp_path / "staging"
    info = publish.stage(repo, staging)
    assert "pages/syllabus.md" in info["staged_files"]
    assert "pages/private-notes.md" not in info["staged_files"]
    assert not (staging / "docs" / "pages" / "private-notes.md").exists()


# ---------------------------------------------------------------------------
# emit_workflow
# ---------------------------------------------------------------------------

def test_emit_workflow(tmp_path):
    dest = publish.emit_workflow(tmp_path)
    assert dest == tmp_path / ".github" / "workflows" / "publish.yml"
    text = dest.read_text()
    assert "actions/deploy-pages@v4" in text
    assert "actions/upload-pages-artifact@v3" in text
    assert "markdown-to-canvas publish ." in text
    assert "--deploy" not in text


# ---------------------------------------------------------------------------
# run_publish (mkdocs subprocess mocked)
# ---------------------------------------------------------------------------

def test_run_publish_build(tmp_path, monkeypatch):
    staging = tmp_path / "staging"
    monkeypatch.setattr(publish.tempfile, "mkdtemp", lambda prefix="": str(staging))
    # Pretend mkdocs is importable so the up-front availability check passes even
    # when the dev env has no mkdocs installed.
    monkeypatch.setattr(publish.importlib.util, "find_spec", lambda name: object())
    calls = []

    def fake_run(cmd, **kw):
        # run_publish cleans up the staging dir afterward, so assert the staged
        # mkdocs.yml exists at the moment mkdocs would actually run.
        assert (staging / "mkdocs.yml").exists()
        calls.append((cmd, kw))

    monkeypatch.setattr(publish.subprocess, "run", fake_run)

    out = tmp_path / "site"
    publish.run_publish(FIXTURES, out)

    assert not staging.exists()  # staging dir is cleaned up after the run
    (cmd, kw), = calls
    assert cmd[:3] == [sys.executable, "-m", "mkdocs"]
    assert cmd[3] == "build"
    assert "--site-dir" in cmd
    assert str(out.resolve()) in cmd
    assert kw["cwd"] == str(FIXTURES.resolve())


def test_run_publish_missing_mkdocs_raises(tmp_path, monkeypatch):
    monkeypatch.setattr(publish.tempfile, "mkdtemp", lambda prefix="": str(tmp_path / "s"))

    def _boom(*a, **k):
        raise FileNotFoundError("mkdocs")

    monkeypatch.setattr(publish.subprocess, "run", _boom)
    import pytest
    with pytest.raises(ValueError, match="mkdocs is not installed"):
        publish.run_publish(FIXTURES, tmp_path / "site")


# ---------------------------------------------------------------------------
# Unpublished module items
# ---------------------------------------------------------------------------


def test_collect_reachable_skips_unpublished_items(tmp_path):
    """Unpublished module items are not followed into the reachable set."""
    (tmp_path / "modules").mkdir()
    (tmp_path / "modules" / "m.md").write_text(
        "---\ntitle: M\npublished: true\n---\n"
        "- [Visible](../pages/vis.md)\n"
        '- [Hidden](../pages/hid.md) <!-- published="false" -->\n'
    )
    (tmp_path / "pages").mkdir()
    (tmp_path / "pages" / "vis.md").write_text("---\ntitle: V\npublished: true\n---\nV\n")
    (tmp_path / "pages" / "hid.md").write_text("---\ntitle: H\n---\nH\n")
    reachable = publish.collect_reachable(tmp_path, {"modules/m.md"})
    assert "pages/vis.md" in reachable
    assert "pages/hid.md" not in reachable


def test_collect_reachable_skips_unpublished_asset(tmp_path):
    """An asset linked only from an unpublished module item is not reachable."""
    (tmp_path / "modules").mkdir()
    (tmp_path / "modules" / "m.md").write_text(
        "---\ntitle: M\npublished: true\n---\n"
        "- [Visible](../pages/vis.md)\n"
        '- [Solutions](../assets/solutions.docx) <!-- published="false" -->\n'
    )
    (tmp_path / "pages").mkdir()
    (tmp_path / "pages" / "vis.md").write_text("---\ntitle: V\npublished: true\n---\nV\n")
    (tmp_path / "assets").mkdir()
    (tmp_path / "assets" / "solutions.docx").write_bytes(b"fake")
    reachable = publish.collect_reachable(tmp_path, {"modules/m.md"})
    assert "pages/vis.md" in reachable
    assert "assets/solutions.docx" not in reachable


def test_stage_excludes_unpublished_asset(tmp_path):
    """Assets linked only from unpublished module items are not staged."""
    repo = tmp_path / "repo"
    (repo / "modules").mkdir(parents=True)
    (repo / "modules" / "m.md").write_text(
        "---\ntitle: M\npublished: true\n---\n"
        '- [Solutions](../assets/solutions.docx) <!-- published="false" -->\n'
    )
    (repo / "assets").mkdir()
    (repo / "assets" / "solutions.docx").write_bytes(b"fake")
    staging = tmp_path / "staging"
    publish.stage(repo, staging)
    assert not (staging / "docs" / "assets" / "solutions.docx").exists()


def test_render_module_overview_omits_unpublished(tmp_path):
    """render_module_overview does not include unpublished items in HTML output."""
    (tmp_path / "modules").mkdir()
    mod = tmp_path / "modules" / "m.md"
    mod.write_text(
        "---\ntitle: Test\npublished: true\n---\n"
        "- [Shown](../pages/a.md)\n"
        '- [Hidden](../pages/b.md) <!-- published="false" -->\n'
    )
    html = publish.render_module_overview(mod, tmp_path)
    assert "Shown" in html
    assert "Hidden" not in html


# ---------------------------------------------------------------------------
# Subfolder support in publish discovery
# ---------------------------------------------------------------------------


def test_discover_published_finds_pages_in_subfolders(tmp_path):
    """discover_published picks up .md files nested in subdirectories."""
    (tmp_path / "pages" / "week1").mkdir(parents=True)
    (tmp_path / "pages" / "week1" / "notes.md").write_text(
        "---\ntitle: Week 1 Notes\npublished: true\n---\nContent\n"
    )
    (tmp_path / "pages" / "overview.md").write_text(
        "---\ntitle: Overview\npublished: true\n---\nContent\n"
    )
    published = publish.discover_published(tmp_path)
    titles = [t for t, _ in published.get("Pages", [])]
    assert "Overview" in titles
    assert "Week 1 Notes" in titles


def test_discover_published_subfolder_paths_are_repo_relative(tmp_path):
    """Paths returned for subfolder files include the subfolder."""
    (tmp_path / "assignments" / "unit1").mkdir(parents=True)
    (tmp_path / "assignments" / "unit1" / "hw.md").write_text(
        "---\ntitle: HW\npublished: true\n---\nBody\n"
    )
    published = publish.discover_published(tmp_path)
    paths = [p for _, p in published.get("Assignments", [])]
    assert "assignments/unit1/hw.md" in paths


def test_discover_type_finds_subfolders(tmp_path):
    """_discover_type recursively finds published content in subfolders."""
    (tmp_path / "discussions" / "week1").mkdir(parents=True)
    (tmp_path / "discussions" / "week1" / "forum.md").write_text(
        "---\ntitle: Week 1 Forum\npublished: true\n---\nDiscuss.\n"
    )
    items = publish._discover_type(tmp_path, "discussions")
    titles = [t for t, _ in items]
    assert "Week 1 Forum" in titles
    paths = [p for _, p in items]
    assert "discussions/week1/forum.md" in paths


def test_find_syllabus_in_subfolder(tmp_path):
    """_find_syllabus finds a syllabus page inside a pages/ subfolder."""
    (tmp_path / "pages" / "admin").mkdir(parents=True)
    (tmp_path / "pages" / "admin" / "syllabus.md").write_text(
        "---\ntitle: Course Syllabus\npublished: true\n---\nContent\n"
    )
    result = publish._find_syllabus(tmp_path)
    assert result is not None
    title, path = result
    assert title == "Course Syllabus"
    assert path == "pages/admin/syllabus.md"


def test_extract_local_refs_awkward_link_shapes(tmp_path):
    page = tmp_path / "pages" / "a.md"
    (tmp_path / "pages").mkdir()
    (tmp_path / "assets" / "F (L)").mkdir(parents=True)
    (tmp_path / "assets" / "F (L)" / "x.java").write_text("")
    (tmp_path / "assets" / "a b.txt").write_text("")
    (tmp_path / "assets" / "plain.txt").write_text("")
    cases = {
        '[x](../assets/F%20(L)/x.java "t")': "assets/F (L)/x.java",
        "[x](<../assets/a b.txt>)": "assets/a b.txt",
        "[x](../assets/a%20b.txt)": "assets/a b.txt",
        '- [[**[x]**]{s=1}](../assets/plain.txt "t")': "assets/plain.txt",
        '[x](../assets/plain.txt "File(s)")': "assets/plain.txt",
    }
    for text, expected in cases.items():
        assert publish.extract_local_refs(text, page, tmp_path) == {expected}, text


# ---------------------------------------------------------------------------
# Links inside snippets
# ---------------------------------------------------------------------------


def _snippet_repo(tmp_path, snippet_text):
    repo = tmp_path / "repo"
    (repo / "course_settings").mkdir(parents=True)
    (repo / "course_settings" / "course_settings.toml").write_text(
        "[course_flags]\nhybrid = false\n"
    )
    (repo / "assets").mkdir()
    (repo / "assets" / "diagram.png").write_bytes(b"png")
    (repo / "snippets").mkdir()
    (repo / "snippets" / "policy.md").write_text(snippet_text)
    (repo / "pages" / "week1").mkdir(parents=True)
    (repo / "pages" / "week1" / "deep.md").write_text(
        "---\ntitle: Deep\npublished: true\n---\n\n[x](../../snippets/policy.md)\n"
    )
    return repo


def test_collect_reachable_follows_links_inside_snippets(tmp_path):
    repo = _snippet_repo(tmp_path, "![d](../assets/diagram.png)\n")
    reachable = publish.collect_reachable(repo, {"pages/week1/deep.md"})
    assert "assets/diagram.png" in reachable
    assert not any(r.startswith("snippets/") for r in reachable)


def test_collect_reachable_skips_snippet_link_in_false_branch(tmp_path):
    repo = _snippet_repo(
        tmp_path,
        "<!-- #if hybrid -->\n![d](../assets/diagram.png)\n<!-- #endif -->\n",
    )
    reachable = publish.collect_reachable(
        repo, {"pages/week1/deep.md"}, flags={"hybrid": False}
    )
    assert "assets/diagram.png" not in reachable


def _snippet_assignment_repo(tmp_path, snippet_text):
    """Assignments are nav items, so a deep assignment is staged."""
    repo = _snippet_repo(tmp_path, snippet_text)
    (repo / "assignments" / "unit1").mkdir(parents=True)
    (repo / "assignments" / "unit1" / "hw.md").write_text(
        "---\ntitle: HW\npublished: true\n---\n\n[x](../../snippets/policy.md)\n"
    )
    return repo


def test_stage_asset_linked_only_from_snippet(tmp_path):
    repo = _snippet_assignment_repo(tmp_path, "![d](../assets/diagram.png)\n")
    staging = tmp_path / "staging"
    info = publish.stage(repo, staging)
    assert info["errors"] == []
    assert "assets/diagram.png" in info["staged_files"]
    staged_hw = staging / "docs" / "assignments" / "unit1" / "hw.md"
    assert "![d](../../assets/diagram.png)" in staged_hw.read_text()
    assert (staged_hw.parent / "../../assets/diagram.png").resolve().exists()


def test_run_publish_stops_on_snippet_link_outside_repo(tmp_path, monkeypatch):
    import pytest

    from tests.conftest import make_current

    repo = _snippet_assignment_repo(tmp_path, "![d](../../assets/diagram.png)\n")
    make_current(repo)
    monkeypatch.setattr(publish.importlib.util, "find_spec", lambda name: object())
    ran = []
    monkeypatch.setattr(publish.subprocess, "run", lambda *a, **k: ran.append(a))
    with pytest.raises(ValueError, match="error"):
        publish.run_publish(repo, tmp_path / "site")
    assert ran == []


# ---------------------------------------------------------------------------
# Broken local links (same rules as update's link rewriting)
# ---------------------------------------------------------------------------


def _assignment_repo(tmp_path, body):
    repo = tmp_path / "repo"
    (repo / "assets").mkdir(parents=True)
    (repo / "assets" / "pic.png").write_bytes(b"png")
    (repo / "pages").mkdir()
    (repo / "pages" / "other.md").write_text("---\ntitle: Other\npublished: true\n---\n\nx\n")
    (repo / "assignments").mkdir()
    (repo / "assignments" / "hw.md").write_text(
        f"---\ntitle: HW\npublished: true\n---\n\n{body}\n"
    )
    return repo


def test_stage_reports_link_escaping_repo(tmp_path):
    repo = _assignment_repo(tmp_path, "![](../../assets/pic.png)")
    info = publish.stage(repo, tmp_path / "staging")
    assert info["errors"] == [
        "  assignments/hw.md: relative path resolves outside the course repo "
        "(check the number of ../ segments): ../../assets/pic.png"
    ]


def test_stage_reports_missing_local_file(tmp_path):
    repo = _assignment_repo(tmp_path, "[gone](../pages/gone.md)")
    info = publish.stage(repo, tmp_path / "staging")
    assert info["errors"] == [
        "  assignments/hw.md: local file not found: pages/gone.md"
    ]


def test_stage_accepts_valid_and_non_local_links(tmp_path):
    repo = _assignment_repo(
        tmp_path,
        "![](../assets/pic.png) [o](../pages/other.md#part-2) "
        "[w](https://example.com) [t](tel:+15555550100) [a](#top) "
        "[c](/courses/1/files/2) `a[i](j)`\n\n```\n[x](../../nowhere.md)\n```",
    )
    info = publish.stage(repo, tmp_path / "staging")
    assert info["errors"] == []


def test_run_publish_stops_on_link_escaping_repo(tmp_path, monkeypatch):
    import pytest

    from tests.conftest import make_current

    repo = _assignment_repo(tmp_path, "![](../../assets/pic.png)")
    make_current(repo)
    monkeypatch.setattr(publish.importlib.util, "find_spec", lambda name: object())
    ran = []
    monkeypatch.setattr(publish.subprocess, "run", lambda *a, **k: ran.append(a))
    with pytest.raises(ValueError, match="error"):
        publish.run_publish(repo, tmp_path / "site")
    assert ran == []


def test_stage_content_renders_a_group_discussion_like_any_other(tmp_path):
    (tmp_path / "discussions").mkdir()
    discussion = tmp_path / "discussions" / "team.md"
    discussion.write_text(
        '---\ntitle: Team\npublished: true\ngroup_category_id: "Project Groups"\n---\n\nPlan.\n'
    )
    assert publish.stage_content_markdown(discussion, tmp_path) == "# Team\n\nPlan.\n"


# ---------------------------------------------------------------------------
# CANVAS_COURSE_REFERENCE: the config's course_id completes the URL
# ---------------------------------------------------------------------------

def _course_reference_repo(tmp_path):
    repo = _assignment_repo(
        tmp_path, "[Grades]($../snippets/inline/CANVAS_COURSE_REFERENCE.md$/grades)"
    )
    ref = repo / "snippets" / "inline" / "CANVAS_COURSE_REFERENCE.md"
    ref.parent.mkdir(parents=True)
    ref.write_text("https://school.instructure.com/courses/\n<!-- note -->\n")
    return repo


def test_stage_appends_the_config_course_id(tmp_path, capsys):
    from markdown_to_canvas.config import Config

    repo = _course_reference_repo(tmp_path)
    cfg = Config(base_url="", course_id=31337, api_token="")
    publish.stage(repo, tmp_path / "staging", cfg)
    staged = (tmp_path / "staging" / "docs" / "assignments" / "hw.md").read_text()
    assert "https://school.instructure.com/courses/31337/grades" in staged
    assert "no course_id" not in capsys.readouterr().out


def test_stage_without_course_id_warns(tmp_path, capsys):
    repo = _course_reference_repo(tmp_path)
    publish.stage(repo, tmp_path / "staging")
    assert "WARNING: no course_id" in capsys.readouterr().out


# ---------------------------------------------------------------------------
# Date placeholders
# ---------------------------------------------------------------------------

_DUE_SETTINGS = (
    'due_dates = [\n'
    '    {name = "HW", due_at = "2026-10-27T23:59:00-07:00"},\n'
    '    {name = "Online", due_at = "2026-11-03T23:59:00-08:00", only_if = "online"},\n'
    ']\n\n[course_flags]\nonline = false\n'
)


def _dated_repo(tmp_path, body):
    repo = _assignment_repo(tmp_path, body)
    (repo / "course_settings").mkdir()
    (repo / "course_settings" / "course_settings.toml").write_text(_DUE_SETTINGS)
    return repo


def test_stage_replaces_date_placeholders(tmp_path):
    repo = _dated_repo(
        tmp_path,
        '[**Due [x]{.replace_date_with}**]{style="color: red"} and '
        '[y]{.replace_date_with item="HW" format="%b %-d"}',
    )
    staging = tmp_path / "staging"
    info = publish.stage(repo, staging)
    assert info["errors"] == []
    text = (staging / "docs" / "assignments" / "hw.md").read_text()
    assert "**Due Tuesday, October 27 by 11:59 PM** and Oct 27" in text
    assert "replace_date_with" not in text


def test_stage_quotes_a_virtual_entry(tmp_path):
    repo = _dated_repo(
        tmp_path, 'Week 3 begins [x]{.replace_date_with item="Start_of_week_3" format="%A, %B %-d"}.'
    )
    settings = repo / "course_settings" / "course_settings.toml"
    settings.write_text(settings.read_text().replace(
        "due_dates = [\n",
        'due_dates = [\n    {name = "Start_of_week_3", virtual = true, '
        'due_at = "2026-10-12T23:59:00-07:00"},\n',
    ))
    staging = tmp_path / "staging"
    info = publish.stage(repo, staging)
    assert info["errors"] == []
    text = (staging / "docs" / "assignments" / "hw.md").read_text()
    assert "Week 3 begins Monday, October 12." in text


def test_stage_reports_unresolved_date_placeholder(tmp_path):
    repo = _dated_repo(tmp_path, '[x]{.replace_date_with item="Online"}')
    info = publish.stage(repo, tmp_path / "staging")
    assert len(info["errors"]) == 1
    assert "assignments/hw.md" in info["errors"][0]
    assert "no due_dates entry named 'Online'" in info["errors"][0]


def _dated_module(repo, heading):
    (repo / "modules").mkdir()
    (repo / "modules" / "week-1.md").write_text(
        f"---\ntitle: Week 1\npublished: true\n---\n## {heading}\n\n"
        "- [HW](../assignments/hw.md)\n"
    )


def test_stage_replaces_date_placeholders_in_module_overview(tmp_path):
    repo = _dated_repo(tmp_path, "Body")
    _dated_module(repo, 'Week 1: [x]{.replace_date_with item="HW" format="%A_%b %-d"}')
    staging = tmp_path / "staging"
    info = publish.stage(repo, staging)
    assert info["errors"] == []
    text = (staging / "docs" / publish.staged_path("modules/week-1.md")).read_text()
    assert "## Week 1: Tuesday_Oct 27\n" in text
    assert "replace_date_with" not in text


def test_stage_reports_unresolved_date_placeholder_in_module(tmp_path):
    repo = _dated_repo(tmp_path, "Body")
    _dated_module(repo, 'Week 1: [x]{.replace_date_with item="Online"}')
    info = publish.stage(repo, tmp_path / "staging")
    assert len(info["errors"]) == 1
    assert "modules/week-1.md" in info["errors"][0]
    assert "no due_dates entry named 'Online'" in info["errors"][0]


def test_run_publish_stops_on_unresolved_date_placeholder(tmp_path, monkeypatch):
    import pytest

    from tests.conftest import make_current

    repo = _dated_repo(tmp_path, '[x]{.replace_date_with item="Nope"}')
    make_current(repo)
    monkeypatch.setattr(publish.importlib.util, "find_spec", lambda name: object())
    ran = []
    monkeypatch.setattr(publish.subprocess, "run", lambda *a, **k: ran.append(a))
    with pytest.raises(ValueError, match="error"):
        publish.run_publish(repo, tmp_path / "site")
    assert ran == []
    assert not (tmp_path / "site").exists()
