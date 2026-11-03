"""Discussion checkpoints: parsing, validation and date resolution (pure), plus
validation during `update` with a mocked Canvas."""
from __future__ import annotations

from datetime import datetime
from pathlib import Path
from unittest.mock import MagicMock

import pytest

from markdown_to_canvas import checkpoints as cp
from markdown_to_canvas.config import Config
from markdown_to_canvas.sync import check_virtual_due_dates, run_sync
from tests.conftest import make_current

TOPIC_DUE = "2026-11-02T23:59:00-08:00"
OTHERS_DUE = "2026-11-03T23:59:00-08:00"


def _block(**overrides):
    block = {
        "reply_to_topic": {"points_possible": 1, "due_at": TOPIC_DUE},
        "reply_to_others": {"points_possible": 1, "replies_required": 2, "due_at": OTHERS_DUE},
    }
    block.update(overrides)
    return block


def _problems(fm, canvas_type="discussion"):
    with pytest.raises(cp.CheckpointError) as exc:
        cp.parse(fm, canvas_type)
    return exc.value.problems


# ---------------------------------------------------------------------------
# parse()
# ---------------------------------------------------------------------------


def test_valid_block() -> None:
    parsed = cp.parse({"title": "F", "checkpoints": _block()}, "discussion")
    assert parsed == cp.Checkpoints(
        cp.Checkpoint(1.0, TOPIC_DUE), cp.Checkpoint(1.0, OTHERS_DUE), 2
    )
    assert parsed.total_points == 2.0


def test_no_block_is_none() -> None:
    assert cp.parse({"title": "F", "points_possible": 2}, "discussion") is None


def test_due_dates_are_optional() -> None:
    block = {
        "reply_to_topic": {"points_possible": 1},
        "reply_to_others": {"points_possible": 2, "replies_required": 1},
    }
    parsed = cp.parse({"checkpoints": block}, "discussion")
    assert parsed.reply_to_topic.due_at is None and parsed.total_points == 3.0


def test_yaml_datetime_values_become_iso_strings() -> None:
    block = _block()
    block["reply_to_topic"]["due_at"] = datetime(2026, 11, 2, 23, 59)
    parsed = cp.parse({"checkpoints": block}, "discussion")
    assert parsed.reply_to_topic.due_at == "2026-11-02T23:59:00"


def test_missing_replies_required() -> None:
    block = _block(reply_to_others={"points_possible": 1})
    assert any("reply_to_others.replies_required' is missing" in p for p in _problems({"checkpoints": block}))


@pytest.mark.parametrize("count", [0, -1, 1.5, "2", True])
def test_bad_replies_required(count) -> None:
    block = _block(reply_to_others={"points_possible": 1, "replies_required": count})
    assert any("replies_required' must be a whole number" in p for p in _problems({"checkpoints": block}))


def test_unknown_top_level_key() -> None:
    block = _block()
    block["reply_to_entry"] = {"points_possible": 1}
    assert any("unknown key 'checkpoints.reply_to_entry'" in p for p in _problems({"checkpoints": block}))


def test_unknown_nested_key() -> None:
    block = _block()
    block["reply_to_topic"]["lock_at"] = TOPIC_DUE
    assert any("unknown key 'checkpoints.reply_to_topic.lock_at'" in p for p in _problems({"checkpoints": block}))


def test_missing_checkpoint() -> None:
    block = _block()
    del block["reply_to_topic"]
    assert "'checkpoints.reply_to_topic' is missing" in _problems({"checkpoints": block})


@pytest.mark.parametrize("points", [-1, "one", None])
def test_bad_points(points) -> None:
    block = _block(reply_to_topic={"points_possible": points})
    assert any("reply_to_topic.points_possible' must be a number" in p for p in _problems({"checkpoints": block}))


def test_bad_due_date() -> None:
    block = _block(reply_to_topic={"points_possible": 1, "due_at": "next Tuesday"})
    assert any("reply_to_topic.due_at' is not a date" in p for p in _problems({"checkpoints": block}))


def test_reply_to_topic_after_reply_to_others() -> None:
    block = _block()
    block["reply_to_topic"]["due_at"] = "2026-11-04T23:59:00-08:00"
    assert any("is after" in p for p in _problems({"checkpoints": block}))


def test_not_a_mapping() -> None:
    assert any("must be a mapping" in p for p in _problems({"checkpoints": "yes"}))


