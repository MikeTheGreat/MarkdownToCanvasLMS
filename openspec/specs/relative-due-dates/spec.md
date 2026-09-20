# relative-due-dates Specification

## Purpose

Defines how a course repo describes due, unlock and lock dates as offsets from
the start of a term, and how those offsets resolve to absolute dates. It
covers the `[relative_due_dates]` section of `course_settings.toml`, the
per-term file, and the arithmetic.

## Requirements

### Requirement: Relative due dates live in one section of course_settings.toml

All relative-due-date settings SHALL be in a single top-level section named
`[relative_due_dates]` of `course_settings/course_settings.toml`. The section
SHALL hold these shared settings, each optional: `days_of_week` (list of
class-day abbreviations `Mon` .. `Sun`), `class_on_noninstructional_days`
(boolean, default `false`), `unlock_relative_default` and
`lock_relative_default` (an offset value as defined below). It SHALL also hold
named tables under `[relative_due_dates.tables.<name>]`. Each table SHALL have
an `items` array, MAY have an `ignore` array of content titles, and MAY
override any of the shared settings. A table's own setting wins over the
shared one. No other top-level key of `course_settings.toml` SHALL carry
relative-due-date settings.

#### Scenario: Table overrides a shared setting
- **WHEN** the section sets `days_of_week = ["Mon", "Wed"]` and the table `summer8` sets `days_of_week = ["Mon", "Tue", "Wed", "Thu"]`
- **THEN** calculations for `summer8` use Monday through Thursday and calculations for any other table use Monday and Wednesday

#### Scenario: Setting absent everywhere
- **WHEN** neither the table nor the section sets `class_on_noninstructional_days`
- **THEN** it is `false`

#### Scenario: Missing class days
- **WHEN** a table contains an item whose offsets use `CLASS_DAY` (or an anchor of `FIRST_CLASS_OF_QUARTER`) and `days_of_week` is set neither on the table nor on the section
- **THEN** the calculation fails with an error naming the item and the missing setting, and nothing is written

### Requirement: Items are keyed by content title

Each entry of a table's `items` array SHALL have a `name` (the title of an
assignment, discussion or quiz, as `due_dates` entries use), MAY have a
`type` (`assignment`, `discussion` or `quiz`) used only to tell apart two
content items with the same title, SHALL have a `relative_to` table with a
`type` of `START_OF_QUARTER`, `FIRST_CLASS_OF_QUARTER`, `NO_DUE_DATE` or
`ASSIGNMENT`, and MAY have `offsets`, `unlock_offset` and `lock_offset`.
When `relative_to.type` is `ASSIGNMENT`, `relative_to.assignment_name` SHALL
name another item of the same table; an anchor never refers to an item of a
different table. An item with the same `name` and `type` (or, without `type`,
the same `name`) as another item in the same table is an error.

#### Scenario: Anchored to another item
- **WHEN** item "Topic Approval" has `relative_to = { type = "ASSIGNMENT", assignment_name = "Find Topics" }` and offsets `["+7 CALENDAR_DAY"]`
- **THEN** its due date is seven calendar days after the computed due date of "Find Topics"

#### Scenario: Anchor names a missing item
- **WHEN** `assignment_name` names an item that is not in the same table
- **THEN** the calculation fails for that item with an error naming both items, and nothing is written

#### Scenario: Anchored to an item with no due date
- **WHEN** item "B" is anchored to item "A" and "A" is anchored to `NO_DUE_DATE`
- **THEN** the calculation fails with an error naming "B" and "A", and nothing is written

#### Scenario: Circular anchors
- **WHEN** item A is anchored to B and B is anchored to A
- **THEN** the calculation fails with an error naming the cycle, and nothing is written

### Requirement: Unknown keys and unreadable values are errors

A key that this capability does not define, in the `[relative_due_dates]`
section, a table, an item, an item's `relative_to`, or the term file, SHALL be
reported as an error naming the key and the allowed keys, and nothing SHALL be
written. The same holds for an offset that does not follow the grammar, a
class-day abbreviation that is not `Mon` through `Sun` (case is ignored), and
a table or item of the wrong kind.

#### Scenario: Misspelled key
- **WHEN** an item has `lock_ofset = "+7 CALENDAR_DAY"`
- **THEN** the command fails with an error naming `lock_ofset` and listing the allowed keys

#### Scenario: Unreadable offset
- **WHEN** an item has the offset `"+7 WEEKS"`
- **THEN** the command fails with an error naming the item and the offset

