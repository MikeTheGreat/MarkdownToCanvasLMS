"""Integration tests: date placeholders during `update` (mocked Canvas)."""
from __future__ import annotations

import os
import tomllib
from pathlib import Path
from unittest.mock import MagicMock

import pytest

from markdown_to_canvas.config import Config
from markdown_to_canvas.sync import run_sync
from tests.conftest import make_current

HW1_DUE = "2026-10-27T23:59:00-07:00"

SETTINGS = f"""\
due_dates = [
    {{name = "HW 1", due_at = "{HW1_DUE}", unlock_at = "KEEP", lock_at = "KEEP"}},
    {{name = "HW 2", due_at = "2026-11-03T23:59:00-08:00", unlock_at = "KEEP", lock_at = "KEEP"}},
    {{name = "Online only", due_at = "2026-11-10T23:59:00-08:00", only_if = "online"}},
    {{name = "Quiz 1", type = "quiz", due_at = "2026-10-20T09:00:00-07:00", unlock_at = "KEEP", lock_at = "KEEP"}},
]

[course_flags]
online = false
"""


def _config() -> Config:
    return Config(base_url="https://school.instructure.com", course_id=1, api_token="tok")


def _write(path: Path, text: str) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text)
    return path


def _repo(tmp_path: Path, settings: str = SETTINGS) -> Path:
    root = tmp_path / "course"
    _write(root / "course_settings" / "course_settings.toml", settings)
    _write(
        root / "assignments" / "hw1.md",
        "---\ntitle: HW 1\npublished: true\n---\n\n"
        "Submit by [Oct 20]{.replace_date_with format=\"%A, %B %-d\"}.\n",
    )
    _write(
        root / "pages" / "schedule.md",
        "---\ntitle: Schedule\npublished: true\n---\n\n"
        "HW 2 is due [x]{.replace_date_with item=\"HW 2\"}.\n",
    )
    make_current(root)
    return root


def _mock_obj(canvas_id: int) -> MagicMock:
    obj = MagicMock()
    obj.id = canvas_id
    obj.page_id = canvas_id
    obj.url = f"obj-{canvas_id}"
    obj.html_url = f"https://school.instructure.com/courses/1/x/{canvas_id}"
    obj.updated_at = "2000-01-01T00:00:00Z"
    obj.edit.return_value = obj
    obj.update.return_value = obj
    return obj


@pytest.fixture
def course(mocker) -> MagicMock:
    mock_canvas_cls = mocker.patch("markdown_to_canvas.canvas_api.Canvas")
    course = MagicMock()
    mock_canvas_cls.return_value.get_course.return_value = course
    course.create_page.side_effect = lambda **kw: _mock_obj(100)
    course.get_page.side_effect = lambda *a, **kw: _mock_obj(100)
    course.create_assignment.side_effect = lambda **kw: _mock_obj(200)
    course.get_assignment.side_effect = lambda *a, **kw: _mock_obj(200)
    course.create_discussion_topic.side_effect = lambda **kw: _mock_obj(300)
    course.get_discussion_topic.side_effect = lambda *a, **kw: _mock_obj(300)
    course.get_assignment_groups.return_value = []
    course.get_rubrics.return_value = []
    course.get_tabs.return_value = []
    return course


def _manifest(root: Path) -> dict:
    with (root / ".manifest-canvas.toml").open("rb") as f:
        return tomllib.load(f)


def _age_everything(root: Path) -> None:
    for path in root.rglob("*"):
        if path.is_file():
            os.utime(path, (0.0, 0.0))


def _bodies(course: MagicMock) -> dict[str, str]:
    """Uploaded HTML by Canvas object kind, from the latest create/edit call."""
    out: dict[str, str] = {}
    for c in course.create_page.call_args_list:
        out["page"] = c.kwargs["wiki_page"]["body"]
    for c in course.create_assignment.call_args_list:
        out["assignment"] = c.kwargs["assignment"]["description"]
    for c in course.create_discussion_topic.call_args_list:
        out["discussion"] = c.kwargs["message"]
    return out


def _set_due_dates(root: Path, settings: str) -> None:
    (root / "course_settings" / "course_settings.toml").write_text(settings)
    make_current(root)


# ---------------------------------------------------------------------------
# Expansion and records
# ---------------------------------------------------------------------------


