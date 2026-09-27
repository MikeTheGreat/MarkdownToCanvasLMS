"""Group sets/group categories: Canvas calls, update, --check-all, targeted sync."""
from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from markdown_to_canvas import canvas_api as capi


def _category(name: str, cid: int) -> SimpleNamespace:
    return SimpleNamespace(name=name, id=cid)


# ---------------------------------------------------------------------------
# canvas_api: listing and creating
# ---------------------------------------------------------------------------


def test_get_group_category_ids_maps_trimmed_names_to_ids() -> None:
    course = MagicMock()
    course.get_group_categories.return_value = [
        _category("Project Groups ", 812), _category("Study Buddies", 813),
    ]
    assert capi.get_group_category_ids(course) == {
        "Project Groups": [812], "Study Buddies": [813],
    }


def test_get_group_category_ids_keeps_every_id_of_a_duplicate_name() -> None:
    course = MagicMock()
    course.get_group_categories.return_value = [
        _category("Project Groups", 812), _category("Project Groups", 900),
    ]
    assert capi.get_group_category_ids(course) == {"Project Groups": [812, 900]}


def test_create_group_category_returns_the_new_id() -> None:
    course = MagicMock()
    course.create_group_category.return_value = _category("Project Groups", 812)
    assert capi.create_group_category(course, "Project Groups") == 812
    course.create_group_category.assert_called_once_with("Project Groups")


# ---------------------------------------------------------------------------
# canvas_api: the change safeguard on existing items
# ---------------------------------------------------------------------------


def _topic(group_category_id=None, subentries=0) -> MagicMock:
    topic = MagicMock()
    topic.id = 5
    topic.html_url = "https://x/discussion_topics/5"
    topic.group_category_id = group_category_id
    topic.discussion_subentry_count = subentries
    topic.update.return_value = topic
    return topic


def _assignment(group_category_id=None, submitted=False) -> MagicMock:
    a = MagicMock()
    a.id = 7
    a.html_url = "https://x/assignments/7"
    a.group_category_id = group_category_id
    a.has_submitted_submissions = submitted
    a.rubric_settings = None
    a.edit.return_value = a
    return a


def test_discussion_unchanged_group_category_is_not_resent() -> None:
    course = MagicMock()
    topic = _topic(group_category_id=812, subentries=4)
    course.get_discussion_topic.return_value = topic
    capi.create_or_update_discussion(course, 5, "T", "<p>b</p>", group_category_id=812)
    assert "group_category_id" not in topic.update.call_args.kwargs
    assert topic.update.call_args.kwargs["message"] == "<p>b</p>"


def test_discussion_gains_group_category_when_it_has_no_replies() -> None:
    course = MagicMock()
    topic = _topic(group_category_id=None, subentries=0)
    course.get_discussion_topic.return_value = topic
    capi.create_or_update_discussion(course, 5, "T", "b", group_category_id=812)
    assert topic.update.call_args.kwargs["group_category_id"] == 812


@pytest.mark.parametrize("subentries", [3, None])
def test_discussion_with_replies_is_not_made_a_group_discussion(subentries) -> None:
    course = MagicMock()
    topic = _topic(group_category_id=None, subentries=subentries)
    if subentries is None:
        del topic.discussion_subentry_count  # Canvas left the field out
    course.get_discussion_topic.return_value = topic
    with pytest.raises(capi.GroupCategoryChangeRefused) as info:
        capi.create_or_update_discussion(course, 5, "T", "b", group_category_id=812)
    assert (info.value.what, info.value.reason) == ("discussion", "student_work")
    topic.update.assert_not_called()


def test_discussion_group_category_is_never_switched() -> None:
    course = MagicMock()
    topic = _topic(group_category_id=812, subentries=0)
    course.get_discussion_topic.return_value = topic
    with pytest.raises(capi.GroupCategoryChangeRefused) as info:
        capi.create_or_update_discussion(course, 5, "T", "b", group_category_id=900)
    assert (info.value.reason, info.value.current, info.value.wanted) == ("switch", 812, 900)
    topic.update.assert_not_called()


