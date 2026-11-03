# Spec Delta

## ADDED Requirements

### Requirement: Reply-to-topic offsets for checkpointed discussions

An item of a `[relative_due_dates]` table MAY have `reply_to_topic_offsets`, a list of offset strings in the grammar used by `offsets` (an empty list is an error). An item with this key is a checkpointed-discussion item: its ordinary anchor and `offsets` SHALL compute its overall due date, which is the due date of its reply-to-others checkpoint, and `reply_to_topic_offsets` SHALL be applied, in order, to that date to give the due date of its reply-to-topic checkpoint. The arithmetic, time zone and daylight-saving rules SHALL be those of `offsets`, and an `HH:MM ABS_TIME` in `reply_to_topic_offsets` SHALL set that checkpoint's time of day. The item's `unlock_offset` and `lock_offset` SHALL apply to the overall due date. A virtual item, or an item whose `type` is given and is not `discussion`, SHALL NOT have the key; either is an error naming the item. A reply-to-topic date later than the overall due date SHALL be an error naming the item, and nothing SHALL be written. Like other computed due dates, the reply-to-topic date SHALL be checked against the term's range.

#### Scenario: Reply-to-topic date two days earlier
- **WHEN** an item's offsets give an overall due date of Tuesday 2026-11-03 23:59 and it has `reply_to_topic_offsets = ["-2 CALENDAR_DAY"]`
- **THEN** its reply-to-others date is 2026-11-03 23:59 and its reply-to-topic date is Sunday 2026-11-01 23:59

#### Scenario: Explicit time for the earlier checkpoint
- **WHEN** an item has `reply_to_topic_offsets = ["-1 CALENDAR_DAY", "17:00 ABS_TIME"]` and an overall due date of 2026-11-03 23:59
- **THEN** its reply-to-topic date is 2026-11-02 17:00

#### Scenario: Earlier checkpoint after the overall date
- **WHEN** an item has `reply_to_topic_offsets = ["+1 CALENDAR_DAY"]`
- **THEN** the command fails with an error naming the item, and nothing is written

#### Scenario: Virtual item with the key
- **WHEN** a virtual item has `reply_to_topic_offsets`
- **THEN** the command fails with an error naming the item, and nothing is written

### Requirement: Anchoring to a checkpointed discussion

An `ASSIGNMENT` anchor that names a checkpointed-discussion item SHALL count from that item's overall (reply-to-others) due date.

#### Scenario: Anchor on a checkpointed discussion
- **WHEN** item B has `relative_to = {type = "ASSIGNMENT", assignment_name = "Unit 02 Forum"}` and "Unit 02 Forum" has a reply-to-others date of 2026-11-03 and a reply-to-topic date of 2026-11-01
- **THEN** B's offsets count from 2026-11-03
