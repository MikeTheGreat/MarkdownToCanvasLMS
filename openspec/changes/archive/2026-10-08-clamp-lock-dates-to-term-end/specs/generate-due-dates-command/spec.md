# Spec Delta

## ADDED Requirements

### Requirement: Clamped lock dates are reported

When `clamp_lock_at_to_last_day_of_term` set one or more `lock_at` values to
the end of the term (see the `relative-due-dates` capability), the output
SHALL include one line giving their total number and the end of the term
(date, time and time zone), split by cause: the number whose computed lock
date was later, and the number whose lock rule was `NONE`. For example:
`4 lock dates set to the term's last day (Fri Dec 18, 2026 11:59 PM PST): 3 were later, 1 was NONE`.
A cause with a count of zero SHALL be left out of the split.

The count SHALL include every entry whose `lock_at` in the plan comes from the
clamp, including entries whose value is unchanged since the last run. It SHALL
NOT include a field kept by `dont_reschedule_dates_before`. With `--verbose`,
each counted resource SHALL be listed under the line, indented with one tab:
its name, its type when the entry has one, and whether it was later or `NONE`.
The line, and the list, SHALL be printed whether or not anything else changes,
and also with `--noop`. When nothing was clamped, or the setting is off, no
line SHALL be printed.

#### Scenario: Both causes
- **WHEN** the setting is true and three items' lock dates fall after the end of the term and one item's lock rule is `NONE`
- **THEN** the output includes a line saying 4 lock dates were set to the term's last day, naming the date with its time and zone, and saying 3 were later and 1 was `NONE`

#### Scenario: One cause only
- **WHEN** the setting is true and two items' lock dates fall after the end of the term and no item has a `NONE` lock rule
- **THEN** the line says 2 lock dates were set to the term's last day, 2 were later, and does not mention `NONE`

#### Scenario: Verbose list
- **WHEN** the command runs with `--verbose` and "Final Project" (an assignment) was later and "Week 10 Discussion" (a discussion) was `NONE`
- **THEN** the summary line is followed by one tab-indented line per resource naming it, its type, and its cause

#### Scenario: Unchanged clamped entry is still counted
- **WHEN** the command runs a second time with the same settings and term, so the clamped lock dates already equal the entries' current values
- **THEN** the output says nothing changed and still includes the clamp line with the same counts

#### Scenario: Kept by the cutoff
- **WHEN** an item's lock rule is `NONE`, its current `lock_at` is a date on or before `dont_reschedule_dates_before`, and the setting is true
- **THEN** its `lock_at` is kept and it is not counted in the clamp line

#### Scenario: Setting off
- **WHEN** the setting is false or absent
- **THEN** no clamp line is printed

### Requirement: import writes the clamp setting commented out

`import` SHALL write the line `# clamp_lock_at_to_last_day_of_term = true`
inside `[relative_due_dates]` of the new `course_settings.toml`, with a comment
above it saying that, when enabled, `generate-due-dates` sets lock dates after
the term file's `last_day`, and lock rules of `NONE`, to `last_day` at 23:59,
that items with no lock rule are left as they are, and that a table may set
the key too. The parsed section SHALL have no
`clamp_lock_at_to_last_day_of_term` key.

#### Scenario: Fresh import
- **WHEN** a user runs `import`
- **THEN** the `[relative_due_dates]` section of the new `course_settings.toml` contains the line `# clamp_lock_at_to_last_day_of_term = true`, and the parsed section has no `clamp_lock_at_to_last_day_of_term` key

#### Scenario: Enabling it
- **WHEN** the user removes the leading `# ` from that line and runs `generate-due-dates`
- **THEN** the setting is true and lock dates are clamped