def test_discussion_without_group_category_is_left_alone() -> None:
    course = MagicMock()
    topic = _topic(group_category_id=812, subentries=4)
    course.get_discussion_topic.return_value = topic
    capi.create_or_update_discussion(course, 5, "T", "b")
    assert "group_category_id" not in topic.update.call_args.kwargs


def test_assignment_unchanged_group_category_is_not_resent() -> None:
    course = MagicMock()
    a = _assignment(group_category_id=812, submitted=True)
    course.get_assignment.return_value = a
    capi.create_or_update_assignment(course, 7, "A", "b", group_category_id=812)
    assert "group_category_id" not in a.edit.call_args.kwargs["assignment"]


def test_assignment_gains_group_category_without_submissions() -> None:
    course = MagicMock()
    a = _assignment(group_category_id=None, submitted=False)
    course.get_assignment.return_value = a
    capi.create_or_update_assignment(course, 7, "A", "b", group_category_id=812)
    assert a.edit.call_args.kwargs["assignment"]["group_category_id"] == 812


def test_assignment_with_submissions_is_not_made_a_group_assignment() -> None:
    course = MagicMock()
    a = _assignment(group_category_id=None, submitted=True)
    course.get_assignment.return_value = a
    with pytest.raises(capi.GroupCategoryChangeRefused, match="student work"):
        capi.create_or_update_assignment(course, 7, "A", "b", group_category_id=812)
    a.edit.assert_not_called()


def test_assignment_group_category_is_never_switched() -> None:
    course = MagicMock()
    a = _assignment(group_category_id=812)
    course.get_assignment.return_value = a
    with pytest.raises(capi.GroupCategoryChangeRefused):
        capi.create_or_update_assignment(course, 7, "A", "b", group_category_id=900)
    a.edit.assert_not_called()


def test_new_items_are_created_with_the_group_category() -> None:
    course = MagicMock()
    course.create_discussion_topic.return_value = _topic()
    course.create_assignment.return_value = _assignment()
    capi.create_or_update_discussion(course, None, "T", "b", group_category_id=812)
    capi.create_or_update_assignment(course, None, "A", "b", group_category_id=812)
    assert course.create_discussion_topic.call_args.kwargs["group_category_id"] == 812
    assert course.create_assignment.call_args.kwargs["assignment"]["group_category_id"] == 812


# ---------------------------------------------------------------------------
# update: listing, creating, resolving
# ---------------------------------------------------------------------------

import re  # noqa: E402
import shutil  # noqa: E402
import tomllib  # noqa: E402
from pathlib import Path  # noqa: E402

from markdown_to_canvas.config import Config  # noqa: E402
from markdown_to_canvas.repo_format import FORMAT_VERSION  # noqa: E402
from markdown_to_canvas.sync import (  # noqa: E402
    load_group_categories,
    run_sync,
    run_targeted_sync,
)

FIXTURES = Path(__file__).parent / "fixtures"


def _config(course_id: int = 999) -> Config:
    return Config(base_url="https://school.instructure.com", course_id=course_id, api_token="tok")


@pytest.fixture
def course_root(tmp_path: Path) -> Path:
    root = tmp_path / "course"
    shutil.copytree(FIXTURES, root, ignore=shutil.ignore_patterns(".manifest-canvas.toml"))
    return root


@pytest.fixture
def mock_course(mocker) -> MagicMock:
    mocker.patch("markdown_to_canvas.manifest.flush")
    canvas_cls = mocker.patch("markdown_to_canvas.canvas_api.Canvas")
    course = MagicMock()
    canvas_cls.return_value.get_course.return_value = course
    course.get_group_categories.return_value = []
    # What the fixture repo's other content needs on a first sync.
    page = MagicMock(page_id=99999, url="syllabus", html_url="https://x/pages/syllabus")
    page.edit.return_value = page
    course.create_page.return_value = page
    course.get_page.return_value = page
    course.upload.return_value = (True, {"id": 77777, "url": "https://x/files/77777/download"})
    course.create_quiz.return_value = MagicMock(id=4444, html_url="https://x/quizzes/4444")
    module = MagicMock(id=66666)
    module.edit.return_value = module
    module.get_module_items.return_value = []
    course.create_module.return_value = module
    course.create_discussion_topic.return_value = _topic()
    course.create_assignment.return_value = _assignment()
    created = iter(range(700, 800))
    course.create_group_category.side_effect = lambda name: _category(name, next(created))
    return course