@pytest.mark.parametrize("key", ["points_possible", "due_at"])
def test_top_level_conflicts(key) -> None:
    problems = _problems({"checkpoints": _block(), key: 2 if key == "points_possible" else OTHERS_DUE})
    assert any(f"'{key}' may not be set together with 'checkpoints'" in p for p in problems)


def test_shared_availability_dates_are_allowed() -> None:
    fm = {"checkpoints": _block(), "unlock_at": "2026-11-01T00:00:00-07:00", "lock_at": "2026-11-05T23:59:00-08:00"}
    assert cp.parse(fm, "discussion") is not None


@pytest.mark.parametrize("canvas_type", ["assignment", "page", "quiz", "announcement"])
def test_block_outside_a_discussion(canvas_type) -> None:
    problems = _problems({"checkpoints": _block()}, canvas_type)
    article = "an" if canvas_type[0] in "aeiou" else "a"
    assert problems == [f"'checkpoints' applies only to discussions, not to {article} {canvas_type}"]


# ---------------------------------------------------------------------------
# entry_problems()
# ---------------------------------------------------------------------------


def _parsed():
    return cp.parse({"checkpoints": _block()}, "discussion")


def test_entry_due_at_with_checkpoints() -> None:
    problems = cp.entry_problems({"name": "F", "due_at": OTHERS_DUE}, _parsed(), "discussion")
    assert len(problems) == 1 and "has 'due_at'" in problems[0]


def test_entry_checkpoint_keys_without_checkpoints() -> None:
    problems = cp.entry_problems({"name": "F", "reply_to_others_due_at": OTHERS_DUE}, None, "discussion")
    assert len(problems) == 1 and "discussion without a 'checkpoints' block" in problems[0]


def test_entry_checkpoint_keys_on_an_assignment() -> None:
    problems = cp.entry_problems({"name": "HW", "reply_to_topic_due_at": TOPIC_DUE}, None, "assignment")
    assert len(problems) == 1
    assert "'reply_to_topic_due_at'" in problems[0] and "but it matches an assignment" in problems[0]


def test_entry_order() -> None:
    entry = {"name": "F", "reply_to_topic_due_at": "2026-11-05T23:59:00-08:00", "reply_to_others_due_at": OTHERS_DUE}
    assert any("is after" in p for p in cp.entry_problems(entry, _parsed(), "discussion"))


def test_entry_valid() -> None:
    entry = {"name": "F", "reply_to_topic_due_at": TOPIC_DUE, "reply_to_others_due_at": "KEEP"}
    assert cp.entry_problems(entry, _parsed(), "discussion") == []
    assert cp.entry_problems(None, _parsed(), "discussion") == []
    assert cp.entry_problems({"name": "F", "due_at": OTHERS_DUE}, None, "discussion") == []


def test_virtual_entry_may_not_have_checkpoint_keys(tmp_path) -> None:
    entries = [{"name": "Week 3", "virtual": True, "due_at": TOPIC_DUE, "reply_to_others_due_at": OTHERS_DUE}]
    with pytest.raises(ValueError, match="may not have 'reply_to_others_due_at'"):
        check_virtual_due_dates(entries, tmp_path)


# ---------------------------------------------------------------------------
# resolve_dates() and graphql_checkpoints()
# ---------------------------------------------------------------------------


def test_resolve_from_frontmatter_only() -> None:
    fm = {"unlock_at": "2026-11-01T00:00:00-07:00"}
    dates = cp.resolve_dates(fm, _parsed(), None, creating=False)
    assert dates.unlock_at == "2026-11-01T00:00:00-07:00"
    assert dates.lock_at is cp.OMIT
    assert dates.reply_to_topic_due_at == TOPIC_DUE
    assert dates.reply_to_others_due_at == OTHERS_DUE


def test_entry_overrides_frontmatter() -> None:
    entry = {"name": "F", "reply_to_others_due_at": "2026-11-04T23:59:00-08:00", "lock_at": "NONE"}
    dates = cp.resolve_dates({}, _parsed(), entry, creating=False)
    assert dates.reply_to_others_due_at == "2026-11-04T23:59:00-08:00"
    assert dates.reply_to_topic_due_at == TOPIC_DUE
    assert dates.lock_at is None


@pytest.mark.parametrize(
    "value, creating, expected",
    [("KEEP", False, cp.OMIT), ("KEEP", True, cp.OMIT), ("NONE", False, None),
     ("CREATE_NONE_THEN_KEEP", True, None), ("CREATE_NONE_THEN_KEEP", False, cp.OMIT)],
)
def test_sentinels(value, creating, expected) -> None:
    entry = {"name": "F", "reply_to_topic_due_at": value}
    assert cp.resolve_dates({}, _parsed(), entry, creating=creating).reply_to_topic_due_at is expected


