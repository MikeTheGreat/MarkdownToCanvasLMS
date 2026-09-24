# copy-between-courses Specification

## Purpose

Lets a user copy course content (pages, assignments, discussions, announcements,
quizzes, question banks, modules) from one course repo into another, together with
the assets, snippets and rubrics that content depends on, so the copy works in the
destination course after the next `update`.

## Requirements

### Requirement: cp command and arguments

The tool SHALL provide a `cp` subcommand invoked as
`cp [--noop|-n] [--verbose|-v] [--overwrite] SRC... COURSE_DIR`. Each `SRC` SHALL
be a file or directory inside a course repo; the source repo SHALL be found by
walking up from each `SRC` to the nearest directory containing
`course_settings/course_settings.toml`, and all `SRC` arguments SHALL belong to the
same source repo. `COURSE_DIR` SHALL be resolved as described in the
`course-registry` capability and names the destination repo. Each copied file SHALL
be written at the same repo-relative path in the destination repo, creating
directories as needed. `cp` SHALL NOT contact Canvas and SHALL NOT read or change
any `.manifest-*.toml` file. `cp` SHALL NOT stage anything in git.

#### Scenario: Copy one page by registry key
- **WHEN** the user runs `cp pages/intro.md 143` from inside course repo A, `143` is registered to repo B, and `intro.md` references nothing
- **THEN** `B/pages/intro.md` is created with the same bytes as `A/pages/intro.md`, and no manifest in A or B changes

#### Scenario: Same repo
- **WHEN** the source repo and the destination repo resolve to the same directory
- **THEN** the command fails with an error that suggests `mv`, and writes nothing

#### Scenario: Sources from two repos
- **WHEN** two `SRC` arguments are in different course repos
- **THEN** the command fails with an error naming both repos, and writes nothing

#### Scenario: Source outside any course
- **WHEN** a `SRC` is not inside any course repo
- **THEN** the command fails with an error naming that path, and writes nothing

#### Scenario: course_settings refused
- **WHEN** a `SRC` is inside `course_settings/`
- **THEN** the command fails with an error saying course settings cannot be copied with `cp`, and writes nothing

### Requirement: Dependencies are copied with each item

For each content file copied (in `pages/`, `assignments/`, `discussions/`,
`announcements/` or any other content folder), `cp` SHALL also copy every existing
local file under `assets/` that the file references (body links and images,
including those introduced through snippets, and `annotatable_attachment`), and
every snippet file the file includes (block, inline and
`PASTE_SNIPPET_INTO_FRONTMATTER` references). A `SRC` that is a quiz folder or a file
inside one SHALL copy the whole quiz folder, plus the assets and snippets referenced
by the quiz file and its question files. A `SRC` inside a question bank folder SHALL
copy the whole bank folder and the assets and snippets its questions reference. A
`SRC` that is a directory SHALL copy every file under it, each with its own
dependencies. Course-flag conditionals SHALL NOT be applied when finding
dependencies: references inside any `#if` branch are copied.

#### Scenario: Assignment with image and snippet
- **WHEN** `assignments/hw1.md` contains `![](../assets/img/diagram.png)` and includes `[x](../snippets/late-policy.md)`, and the user copies `assignments/hw1.md`
- **THEN** `assignments/hw1.md`, `assets/img/diagram.png` and `snippets/late-policy.md` are all copied

#### Scenario: Asset referenced only inside a snippet
- **WHEN** a copied page includes a snippet whose body contains an image in `assets/`
- **THEN** that image is copied

#### Scenario: Annotatable attachment
- **WHEN** a copied assignment has `annotatable_attachment: "assets/worksheet.pdf"`
- **THEN** `assets/worksheet.pdf` is copied

#### Scenario: Quiz folder
- **WHEN** the user copies `quizzes/week-1-quiz/week-1-quiz.md`
- **THEN** the whole `quizzes/week-1-quiz/` folder is copied, plus the assets referenced by its description and question files

#### Scenario: Reference inside a false conditional branch
- **WHEN** a copied page references an image only inside `#if online` and the source's `online` flag is false
- **THEN** the image is still copied

### Requirement: Modules copy the items they list