def test_placeholders_are_replaced_and_recorded(tmp_path, course) -> None:
    root = _repo(tmp_path)
    assert run_sync(_config(), root) is False
    bodies = _bodies(course)
    assert "Submit by Tuesday, October 27." in bodies["assignment"]
    assert "HW 2 is due Tuesday, November 3 by 11:59 PM." in bodies["page"]
    assert "replace_date_with" not in bodies["assignment"] + bodies["page"]
    manifest = _manifest(root)
    assert manifest["assignments/hw1.md"]["dates_used"] == [
        {"item": "HW 1", "type": "assignment", "field": "due_at",
         "format": "%A, %B %-d", "text": "Tuesday, October 27"}
    ]
    assert manifest["pages/schedule.md"]["dates_used"][0]["item"] == "HW 2"


def test_file_without_placeholders_has_no_record(tmp_path, course) -> None:
    root = _repo(tmp_path)
    _write(root / "pages" / "plain.md", "---\ntitle: Plain\npublished: true\n---\n\nHi.\n")
    make_current(root)
    run_sync(_config(), root)
    assert "dates_used" not in _manifest(root)["pages/plain.md"]


def test_unresolved_placeholder_skips_only_that_file(tmp_path, course, capsys) -> None:
    root = _repo(tmp_path)
    _write(
        root / "discussions" / "d.md",
        "---\ntitle: D\npublished: true\n---\n\nBy [x]{.replace_date_with item=\"HW 9\"}.\n",
    )
    make_current(root)
    assert run_sync(_config(), root) is True
    course.create_discussion_topic.assert_not_called()
    assert course.create_page.called and course.create_assignment.called
    out = capsys.readouterr().out
    assert "discussions/d.md" in out and "no due_dates entry named 'HW 9'" in out
    assert "discussions/d.md" not in _manifest(root)


def test_only_if_removed_entry_does_not_resolve(tmp_path, course, capsys) -> None:
    root = _repo(tmp_path)
    _write(
        root / "pages" / "online.md",
        "---\ntitle: Online\npublished: true\n---\n\n[x]{.replace_date_with item=\"Online only\"}\n",
    )
    make_current(root)
    assert run_sync(_config(), root) is True
    assert "no due_dates entry named 'Online only'" in capsys.readouterr().out


def test_page_without_item_is_an_error(tmp_path, course, capsys) -> None:
    root = _repo(tmp_path)
    _write(root / "pages" / "p.md", "---\ntitle: P\npublished: true\n---\n\n[x]{.replace_date_with}\n")
    make_current(root)
    assert run_sync(_config(), root) is True
    assert "needs item=" in capsys.readouterr().out


def test_bad_format_setting_is_a_run_error(tmp_path, course) -> None:
    root = _repo(tmp_path, SETTINGS.replace("due_dates = [", "replace_date_with_format = 3\ndue_dates = [", 1))
    with pytest.raises(ValueError, match="replace_date_with_format must be a string"):
        run_sync(_config(), root)


def test_syllabus(tmp_path, course) -> None:
    root = _repo(tmp_path)
    _write(root / "course_settings" / "syllabus.md", "HW 1: [x]{.replace_date_with item=\"HW 1\" format=\"%b %-d\"}\n")
    make_current(root)
    assert run_sync(_config(), root) is False
    syllabus = [c for c in course.update.call_args_list if "syllabus_body" in c.kwargs.get("course", {})]
    assert "HW 1: Oct 27" in syllabus[-1].kwargs["course"]["syllabus_body"]
    assert _manifest(root)["course_settings/syllabus.md"]["dates_used"][0]["text"] == "Oct 27"


# ---------------------------------------------------------------------------
# Quizzes and question banks
# ---------------------------------------------------------------------------


def _quiz(root: Path) -> None:
    _write(
        root / "quizzes" / "quiz-1" / "quiz-1.md",
        "---\ntitle: Quiz 1\npublished: true\n---\n\n"
        "Opens until [x]{.replace_date_with format=\"%b %-d %-I:%M %p\"}.\n\n"
        "1. [Q1](questions/q1.md)\n",
    )
    _write(
        root / "quizzes" / "quiz-1" / "questions" / "q1.md",
        "---\nquestion_type: essay_question\npoints_possible: 1\n---\n\n"
        "# Question\n\nWhat is due [x]{.replace_date_with format=\"%-d\"}? Also [y]{.replace_date_with item=\"HW 1\" format=\"%-d\"}.\n",
    )
    make_current(root)


def test_quiz_description_and_questions(tmp_path, course, mocker) -> None:
    root = _repo(tmp_path)
    _quiz(root)
    api_quiz = mocker.patch(
        "markdown_to_canvas.canvas_api.create_or_update_quiz",
        return_value={"canvas_id": 400, "html_url": "https://x/quizzes/400"},
    )
    questions = mocker.patch("markdown_to_canvas.canvas_api.sync_quiz_questions", return_value={})
    mocker.patch("markdown_to_canvas.canvas_api.finalize_quiz_publish_state", return_value=False)
    assert run_sync(_config(), root) is False
    desc = api_quiz.call_args.args[3]
    assert "Opens until Oct 20 9:00 AM." in desc
    (q,) = questions.call_args.args[2]
    assert "What is due 20? Also 27." in q["question_text"]
    records = _manifest(root)["quizzes/quiz-1/quiz-1.md"]["dates_used"]
    assert {(r["item"], r["text"]) for r in records} == {
        ("Quiz 1", "Oct 20 9:00 AM"), ("Quiz 1", "20"), ("HW 1", "27")
    }


