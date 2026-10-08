# Spec Delta

## ADDED Requirements

### Requirement: Lock dates clamped to the term's last day

`clamp_lock_at_to_last_day_of_term` SHALL be an optional boolean setting of
`[relative_due_dates]`. A table (`[relative_due_dates.tables.NAME]`) MAY set it
too, and the table's value SHALL override the section's, as for the other
shared settings. When neither sets it, it SHALL be false. A value that is not
`true` or `false` SHALL be an error naming the key, and nothing SHALL be
written.

The end of the term is the term file's `last_day` at 23:59 in the term file's
time zone. When the setting is true for the selected table, each ordinary
(not virtual) item's `lock_at` SHALL be decided as follows, after the lock
rule, `default_lock_time` and any `ABS_TIME` have been applied:

- a computed lock date later than the end of the term SHALL become the end of
  the term;
- a computed lock date at or before the end of the term SHALL be unchanged;
- a `NONE` lock rule SHALL give the end of the term instead of `NONE`, whether
  or not the item has a due date;
- `KEEP` (no lock rule applies, or an offset rule on an item with no due date)
  SHALL be unchanged, so the field in `due_dates` is left as it is.

`unlock_at` and `due_at` SHALL NOT be affected. When the setting is false or
absent, every lock date SHALL be the same as without this requirement.

#### Scenario: Lock date past the term
- **WHEN** the setting is true, `last_day = 2026-12-18`, the time zone is `America/Los_Angeles`, and an item due `2026-12-15T23:59:00-08:00` has the lock rule `"+7 CALENDAR_DAY"`
- **THEN** its `lock_at` is `2026-12-18T23:59:00-08:00`

#### Scenario: Lock date inside the term
- **WHEN** the setting is true, `last_day = 2026-12-18`, and an item's computed lock date is `2026-12-10T23:59:00-08:00`
- **THEN** its `lock_at` is `2026-12-10T23:59:00-08:00`

#### Scenario: NONE becomes the last day
- **WHEN** the setting is true, `last_day = 2026-12-18`, and an item's lock rule is `NONE`
- **THEN** its `lock_at` is `2026-12-18T23:59:00-08:00`

#### Scenario: NONE on an item with no due date
- **WHEN** the setting is true and an item anchored to `NO_DUE_DATE` has the lock rule `NONE`
- **THEN** its `due_at` is `NONE` and its `lock_at` is the end of the term

#### Scenario: KEEP is untouched
- **WHEN** the setting is true and no lock rule applies to an item
- **THEN** its `lock_at` is `KEEP`

#### Scenario: Table overrides the section
- **WHEN** `[relative_due_dates]` sets the key to true, the table `[relative_due_dates.tables.evening]` sets it to false, and `--table evening` is used
- **THEN** no lock date is clamped

#### Scenario: Setting absent
- **WHEN** neither the section nor the table sets the key
- **THEN** an item whose lock rule gives a date after `last_day` keeps that date, and a `NONE` rule gives `NONE`

#### Scenario: Unreadable value
- **WHEN** `clamp_lock_at_to_last_day_of_term = "yes"`
- **THEN** the command fails with an error naming `clamp_lock_at_to_last_day_of_term`, and nothing is written
