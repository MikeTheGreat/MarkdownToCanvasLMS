# Spec Delta

## MODIFIED Requirements

### Requirement: Term file supplies the dates that change every term

A term file SHALL be a TOML file with: `first_day` and `last_day` (dates,
`YYYY-MM-DD`), `time_zone` (an IANA zone name such as `America/Los_Angeles`),
`default_due_time` (`HH:MM`), and `noninstructional_days` (array of tables, each
with `title` and `date`). A term file SHALL NOT name the table to use; the key
`relative_table` is not part of the format and SHALL be reported as an unknown
key like any other. The term file SHALL NOT be read from a fixed location; it is
named by an argument of the command, as a path or a term name (see the
`course-registry` capability). Emitted dates SHALL carry the UTC offset that
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

#### Scenario: Old relative_table key
- **WHEN** the term file has `relative_table = "quarter11"`
- **THEN** the command fails with an error that names `relative_table` and the term file, lists the allowed keys, says to use `--table`, and changes nothing

### Requirement: Selecting a table

The table used SHALL be the one named by `--table`, else the table named
`default`. When `--table` is not given and the section has no table named
`default`, the command SHALL fail with an error that lists the table names and
says to use `--table`, even when the section has exactly one other table. A name
that matches no table SHALL fail with an error that lists the table names.

#### Scenario: No selection
- **WHEN** the section has tables `default` and `summer8` and `--table` is not given
- **THEN** `default` is used

#### Scenario: One table, no selection
- **WHEN** the section has only `[relative_due_dates.tables.default]` and no table is named
- **THEN** that table is used

#### Scenario: Several tables, no selection
- **WHEN** the section has tables `quarter11` and `summer8` and `--table` is not given
- **THEN** the command fails with an error listing `quarter11` and `summer8`, telling the user to use `--table`, and changes nothing

#### Scenario: One table not named default
- **WHEN** the section has only `quarter11` and `--table` is not given
- **THEN** the command fails with an error listing `quarter11` and telling the user to use `--table`

#### Scenario: Command line wins
- **WHEN** the section has tables `default` and `summer8` and the user passes `--table summer8`
- **THEN** `summer8` is used