def _settings(root: Path, names: str = '["Project Groups"]') -> None:
    (root / "course_settings" / "course_settings.toml").write_text(
        f"format_version = {FORMAT_VERSION}\ngroup_categories = {names}\n"
    )


def _discussion(root: Path, name: str = "team-plan", extra: str = 'group_category_id: "Project Groups"\n') -> str:
    path = root / "discussions" / f"{name}.md"
    path.write_text(f'---\ntitle: "{name}"\npublished: true\n{extra}---\n\nPlan it.\n')
    return f"discussions/{name}.md"


def _discussion_calls(course: MagicMock, title: str) -> list:
    return [c for c in course.create_discussion_topic.call_args_list if c.kwargs.get("title") == title]


def test_load_group_categories_reads_trimmed_names(tmp_path) -> None:
    assert load_group_categories(tmp_path, {"group_categories": [" A ", "B"]}) == ["A", "B"]
    assert load_group_categories(tmp_path, {}) == []


@pytest.mark.parametrize(
    "value, match",
    [
        ('"Project Groups"', "array"),
        ("[1]", "array"),
        ('["  "]', "empty"),
        ('["A", " A"]', "more than once"),
    ],
)
def test_bad_group_categories_stop_update_before_canvas(course_root, mock_course, value, match) -> None:
    _settings(course_root, value)
    with pytest.raises(ValueError, match=match):
        run_sync(_config(), course_root)
    assert mock_course.mock_calls == []


def test_empty_list_makes_no_group_category_request(course_root, mock_course) -> None:
    _settings(course_root, "[]")
    run_sync(_config(), course_root)
    mock_course.get_group_categories.assert_not_called()
    mock_course.create_group_category.assert_not_called()


def test_group_categories_are_not_course_metadata(course_root, mock_course) -> None:
    _settings(course_root)
    run_sync(_config(), course_root)
    assert "group_categories" not in str(mock_course.update.call_args_list)
    assert "group_categories" not in str(mock_course.update_settings.call_args_list)


def test_brand_new_course_gets_the_listed_group_categories(course_root, mock_course, capsys) -> None:
    _settings(course_root, '["Project Groups", "Study Buddies"]')
    run_sync(_config(), course_root)
    assert [c.args for c in mock_course.create_group_category.call_args_list] == [
        ("Project Groups",), ("Study Buddies",),
    ]
    out = capsys.readouterr().out
    assert "Created group set/group category: Project Groups" in out


def test_existing_and_unlisted_group_categories_are_left_alone(course_root, mock_course) -> None:
    _settings(course_root)
    mock_course.get_group_categories.return_value = [
        _category("Project Groups", 812), _category("Lab Partners", 813),
    ]
    run_sync(_config(), course_root)
    mock_course.create_group_category.assert_not_called()


def test_group_categories_are_listed_once_per_run_and_not_cached(course_root, mock_course, capsys) -> None:
    _settings(course_root)
    mock_course.get_group_categories.return_value = [_category("Project Groups", 812)]
    for name in ("d1", "d2", "d3"):
        _discussion(course_root, name)
    (course_root / "assignments" / "group-hw.md").write_text(
        '---\ntitle: "Group HW"\ngroup_category_id: "Project Groups"\n---\n\nDo it.\n'
    )
    run_sync(_config(), course_root)
    assert "group set/group category" not in capsys.readouterr().out
    assert mock_course.get_group_categories.call_count == 1
    assert len([c for c in mock_course.create_discussion_topic.call_args_list
                if c.kwargs.get("group_category_id") == 812]) == 3
    manifest = (course_root / ".manifest-canvas.toml")
    if manifest.exists():
        assert "812" not in manifest.read_text()