def test_empty_entry_value_is_keep_and_reported() -> None:
    dates = cp.resolve_dates({}, _parsed(), {"name": "F", "reply_to_topic_due_at": ""}, creating=False)
    assert dates.reply_to_topic_due_at is cp.OMIT
    assert dates.empty_keys == ("reply_to_topic_due_at",)


def test_graphql_checkpoints_shape() -> None:
    entry = {"name": "F", "reply_to_topic_due_at": "KEEP", "reply_to_others_due_at": "NONE", "unlock_at": "2026-11-01T00:00:00-07:00"}
    dates = cp.resolve_dates({}, _parsed(), entry, creating=False)
    assert cp.graphql_checkpoints(_parsed(), dates) == [
        {"checkpointLabel": "reply_to_topic", "pointsPossible": 1.0,
         "dates": [{"type": "everyone", "unlockAt": "2026-11-01T00:00:00-07:00"}]},
        {"checkpointLabel": "reply_to_entry", "pointsPossible": 1.0, "repliesRequired": 2,
         "dates": [{"type": "everyone", "dueAt": None, "unlockAt": "2026-11-01T00:00:00-07:00"}]},
    ]


def test_feature_off_message_names_the_alternatives() -> None:
    msg = cp.feature_off_message("discussions/forum.md")
    for text in ("discussions/forum.md", "Discussion Checkpoints", "points_possible",
                 "due_at", "require_initial_post: true", "replace_date_with"):
        assert text in msg


# ---------------------------------------------------------------------------
# Validation during update (mocked Canvas)
# ---------------------------------------------------------------------------


def _config() -> Config:
    return Config(base_url="https://school.instructure.com", course_id=1, api_token="tok")


def _write(path: Path, text: str) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text)
    return path


def _mock_obj(canvas_id: int) -> MagicMock:
    obj = MagicMock()
    obj.id = canvas_id
    obj.page_id = canvas_id
    obj.url = f"obj-{canvas_id}"
    obj.html_url = f"https://school.instructure.com/courses/1/x/{canvas_id}"
    obj.updated_at = "2000-01-01T00:00:00Z"
    obj.assignment_id = None
    obj.assignment = None
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
    course.create_discussion_topic.side_effect = lambda **kw: _mock_obj(300)
    course.get_assignment_groups.return_value = []
    course.get_rubrics.return_value = []
    course.get_tabs.return_value = []
    return course


def _invalid_repo(tmp_path: Path, settings: str = "") -> Path:
    root = tmp_path / "course"
    _write(root / "course_settings" / "course_settings.toml", settings)
    _write(
        root / "discussions" / "forum.md",
        "---\ntitle: Forum\npublished: true\npoints_possible: 2\ncheckpoints:\n"
        "    reply_to_topic:\n        points_possible: 1\n"
        "    reply_to_others:\n        points_possible: 1\n        replies_required: 1\n"
        "---\n\nPost.\n",
    )
    _write(root / "pages" / "info.md", "---\ntitle: Info\npublished: true\n---\n\nHi.\n")
    make_current(root)
    return root


def test_invalid_block_skips_only_that_discussion(tmp_path, course, capsys) -> None:
    root = _invalid_repo(tmp_path)
    assert run_sync(_config(), root) is True  # errors -> nonzero exit
    course.create_page.assert_called_once()
    course.create_discussion_topic.assert_not_called()
    out = capsys.readouterr().out
    assert "ERROR: discussions/forum.md: 'points_possible' may not be set together with 'checkpoints'" in out


def test_mismatched_due_dates_entry_skips_the_file(tmp_path, course, capsys) -> None:
    root = tmp_path / "course"
    _write(
        root / "course_settings" / "course_settings.toml",
        f'due_dates = [{{name = "Forum", type = "discussion", reply_to_others_due_at = "{OTHERS_DUE}"}}]\n',
    )
    _write(root / "discussions" / "forum.md", "---\ntitle: Forum\npoints_possible: 2\n---\n\nPost.\n")
    make_current(root)
    assert run_sync(_config(), root) is True
    course.create_discussion_topic.assert_not_called()
    assert "which only a discussion with 'checkpoints' may have" in capsys.readouterr().out


