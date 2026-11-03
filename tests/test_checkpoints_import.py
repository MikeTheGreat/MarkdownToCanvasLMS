"""Importing a checkpointed discussion from an IMSCC export, and the round trip
through `update` (mocked Canvas)."""
from __future__ import annotations

import shutil
import tomllib
from pathlib import Path
from unittest.mock import MagicMock

import pytest

from markdown_to_canvas import checkpoints as cp
from markdown_to_canvas.config import Config
from markdown_to_canvas.convert import parse_frontmatter
from markdown_to_canvas.imscc_import import parse_topic_meta, run_import
from markdown_to_canvas.sync import run_targeted_sync

FIXTURE_DIR = Path(__file__).parent / "fixtures" / "imscc"

# Shaped like the topicMeta of "Discussion Checkpoints Experiment" in a real
# Canvas export (coll101-ol3-12086-f26-college-strategies-export.imscc),
# trimmed to the elements the importer reads.
TOPIC_META = """\
<?xml version="1.0" encoding="UTF-8"?>
<topicMeta identifier="g_cp_meta" xmlns="http://canvas.instructure.com/xsd/cccv1p0"
           xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance">
  <topic_id>g_cp</topic_id>
  <title>Discussion Checkpoints Experiment</title>
  <type>topic</type>
  <discussion_type>threaded</discussion_type>
  <has_group_category>false</has_group_category>
  <workflow_state>unpublished</workflow_state>
  <assignment identifier="g_cp_assignment">
    <title>Discussion Checkpoints Experiment</title>
    <due_at/>
    <lock_at>2026-11-05T07:59:59</lock_at>
    <unlock_at>2026-11-01T07:00:00</unlock_at>
    <workflow_state>unpublished</workflow_state>
    <points_possible>2.0</points_possible>
    <grading_type>points</grading_type>
    <submission_types>discussion_topic</submission_types>
    <sub_assignments>
      <sub_assignment identifier="g_cp_rtt" tag="reply_to_topic">
        <title>Discussion Checkpoints Experiment</title>
        <due_at>2026-11-03T07:59:59</due_at>
        <lock_at>2026-11-05T07:59:59</lock_at>
        <unlock_at>2026-11-01T07:00:00</unlock_at>
        <points_possible>1.0</points_possible>
      </sub_assignment>
      <sub_assignment identifier="g_cp_rte" tag="reply_to_entry">
        <title>Discussion Checkpoints Experiment</title>
        <due_at>2026-11-04T07:59:59</due_at>
        <lock_at>2026-11-05T07:59:59</lock_at>
        <unlock_at>2026-11-01T07:00:00</unlock_at>
        <points_possible>1.0</points_possible>
      </sub_assignment>
    </sub_assignments>
  </assignment>
  <reply_to_entry_required_count>1</reply_to_entry_required_count>
</topicMeta>
"""

TOPIC = """\
<?xml version="1.0" encoding="UTF-8"?>
<topic xmlns="http://www.imsglobal.org/xsd/imsccv1p1/imsdt_v1p1">
  <title>Discussion Checkpoints Experiment</title>
  <text texttype="text/html">&lt;p&gt;Write your headline.&lt;/p&gt;</text>
</topic>
"""

RESOURCES = """\
    <resource identifier="g_cp" type="imsdt_xmlv1p1" href="g_cp.xml">
      <file href="g_cp.xml"/>
      <dependency identifierref="g_cp_meta"/>
    </resource>
    <resource identifier="g_cp_meta"
              type="associatedcontent/imscc_xmlv1p1/learning-application-resource"
              href="g_cp_meta.xml">
      <file href="g_cp_meta.xml"/>
    </resource>

    <!-- Quiz -->"""

EXPECTED_FRONTMATTER = """\
---
title: "Discussion Checkpoints Experiment"
published: false
require_initial_post: false
checkpoints:
    reply_to_topic:
        points_possible: 1.0
        # due_at: "2026-11-03T07:59:59"
    # reply_to_others: each student's replies to other students' posts (Canvas's "Required Replies" checkpoint)
    reply_to_others:
        points_possible: 1.0
        replies_required: 1
        # due_at: "2026-11-04T07:59:59"
    # Due dates are managed centrally in course_settings/course_settings.toml
    # unlock_at: "2026-11-01T07:00:00"
    # lock_at: "2026-11-05T07:59:59"
---
"""


def _cartridge(tmp_path: Path) -> Path:
    src = tmp_path / "imscc"
    shutil.copytree(FIXTURE_DIR, src)
    (src / "g_cp.xml").write_text(TOPIC)
    (src / "g_cp_meta.xml").write_text(TOPIC_META)
    manifest = src / "imsmanifest.xml"
    text = manifest.read_text()
    assert text.count("    <!-- Quiz -->") == 1
    manifest.write_text(text.replace("    <!-- Quiz -->", RESOURCES))
    return src


