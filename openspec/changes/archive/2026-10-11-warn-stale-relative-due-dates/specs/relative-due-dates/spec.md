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
to every table and which a table SHALL NOT set. It MAY also hold
`last_generated_hash`, written by `generate-due-dates` (see the
`stale-relative-due-dates-warning` capability), which is not a setting, does not
affect any calculation, and which a table SHALL NOT set. It SHALL also hold
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

#### Scenario: Fingerprint in the section
- **WHEN** the section has `last_generated_hash`
- **THEN** `generate-due-dates` accepts it and computes the same dates as without it

#### Scenario: Fingerprint set on a table
- **WHEN** the table `summer8` sets `last_generated_hash`
- **THEN** the command fails with an unknown-key error naming `last_generated_hash` and the table, and nothing is written