When a module file is copied, `cp` SHALL also copy every local item the module
lists (content files and linked asset files), each with its dependencies as in the
previous requirement. External URL and SubHeader items copy nothing. When the
destination has `course_settings/module_order.toml` and its `order` array does not
already list the module's filename, `cp` SHALL append the filename to `order`,
preserving the rest of the file's formatting and comments. When the destination has
no `module_order.toml`, `cp` SHALL NOT create one.

#### Scenario: Module with items
- **WHEN** `modules/week-1.md` lists `pages/intro.md`, `assignments/hw1.md` and an external URL, and the user copies `modules/week-1.md`
- **THEN** the module file, both linked content files, and their assets and snippets are copied

#### Scenario: module_order updated
- **WHEN** the destination's `module_order.toml` has `order = ["intro.md"]` and the user copies `modules/week-1.md`
- **THEN** the destination's `order` becomes `["intro.md", "week-1.md"]` and comments in the file are unchanged

#### Scenario: Module already listed
- **WHEN** the destination's `order` already contains `"week-1.md"`
- **THEN** `module_order.toml` is not changed

### Requirement: Links to other content are not followed

Outside a module's item list, links from copied files to content files (pages,
assignments, discussions, announcements, quizzes) that were not themselves selected
for copying SHALL NOT be followed. The links SHALL be left unchanged in the copied
files. `cp` SHALL print each such link with its target path and whether a file
already exists at that path in the destination.

#### Scenario: Link to an uncopied page
- **WHEN** a copied assignment links to `../pages/syllabus.md`, which is not being copied and does not exist in the destination
- **THEN** `pages/syllabus.md` is not copied, the link text in the copied assignment is unchanged, and the output lists `pages/syllabus.md` as missing in the destination

#### Scenario: Link target already in the destination
- **WHEN** the linked page is not being copied but the destination already has a file at that path
- **THEN** the output lists it as present in the destination

### Requirement: Conflicts abort the copy unless --overwrite is given

Before writing anything, `cp` SHALL determine, for every file it would write,
whether the destination file is absent, byte-identical, or different. Identical files
SHALL be skipped. If any file is different and `--overwrite` was not given, `cp` SHALL
list every such file and exit with a non-zero status without writing any file. With
`--overwrite`, different files SHALL be replaced. Snippet files pulled in as
dependencies (not named as a `SRC`) are exempt: when the destination already has a snippet at the same
path, the destination's version SHALL be kept (even with `--overwrite`) and reported,
and it SHALL NOT count as a conflict. Every file `cp` writes SHALL have a modification
time of the moment it was written, not the source file's modification time.

#### Scenario: Conflicting asset aborts
- **WHEN** the copy would write `assets/img/diagram.png` and the destination already has a different `assets/img/diagram.png`
- **THEN** the command lists that file as a conflict, exits non-zero, and writes no file at all (including the non-conflicting ones)

#### Scenario: Overwrite
- **WHEN** the same conflict exists and `--overwrite` is given
- **THEN** the destination file is replaced with the source's content

#### Scenario: Identical file
- **WHEN** the destination already has an identical `assets/img/diagram.png`
- **THEN** it is not rewritten and is not reported as a conflict

#### Scenario: Destination snippet kept
- **WHEN** a copied page includes `snippets/inline/CANVAS_COURSE_ID.md` and the destination already has a different file at that path
- **THEN** the destination's snippet is left unchanged, the output reports it was kept, and the copy proceeds

#### Scenario: Snippet named as SRC
- **WHEN** the user runs `cp snippets/late-policy.md 143` and the destination has a different `snippets/late-policy.md`
- **THEN** it is reported as a conflict and nothing is written unless `--overwrite` is given

#### Scenario: Overwritten file is re-uploaded
- **WHEN** `--overwrite` replaces a destination file whose manifest entry has a `last_synced` later than the source file's modification time
- **THEN** the replaced file's modification time is later than that `last_synced`, so the next `update` uploads it

### Requirement: Rubrics are merged into the destination