def test_group_discussion_by_name_gets_the_course_id(course_root, mock_course) -> None:
    _settings(course_root)
    mock_course.get_group_categories.return_value = [_category("Project Groups", 812)]
    _discussion(course_root)
    run_sync(_config(), course_root)
    (call,) = _discussion_calls(mock_course, "team-plan")
    assert call.kwargs["group_category_id"] == 812
    assert "assignment" not in call.kwargs


def test_graded_group_discussion_sends_both(course_root, mock_course) -> None:
    _settings(course_root)
    mock_course.get_group_categories.return_value = [_category("Project Groups", 812)]
    _discussion(course_root, extra='group_category_id: "Project Groups"\npoints_possible: 10\n')
    run_sync(_config(), course_root)
    (call,) = _discussion_calls(mock_course, "team-plan")
    assert call.kwargs["group_category_id"] == 812
    assert call.kwargs["assignment"]["points_possible"] == 10
    assert "group_category_id" not in call.kwargs["assignment"]


def test_two_courses_resolve_the_same_name_to_their_own_ids(course_root, mock_course, tmp_path) -> None:
    _settings(course_root)
    _discussion(course_root)
    mock_course.get_group_categories.return_value = [_category("Project Groups", 812)]
    run_sync(_config(111), course_root)
    ol3 = _discussion_calls(mock_course, "team-plan")[-1]
    mock_course.create_discussion_topic.reset_mock()
    mock_course.get_group_categories.return_value = [_category("Project Groups", 907)]
    run_sync(_config(222), course_root, force_uploads=True)
    ol4 = _discussion_calls(mock_course, "team-plan")[-1]
    assert (ol3.kwargs["group_category_id"], ol4.kwargs["group_category_id"]) == (812, 907)


def test_group_assignment_by_name(course_root, mock_course) -> None:
    _settings(course_root)
    mock_course.get_group_categories.return_value = [_category("Project Groups", 812)]
    (course_root / "assignments" / "group-hw.md").write_text(
        '---\ntitle: "Group HW"\ngroup_category_id: "Project Groups"\n'
        "grade_group_students_individually: true\n---\n\nDo it.\n"
    )
    run_sync(_config(), course_root)
    sent = [
        c.kwargs["assignment"] for c in mock_course.create_assignment.call_args_list
        if c.kwargs["assignment"]["name"] == "Group HW"
    ]
    assert sent[-1]["group_category_id"] == 812
    assert sent[-1]["grade_group_students_individually"] is True


def test_numeric_id_is_sent_unchanged_without_a_lookup(course_root, mock_course) -> None:
    _settings(course_root, "[]")
    _discussion(course_root, extra="group_category_id: 812\n")
    run_sync(_config(), course_root)
    (call,) = _discussion_calls(mock_course, "team-plan")
    assert call.kwargs["group_category_id"] == 812
    mock_course.get_group_categories.assert_not_called()


@pytest.mark.parametrize("on_canvas", [False, True])
def test_unlisted_name_blocks_only_that_file(course_root, mock_course, capsys, on_canvas) -> None:
    _settings(course_root)
    if on_canvas:
        mock_course.get_group_categories.return_value = [_category("Lab Partners", 813)]
    _discussion(course_root, extra='group_category_id: "Lab Partners"\n')
    had_errors = run_sync(_config(), course_root)
    assert had_errors
    assert _discussion_calls(mock_course, "team-plan") == []
    assert _discussion_calls(mock_course, "Introduce Yourself")  # other files still sync
    out = capsys.readouterr().out
    assert "discussions/team-plan.md" in out and "'Lab Partners'" in out
    assert "add it to group_categories" in out


def test_duplicate_names_on_canvas_block_the_file(course_root, mock_course, capsys) -> None:
    _settings(course_root)
    mock_course.get_group_categories.return_value = [
        _category("Project Groups", 812), _category("Project Groups", 900),
    ]
    _discussion(course_root)
    assert run_sync(_config(), course_root)
    assert _discussion_calls(mock_course, "team-plan") == []
    assert "812, 900" in capsys.readouterr().out


def test_failed_creation_blocks_files_that_use_it(course_root, mock_course, capsys) -> None:
    _settings(course_root)
    mock_course.create_group_category.side_effect = RuntimeError("boom")
    _discussion(course_root)
    assert run_sync(_config(), course_root)
    assert _discussion_calls(mock_course, "team-plan") == []
    assert mock_course.create_group_category.call_count == 1  # not retried per file