def test_checkpoints_on_an_assignment_is_an_error(tmp_path, course, capsys) -> None:
    root = tmp_path / "course"
    _write(
        root / "assignments" / "hw.md",
        "---\ntitle: HW\ncheckpoints:\n    reply_to_topic:\n        points_possible: 1\n---\n\nDo it.\n",
    )
    make_current(root)
    assert run_sync(_config(), root) is True
    course.create_assignment.assert_not_called()
    assert "'checkpoints' applies only to discussions, not to an assignment" in capsys.readouterr().out


# ---------------------------------------------------------------------------
# canvas_api: flag lookup, GraphQL calls, checkpoint state on update
# ---------------------------------------------------------------------------

from canvasapi.exceptions import Forbidden  # noqa: E402

from markdown_to_canvas import canvas_api as capi  # noqa: E402
from markdown_to_canvas import dryrun  # noqa: E402


def _response(payload):
    resp = MagicMock()
    resp.json.return_value = payload
    return resp


def _api_course(flag_state="allowed_on", graphql_payload=None):
    """A course whose requester answers the flag GET and GraphQL POSTs."""
    course = MagicMock()
    course.id = 1
    course.account_id = 55
    graphql_payload = graphql_payload or {"data": {"updateDiscussionTopic": {"errors": None}}}

    def request(method, endpoint, **kwargs):
        if method == "GET" and endpoint.endswith("features/flags/discussion_checkpoints"):
            if isinstance(flag_state, Exception):
                raise flag_state
            return _response({"feature": "discussion_checkpoints", "state": flag_state})
        if method == "POST" and endpoint == "graphql":
            return _response(graphql_payload)
        raise AssertionError(f"unexpected request {method} {endpoint}")

    course._requester.request.side_effect = request
    return course


def _graphql_inputs(course):
    return [
        c.kwargs["json"]["variables"]["input"]
        for c in course._requester.request.call_args_list
        if c.args[:2] == ("POST", "graphql")
    ]


@pytest.mark.parametrize(
    "state, expected", [("on", True), ("allowed_on", True), ("off", False), ("allowed", False), ("weird", None)]
)
def test_flag_states(state, expected) -> None:
    course = _api_course(state)
    assert capi.discussion_checkpoints_enabled(course) is expected
    course._requester.request.assert_called_once_with(
        "GET", "accounts/55/features/flags/discussion_checkpoints"
    )


def test_flag_lookup_refused_is_unknown() -> None:
    course = _api_course(Forbidden("no"))
    assert capi.discussion_checkpoints_enabled(course) is None


def test_flag_lookup_without_account_id() -> None:
    course = MagicMock(spec=["id", "_requester"])
    assert capi.discussion_checkpoints_enabled(course) is None


def test_set_discussion_checkpoints_variables() -> None:
    course = _api_course()
    payload = [{"checkpointLabel": "reply_to_topic"}, {"checkpointLabel": "reply_to_entry"}]
    capi.set_discussion_checkpoints(course, 42, payload)
    assert _graphql_inputs(course) == [
        {"discussionTopicId": "42", "assignment": {"forCheckpoints": True}, "checkpoints": payload}
    ]


def test_remove_discussion_checkpoints_variables() -> None:
    course = _api_course()
    capi.remove_discussion_checkpoints(course, 42, 2)
    assert _graphql_inputs(course) == [
        {"discussionTopicId": "42", "setCheckpoints": False,
         "assignment": {"forCheckpoints": False, "pointsPossible": 2.0}}
    ]


def test_flag_disabled_error_is_mapped() -> None:
    course = _api_course(graphql_payload={
        "errors": [{"message": "discussion_checkpoints feature flag must be enabled"}]
    })
    with pytest.raises(capi.CheckpointsDisabled):
        capi.set_discussion_checkpoints(course, 42, [])


def test_replies_error_is_mapped() -> None:
    course = _api_course(graphql_payload={"data": {"updateDiscussionTopic": {
        "errors": [{"attribute": "message", "message": "Checkpoints cannot be enabled after replies have been made."}]
    }}})
    with pytest.raises(capi.CheckpointChangeRefused) as exc:
        capi.set_discussion_checkpoints(course, 42, [])
    assert exc.value.action == "add"


def test_other_payload_error_raises() -> None:
    course = _api_course(graphql_payload={"data": {"updateDiscussionTopic": {
        "errors": [{"attribute": "x", "message": "something else"}]
    }}})
    with pytest.raises(RuntimeError, match="something else"):
        capi.set_discussion_checkpoints(course, 42, [])