def test_question_bank_placeholder_needs_item(tmp_path, course, capsys) -> None:
    root = _repo(tmp_path)
    _write(root / "question_banks" / "bank" / "bank.toml", 'bank_title = "Bank"\n')
    _write(
        root / "question_banks" / "bank" / "questions" / "q.md",
        "---\nquestion_type: essay_question\n---\n\n# Question\n\nBy [x]{.replace_date_with}?\n",
    )
    make_current(root)
    assert run_sync(_config(), root) is True
    out = capsys.readouterr().out
    assert "question_banks/bank/questions/q.md" in out and "needs item=" in out


# ---------------------------------------------------------------------------
# Staleness
# ---------------------------------------------------------------------------


def _synced_and_aged(tmp_path, course) -> Path:
    root = _repo(tmp_path)
    assert run_sync(_config(), root) is False
    _age_everything(root)
    course.reset_mock()
    return root


def test_nothing_changes_nothing_uploads(tmp_path, course) -> None:
    root = _synced_and_aged(tmp_path, course)
    make_current(root)
    run_sync(_config(), root)
    course.get_assignment.assert_not_called()
    course.get_page.assert_not_called()


def test_due_date_change_reuploads_only_quoting_file(tmp_path, course, capsys) -> None:
    root = _synced_and_aged(tmp_path, course)
    _set_due_dates(root, SETTINGS.replace(HW1_DUE, "2026-10-28T23:59:00-07:00"))
    _age_everything(root)  # only the recorded text differs now
    make_current(root)
    run_sync(_config(), root, verbose=True)
    assert course.get_assignment.called
    course.get_page.assert_not_called()
    out = capsys.readouterr().out
    assert "re-syncing: date for 'HW 1' (due_at) changed 'Tuesday, October 27' → 'Wednesday, October 28'" in out
    assert _manifest(root)["assignments/hw1.md"]["dates_used"][0]["text"] == "Wednesday, October 28"


def test_unrelated_due_date_change_reuploads_nothing(tmp_path, course) -> None:
    root = _synced_and_aged(tmp_path, course)
    _set_due_dates(root, SETTINGS.replace("2026-10-20T09:00:00", "2026-10-21T09:00:00"))
    _age_everything(root)
    make_current(root)
    run_sync(_config(), root)
    course.get_assignment.assert_not_called()
    course.get_page.assert_not_called()


def test_default_format_change_reuploads_files_using_it(tmp_path, course) -> None:
    root = _synced_and_aged(tmp_path, course)
    _set_due_dates(root, 'replace_date_with_format = "%b %-d"\n' + SETTINGS)
    _age_everything(root)
    make_current(root)
    run_sync(_config(), root)
    course.get_page.assert_called()  # schedule.md uses the default format
    course.get_assignment.assert_not_called()  # hw1.md gives its own format


def test_record_that_no_longer_resolves_makes_file_stale(tmp_path, course, capsys) -> None:
    root = _synced_and_aged(tmp_path, course)
    _set_due_dates(root, SETTINGS.replace('{name = "HW 2"', '{name = "HW 2b"'))
    _age_everything(root)
    make_current(root)
    assert run_sync(_config(), root) is True
    assert "no due_dates entry named 'HW 2'" in capsys.readouterr().out


def _updated_at(course: MagicMock, when: str) -> None:
    def obj(*a, **kw):
        o = _mock_obj(200)
        o.updated_at = when
        return o
    course.get_assignment.side_effect = obj


def test_reupload_not_blocked_by_our_own_last_upload(tmp_path, course) -> None:
    """Canvas's updated_at is the time of our last upload, later than the
    (unchanged) file; the date-driven re-upload must still happen."""
    root = _synced_and_aged(tmp_path, course)
    last = _manifest(root)["assignments/hw1.md"]["last_synced"]
    _updated_at(course, last)
    _set_due_dates(root, SETTINGS.replace(HW1_DUE, "2026-10-28T23:59:00-07:00"))
    _age_everything(root)
    make_current(root)
    run_sync(_config(), root)
    assert _manifest(root)["assignments/hw1.md"]["dates_used"][0]["text"] == "Wednesday, October 28"


