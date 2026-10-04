# Spec Delta

## MODIFIED Requirements

### Requirement: Relative due dates live in one section of course_settings.toml

All relative-due-date settings SHALL be in a single top-level section named
`[relative_due_dates]` of `course_settings/course_settings.toml`. The section
SHALL hold these shared settings, each optional: `days_of_week` (list of
class-day abbreviations `Mon` .. `Sun`), `class_on_noninstructional_days`
(boolean, default `false`), `unlock_relative_default` and
`lock_relative_default` (an offset value as defined below), and
`default_unlock_time` and `default_lock_time` (`"HH:MM"`, see "Default unlock
and lock times"). It MAY also hold
`dont_reschedule_dates_before` (see "A cutoff for rescheduling"), which applies
to every table and which a table SHALL NOT set. It SHALL also hold
named tables under `[relative_due_dates.tables.<name>]`. Each table SHALL have
an `items` array, MAY have an `ignore` array of content titles, and MAY
override any of the shared settings except `dont_reschedule_dates_before`. A
table's own setting wins over the shared one. No other top-level key of
`course_settings.toml` SHALL carry relative-due-date settings.

#### Scenario: Table overrides a shared setting
- **WHEN** the section sets `days_of_week = ["Mon", "Wed"]` and the table `summer8` sets `days_of_week = ["Mon", "Tue", "Wed", "Thu"]`
- **THEN** calculations for `summer8` use Monday through Thursday and calculations for any other table use Monday and Wednesday

#### Scenario: Setting absent everywhere
- **WHEN** neither the table nor the section sets `class_on_noninstructional_days`
- **THEN** it is `false`

#### Scenario: Missing class days
- **WHEN** a table contains an item whose offsets use `CLASS_DAY` (or an anchor of `FIRST_CLASS_OF_QUARTER`) and `days_of_week` is set neither on the table nor on the section
- **THEN** the calculation fails with an error naming the item and the missing setting, and nothing is written

#### Scenario: Table overrides a default time
- **WHEN** the section sets `default_unlock_time = "00:00"` and the table `summer8` sets `default_unlock_time = "08:00"`
- **THEN** unlock dates computed for `summer8` are at 08:00 and those for any other table at 00:00

#### Scenario: Cutoff set on a table
- **WHEN** the table `summer8` sets `dont_reschedule_dates_before = "2026-07-01"`
- **THEN** the command fails with an unknown-key error naming `dont_reschedule_dates_before` and the table, and nothing is written

## ADDED Requirements

### Requirement: Default unlock and lock times

`default_unlock_time` and `default_lock_time` SHALL each be a time `"HH:MM"`
(24-hour). An unreadable value SHALL be an error naming the key and the value,
and nothing SHALL be written. When `default_unlock_time` (or
`default_lock_time`) applies to an item's table, the item's computed
`unlock_at` (or `lock_at`) SHALL be the date that the rule's offsets give, at
that time of day, unless the item's due time is explicit or the rule sets a
time. The item's due time is explicit when the item's own `offsets` contain an
`HH:MM ABS_TIME` offset; the rule sets a time when the unlock or lock rule that
applies (the item's own or a default rule) contains one. In either of those
cases, and when the setting is absent, the result SHALL be as it is without
these settings: the rule's offsets applied to the due date, keeping its time
unless the rule's `ABS_TIME` replaces it. A `NONE` or `KEEP` result, and an
item with no due date, SHALL NOT be affected.

#### Scenario: Unlock at the start of the day
- **WHEN** `default_unlock_time = "00:00"` and an item due `2026-10-05T23:59:00-07:00` has the unlock rule `"-7 CALENDAR_DAY"`
- **THEN** its `unlock_at` is `2026-09-28T00:00:00-07:00`

#### Scenario: Lock at the end of the day
- **WHEN** `default_lock_time = "23:59"`, the default due time is 17:00, and an item with no `ABS_TIME` offset is due 2026-10-05 at 17:00 with the lock rule `"+7 CALENDAR_DAY"`
- **THEN** its `lock_at` is `2026-10-12T23:59:00-07:00`

#### Scenario: Explicit due time is kept
- **WHEN** `default_lock_time = "23:59"` and an item has offsets `["+1 CLASS_DAY", "17:00 ABS_TIME"]`, a due date of 2026-10-05 at 17:00, and the lock rule `"+7 CALENDAR_DAY"`
- **THEN** its `lock_at` is `2026-10-12T17:00:00-07:00`

#### Scenario: The rule's own time wins
- **WHEN** `default_lock_time = "23:59"` and an item's `lock_offset` is `["+7 CALENDAR_DAY", "08:00 ABS_TIME"]`
- **THEN** its lock time is 08:00

#### Scenario: Settings absent
- **WHEN** neither the table nor the section sets `default_unlock_time` or `default_lock_time`
- **THEN** every computed date is the same as without this requirement

#### Scenario: NONE and KEEP are unaffected
- **WHEN** `default_unlock_time = "00:00"` and an item's unlock rule is `NONE`, or no unlock rule applies
- **THEN** its `unlock_at` is `NONE`, or `KEEP`

#### Scenario: Unreadable time
- **WHEN** `default_lock_time = "25:00"`
- **THEN** the command fails with an error naming `default_lock_time` and the value, and nothing is written

### Requirement: A cutoff for rescheduling

`dont_reschedule_dates_before` in `[relative_due_dates]` SHALL be a string in
one of these forms:

- `""` (empty): there is no cutoff.
- `"YYYY-MM-DD"`: the cutoff is 23:59:59 on that date.
- `"YYYY-MM-DD HH:MM"` (24-hour time, one space between date and time): the
  cutoff is that time on that date.

An absent key SHALL mean the same as `""`. The date and time SHALL be read in
the term file's `time_zone`. Any other value, including a value with a UTC
offset, a `T` separator, seconds, a TOML date or datetime literal, or a
non-string, SHALL be an error that names the key, the value and the two
accepted forms, and nothing SHALL be written.

When a cutoff is set, it SHALL lie within the term: no earlier than 00:00 on
the term file's `first_day` and no later than 23:59:59 on its `last_day`, both
inclusive. A cutoff outside that range SHALL be an error naming the cutoff, the
term file and its first and last day. The error SHALL stop the command before
any date is computed or written.

#### Scenario: Date only means end of day
- **WHEN** the term's time zone is `America/Los_Angeles` and `dont_reschedule_dates_before = "2026-10-01"`
- **THEN** the cutoff is 2026-10-01 23:59:59 Pacific Daylight Time

#### Scenario: Date and time
- **WHEN** `dont_reschedule_dates_before = "2026-10-01 08:30"`
- **THEN** the cutoff is 2026-10-01 08:30:00 in the term's time zone

#### Scenario: Empty value
- **WHEN** `dont_reschedule_dates_before = ""`
- **THEN** there is no cutoff and every date is generated as if the key were absent

#### Scenario: Unreadable value
- **WHEN** `dont_reschedule_dates_before = "2026-10-01T00:00-07:00"`
- **THEN** the command fails with an error naming the key, the value and the two accepted forms, and nothing is written

#### Scenario: Cutoff from an earlier term
- **WHEN** `dont_reschedule_dates_before = "2026-12-18"` and the term file has `first_day = 2027-01-05` and `last_day = 2027-03-20`
- **THEN** the command fails before computing any date, the error names the cutoff, the term file, 2027-01-05 and 2027-03-20, and `course_settings.toml` is not modified

#### Scenario: Cutoff on the last day of the term
- **WHEN** `dont_reschedule_dates_before = "2026-12-18"` and the term's `last_day` is 2026-12-18
- **THEN** the cutoff is accepted