def _topic(is_checkpointed=False, replies=0):
    topic = MagicMock()
    topic.id = 42
    topic.html_url = "https://x/discussion_topics/42"
    topic.is_checkpointed = is_checkpointed
    topic.discussion_subentry_count = replies
    topic.assignment_id = 7
    topic.assignment = {"id": 7, "has_sub_assignments": is_checkpointed, "rubric_settings": None}
    topic.group_category_id = None
    topic.update.return_value = topic
    return topic


_PARENT = {"points_possible": 2.0, "due_at": OTHERS_DUE, "unlock_at": "u", "lock_at": "l", "assignment_group_id": 9}


def test_checkpointed_topic_gets_no_parent_keys() -> None:
    course = _api_course()
    topic = _topic(is_checkpointed=True)
    course.get_discussion_topic.return_value = topic
    result = capi.create_or_update_discussion(
        course, 42, "F", "<p>b</p>", checkpoints_wanted=True, assignment=dict(_PARENT)
    )
    assert topic.update.call_args.kwargs["assignment"] == {"assignment_group_id": 9}
    assert result["was_checkpointed"] is True


def test_plain_topic_keeps_parent_keys_when_converting() -> None:
    course = _api_course()
    topic = _topic()
    course.get_discussion_topic.return_value = topic
    result = capi.create_or_update_discussion(
        course, 42, "F", "<p>b</p>", checkpoints_wanted=True, assignment=dict(_PARENT)
    )
    assert topic.update.call_args.kwargs["assignment"] == _PARENT
    assert result["was_checkpointed"] is False


def test_removal_happens_before_the_rest_update() -> None:
    course = _api_course()
    topic = _topic(is_checkpointed=True)
    course.get_discussion_topic.return_value = topic
    order: list[str] = []
    course._requester.request.side_effect = (
        lambda *a, **k: (order.append("graphql"), _response({"data": {"updateDiscussionTopic": {"errors": None}}}))[1]
    )
    topic.update.side_effect = lambda **k: (order.append("rest"), topic)[1]
    result = capi.create_or_update_discussion(
        course, 42, "F", "<p>b</p>", checkpoints_wanted=False, assignment=dict(_PARENT)
    )
    assert order == ["graphql", "rest"]
    assert result["checkpoints_removed"] is True
    assert topic.update.call_args.kwargs["assignment"] == _PARENT


@pytest.mark.parametrize("is_checkpointed, wanted, action", [(True, False, "remove"), (False, True, "add")])
def test_refusals_with_replies(is_checkpointed, wanted, action) -> None:
    course = _api_course()
    topic = _topic(is_checkpointed=is_checkpointed, replies=3)
    course.get_discussion_topic.return_value = topic
    with pytest.raises(capi.CheckpointChangeRefused) as exc:
        capi.create_or_update_discussion(course, 42, "F", "b", checkpoints_wanted=wanted, assignment=dict(_PARENT))
    assert exc.value.action == action
    topic.update.assert_not_called()
    assert _graphql_inputs(course) == []


def test_announcements_and_other_callers_skip_the_state_check() -> None:
    course = _api_course()
    topic = _topic(is_checkpointed=True, replies=3)
    course.get_discussion_topic.return_value = topic
    capi.create_or_update_discussion(course, 42, "F", "b", assignment=dict(_PARENT))
    assert topic.update.call_args.kwargs["assignment"] == _PARENT


def test_noop_reports_turning_checkpoints_off(mocker, capsys) -> None:
    mocker.patch.object(capi, "get_discussion_checkpoint_state", return_value=(True, False))
    result = dryrun.NoopCanvas().create_or_update_discussion(
        object(), 42, "F", "b", checkpoints_wanted=False, assignment={"points_possible": 2}
    )
    assert result["checkpoints_removed"] is True
    assert "Would turn off checkpoints" in capsys.readouterr().out


def test_noop_reports_refusal(mocker) -> None:
    mocker.patch.object(capi, "get_discussion_checkpoint_state", return_value=(False, True))
    with pytest.raises(capi.CheckpointChangeRefused):
        dryrun.NoopCanvas().create_or_update_discussion(object(), 42, "F", "b", checkpoints_wanted=True)


def test_dry_run_double_has_the_checkpoint_functions() -> None:
    api = dryrun.DryRunCanvas()
    assert api.discussion_checkpoints_enabled(object()) is None
    assert api.set_discussion_checkpoints(object(), 1, []) is None
    assert api.remove_discussion_checkpoints(object(), 1, 2) is None


