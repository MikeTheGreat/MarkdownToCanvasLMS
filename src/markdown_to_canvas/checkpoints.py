"""Discussion checkpoints: the ``checkpoints`` frontmatter block and its dates.

A checkpointed discussion is a graded discussion split by Canvas into two
graded parts, each with its own points and due date: the student's reply to
the topic, and a number of replies to classmates' posts. In a course repo:

```yaml
unlock_at: "..."            # shared by both checkpoints
lock_at: "..."
checkpoints:
    reply_to_topic:
        points_possible: 1
        due_at: "2026-11-02T23:59:00-08:00"
    reply_to_others:        # Canvas's "reply_to_entry" checkpoint
        points_possible: 1
        replies_required: 2
        due_at: "2026-11-03T23:59:00-08:00"
```

A ``due_dates`` entry in ``course_settings.toml`` gives the two due dates as
``reply_to_topic_due_at`` / ``reply_to_others_due_at`` instead of ``due_at``.

This module is pure: parsing, validation and date resolution, no Canvas calls.
Canvas behavior it relies on is recorded in ARCHITECTURE.md ("Discussion
checkpoints").
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime
from typing import Any

#: The frontmatter key.
KEY = "checkpoints"

REPLY_TO_TOPIC = "reply_to_topic"
REPLY_TO_OTHERS = "reply_to_others"

#: Repo name -> Canvas's checkpoint tag (``sub_assignment_tag`` / GraphQL label).
CANVAS_TAGS = {REPLY_TO_TOPIC: "reply_to_topic", REPLY_TO_OTHERS: "reply_to_entry"}

#: due_dates keys used instead of due_at for a checkpointed discussion.
REPLY_TO_TOPIC_DUE = "reply_to_topic_due_at"
REPLY_TO_OTHERS_DUE = "reply_to_others_due_at"
ENTRY_KEYS = (REPLY_TO_TOPIC_DUE, REPLY_TO_OTHERS_DUE)

#: Keys of a checkpointed discussion's resolved_dates cache, in order.
SYMBOLIC_KEYS = ("unlock_at", REPLY_TO_TOPIC_DUE, REPLY_TO_OTHERS_DUE, "lock_at")

#: Top-level frontmatter keys that conflict with a checkpoints block.
CONFLICTING_KEYS = ("points_possible", "due_at")

_CHECKPOINT_KEYS = {
    REPLY_TO_TOPIC: ("points_possible", "due_at"),
    REPLY_TO_OTHERS: ("points_possible", "replies_required", "due_at"),
}

_SENTINELS = {"none", "keep", "create_none_then_keep"}

#: Stands for "leave this value alone in Canvas" in resolved dates. Not None,
#: because None means "clear it" (GraphQL null).
OMIT = object()


class CheckpointError(ValueError):
    """The frontmatter block or a due_dates entry is invalid.

    ``problems`` holds one message per problem (without the file name).
    """

    def __init__(self, problems: list[str]):
        super().__init__("; ".join(problems))
        self.problems = problems


@dataclass(frozen=True)
class Checkpoint:
    points_possible: float
    due_at: str | None


@dataclass(frozen=True)
class Checkpoints:
    reply_to_topic: Checkpoint
    reply_to_others: Checkpoint
    replies_required: int

    @property
    def total_points(self) -> float:
        return self.reply_to_topic.points_possible + self.reply_to_others.points_possible


def _date_text(value: Any) -> str | None:
    """A YAML/TOML date value as the string sent to Canvas, or None if not a date."""
    if isinstance(value, datetime):
        return value.isoformat()
    if isinstance(value, date):
        return value.isoformat()
    if isinstance(value, str) and value.strip():
        try:
            datetime.fromisoformat(value.strip())
        except ValueError:
            return None
        return value.strip()
    return None


def _with_article(noun: str) -> str:
    return f"{'an' if noun[:1] in 'aeiou' else 'a'} {noun}"


def _is_number(value: Any) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool)


def _earlier_or_equal(first: str, second: str) -> bool | None:
    """True if first <= second; None when the two cannot be compared
    (one has a UTC offset and the other does not)."""
    try:
        return datetime.fromisoformat(first) <= datetime.fromisoformat(second)
    except (TypeError, ValueError):
        return None


def parse(frontmatter: dict[str, Any], canvas_type: str | None) -> Checkpoints | None:
    """Return the file's checkpoints, None when it has no ``checkpoints`` key.

    Raises CheckpointError listing every problem: a block on anything but a
    discussion, unknown or missing keys, bad values, a top-level
    ``points_possible``/``due_at`` beside the block, and a reply-to-topic
    due date after the reply-to-others one.
    """
    if KEY not in frontmatter:
        return None
    block = frontmatter[KEY]
    if canvas_type != "discussion":
        raise CheckpointError(
            [f"'{KEY}' applies only to discussions, not to {_with_article(canvas_type or 'file of this kind')}"]
        )
    problems: list[str] = []
    for key in CONFLICTING_KEYS:
        if key in frontmatter:
            problems.append(
                f"'{key}' may not be set together with '{KEY}' (a checkpointed "
                f"discussion's points are the sum of its checkpoints' points, and its "
                f"due dates are the checkpoints' due dates)"
            )
    if not isinstance(block, dict):
        raise CheckpointError(
            problems + [f"'{KEY}' must be a mapping with '{REPLY_TO_TOPIC}' and '{REPLY_TO_OTHERS}'"]
        )
    for key in block:
        if key not in _CHECKPOINT_KEYS:
            problems.append(
                f"unknown key '{KEY}.{key}' (allowed: {REPLY_TO_TOPIC}, {REPLY_TO_OTHERS})"
            )
    parsed: dict[str, Checkpoint] = {}
    replies_required = 0
    for name, allowed in _CHECKPOINT_KEYS.items():
        where = f"{KEY}.{name}"
        if name not in block:
            problems.append(f"'{where}' is missing")
            continue
        sub = block[name]
        if not isinstance(sub, dict):
            problems.append(f"'{where}' must be a mapping")
            continue
        for key in sub:
            if key not in allowed:
                problems.append(f"unknown key '{where}.{key}' (allowed: {', '.join(allowed)})")
        points = sub.get("points_possible")
        if "points_possible" not in sub:
            problems.append(f"'{where}.points_possible' is missing")
        elif not _is_number(points) or points < 0:
            problems.append(f"'{where}.points_possible' must be a number of at least 0, got {points!r}")
        due_at: str | None = None
        if sub.get("due_at") is not None:
            due_at = _date_text(sub["due_at"])
            if due_at is None:
                problems.append(f"'{where}.due_at' is not a date: {sub['due_at']!r}")
        if name == REPLY_TO_OTHERS:
            count = sub.get("replies_required")
            if "replies_required" not in sub:
                problems.append(f"'{where}.replies_required' is missing")
            elif not isinstance(count, int) or isinstance(count, bool) or count < 1:
                problems.append(f"'{where}.replies_required' must be a whole number of at least 1, got {count!r}")
            else:
                replies_required = count
        if _is_number(points) and points >= 0:
            parsed[name] = Checkpoint(float(points), due_at)
    topic, others = parsed.get(REPLY_TO_TOPIC), parsed.get(REPLY_TO_OTHERS)
    if topic and others and topic.due_at and others.due_at:
        if _earlier_or_equal(topic.due_at, others.due_at) is False:
            problems.append(
                f"'{KEY}.{REPLY_TO_TOPIC}.due_at' ({topic.due_at}) is after "
                f"'{KEY}.{REPLY_TO_OTHERS}.due_at' ({others.due_at})"
            )
    if problems:
        raise CheckpointError(problems)
    assert topic is not None and others is not None
    return Checkpoints(topic, others, replies_required)


def entry_problems(
    entry: dict[str, Any] | None, checkpoints: Checkpoints | None, canvas_type: str | None
) -> list[str]:
    """Problems with a content file's matched due_dates entry, given its checkpoints."""
    if entry is None:
        return []
    name = entry.get("name", "?")
    present = [k for k in ENTRY_KEYS if k in entry]
    problems: list[str] = []
    if checkpoints is not None:
        if "due_at" in entry:
            problems.append(
                f"due_dates entry {name!r} has 'due_at', but the discussion has '{KEY}'; "
                f"use '{REPLY_TO_TOPIC_DUE}' and '{REPLY_TO_OTHERS_DUE}' instead"
            )
        topic, others = entry.get(REPLY_TO_TOPIC_DUE), entry.get(REPLY_TO_OTHERS_DUE)
        topic_text, others_text = _date_text(topic), _date_text(others)
        if topic_text and others_text and _earlier_or_equal(topic_text, others_text) is False:
            problems.append(
                f"due_dates entry {name!r}: '{REPLY_TO_TOPIC_DUE}' ({topic_text}) is after "
                f"'{REPLY_TO_OTHERS_DUE}' ({others_text})"
            )
    elif present:
        what = "discussion without a 'checkpoints' block" if canvas_type == "discussion" else (
            canvas_type or "item"
        )
        problems.append(
            f"due_dates entry {name!r} has {', '.join(repr(k) for k in present)}, which only "
            f"a discussion with '{KEY}' may have, but it matches {_with_article(what)}"
        )
    return problems


