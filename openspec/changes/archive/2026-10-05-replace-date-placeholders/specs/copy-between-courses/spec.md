# Spec Delta

## ADDED Requirements

### Requirement: Date placeholders the destination cannot resolve produce warnings

For each copied file, and each snippet it includes, `cp` SHALL find every
`replace_date_with` placeholder that names an `item` and SHALL print a warning
when the destination's `course_settings.toml` has no `due_dates` entry with that
`name` (and matching `type`, when the placeholder gives one). A placeholder
without `item` is covered by the existing warning about the item's own
`due_dates` entry and SHALL NOT be warned about again. Warnings SHALL NOT stop
the copy, and `cp` SHALL NOT copy `due_dates` entries.

#### Scenario: Referenced entry missing in the destination
- **WHEN** a copied page has `[x]{.replace_date_with item="Career Exploration Assignment"}` and the destination's `due_dates` has no entry with that name
- **THEN** the page is copied unchanged and a warning names the page and `Career Exploration Assignment`

#### Scenario: Referenced entry present
- **WHEN** the destination's `due_dates` has that entry
- **THEN** no warning is printed for the placeholder