### Requirement: Term file supplies the dates that change every term

A term file SHALL be a TOML file with: `first_day` and `last_day` (dates,
`YYYY-MM-DD`), `time_zone` (an IANA zone name such as `America/Los_Angeles`),
`default_due_time` (`HH:MM`), `noninstructional_days` (array of tables, each
with `title` and `date`), and optionally `relative_table` (the name of the
table to use). The term file SHALL NOT be read from a fixed location; its path
is an argument of the command. Emitted dates SHALL carry the UTC offset that
the time zone has on that date.

#### Scenario: Offset follows daylight-saving time
- **WHEN** the time zone is `America/Los_Angeles` and two due dates fall on 2026-10-30 and 2026-11-02 with a default due time of 23:59
- **THEN** they are written as `2026-10-30T23:59:00-07:00` and `2026-11-02T23:59:00-08:00`

#### Scenario: Unknown time zone
- **WHEN** `time_zone` is not a valid IANA name
- **THEN** the command fails with an error that names the value and the term file

#### Scenario: Required key missing
- **WHEN** the term file has no `first_day`
- **THEN** the command fails with an error that names the missing key and the term file

### Requirement: Anchors and offsets resolve as in MikesGradingTool

Every anchor and offset SHALL give the same date as MikesGradingTool's
relative-due-date calculation for the same inputs, with two deliberate
differences: the daylight-saving rule in the next requirement, and `-N
CLASS_DAY` (below). The anchors are: `START_OF_QUARTER`
(the term's first day), `FIRST_CLASS_OF_QUARTER` (the first class day on or
after the first day), `NO_DUE_DATE` (no due date), and `ASSIGNMENT` (the
computed due date of the named item). The default due time is applied to the
anchor's date before offsets run. Offsets are applied in list order. They are:
`+N CALENDAR_DAY` and `-N CALENDAR_DAY` (move N calendar days);
`+N CLASS_DAY` and `-N CLASS_DAY` (move to the Nth next or previous day
in `days_of_week`, skipping non-instructional days unless
`class_on_noninstructional_days` is true; the grading tool's backward move
only finds the previous class day when there are one or two class days a
week, so `-N CLASS_DAY` follows the stated meaning instead of copying that); `<Day> NEAREST_CALENDAR_DAY`
(move to the closest date, earlier or later, that falls on that weekday; a date
already on that weekday does not move); and `HH:MM ABS_TIME` (replace the time of day, keep the
date). An item anchored to `NO_DUE_DATE` has no due date. `days_of_week` is read as a
set of weekdays and used in week order, whatever order it is written in.

#### Scenario: Class-day offset
- **WHEN** the first day is Wednesday 2026-09-30, `days_of_week = ["Mon", "Wed"]`, and an item is anchored to `START_OF_QUARTER` with offsets `["+1 CLASS_DAY"]`
- **THEN** its due date is Monday 2026-10-05 at the default due time

#### Scenario: Class-day offset skips a non-instructional day
- **WHEN** 2026-10-21 (a Wednesday) is listed in `noninstructional_days`, `class_on_noninstructional_days` is false, and an item anchored to another item due Monday 2026-10-19 has offsets `["+1 CLASS_DAY"]`
- **THEN** its due date is Monday 2026-10-26

#### Scenario: Previous class day
- **WHEN** `days_of_week = ["Mon", "Wed", "Fri"]`, the first day is Wednesday 2026-09-30, and an item is anchored to `START_OF_QUARTER` with offsets `["-1 CLASS_DAY"]`
- **THEN** its due date is Monday 2026-09-28

#### Scenario: Class days written out of order
- **WHEN** `days_of_week = ["Fri", "Wed", "Mon"]` and an item counts `+1 CLASS_DAY` from Wednesday 2026-09-30
- **THEN** its due date is Friday 2026-10-02

#### Scenario: Nearest weekday
- **WHEN** an item's computed date is Wednesday 2026-10-07 and its next offset is `Fri NEAREST_CALENDAR_DAY`
- **THEN** its due date is Friday 2026-10-09

#### Scenario: Absolute time
- **WHEN** an item has offsets `["+3 CALENDAR_DAY", "17:00 ABS_TIME"]`
- **THEN** the date moves three days and the time of day is 17:00, not the default due time