@pytest.mark.parametrize(
    "what, reason, current, expected",
    [
        ("discussion", "switch", 813,
         ['uses group set/group category "Study Buddies" (ID 813)',
          'asks for "Project Groups" (ID 812)',
          'tick "This is a Group Discussion"', "make a new discussion instead"]),
        ("discussion", "student_work", None,
         ["already has student replies", "remove group_category_id from the file"]),
        ("assignment", "switch", 999,
         ["uses group set/group category ID 999", 'tick "This is a Group Assignment"']),
    ],
)
def test_refused_change_is_an_error_and_not_recorded(
    course_root, mock_course, mocker, capsys, what, reason, current, expected
) -> None:
    _settings(course_root, '["Project Groups", "Study Buddies"]')
    mock_course.get_group_categories.return_value = [
        _category("Project Groups", 812), _category("Study Buddies", 813),
    ]
    key = _discussion(course_root)
    if what == "assignment":
        (course_root / "assignments" / "team-plan.md").write_text(
            '---\ntitle: "team-plan"\ngroup_category_id: "Project Groups"\n---\n\nx\n'
        )
        key = "assignments/team-plan.md"
    func = "create_or_update_" + what
    real = getattr(capi, func)

    def fake(course, canvas_id, title, body, **kwargs):
        if title == "team-plan":
            raise capi.GroupCategoryChangeRefused(what, reason, current, kwargs["group_category_id"])
        return real(course, canvas_id, title, body, **kwargs)

    mocker.patch.object(capi, func, side_effect=fake)
    assert run_sync(_config(), course_root)
    out = " ".join(capsys.readouterr().out.split())
    assert f"ERROR: {key}: not uploaded." in out
    for text in expected:
        assert text in out
    manifest = course_root / ".manifest-canvas.toml"
    if manifest.exists():
        assert key not in tomllib.loads(manifest.read_text())


def test_announcement_ignores_group_category_id(course_root, mock_course, capsys) -> None:
    _settings(course_root)
    (course_root / "announcements").mkdir()
    (course_root / "announcements" / "hi.md").write_text(
        '---\ntitle: "Hi"\npublished: true\ngroup_category_id: "Project Groups"\n---\n\nHello.\n'
    )
    run_sync(_config(), course_root)
    out = capsys.readouterr().out
    assert "ignoring frontmatter field 'group_category_id'" in out
    (call,) = _discussion_calls(mock_course, "Hi")
    assert "group_category_id" not in call.kwargs


# ---------------------------------------------------------------------------
# targeted sync and --check-all
# ---------------------------------------------------------------------------


def test_targeted_sync_creates_a_listed_group_category_on_demand(course_root, mock_course, capsys) -> None:
    _settings(course_root, '["Project Groups", "Unused"]')
    key = _discussion(course_root)
    run_targeted_sync(_config(), course_root, [], [str(course_root / key)])
    assert [c.args for c in mock_course.create_group_category.call_args_list] == [("Project Groups",)]
    (call,) = _discussion_calls(mock_course, "team-plan")
    assert call.kwargs["group_category_id"] == 700


def test_check_all_resolves_listed_names_offline(course_root, mocker, capsys) -> None:
    mocker.patch(
        "markdown_to_canvas.canvas_api.Canvas",
        side_effect=AssertionError("check-all must not contact Canvas"),
    )
    _settings(course_root)
    _discussion(course_root)
    assert run_sync(_config(), course_root, check_all=True) is False
    assert "Would create group set/group category: Project Groups" in capsys.readouterr().out


def test_check_all_reports_an_unlisted_name(course_root, mocker, capsys) -> None:
    mocker.patch(
        "markdown_to_canvas.canvas_api.Canvas",
        side_effect=AssertionError("check-all must not contact Canvas"),
    )
    _settings(course_root)
    _discussion(course_root, extra='group_category_id: "Lab Partners"\n')
    assert run_sync(_config(), course_root, check_all=True) is True
    out = capsys.readouterr().out
    assert "'Lab Partners' is not listed" in out


