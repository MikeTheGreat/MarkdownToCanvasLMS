# Spec Delta

## MODIFIED Requirements

### Requirement: Only due_dates entries can be referenced

A placeholder SHALL resolve against the top-level `due_dates` array of
`course_settings.toml`, after entries whose `only_if` is not met by the course
flags of the run have been removed (the same list the dates sent to Canvas come
from). Virtual entries (see the `virtual-due-dates` capability) SHALL be
referenceable in the same way as ordinary entries. An entry matches when its
`name` equals the placeholder's `item` exactly and, when the placeholder gives
`type`, the entry is an ordinary entry whose `type` is that type or is absent;
a placeholder with `type` SHALL NOT match a virtual entry. Nothing else
(content files, `relative_due_dates` tables, the term file) SHALL be consulted.
An entry SHALL be referenceable whether or not any content file has its title.

#### Scenario: Entry of another item
- **WHEN** a page refers to `item="Career Exploration Assignment"` and `due_dates` has that entry
- **THEN** the page shows that entry's date

#### Scenario: Entry removed by only_if
- **WHEN** the only entry named `HW 1` has `only_if = "online"` and the run's flags set `online = false`
- **THEN** a placeholder naming `HW 1` is an unresolved-placeholder error

#### Scenario: Moving files does not affect references
- **WHEN** the file a placeholder names by title is moved with `mv`
- **THEN** the placeholder still resolves to the same entry

#### Scenario: Virtual entry
- **WHEN** a page has `Week 3 begins [x]{.replace_date_with item="Start_of_week_3" format="%A, %B %-d"}` and `due_dates` has a virtual entry `Start_of_week_3` with `due_at = "2026-10-12T23:59:00-07:00"`
- **THEN** the page shows "Week 3 begins Monday, October 12"

#### Scenario: Type filter skips a virtual entry
- **WHEN** a placeholder has `item="Start_of_week_3" type=assignment` and the only entry with that name is virtual
- **THEN** it is an unresolved-placeholder error saying no entry matches