# ---------------------------------------------------------------------------
# update: uploading, converting and turning off checkpoints (mocked Canvas)
# ---------------------------------------------------------------------------

import os  # noqa: E402
import tomllib  # noqa: E402

_CP_FRONTMATTER = (
    "---\ntitle: Forum\npublished: true\nassignment_group_id: Forums\n"
    'unlock_at: "2026-11-01T00:00:00-07:00"\n'
    "checkpoints:\n"
    "    reply_to_topic:\n        points_possible: 1\n"
    f'        due_at: "{TOPIC_DUE}"\n'
    "    reply_to_others:\n        points_possible: 2\n        replies_required: 2\n"
    f'        due_at: "{OTHERS_DUE}"\n'
    "---\n\nPost.\n"
)

_PLAIN_FRONTMATTER = (
    f'---\ntitle: Forum\npublished: true\npoints_possible: 3\ndue_at: "{OTHERS_DUE}"\n---\n\nPost.\n'
)


def _cp_course(mocker, flag_state="allowed_on", graphql_payload=None, topic=None):
    mock_canvas_cls = mocker.patch("markdown_to_canvas.canvas_api.Canvas")
    course = _api_course(flag_state, graphql_payload)
    mock_canvas_cls.return_value.get_course.return_value = course
    course.get_assignment_groups.return_value = [MagicMock(id=9, name="Forums")]
    course.get_assignment_groups.return_value[0].name = "Forums"
    course.get_rubrics.return_value = []
    course.get_tabs.return_value = []
    new_topic = topic or _topic()
    course.create_discussion_topic.return_value = new_topic
    course.get_discussion_topic.return_value = new_topic
    return course


def _cp_repo(tmp_path: Path, text: str = _CP_FRONTMATTER, settings: str = "", manifest_id: int | None = None) -> Path:
    root = tmp_path / "course"
    _write(root / "course_settings" / "course_settings.toml", settings)
    _write(root / "discussions" / "forum.md", text)
    make_current(root)
    if manifest_id is not None:
        from markdown_to_canvas.repo_format import FORMAT_VERSION

        _write(
            root / ".manifest-canvas.toml",
            f'[_repo_format]\nformat_version = {FORMAT_VERSION}\n\n["discussions/forum.md"]\n'
            f'canvas_id = {manifest_id}\ncanvas_type = "discussion"\nlast_synced = "2000-01-01T00:00:00+00:00"\n',
        )
    return root


def _manifest_entry(root: Path) -> dict:
    with (root / ".manifest-canvas.toml").open("rb") as f:
        return tomllib.load(f)["discussions/forum.md"]


def test_new_checkpointed_discussion(tmp_path, mocker) -> None:
    course = _cp_course(mocker)
    root = _cp_repo(tmp_path)
    assert run_sync(_config(), root) is False
    rest = course.create_discussion_topic.call_args.kwargs
    assert rest["assignment"] == {
        "points_possible": 3.0, "due_at": OTHERS_DUE,
        "unlock_at": "2026-11-01T00:00:00-07:00", "assignment_group_id": 9,
    }
    (inp,) = _graphql_inputs(course)
    assert inp["discussionTopicId"] == "42"
    assert inp["checkpoints"] == [
        {"checkpointLabel": "reply_to_topic", "pointsPossible": 1.0,
         "dates": [{"type": "everyone", "dueAt": TOPIC_DUE, "unlockAt": "2026-11-01T00:00:00-07:00"}]},
        {"checkpointLabel": "reply_to_entry", "pointsPossible": 2.0, "repliesRequired": 2,
         "dates": [{"type": "everyone", "dueAt": OTHERS_DUE, "unlockAt": "2026-11-01T00:00:00-07:00"}]},
    ]
    assert _manifest_entry(root)["canvas_id"] == 42
    assert "last_synced" in _manifest_entry(root)


