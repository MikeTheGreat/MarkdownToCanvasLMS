## MODIFIED Requirements

### Requirement: Items are keyed by content title

Each entry of a table's `items` array SHALL have a `name` (the title of an
assignment, discussion or quiz, as `due_dates` entries use, or, for a virtual
item, a name for a date; see "Virtual items"), MAY have a
`type` (`assignment`, `discussion` or `quiz`) used only to tell apart two
content items with the same title, SHALL have a `relative_to` table with a
`type` of `START_OF_QUARTER`, `FIRST_CLASS_OF_QUARTER`, `NO_DUE_DATE`,
`ASSIGNMENT` or `ABSOLUTE_DATE`, and MAY have `offsets`, `unlock_offset`,
`lock_offset` and `virtual`.
When `relative_to.type` is `ASSIGNMENT`, `relative_to.assignment_name` SHALL
name another item of the same table, virtual or not; an anchor never refers to
an item of a different table. An item with the same `name` and `type` (or,
without `type`, the same `name`) as another item in the same table is an error.

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

## ADDED Requirements

### Requirement: Virtual items

An item with `virtual = true` SHALL be a virtual item: a name for a date that
other items of the same table can count from. `virtual` SHALL be a boolean;
`false` or an absent key means an ordinary item, and any other value SHALL be
an error naming the item. A virtual item's date SHALL be computed from its
`relative_to` and `offsets` exactly as an ordinary item's due date is, and an
item anchored to it with `relative_to = { type = "ASSIGNMENT", assignment_name
= "<virtual name>" }` SHALL count from that date as it would from an ordinary
item's due date.

A virtual item SHALL NOT have `type`, `unlock_offset` or `lock_offset`, and its
`relative_to.type` SHALL NOT be `NO_DUE_DATE`; each of these SHALL be an error
naming the item and the key or anchor, and nothing SHALL be written.

A virtual item's date SHALL be checked against the term in the same way as an
ordinary item's due date: a date before the term file's `first_day` or after
its `last_day` SHALL be reported in the same out-of-term error, and nothing
SHALL be written.

A virtual item SHALL NOT have the same `name` as another item of the same
table, virtual or not; this is the duplicate-name error above.

#### Scenario: Week anchor
- **WHEN** the table has a virtual item `Start_of_week_3` with `relative_to = { type = "START_OF_QUARTER" }` and offsets `["+14 CALENDAR_DAY"]`, and an item "Lab 3" with `relative_to = { type = "ASSIGNMENT", assignment_name = "Start_of_week_3" }` and offsets `["-1 CALENDAR_DAY", "+2 CLASS_DAY"]`
- **THEN** "Lab 3" is due on the second class day on or after the date 14 calendar days after the term's `first_day`, at `default_due_time`

#### Scenario: Virtual anchored to virtual
- **WHEN** virtual item `Start_of_week_4` is anchored to virtual item `Start_of_week_3` with offsets `["+7 CALENDAR_DAY"]`
- **THEN** its date is seven calendar days after `Start_of_week_3`'s date, and items anchored to `Start_of_week_4` count from that date

#### Scenario: Virtual item with a lock rule
- **WHEN** a virtual item has `lock_offset = "+7 CALENDAR_DAY"`
- **THEN** the command fails with an error naming the item and `lock_offset`, and nothing is written

#### Scenario: Virtual item with a type
- **WHEN** a virtual item has `type = "assignment"`
- **THEN** the command fails with an error naming the item and `type`, and nothing is written

#### Scenario: Virtual item with no date
- **WHEN** a virtual item has `relative_to = { type = "NO_DUE_DATE" }`
- **THEN** the command fails with an error naming the item and `NO_DUE_DATE`, and nothing is written

#### Scenario: Not a boolean
- **WHEN** an item has `virtual = "yes"`
- **THEN** the command fails with an error naming the item and `virtual`, and nothing is written

#### Scenario: Virtual date outside the term
- **WHEN** a virtual item `Start_of_week_12` computes to a date after the term's `last_day`
- **THEN** the out-of-term error lists `Start_of_week_12` with its date, and nothing is written

#### Scenario: Same name as an ordinary item
- **WHEN** a table has an ordinary item "Week 3" and a virtual item "Week 3"
- **THEN** the command fails with the duplicate-name error, and nothing is written
