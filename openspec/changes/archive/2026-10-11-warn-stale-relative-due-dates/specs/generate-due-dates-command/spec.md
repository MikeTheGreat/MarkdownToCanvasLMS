# Spec Delta

## ADDED Requirements

### Requirement: A clean run records last_generated_hash

When a run finishes without errors, `generate-due-dates` SHALL set
`last_generated_hash` at the top level of `[relative_due_dates]` (not inside a
table) to the fingerprint of the section as it was read for that run (see the
`stale-relative-due-dates-warning` capability). A run finishes without errors
when it writes the confirmed changes, or finds nothing to change, and does not
exit with a non-zero status.

When dates are written, the fingerprint SHALL be written in the same write as
the dates. When nothing would change and `last_generated_hash` is absent or
differs from the fingerprint, the command SHALL write only `last_generated_hash`,
without asking (also without a terminal and without `--yes`), and print one line
saying it recorded the fingerprint. When nothing would change and
`last_generated_hash` already equals the fingerprint, the file SHALL NOT be
modified.

The command SHALL NOT write or change `last_generated_hash` when:
- `--noop` is given;
- the user declines the confirmation;
- the run fails without a terminal and without `--yes`;
- it stops with an error and writes nothing (for example a due date outside the
  term);
- it writes dates but exits with a non-zero status (inconsistent entries left
  unchanged under `dont_reschedule_dates_before`, or date placeholders that do
  not resolve).

The rest of `course_settings.toml` SHALL be left as it is, as for any other
write by this command.

#### Scenario: Dates written
- **WHEN** the user confirms a diff that changes two entries
- **THEN** `due_dates` has the two changes and `[relative_due_dates]` has `last_generated_hash` equal to the section's fingerprint

#### Scenario: Nothing to change, no fingerprint yet
- **WHEN** every computed value already equals the entry's current value and the section has no `last_generated_hash`
- **THEN** the command prints that nothing changed, prints that it recorded the fingerprint, does not prompt, and the only change to `course_settings.toml` is the added `last_generated_hash`

#### Scenario: Nothing to change, fingerprint current
- **WHEN** every computed value already equals the entry's current value and `last_generated_hash` equals the fingerprint
- **THEN** `course_settings.toml` is byte-for-byte unchanged

#### Scenario: Declined
- **WHEN** the user answers no at the prompt
- **THEN** `last_generated_hash` is unchanged

#### Scenario: Dry run
- **WHEN** the user runs the command with `--noop`, whether or not anything would change
- **THEN** `course_settings.toml` is byte-for-byte unchanged

#### Scenario: Placeholder errors
- **WHEN** the confirmed changes are written but a date placeholder does not resolve against the new dates, so the command exits with status 1
- **THEN** `due_dates` has the changes and `last_generated_hash` is unchanged

#### Scenario: Inconsistent entry
- **WHEN** an entry is left unchanged because keeping its fields before the cutoff would put it out of order, and the command exits with status 1
- **THEN** `last_generated_hash` is unchanged

## MODIFIED Requirements

### Requirement: Changes are shown before anything is written

The first line of output after the course directory (and, when the term comes
from the course registry, the term file line) SHALL state the cutoff from
`dont_reschedule_dates_before`: its date, time and time zone, or that no cutoff
is set. This line SHALL be printed on every run that gets past validation,
including runs where nothing changes.

Unless `--noop` is given, the command SHALL calculate all dates first, print
each entry that would be added or changed, and ask the user to confirm before
writing. An entry is shown as its name on one line (marked "(new entry)" when
added) followed by the fields in alphabetical order, indented with a tab: `field: old -> new`
for a changed field, `field: value` for an added entry. When the old and new
value of a changed field are both dates, they are printed on two lines
(`field: old`, then `-> new` right-aligned under the field name) so the values
start in the same column. Lines for changes SHALL be shown in yellow when the output is a
terminal; entries whose computed values equal the current ones SHALL be
listed as unchanged, in normal colour, or counted in a summary line.

When one or more resources had a field kept by the cutoff, the output SHALL
include one line giving their number and the cutoff, saying they were not
rescheduled because of `dont_reschedule_dates_before`. With `--verbose`, each
of those resources SHALL be listed under that line, indented with one tab: its
name, its type when the entry has one, and the names of the kept fields. This
line, and the list, SHALL be printed whether or not anything else changes.
Errors for inconsistent entries SHALL be printed with the changes, before the
confirmation prompt.

If the user declines, nothing is written. If nothing would change, the command says
so and does not ask; it writes nothing except `last_generated_hash`, as described
in "A clean run records last_generated_hash". A run without a terminal on
standard input and without `--yes` SHALL fail with an error that says to pass
`--yes`, and write nothing, when there are changes to confirm.
With `--yes`, the confirmation is skipped and the diff is still printed.

#### Scenario: Confirmed
- **WHEN** the user runs the command, sees the diff, and answers yes
- **THEN** `due_dates` is updated as shown

#### Scenario: Declined
- **WHEN** the user answers no
- **THEN** `course_settings.toml` is not modified and the command exits without an error

#### Scenario: Nothing to change
- **WHEN** every computed value already equals the entry's current value
- **THEN** the command prints that nothing changed, does not prompt, and modifies the file only to record `last_generated_hash` when it is absent or out of date

#### Scenario: Hand-edited entry is overwritten visibly
- **WHEN** a user changed an entry's `due_at` by hand to a date after the cutoff (or there is no cutoff) and that item is in the table
- **THEN** the diff lists the entry with the hand-edited value as old and the computed value as new, and it is overwritten only if the user confirms

#### Scenario: No terminal, no --yes
- **WHEN** standard input is not a terminal, `--yes` is absent, and there are changes to confirm
- **THEN** the command exits with a non-zero status, names `--yes`, and writes nothing

#### Scenario: Cutoff shown
- **WHEN** `dont_reschedule_dates_before = "2026-10-01"` and the term's time zone is `America/Los_Angeles`
- **THEN** the output, before any entry, states the cutoff as 2026-10-01 at 11:59 PM with the zone (PDT)

#### Scenario: No cutoff shown
- **WHEN** `dont_reschedule_dates_before` is absent or `""`
- **THEN** the output, before any entry, says no cutoff is set

#### Scenario: Kept resources counted when nothing else changes
- **WHEN** three resources would have had fields changed but every such field was kept by the cutoff, and no other entry changes
- **THEN** the output includes a line saying 3 resources were not rescheduled because of `dont_reschedule_dates_before` and naming the cutoff, says nothing changed, and does not prompt

#### Scenario: Verbose list of kept resources
- **WHEN** the command runs with `--verbose`, "Week 1 Problem Set" had `unlock_at`, `due_at` and `lock_at` kept, and the discussion "Week 2 Discussion" had only `unlock_at` kept
- **THEN** the summary line is followed by one tab-indented line per resource, naming "Week 1 Problem Set" with `unlock_at, due_at, lock_at`, and "Week 2 Discussion" with its type and `unlock_at`

#### Scenario: Without --verbose
- **WHEN** resources had fields kept and `--verbose` is not given
- **THEN** the summary line is printed and the resources are not listed