For each copied file (assignment or discussion) whose frontmatter has `rubric`
set to a string title, `cp`
SHALL look for a `[[rubrics]]` entry with that title in the destination's
`course_settings/rubrics.toml`. If one exists, `cp` SHALL NOT change the
destination's rubric; if its criteria and ratings (descriptions, long descriptions
and points) differ from the source rubric's, `cp` SHALL print a warning. If none
exists, `cp` SHALL append the source's `[[rubrics]]` block for that title, including
its sub-tables and comments, to the destination's `rubrics.toml`, creating the file
if it does not exist, and leaving the rest of the file byte-identical. A rubric
referenced by several copied files SHALL be appended once. If the source
`rubrics.toml` has no rubric with that title, `cp` SHALL warn and append nothing. A
numeric `rubric` value SHALL produce a warning that the ID belongs to the source
course.

#### Scenario: Rubric present in destination
- **WHEN** a copied assignment has `rubric: "Essay Rubric"` and the destination's `rubrics.toml` already has a rubric titled `Essay Rubric` with the same criteria
- **THEN** the destination's `rubrics.toml` is unchanged and no warning is printed

#### Scenario: Rubric present but different
- **WHEN** the destination's `Essay Rubric` has different criteria from the source's
- **THEN** the destination's `rubrics.toml` is unchanged and a warning names the rubric and says the destination's version will be used

#### Scenario: Rubric missing in destination
- **WHEN** the destination's `rubrics.toml` has no `Essay Rubric`
- **THEN** the source's `Essay Rubric` block is appended and every existing byte of the file is preserved

#### Scenario: No rubrics.toml in destination
- **WHEN** the destination has no `course_settings/rubrics.toml`
- **THEN** the file is created containing the source's rubric block

#### Scenario: Numeric rubric id
- **WHEN** a copied assignment has `rubric: 4567`
- **THEN** a warning says the numeric rubric ID refers to the source course and nothing is appended

### Requirement: Course-specific values produce warnings

Copied files SHALL be written byte-identical to the source (frontmatter included).
`cp` SHALL print a warning for each copied file that:
- has an `assignment_group_id` name not defined in the destination's `course_settings.toml`;
- has a numeric `group_category_id`, `final_grader_id` or `assignment_group_id`;
- uses a course flag (in `published_if` or an `#if`/`#elif` directive) that the destination does not define;
- has a title matching an entry in the source's `due_dates` table, or an item in the source's `relative_due_dates` tables, saying those dates were not copied;
- has the same title and content type as a different existing file in the destination;
- contains an absolute URL to the source course on Canvas (`/courses/<source course id>/`), when the source course id is known from the source repo's `canvas.toml`.

Warnings SHALL NOT stop the copy.

#### Scenario: Unknown assignment group
- **WHEN** a copied assignment has `assignment_group_id: "Labs"` and the destination defines no `Labs` group
- **THEN** the file is copied unchanged and a warning names the file and the group

#### Scenario: Centralized due date
- **WHEN** the source's `due_dates` has an entry titled `HW 1` and a copied assignment is titled `HW 1`
- **THEN** a warning says the due dates for `HW 1` live in the source's `course_settings.toml` and were not copied

#### Scenario: Title collision
- **WHEN** the destination already has `assignments/old-hw1.md` titled `HW 1` and the copied `assignments/hw1.md` is also titled `HW 1`
- **THEN** a warning names both files

### Requirement: .canvasignore in the source is respected

Files matched by the source repo's `.canvasignore` SHALL NOT be copied as
dependencies, and each skipped file SHALL be reported. A `SRC` argument that is
itself ignored SHALL be reported and skipped.

#### Scenario: Ignored asset
- **WHEN** a copied page references `assets/draft.png` and the source's `.canvasignore` matches it
- **THEN** `assets/draft.png` is not copied and the output says it was skipped because of `.canvasignore`

### Requirement: Noop and output

With `--noop`, `cp` SHALL print what it would do (files to create, files identical,
conflicts, snippets kept, rubric appends, `module_order.toml` change, links not
followed, warnings) and SHALL write nothing, and its exit status SHALL be non-zero
when conflicts exist without `--overwrite`. Without `--verbose`, identical files SHALL
be summarised as a count; with `--verbose` each is listed. `cp` SHALL end by
reminding the user to run `update` on the destination course.

#### Scenario: Noop writes nothing
- **WHEN** the user runs `cp --noop modules/week-1.md 143`
- **THEN** the planned copies, rubric changes and warnings are printed and no file in either repo changes