#### Scenario: First class of the quarter
- **WHEN** the first day is Wednesday 2026-09-30, `days_of_week = ["Mon", "Wed"]`, and an item is anchored to `FIRST_CLASS_OF_QUARTER` with no offsets
- **THEN** its due date is 2026-09-30 at the default due time

### Requirement: Wall-clock time stays fixed across daylight-saving changes

Offsets SHALL be applied to local calendar dates in the term's time zone, and
the UTC offset SHALL be attached to the final local date and time. A due time
of 23:59 SHALL therefore stay 23:59 local time on both sides of a
daylight-saving change. (MikesGradingTool moves the local time by an hour when an
item's own offsets cross a change: an hour early counting forward, an hour late
counting backward, which can move a 23:59 due time to 00:59 on the next day.)

#### Scenario: Due time survives a DST change
- **WHEN** the time zone is `America/Los_Angeles`, the first day is 2026-09-30, the default due time is 23:59, and an item has offsets `["+60 CALENDAR_DAY"]`
- **THEN** its due date is `2026-11-29T23:59:00-08:00`

### Requirement: Lock and unlock offsets are measured from the item's due date

An item's `unlock_offset` and `lock_offset` SHALL each be a string or a list of
strings. Each string is either `NONE` or an offset in the grammar above
(including `HH:MM ABS_TIME`); the offsets of a list are applied in order,
starting from the item's own computed due date. `NONE` SHALL be the only
element when it is used. The result is the item's `unlock_at` or `lock_at`.
When an item has no `unlock_offset` (or `lock_offset`), the table's setting
`unlock_relative_default` (or `lock_relative_default`) applies, then the
shared one. When none is set, the field is `KEEP`. When an item has no due
date and the rule for lock or unlock is an offset (not `NONE`), the field is
`KEEP` and a warning naming the item is printed; a `NONE` rule needs no due
date.

#### Scenario: Lock a week after the due date
- **WHEN** `lock_relative_default = "+7 CALENDAR_DAY"` and an item due `2026-10-05T23:59:00-07:00` has no `lock_offset`
- **THEN** its lock date is `2026-10-12T23:59:00-07:00`

#### Scenario: Unlock at the start of the quarter
- **WHEN** an item's `unlock_offset` is `NONE`
- **THEN** its `unlock_at` is `NONE`

#### Scenario: List with an absolute time
- **WHEN** an item due 2026-10-05 has `lock_offset = ["+7 CALENDAR_DAY", "08:00 ABS_TIME"]`
- **THEN** its lock date is 2026-10-12 at 08:00 local time

#### Scenario: Item's rule wins over the default
- **WHEN** `lock_relative_default = "+7 CALENDAR_DAY"` and an item sets `lock_offset = "+2 CALENDAR_DAY"`
- **THEN** the item locks two days after its due date

#### Scenario: No rule anywhere
- **WHEN** neither the item nor the table nor the section sets a lock rule
- **THEN** the item's `lock_at` is `KEEP`

#### Scenario: Lock rule but no due date
- **WHEN** an item is anchored to `NO_DUE_DATE` and a lock rule applies to it
- **THEN** its `due_at` is `NONE`, its `lock_at` is `KEEP`, and a warning names the item

### Requirement: Selecting a table

The table used SHALL be the one named by `--table`, else the term file's
`relative_table`. When neither is given and the section has exactly one table,
that table SHALL be used. When neither is given and there are several, the
command SHALL fail with an error that lists the table names. A name that
matches no table SHALL fail with an error that lists the table names.

#### Scenario: One table, no selection
- **WHEN** the section has only `[relative_due_dates.tables.default]` and no table is named
- **THEN** that table is used

#### Scenario: Several tables, no selection
- **WHEN** the section has tables `quarter11` and `summer8` and neither `--table` nor `relative_table` is given
- **THEN** the command fails with an error listing `quarter11` and `summer8` and changes nothing

#### Scenario: Command line wins
- **WHEN** the term file says `relative_table = "quarter11"` and the user passes `--table summer8`
- **THEN** `summer8` is used

### Requirement: Relative due dates do not affect Canvas course settings

`relative_due_dates` SHALL NOT be sent to Canvas, and a change to it SHALL NOT
cause `update` to send course settings to Canvas. The section SHALL NOT change
what `update` does with `due_dates`.

#### Scenario: Update after editing the relative table
- **WHEN** only `[relative_due_dates]` changed in `course_settings.toml` since the last `update`
- **THEN** `update` makes no course-settings API call