def _resolve_value(
    value: Any, *, creating: bool, key: str, empty_keys: list[str]
) -> Any:
    """A due_dates value -> a date string, None (clear) or OMIT (leave alone)."""
    if isinstance(value, str) and value.strip().lower() in _SENTINELS:
        sentinel = value.strip().lower()
        if sentinel == "none":
            return None
        if sentinel == "keep":
            return OMIT
        return None if creating else OMIT
    text = _date_text(value)
    if text:
        return text
    empty_keys.append(key)
    return OMIT


@dataclass(frozen=True)
class ResolvedDates:
    """Each value is a date string, None (clear in Canvas) or OMIT (leave alone)."""

    unlock_at: Any
    lock_at: Any
    reply_to_topic_due_at: Any
    reply_to_others_due_at: Any
    #: due_dates keys whose value was empty (treated as KEEP, warned about).
    empty_keys: tuple[str, ...] = ()


def resolve_dates(
    frontmatter: dict[str, Any],
    checkpoints: Checkpoints,
    entry: dict[str, Any] | None,
    *,
    creating: bool,
) -> ResolvedDates:
    """The four dates to send, from the frontmatter overridden by the due_dates entry.

    ``creating`` is true when the topic is being created or converted to a
    checkpointed one (CREATE_NONE_THEN_KEEP then clears the date). A key
    absent from both the entry and the frontmatter is left alone.
    """
    fm_values = {
        "unlock_at": _date_text(frontmatter.get("unlock_at")) or OMIT,
        "lock_at": _date_text(frontmatter.get("lock_at")) or OMIT,
        REPLY_TO_TOPIC_DUE: checkpoints.reply_to_topic.due_at or OMIT,
        REPLY_TO_OTHERS_DUE: checkpoints.reply_to_others.due_at or OMIT,
    }
    empty: list[str] = []
    values = dict(fm_values)
    if entry is not None:
        for key in SYMBOLIC_KEYS:
            if key in entry:
                values[key] = _resolve_value(entry[key], creating=creating, key=key, empty_keys=empty)
    return ResolvedDates(
        unlock_at=values["unlock_at"],
        lock_at=values["lock_at"],
        reply_to_topic_due_at=values[REPLY_TO_TOPIC_DUE],
        reply_to_others_due_at=values[REPLY_TO_OTHERS_DUE],
        empty_keys=tuple(empty),
    )


