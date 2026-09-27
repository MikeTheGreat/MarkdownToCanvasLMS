# Spec Delta

## Purpose

Lets a course repo declare its group sets/group categories, attach discussions
and assignments to them by name, and recreate both on any Canvas course
(including a brand-new one) through `update` and from a Canvas export through
`import`.

## ADDED Requirements

### Requirement: course_settings.toml lists the group sets/group categories

`course_settings/course_settings.toml` SHALL accept a top-level key
`group_categories` whose value is an array of strings, each the name of a group
set/group category, for example
`group_categories = ["Project Groups", "Study Buddies"]`. A value that is not an
array, an element that is not a string or is empty after trimming surrounding
whitespace, or two elements that are equal after trimming SHALL be a
configuration error that stops `update` before it changes anything on Canvas. A
repo with no `group_categories` key SHALL behave as if the list were empty.

#### Scenario: Valid list
- **WHEN** `course_settings.toml` contains `group_categories = ["Project Groups", "Study Buddies"]`
- **THEN** `update` reads both names without error

#### Scenario: Empty list
- **WHEN** `course_settings.toml` contains `group_categories = []`
- **THEN** `update` creates no group sets/group categories and makes no group set/group category request to Canvas

#### Scenario: Duplicate names
- **WHEN** `course_settings.toml` contains `group_categories = ["Project Groups", "Project Groups"]`
- **THEN** `update` exits with an error naming the duplicate and changes nothing on Canvas

### Requirement: update creates missing group sets/group categories

A full `update` run SHALL, before uploading any content, compare the listed names
with the group sets/group categories that exist in the target Canvas course, by
exact name after trimming surrounding whitespace. For each listed name with no
match it SHALL create an empty group set/group category of that name in the
Canvas course and print a line naming it. It SHALL NOT create groups inside the
group set/group category, place students in groups, rename, change, or delete any
group set/group category, including ones that exist on Canvas but are not listed.
A targeted `update` (`-t`/`-s`) SHALL create a listed group set/group category
that is missing on Canvas when a file it uploads names it.

#### Scenario: Brand-new course
- **WHEN** the repo lists `Project Groups` and the Canvas course has no group set/group category of that name
- **THEN** `update` creates an empty `Project Groups` group set/group category and reports it

#### Scenario: Already exists
- **WHEN** the Canvas course already has a `Project Groups` group set/group category
- **THEN** `update` does not create another and leaves the existing one and its groups unchanged

#### Scenario: Unlisted group set/group category on Canvas
- **WHEN** the Canvas course has a `Lab Partners` group set/group category that the repo does not list
- **THEN** `update` leaves it unchanged

#### Scenario: Check-only run
- **WHEN** `update --check-all` runs on a repo that lists `Project Groups`
- **THEN** nothing is created on Canvas and Canvas is not contacted

### Requirement: Discussions and assignments name their group set/group category

A discussion or assignment file's frontmatter SHALL accept `group_category_id`
whose value is either a string naming a group set/group category or an integer
Canvas group set/group category ID. When the value is a string, `update` SHALL
resolve it to the Canvas ID of the group set/group category of that name in the
target course, where the name MUST appear in the repo's `group_categories`
list, even when a group set/group category of that name already exists on
Canvas. The resolved ID SHALL be sent to Canvas, making the discussion a group
discussion or the assignment a group assignment. An integer value SHALL be sent
unchanged. The same repo file SHALL resolve to each target course's own ID when
synced with different `--config` files.

#### Scenario: Group discussion by name
- **WHEN** `discussions/team-plan.md` has `group_category_id: "Project Groups"`, the repo lists `Project Groups`, and the Canvas course's `Project Groups` has ID 812
- **THEN** `update` creates or updates the discussion as a group discussion of group set/group category 812

#### Scenario: Two courses from one repo
- **WHEN** the same file is synced with `canvas-ol-3.toml` (where `Project Groups` is ID 812) and `canvas-ol-4.toml` (where it is ID 907)
- **THEN** the OL-3 discussion uses 812 and the OL-4 discussion uses 907

#### Scenario: Group assignment by name
- **WHEN** an assignment has `group_category_id: "Project Groups"` and `grade_group_students_individually: true`
- **THEN** `update` makes it a group assignment of that group set/group category, graded individually

#### Scenario: Graded group discussion
- **WHEN** a discussion has `group_category_id: "Project Groups"` and `points_possible: 10`
- **THEN** `update` creates a graded group discussion

#### Scenario: Numeric ID
- **WHEN** a discussion has `group_category_id: 812`
- **THEN** `update` sends 812 unchanged, without looking it up

### Requirement: An unresolvable group set/group category name blocks the file

