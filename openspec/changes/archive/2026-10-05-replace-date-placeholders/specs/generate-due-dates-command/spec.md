# Spec Delta

## ADDED Requirements

### Requirement: Date placeholders are checked against the generated dates

After computing its plan, `generate-due-dates` SHALL check every
`replace_date_with` placeholder in the repo's content (the files and snippets
listed under "Where placeholders are expanded" in the `date-placeholders`
capability, honoring `.canvasignore`) against the `due_dates` array as it
would be after the plan is applied. It SHALL use the same resolution rules as
`update` (see the `date-placeholders` capability), except that `only_if` is not
evaluated, consistent with the rest of this command, so every entry counts.
Each placeholder that does not resolve SHALL be reported as an error naming the
file and the placeholder, printed with the plan's other errors before any
prompt. These errors SHALL NOT stop the dates from being written, and SHALL make
the command exit non-zero, as the plan's other errors do. With `--noop` they
SHALL be reported the same way.

#### Scenario: Placeholder names a missing entry
- **WHEN** a discussion has `[x]{.replace_date_with item="HW 9"}` and no `due_dates` entry or table item will be named `HW 9`
- **THEN** `generate-due-dates` reports an error naming the discussion and `HW 9`, writes the plan if confirmed, and exits non-zero

#### Scenario: Entry the plan adds
- **WHEN** a placeholder names `HW 3`, which has no `due_dates` entry yet but is an item of the selected table
- **THEN** no error is reported for it

#### Scenario: Entry with no due date
- **WHEN** a placeholder quotes `due_at` of an entry whose `due_at` will be `NONE`
- **THEN** an error is reported for it