def graphql_checkpoints(checkpoints: Checkpoints, dates: ResolvedDates) -> list[dict[str, Any]]:
    """The ``checkpoints`` input of Canvas's discussion-topic mutations.

    Per measurement (2026-11-02), an omitted dueAt/unlockAt/lockAt leaves the
    value unchanged and an explicit null clears it.
    """

    def date_entry(due: Any) -> dict[str, Any]:
        out: dict[str, Any] = {"type": "everyone"}
        for gql_key, value in (("dueAt", due), ("unlockAt", dates.unlock_at), ("lockAt", dates.lock_at)):
            if value is not OMIT:
                out[gql_key] = value
        return out

    return [
        {
            "checkpointLabel": CANVAS_TAGS[REPLY_TO_TOPIC],
            "pointsPossible": checkpoints.reply_to_topic.points_possible,
            "dates": [date_entry(dates.reply_to_topic_due_at)],
        },
        {
            "checkpointLabel": CANVAS_TAGS[REPLY_TO_OTHERS],
            "pointsPossible": checkpoints.reply_to_others.points_possible,
            "repliesRequired": checkpoints.replies_required,
            "dates": [date_entry(dates.reply_to_others_due_at)],
        },
    ]


def feature_off_message(local_key: str) -> str:
    """The error for a checkpointed discussion in a course without the feature."""
    return (
        f"ERROR: {local_key}: this course's Canvas account does not have Discussion "
        f"Checkpoints turned on, so checkpoints cannot be used in this course. The "
        f"discussion was not uploaded. To upload it without checkpoints, comment out the "
        f"'{KEY}' block and use instead:\n"
        f"      points_possible: <the combined points of both checkpoints>\n"
        f"      due_at: <the reply-to-others date> (or due_at in its due_dates entry, in "
        f"place of {REPLY_TO_TOPIC_DUE}/{REPLY_TO_OTHERS_DUE})\n"
        f"      require_initial_post: true\n"
        f"    and write the earlier reply-to-topic deadline into the discussion's body, "
        f"for example as a virtual due_dates entry quoted with a "
        f'[date]{{.replace_date_with item="..."}} placeholder.'
    )