def test_reupload_respects_newer_on_canvas(tmp_path, course, capsys) -> None:
    """An edit made in Canvas after the last upload still blocks the re-upload."""
    root = _synced_and_aged(tmp_path, course)
    _updated_at(course, "2999-01-01T00:00:00Z")
    _set_due_dates(root, SETTINGS.replace(HW1_DUE, "2026-10-28T23:59:00-07:00"))
    _age_everything(root)
    make_current(root)
    run_sync(_config(), root)
    assert "Skipping (Canvas is newer): assignments/hw1.md" in capsys.readouterr().out
    assert _manifest(root)["assignments/hw1.md"]["dates_used"][0]["text"] == "Tuesday, October 27"


# ---------------------------------------------------------------------------
# Module files
# ---------------------------------------------------------------------------


def _module_course(course: MagicMock) -> MagicMock:
    """Make ``course`` create one module; returns it (its items are recorded)."""
    module = MagicMock()
    module.id = 500
    module.get_module_items.return_value = []
    module.create_module_item.side_effect = lambda **kw: MagicMock(id=600)
    course.get_modules.return_value = []
    course.create_module.return_value = module
    course.get_module.return_value = module
    module.edit.return_value = module
    return module


def _item_titles(module: MagicMock) -> list[str]:
    return [c.kwargs["module_item"]["title"] for c in module.create_module_item.call_args_list]


def _week(root: Path, heading: str) -> Path:
    return _write(
        root / "modules" / "week-1.md",
        f"---\ntitle: Week 1\n---\n## {heading}\n\n- [HW 1](../assignments/hw1.md)\n"
        f"- Due [x]{{.replace_date_with item=\"HW 2\" format=\"%b %-d\"}}\n",
    )


def test_module_placeholders_are_replaced_and_recorded(tmp_path, course) -> None:
    root = _repo(tmp_path)
    module = _module_course(course)
    _week(root, 'Week 1: [A]{.replace_date_with item="HW 1" format="%A, %B %-d"} - '
                '[B]{.replace_date_with item="Quiz 1" format="%A, %B %-d"}')
    make_current(root)
    assert run_sync(_config(), root) is False
    assert _item_titles(module) == [
        "Week 1: Tuesday, October 27 - Tuesday, October 20", "HW 1", "Due Nov 3",
    ]
    records = _manifest(root)["modules/week-1.md"]["dates_used"]
    assert [r["item"] for r in records] == ["HW 1", "Quiz 1", "HW 2"]


def test_module_dates_are_not_markdown_escaped(tmp_path, course) -> None:
    root = _repo(tmp_path)
    module = _module_course(course)
    _week(root, 'Due [x]{.replace_date_with item="HW 1" format="%-m_%-d"}')
    make_current(root)
    run_sync(_config(), root)
    assert _item_titles(module)[0] == "Due 10_27"


def test_module_unresolved_placeholder_skips_module(tmp_path, course, capsys) -> None:
    root = _repo(tmp_path)
    module = _module_course(course)
    _week(root, 'Week 1: [x]{.replace_date_with item="HW 9"}')
    make_current(root)
    assert run_sync(_config(), root) is True
    module.create_module_item.assert_not_called()
    out = capsys.readouterr().out
    assert "modules/week-1.md: date placeholder" in out
    assert "no due_dates entry named 'HW 9'" in out
    assert "modules/week-1.md" not in _manifest(root)


def test_module_placeholder_needs_item(tmp_path, course, capsys) -> None:
    root = _repo(tmp_path)
    _module_course(course)
    _week(root, "Week 1: [x]{.replace_date_with}")
    make_current(root)
    assert run_sync(_config(), root) is True
    assert "needs item=" in capsys.readouterr().out


def test_module_due_date_change_resyncs_module(tmp_path, course, capsys) -> None:
    root = _repo(tmp_path)
    module = _module_course(course)
    _week(root, 'Week 1: [x]{.replace_date_with item="HW 2" format="%b %-d"}')
    make_current(root)
    assert run_sync(_config(), root) is False
    _age_everything(root)
    module.reset_mock()
    module.get_module_items.return_value = []
    module.create_module_item.side_effect = lambda **kw: MagicMock(id=600)

    make_current(root)
    run_sync(_config(), root)  # nothing changed
    module.create_module_item.assert_not_called()

    _set_due_dates(root, SETTINGS.replace("2026-11-03T23:59", "2026-11-04T23:59"))
    _age_everything(root)
    make_current(root)
    run_sync(_config(), root, verbose=True)
    assert _item_titles(module)[0] == "Week 1: Nov 4"
    assert "re-syncing: date for 'HW 2' (due_at) changed 'Nov 3' → 'Nov 4'" in capsys.readouterr().out