def test_already_checkpointed_never_gets_parent_keys(tmp_path, mocker) -> None:
    topic = _topic(is_checkpointed=True)
    course = _cp_course(mocker, topic=topic)
    settings = (
        'due_dates = [{name = "Forum", type = "discussion", unlock_at = "KEEP", lock_at = "KEEP", '
        'reply_to_topic_due_at = "CREATE_NONE_THEN_KEEP", '
        f'reply_to_others_due_at = "{OTHERS_DUE}"}}]\n'
    )
    root = _cp_repo(tmp_path, settings=settings, manifest_id=42)
    assert run_sync(_config(), root) is False
    sent = topic.update.call_args.kwargs["assignment"]
    assert not set(sent) & set(capi.CHECKPOINT_PARENT_KEYS)
    (inp,) = _graphql_inputs(course)
    # Existing checkpointed topic: CREATE_NONE_THEN_KEEP and KEEP leave Canvas alone.
    assert inp["checkpoints"][0]["dates"] == [{"type": "everyone"}]
    assert inp["checkpoints"][1]["dates"] == [{"type": "everyone", "dueAt": OTHERS_DUE}]
    assert _manifest_entry(root)["resolved_dates"] == {
        "unlock_at": "KEEP", "reply_to_topic_due_at": "KEEP",
        "reply_to_others_due_at": OTHERS_DUE, "lock_at": "KEEP",
    }


def test_plain_discussion_is_converted(tmp_path, mocker) -> None:
    topic = _topic(is_checkpointed=False, replies=0)
    course = _cp_course(mocker, topic=topic)
    settings = (
        'due_dates = [{name = "Forum", type = "discussion", '
        'reply_to_topic_due_at = "CREATE_NONE_THEN_KEEP", '
        f'reply_to_others_due_at = "{OTHERS_DUE}"}}]\n'
    )
    root = _cp_repo(tmp_path, settings=settings, manifest_id=42)
    assert run_sync(_config(), root) is False
    assert topic.update.call_args.kwargs["assignment"]["points_possible"] == 3.0
    (inp,) = _graphql_inputs(course)
    # Converting counts as creating: CREATE_NONE_THEN_KEEP clears the date.
    assert inp["checkpoints"][0]["dates"][0]["dueAt"] is None


def test_feature_off_uploads_nothing_for_the_discussion(tmp_path, mocker, capsys) -> None:
    course = _cp_course(mocker, flag_state="off")
    root = _cp_repo(tmp_path)
    _write(root / "pages" / "info.md", "---\ntitle: Info\n---\n\nHi.\n")
    course.create_page.return_value = MagicMock(page_id=1, url="info", html_url="h")
    assert run_sync(_config(), root) is True
    course.create_discussion_topic.assert_not_called()
    course.create_page.assert_called_once()
    assert _graphql_inputs(course) == []
    out = capsys.readouterr().out
    assert "does not have Discussion Checkpoints turned on" in out
    assert "require_initial_post: true" in out


def test_flag_looked_up_once_per_run(tmp_path, mocker) -> None:
    course = _cp_course(mocker)
    root = _cp_repo(tmp_path)
    _write(root / "discussions" / "forum2.md", _CP_FRONTMATTER.replace("title: Forum", "title: Forum 2"))
    assert run_sync(_config(), root) is False
    gets = [c for c in course._requester.request.call_args_list if c.args[0] == "GET"]
    assert len(gets) == 1


def test_no_flag_lookup_without_checkpoints(tmp_path, mocker) -> None:
    course = _cp_course(mocker)
    root = _cp_repo(tmp_path, text=_PLAIN_FRONTMATTER)
    assert run_sync(_config(), root) is False
    assert course._requester.request.call_args_list == []


def test_graphql_failure_after_rest_records_but_retries(tmp_path, mocker, capsys) -> None:
    course = _cp_course(mocker, graphql_payload={"errors": [{"message": "boom"}]})
    root = _cp_repo(tmp_path)
    assert run_sync(_config(), root) is True
    entry = _manifest_entry(root)
    assert entry["canvas_id"] == 42 and "last_synced" not in entry
    out = capsys.readouterr().out
    assert "setting checkpoints failed" in out and "plain graded discussion" in out


def test_flag_unknown_then_graphql_refuses(tmp_path, mocker, capsys) -> None:
    course = _cp_course(mocker, flag_state=Forbidden("no"), graphql_payload={
        "errors": [{"message": "discussion_checkpoints feature flag must be enabled"}]
    })
    root = _cp_repo(tmp_path)
    assert run_sync(_config(), root) is True
    out = capsys.readouterr().out
    assert "does not have Discussion Checkpoints turned on" in out
    assert "currently a plain graded discussion" in out