When a discussion's or assignment's `group_category_id` is a string that is not in
the repo's `group_categories` list, or that cannot be resolved or created on
Canvas, `update` SHALL NOT upload that file (neither create nor update it on
Canvas), SHALL print an error naming the file and the group set/group category
name, SHALL list the error in the end-of-run error summary, and SHALL exit with a
non-zero status. Other files SHALL continue to sync. `update --check-all` SHALL
report the unlisted-name error the same way.

#### Scenario: Name not listed
- **WHEN** a discussion has `group_category_id: "Projct Groups"` (typo) and the repo lists only `Project Groups`
- **THEN** the discussion is not created on Canvas, the error names the file and `Projct Groups`, and the run exits non-zero

#### Scenario: Check-only catches it
- **WHEN** the same repo is checked with `update --check-all`
- **THEN** the same error is reported

#### Scenario: Exists on Canvas but not listed
- **WHEN** a discussion has `group_category_id: "Lab Partners"`, the Canvas course has a `Lab Partners` group set/group category, and the repo's list does not include it
- **THEN** the discussion is not uploaded and the error says to add `Lab Partners` to `group_categories` in `course_settings.toml`

### Requirement: update never changes a group set/group category under student work

When a discussion or assignment already exists on Canvas, `update` SHALL:
- not send the group set/group category when Canvas already has the resolved one;
- set it on an item that has none only if the discussion has no replies or the
  assignment has no submissions;
- never replace one group set/group category with a different one.

In the refused cases `update` SHALL NOT upload the file, SHALL print an error
naming the file and saying to change the group set/group category in Canvas, and
SHALL exit non-zero.

#### Scenario: Unchanged after students post
- **WHEN** a group discussion with student replies is re-synced with the same `group_category_id`
- **THEN** the body and other settings are updated and no group set/group category value is sent

#### Scenario: Adding a group set/group category to an unused discussion
- **WHEN** an existing discussion with no replies gains `group_category_id: "Project Groups"`
- **THEN** it becomes a group discussion

#### Scenario: Adding one after replies
- **WHEN** an existing whole-class discussion with replies gains `group_category_id: "Project Groups"`
- **THEN** the file is not uploaded and an error says to change it in Canvas

#### Scenario: Switching group sets/group categories
- **WHEN** a group discussion using `Project Groups` is edited to `group_category_id: "Study Buddies"`
- **THEN** the file is not uploaded and an error says to change it in Canvas

### Requirement: Removing group_category_id leaves Canvas unchanged

When `group_category_id` is absent from a discussion's or assignment's frontmatter,
`update` SHALL NOT send any group set/group category value, so an existing group
setting on Canvas is left as it is. The README SHALL state that removing the key
does not turn a group discussion back into a whole-class discussion (or a group
assignment into an individual one), and that this has to be done in Canvas.

#### Scenario: Key removed after sync
- **WHEN** a discussion that was synced as a group discussion has its `group_category_id` line deleted and is synced again
- **THEN** the discussion on Canvas remains a group discussion

### Requirement: Announcements do not take group_category_id

`group_category_id` in an announcement's frontmatter SHALL be reported with the
existing "ignoring frontmatter field" warning and not sent to Canvas.

#### Scenario: Announcement with the key
- **WHEN** an announcement has `group_category_id: "Project Groups"`
- **THEN** `update` warns that it is ignoring `group_category_id` and posts the announcement without it

### Requirement: import carries group sets/group categories over

When the Canvas export marks a discussion topic (in its topic metadata) or an
assignment (in its assignment settings) as belonging to a group set/group
category, `import` SHALL write `group_category_id: "<group set/group category
name>"` as active frontmatter in that discussion's or assignment's Markdown file.
`import` SHALL always write a top-level `group_categories` array in the
`course_settings.toml` it creates, holding each distinct group set/group category
name found in the export in first-seen order. An export with no group
sets/group categories SHALL produce `group_categories = []` and no
`group_category_id` keys.

#### Scenario: Group discussion in export
- **WHEN** a discussion's topic metadata has `has_group_category` true and `group_category` `Project Groups`
- **THEN** the imported discussion's frontmatter has `group_category_id: "Project Groups"`

#### Scenario: Group assignment in export
- **WHEN** an assignment's settings have `group_category` `Project Groups`
- **THEN** the imported assignment's frontmatter has `group_category_id: "Project Groups"`

#### Scenario: List written once per name
- **WHEN** fifteen imported items all use `Project Groups`
- **THEN** `course_settings.toml` has `group_categories = ["Project Groups"]`

#### Scenario: No group sets/group categories in export
- **WHEN** the export has no item with a group set/group category
- **THEN** `course_settings.toml` has `group_categories = []`

#### Scenario: Round trip into a new course
- **WHEN** a course is imported and then synced with `update` into an empty Canvas course
- **THEN** the empty course gets a `Project Groups` group set/group category and the group discussions and group assignments attached to it