# ---------------------------------------------------------------------------
# import
# ---------------------------------------------------------------------------

from markdown_to_canvas.imscc_import import (  # noqa: E402
    parse_assignment_settings,
    parse_topic_meta,
    run_import,
)

_NS = 'xmlns="http://canvas.instructure.com/xsd/cccv1p0"'


def test_topic_meta_group_category_is_read_from_the_topic_level(tmp_path) -> None:
    # Shaped like a real Canvas export: the graded discussion's nested
    # <assignment> says has_group_category false; the topic's own says true.
    meta = tmp_path / "meta.xml"
    meta.write_text(
        f'<?xml version="1.0"?>\n<topicMeta identifier="t" {_NS}>\n'
        "  <title>Lab 3</title>\n  <type>topic</type>\n"
        "  <has_group_category>true</has_group_category>\n"
        "  <group_category>Project Groups</group_category>\n"
        "  <workflow_state>active</workflow_state>\n"
        '  <assignment identifier="a">\n    <points_possible>20.0</points_possible>\n'
        "    <has_group_category>false</has_group_category>\n  </assignment>\n"
        "</topicMeta>\n"
    )
    assert parse_topic_meta(meta)["group_category_id"] == "Project Groups"


def test_topic_meta_without_group_category(tmp_path) -> None:
    meta = tmp_path / "meta.xml"
    meta.write_text(
        f'<?xml version="1.0"?>\n<topicMeta identifier="t" {_NS}>\n'
        "  <title>T</title>\n  <has_group_category>false</has_group_category>\n"
        "  <group_category>Stale</group_category>\n</topicMeta>\n"
    )
    assert "group_category_id" not in parse_topic_meta(meta)


def test_assignment_settings_group_category_requires_the_flag(tmp_path) -> None:
    path = tmp_path / "assignment_settings.xml"
    path.write_text(
        f'<?xml version="1.0"?>\n<assignment identifier="a" {_NS}>\n  <title>A</title>\n'
        "  <has_group_category>false</has_group_category>\n"
        "  <group_category>Stale</group_category>\n</assignment>\n"
    )
    assert "group_category_id" not in parse_assignment_settings(path)


@pytest.fixture
def group_export(tmp_path: Path) -> Path:
    """The import fixture with its discussion turned into a group discussion."""
    src = tmp_path / "export"
    shutil.copytree(FIXTURES / "imscc", src)
    meta = src / "g_discussion_1_meta.xml"
    meta.write_text(
        meta.read_text().replace(
            "<has_group_category>false</has_group_category>",
            "<has_group_category>true</has_group_category>\n"
            "  <group_category>Project Groups</group_category>",
            1,
        )
    )
    return src


def test_import_writes_group_category_frontmatter_and_one_list_entry(group_export, tmp_path) -> None:
    out = tmp_path / "repo"
    run_import(group_export, out)
    discussion = next(
        t for t in (p.read_text() for p in (out / "discussions").glob("*.md"))
        if "Week 01 Forum" in t
    )
    assignment = (out / "assignments" / "my-assignment.md").read_text()
    assert 'group_category_id: "Project Groups"' in discussion
    assert 'group_category_id: "Project Groups"' in assignment
    text = (out / "course_settings" / "course_settings.toml").read_text()
    assert tomllib.loads(text)["group_categories"] == ["Project Groups"]
    assert text.count("Project Groups") == 1
    first_header = re.search(r"^\[", text, re.MULTILINE).start()
    assert text.index("group_categories") < first_header


def test_import_without_group_categories_writes_an_empty_list(tmp_path) -> None:
    src = tmp_path / "export"
    shutil.copytree(FIXTURES / "imscc", src)
    settings = src / "g_assignment_1" / "assignment_settings.xml"
    settings.write_text(
        settings.read_text().replace("<has_group_category>true</has_group_category>", "")
        .replace("<group_category>Project Groups</group_category>", "")
    )
    out = tmp_path / "repo"
    run_import(src, out)
    data = tomllib.loads((out / "course_settings" / "course_settings.toml").read_text())
    assert data["group_categories"] == []
    assert "group_category_id" not in (out / "assignments" / "my-assignment.md").read_text()