def test_block_removed_turns_checkpoints_off(tmp_path, mocker, capsys) -> None:
    topic = _topic(is_checkpointed=True, replies=0)
    course = _cp_course(mocker, topic=topic)
    root = _cp_repo(tmp_path, text=_PLAIN_FRONTMATTER, manifest_id=42)
    assert run_sync(_config(), root) is False
    (inp,) = _graphql_inputs(course)
    assert inp["setCheckpoints"] is False and inp["assignment"]["pointsPossible"] == 3.0
    assert topic.update.call_args.kwargs["assignment"] == {"points_possible": 3, "due_at": OTHERS_DUE}
    assert "Turned off checkpoints" in capsys.readouterr().out


def test_block_removed_with_replies_is_refused(tmp_path, mocker, capsys) -> None:
    topic = _topic(is_checkpointed=True, replies=4)
    course = _cp_course(mocker, topic=topic)
    root = _cp_repo(tmp_path, text=_PLAIN_FRONTMATTER, manifest_id=42)
    assert run_sync(_config(), root) is True
    topic.update.assert_not_called()
    assert _graphql_inputs(course) == []
    assert "cannot be removed through the tool from a discussion that has replies" in capsys.readouterr().out


def test_checkpoints_added_after_replies_is_refused(tmp_path, mocker, capsys) -> None:
    topic = _topic(is_checkpointed=False, replies=4)
    course = _cp_course(mocker, topic=topic)
    root = _cp_repo(tmp_path, manifest_id=42)
    assert run_sync(_config(), root) is True
    topic.update.assert_not_called()
    assert _graphql_inputs(course) == []
    assert "does not allow checkpoints to be added" in capsys.readouterr().out


def test_invalid_block_never_turns_checkpoints_off(tmp_path, mocker) -> None:
    topic = _topic(is_checkpointed=True, replies=0)
    course = _cp_course(mocker, topic=topic)
    bad = _CP_FRONTMATTER.replace("replies_required: 2", "replies_required: 0")
    root = _cp_repo(tmp_path, text=bad, manifest_id=42)
    assert run_sync(_config(), root) is True
    topic.update.assert_not_called()  # (a read for the newer-on-Canvas check is fine)
    assert _graphql_inputs(course) == []


# ---------------------------------------------------------------------------
# update: the dates-only pass
# ---------------------------------------------------------------------------


def _synced_cp_repo(tmp_path, mocker, settings):
    """A checkpointed discussion already uploaded (file older than last_synced)."""
    topic = _topic(is_checkpointed=True)
    course = _cp_course(mocker, topic=topic)
    root = _cp_repo(tmp_path, settings=settings)
    assert run_sync(_config(), root) is False
    for path in root.rglob("*.md"):
        os.utime(path, (0.0, 0.0))
    course._requester.request.reset_mock()
    topic.update.reset_mock()
    course.create_discussion_topic.reset_mock()
    return root, course, topic


_DATED = (
    'due_dates = [{{name = "Forum", type = "discussion", unlock_at = "KEEP", lock_at = "KEEP", '
    'reply_to_topic_due_at = "{topic}", reply_to_others_due_at = "{others}"}}]\n'
)


def test_dates_only_change_sends_one_graphql_call(tmp_path, mocker) -> None:
    root, course, topic = _synced_cp_repo(
        tmp_path, mocker, _DATED.format(topic=TOPIC_DUE, others=OTHERS_DUE)
    )
    new_due = "2026-11-04T23:59:00-08:00"
    (root / "course_settings" / "course_settings.toml").write_text(
        _DATED.format(topic=TOPIC_DUE, others=new_due)
    )
    make_current(root)
    os.utime(root / "course_settings" / "course_settings.toml", (0.0, 0.0))
    assert run_sync(_config(), root) is False
    course.create_discussion_topic.assert_not_called()
    topic.update.assert_not_called()  # no REST update_dates for a checkpointed discussion
    (inp,) = _graphql_inputs(course)
    assert inp["checkpoints"][0]["dates"] == [{"type": "everyone", "dueAt": TOPIC_DUE}]
    assert inp["checkpoints"][1]["dates"] == [{"type": "everyone", "dueAt": new_due}]
    assert inp["checkpoints"][1]["repliesRequired"] == 2
    assert _manifest_entry(root)["resolved_dates"]["reply_to_others_due_at"] == new_due


def test_unchanged_dates_send_nothing(tmp_path, mocker) -> None:
    root, course, topic = _synced_cp_repo(
        tmp_path, mocker, _DATED.format(topic=TOPIC_DUE, others=OTHERS_DUE)
    )
    assert run_sync(_config(), root) is False
    assert _graphql_inputs(course) == []
    topic.update.assert_not_called()