@pytest.fixture(scope="module")
def imported(tmp_path_factory) -> Path:
    tmp = tmp_path_factory.mktemp("cp_import")
    out = tmp / "course"
    run_import(_cartridge(tmp), out)
    return out


def _md(imported: Path) -> Path:
    return imported / "discussions" / "discussion-checkpoints-experiment.md"


def test_parse_topic_meta(tmp_path) -> None:
    path = tmp_path / "meta.xml"
    path.write_text(TOPIC_META)
    fields = parse_topic_meta(path)
    assert "points_possible" not in fields and "due_at" not in fields
    assert fields["checkpoints"] == {
        "reply_to_topic": {"points_possible": 1.0, "_due_at": "2026-11-03T07:59:59"},
        "reply_to_others": {"points_possible": 1.0, "replies_required": 1, "_due_at": "2026-11-04T07:59:59"},
    }
    assert fields["unlock_at"] == "2026-11-01T07:00:00"


def test_missing_required_count_means_one(tmp_path) -> None:
    path = tmp_path / "meta.xml"
    path.write_text(TOPIC_META.replace("<reply_to_entry_required_count>1</reply_to_entry_required_count>", ""))
    assert parse_topic_meta(path)["checkpoints"]["reply_to_others"]["replies_required"] == 1


def test_plain_discussion_is_unchanged(tmp_path) -> None:
    path = tmp_path / "meta.xml"
    path.write_text(FIXTURE_DIR.joinpath("g_discussion_1_meta.xml").read_text())
    fields = parse_topic_meta(path)
    assert "checkpoints" not in fields and fields["points_possible"] == 10.0


def test_frontmatter_text(imported) -> None:
    text = _md(imported).read_text()
    assert text.startswith(EXPECTED_FRONTMATTER)


def test_frontmatter_parses_back_to_a_valid_block(imported) -> None:
    fm, _ = parse_frontmatter(_md(imported).read_text())
    parsed = cp.parse(fm, "discussion")
    assert parsed == cp.Checkpoints(cp.Checkpoint(1.0, None), cp.Checkpoint(1.0, None), 1)


def test_due_dates_row(imported) -> None:
    settings = tomllib.loads((imported / "course_settings" / "course_settings.toml").read_text())
    (entry,) = [e for e in settings["due_dates"] if e["name"] == "Discussion Checkpoints Experiment"]
    assert entry == {
        "name": "Discussion Checkpoints Experiment", "type": "discussion",
        "unlock_at": "2026-11-01T07:00:00",
        "reply_to_topic_due_at": "2026-11-03T07:59:59",
        "reply_to_others_due_at": "2026-11-04T07:59:59",
        "lock_at": "2026-11-05T07:59:59",
    }
    assert list(entry) == ["name", "type", "unlock_at", "reply_to_topic_due_at", "reply_to_others_due_at", "lock_at"]


def test_round_trip_through_update(imported, tmp_path, mocker) -> None:
    root = tmp_path / "course"
    shutil.copytree(imported, root)
    mock_canvas_cls = mocker.patch("markdown_to_canvas.canvas_api.Canvas")
    course = MagicMock()
    course.account_id = 5
    mock_canvas_cls.return_value.get_course.return_value = course
    course.get_assignment_groups.return_value = []
    course.get_rubrics.return_value = []
    course.get_tabs.return_value = []
    topic = MagicMock(id=77, html_url="h", assignment_id=8, assignment=None)
    course.create_discussion_topic.return_value = topic
    calls: list[dict] = []

    def request(method, endpoint, **kwargs):
        resp = MagicMock()
        if method == "GET":
            resp.json.return_value = {"state": "allowed_on"}
        else:
            calls.append(kwargs["json"]["variables"]["input"])
            resp.json.return_value = {"data": {"updateDiscussionTopic": {"errors": None}}}
        return resp

    course._requester.request.side_effect = request
    config = Config(base_url="https://school.instructure.com", course_id=1, api_token="tok")
    had_errors = run_targeted_sync(config, root, [], [str(_md(root))])
    assert had_errors is False
    rest = course.create_discussion_topic.call_args.kwargs["assignment"]
    assert rest["points_possible"] == 2.0 and rest["due_at"] == "2026-11-04T07:59:59"
    (inp,) = calls
    assert inp["checkpoints"] == [
        {"checkpointLabel": "reply_to_topic", "pointsPossible": 1.0,
         "dates": [{"type": "everyone", "dueAt": "2026-11-03T07:59:59",
                    "unlockAt": "2026-11-01T07:00:00", "lockAt": "2026-11-05T07:59:59"}]},
        {"checkpointLabel": "reply_to_entry", "pointsPossible": 1.0, "repliesRequired": 1,
         "dates": [{"type": "everyone", "dueAt": "2026-11-04T07:59:59",
                    "unlockAt": "2026-11-01T07:00:00", "lockAt": "2026-11-05T07:59:59"}]},
    ]