def test_import_then_update_recreates_group_work_in_an_empty_course(
    group_export, tmp_path, mock_course, capsys
) -> None:
    out = tmp_path / "repo"
    run_import(group_export, out)
    run_sync(_config(), out)
    assert [c.args for c in mock_course.create_group_category.call_args_list] == [("Project Groups",)]
    discussion_calls = [
        c for c in mock_course.create_discussion_topic.call_args_list
        if c.kwargs.get("group_category_id") == 700
    ]
    assignment_calls = [
        c for c in mock_course.create_assignment.call_args_list
        if c.kwargs["assignment"].get("group_category_id") == 700
    ]
    assert discussion_calls and assignment_calls
    assert "is not listed" not in capsys.readouterr().out


# ---------------------------------------------------------------------------
# published: false on an item Canvas will not unpublish
# ---------------------------------------------------------------------------

from canvasapi.exceptions import BadRequest  # noqa: E402

_CANT_UNPUBLISH = (
    '{"errors":{"published":[{"attribute":"workflow_state",'
    '"message":"Can\'t unpublish if there are student submissions"}]}}'
)


def test_assignment_that_cannot_be_unpublished_is_updated_without_published() -> None:
    course = MagicMock()
    a = _assignment()
    course.get_assignment.return_value = a
    a.edit.side_effect = [BadRequest(_CANT_UNPUBLISH), a]
    entry = capi.create_or_update_assignment(course, 7, "A", "<p>new</p>", published=False)
    assert "Can't unpublish" in entry["unpublish_refused"]
    retry = a.edit.call_args_list[1].kwargs["assignment"]
    assert "published" not in retry
    assert retry["description"] == "<p>new</p>"


def test_discussion_that_cannot_be_unpublished_is_updated_without_published() -> None:
    course = MagicMock()
    topic = _topic()
    course.get_discussion_topic.return_value = topic
    topic.update.side_effect = [BadRequest(_CANT_UNPUBLISH), topic]
    entry = capi.create_or_update_discussion(course, 5, "T", "b", published=False)
    assert entry["unpublish_refused"]
    assert "published" not in topic.update.call_args_list[1].kwargs


def test_other_bad_requests_still_raise() -> None:
    course = MagicMock()
    a = _assignment()
    course.get_assignment.return_value = a
    a.edit.side_effect = BadRequest('{"errors":"something else"}')
    with pytest.raises(BadRequest):
        capi.create_or_update_assignment(course, 7, "A", "b", published=False)
    assert a.edit.call_count == 1


def test_publishing_error_is_not_retried_when_publishing(mocker) -> None:
    course = MagicMock()
    a = _assignment()
    course.get_assignment.return_value = a
    a.edit.side_effect = BadRequest(_CANT_UNPUBLISH)
    with pytest.raises(BadRequest):
        capi.create_or_update_assignment(course, 7, "A", "b", published=True)


def test_update_reports_the_refusal_and_keeps_going(course_root, mock_course, mocker, capsys) -> None:
    _settings(course_root, "[]")
    (course_root / "assignments" / "hw.md").write_text(
        '---\ntitle: "HW"\npublished: false\n---\n\nNew text.\n'
    )
    real = capi.create_or_update_assignment

    def fake(course, canvas_id, title, body, **kwargs):
        entry = real(course, canvas_id, title, body, **kwargs)
        if title == "HW":
            entry["unpublish_refused"] = _CANT_UNPUBLISH
        return entry

    mocker.patch.object(capi, "create_or_update_assignment", side_effect=fake)
    record = mocker.spy(__import__("markdown_to_canvas.manifest", fromlist=["record"]), "record")
    assert run_sync(_config(), course_root) is True
    out = capsys.readouterr().out
    assert "ERROR: assignments/hw.md: published is false, but Canvas will not unpublish" in out
    assert "Set 'published: true'" in out
    hw = [c for c in record.call_args_list if c.args[2] == "assignments/hw.md"]
    assert hw and hw[-1].kwargs["mark_synced"] is False
    assert _discussion_calls(mock_course, "Introduce Yourself")  # the run went on
