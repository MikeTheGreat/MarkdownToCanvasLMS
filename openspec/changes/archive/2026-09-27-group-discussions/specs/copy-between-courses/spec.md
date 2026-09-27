# Spec Delta

## ADDED Requirements

### Requirement: Group sets/group categories are merged into the destination

For each copied file (assignment or discussion) whose frontmatter has
`group_category_id` set to a string name, `cp` SHALL check the destination's
top-level `group_categories` array in `course_settings/course_settings.toml`. If
the name is already there (compared after trimming surrounding whitespace), `cp`
SHALL leave the destination's list unchanged. If it is not, `cp` SHALL append the
name to the end of the array, creating `group_categories = [...]` before the first
table or array-of-tables header when the key is absent, leave the rest of the file
unchanged (other keys, comments, layout), and print a line naming the added group
set/group category. A name used by several copied files SHALL be added once. With
`--noop`, `cp` SHALL report the name it would add and change nothing. A numeric
`group_category_id` SHALL NOT be added (it is covered by the course-specific
warnings).

#### Scenario: Name missing in destination
- **WHEN** a copied discussion has `group_category_id: "Project Groups"` and the destination has `group_categories = ["Study Buddies"]`
- **THEN** the destination's line becomes `group_categories = ["Study Buddies", "Project Groups"]`, the rest of the file is unchanged, and a line reports the addition

#### Scenario: Name present in destination
- **WHEN** the destination already lists `Project Groups`
- **THEN** the destination's `course_settings.toml` is unchanged and nothing is reported for it

#### Scenario: Key absent in destination
- **WHEN** the destination's `course_settings.toml` has no `group_categories` key
- **THEN** `group_categories = ["Project Groups"]` is added above its first table

#### Scenario: Several files, one name
- **WHEN** three copied files all use `Project Groups` and the destination does not list it
- **THEN** `Project Groups` is added once

#### Scenario: Noop
- **WHEN** the same copy runs with `--noop`
- **THEN** the output says `Project Groups` would be added and no file changes

## MODIFIED Requirements

### Requirement: Course-specific values produce warnings

Copied files SHALL be written byte-identical to the source (frontmatter included).
`cp` SHALL print a warning for each copied file that:
- has an `assignment_group_id` name not defined in the destination's `course_settings.toml`;
- has a numeric `group_category_id`, `final_grader_id` or `assignment_group_id`;
- uses a course flag (in `published_if` or an `#if`/`#elif` directive) that the destination does not define;
- has a title matching an entry in the source's `due_dates` table, or an item in the source's `relative_due_dates` tables, saying those dates were not copied;
- has the same title and content type as a different existing file in the destination;
- contains an absolute URL to the source course on Canvas (`/courses/<source course id>/`), when the source course id is known from the source repo's `canvas.toml`.

A `group_category_id` name is not warned about; it is merged into the destination
(see "Group sets/group categories are merged into the destination").

Warnings SHALL NOT stop the copy.

#### Scenario: Unknown assignment group
- **WHEN** a copied assignment has `assignment_group_id: "Labs"` and the destination defines no `Labs` group
- **THEN** the file is copied unchanged and a warning names the file and the group

#### Scenario: Numeric group set/group category ID
- **WHEN** a copied assignment has `group_category_id: 34`
- **THEN** a warning says 34 is a Canvas ID from the source course

#### Scenario: Centralized due date
- **WHEN** the source's `due_dates` has an entry titled `HW 1` and a copied assignment is titled `HW 1`
- **THEN** a warning says the due dates for `HW 1` live in the source's `course_settings.toml` and were not copied

#### Scenario: Title collision
- **WHEN** the destination already has `assignments/old-hw1.md` titled `HW 1` and the copied `assignments/hw1.md` is also titled `HW 1`
- **THEN** a warning names both files
