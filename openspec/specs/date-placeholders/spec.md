# date-placeholders Specification

## Purpose

Lets a course author quote a date from the centralized `due_dates` table in the
body of a page, assignment, discussion or quiz, so the quoted text changes when
the table does instead of going stale each term.

## Requirements

### Requirement: Date placeholder syntax

A date placeholder SHALL be a Pandoc bracketed span whose attributes include the
class `replace_date_with`: `[TEXT]{.replace_date_with ATTRIBUTES}`. `TEXT` is
fallback text for editor previews; it SHALL NOT appear in the output and SHALL
NOT contain `[` or `]`. The recognized attributes SHALL be:

- `item`: the `name` of a `due_dates` entry. Optional (see "The file's own entry").
- `type`: `assignment`, `discussion` or `quiz`. Optional; restricts matching to
  entries whose `type` equals it or that give no `type`.
- `field`: `due_at`, `unlock_at` or `lock_at`. Optional; defaults to `due_at`.
- `format`: a strftime format string. Optional; defaults to the course-wide
  default (see "Course-wide default format").

Attribute values MAY be quoted (`item="HW 1: Loops"`) or, when they contain no
spaces or quotes, bare (`field=due_at`). Any other attribute, and any other class
or id on the span, SHALL be an error for that placeholder.

The tool SHALL replace the whole span (brackets, text and attributes) with the
formatted date as plain text. No span element, class or `data-` attribute from
the placeholder SHALL reach Canvas or the published site. A placeholder inside
another span or inside emphasis (`[**by [x]{.replace_date_with}**]{style="..."}`)
SHALL be replaced and the surrounding markup kept.

#### Scenario: Placeholder replaced by the due date
- **WHEN** `due_dates` has `{name = "HW 1", due_at = "2026-10-27T23:59:00-07:00"}` and a page body contains `Submit by [Oct 20]{.replace_date_with item="HW 1" format="%A, %B %-d"}.`
- **THEN** the uploaded HTML contains `Submit by Tuesday, October 27.` and no `replace_date_with` text

#### Scenario: Nested inside a styled span
- **WHEN** a body contains `[**Complete Step 5 by [x]{.replace_date_with item="HW 1" format="%B %-d"}**]{style="background-color: #fbeeb8;"}`
- **THEN** the uploaded HTML has a span with that style containing `<strong>Complete Step 5 by October 27</strong>`

#### Scenario: Other fields
- **WHEN** a placeholder has `field=lock_at` and the entry's `lock_at` is `2026-11-03T23:59:00-08:00`
- **THEN** the lock date is shown

#### Scenario: Unknown attribute
- **WHEN** a placeholder has `feild=lock_at`
- **THEN** it is an error naming the file and the attribute

#### Scenario: Placeholder in code is left alone
- **WHEN** the span text appears inside a fenced code block or an inline code span
- **THEN** it is left exactly as written and is not an error

### Requirement: Only due_dates entries can be referenced

A placeholder SHALL resolve against the top-level `due_dates` array of
`course_settings.toml`, after entries whose `only_if` is not met by the course
flags of the run have been removed (the same list the dates sent to Canvas come
from). An entry matches when its `name` equals the placeholder's `item` exactly
and, when the placeholder gives `type`, the entry's `type` is that type or is
absent. Nothing else (content files, `relative_due_dates` tables, the term file)
SHALL be consulted. An entry SHALL be referenceable whether or not any content
file has its title.

#### Scenario: Entry of another item
- **WHEN** a page refers to `item="Career Exploration Assignment"` and `due_dates` has that entry
- **THEN** the page shows that entry's date

#### Scenario: Entry removed by only_if
- **WHEN** the only entry named `HW 1` has `only_if = "online"` and the run's flags set `online = false`
- **THEN** a placeholder naming `HW 1` is an unresolved-placeholder error

#### Scenario: Moving files does not affect references
- **WHEN** the file a placeholder names by title is moved with `mv`
- **THEN** the placeholder still resolves to the same entry

### Requirement: The file's own entry

A placeholder without `item` SHALL refer to the `due_dates` entry of the file it
is written in (for a placeholder inside a snippet, the file that includes the
snippet): the entry matched by the file's title (frontmatter `title`, else the
file name without `.md`) and its content type, as the due-dates pass matches
it. For a quiz question file the file is the quiz it belongs to. In any other
file (pages, announcements, the syllabus, question banks) a placeholder without
`item` SHALL be an error.

#### Scenario: Assignment quotes its own due date
- **WHEN** `assignments/hw1.md` has title `HW 1`, `due_dates` has an entry `HW 1`, and the body has `[x]{.replace_date_with}`
- **THEN** the placeholder shows that entry's `due_at` in the default format

#### Scenario: Page without item
- **WHEN** a file in `pages/` has `[x]{.replace_date_with}`
- **THEN** it is an error saying the placeholder needs `item` because pages have no due date

### Requirement: Unresolved placeholders are errors

Each of these SHALL be an error naming the file and the placeholder:
- no entry matches;
- more than one entry matches;
- the selected field's value is `NONE`, `KEEP`, `CREATE_NONE_THEN_KEEP` or an
  empty string (case-insensitive for the sentinels), or the key is missing;
- the value is not a date-time the tool can parse;
- an attribute is unknown or has an invalid value;
- a span with class `replace_date_with` that the tool could not parse, for
  example because its text contains brackets.

During `update`, a file with such an error SHALL NOT be uploaded, its manifest
entry SHALL NOT be marked synced (so the error repeats on the next run until
fixed), every other file SHALL still be processed, and the run SHALL exit
non-zero. During `publish`, every such error in the site SHALL be reported and
`publish` SHALL then stop without writing the site, as it does for broken local
links.

#### Scenario: Ambiguous name
- **WHEN** `due_dates` has two entries named `Week 3`, one `type = "quiz"` and one `type = "assignment"`, and a placeholder names `item="Week 3"` without `type`
- **THEN** it is an error saying the name is ambiguous and that `type=` selects one

#### Scenario: Type disambiguates
- **WHEN** the same placeholder adds `type=quiz`
- **THEN** it shows the quiz entry's date

#### Scenario: Sentinel value
- **WHEN** the referenced entry has `due_at = "NONE"`
- **THEN** it is an error saying the entry has no due date

#### Scenario: publish stops on an unresolved placeholder
- **WHEN** `publish` runs and one page has an unresolved placeholder
- **THEN** the error is reported, no site files are written, and the command exits non-zero

#### Scenario: Error does not stop the update
- **WHEN** one discussion has an unresolved placeholder and other files are stale
- **THEN** the discussion is skipped with the error, the other files are uploaded, and the command exits non-zero

### Requirement: Dates are shown in the time stored in due_dates

A date SHALL be formatted in the clock time and UTC offset written in the
`due_dates` value, with no time-zone conversion. A value with an offset
(`2026-10-27T23:59:00-07:00`) SHALL be shown as 23:59 on October 27. A value
with no offset SHALL be shown as written. Format directives SHALL behave as in
Python's `datetime.strftime`. The no-padding forms `%-d`, `%-m`, `%-H`, `%-I`,
`%-M` and `%-j` SHALL work on every platform the tool supports.

#### Scenario: Offset kept
- **WHEN** the value is `2026-10-27T23:59:00-07:00` and the format is `%-I:%M %p`
- **THEN** the text is `11:59 PM`

### Requirement: Course-wide default format

`course_settings.toml` SHALL accept an optional top-level string key
`replace_date_with_format`, the format used by placeholders without `format`.
When the key is absent the default SHALL be `%A, %B %-d at %-I:%M %p` (for
example `Tuesday, October 27 at 11:59 PM`). A non-string value SHALL be a
whole-run configuration error. `import` SHALL write the key with that default,
before the first table header so it stays top-level, with a comment on the line
directly above it saying it is the date format for `replace_date_with`
placeholders. Changing the key SHALL NOT trigger a course-settings upload.

#### Scenario: Default format
- **WHEN** the key is absent and a placeholder has no `format`
- **THEN** the date is shown as e.g. `Tuesday, October 27 at 11:59 PM`

#### Scenario: Import writes the key
- **WHEN** `import` creates `course_settings.toml`
- **THEN** it contains `replace_date_with_format = "%A, %B %-d at %-I:%M %p"` at the top level with a one-line comment directly above it

### Requirement: Where placeholders are expanded

Placeholders SHALL be expanded in the body text of pages, assignments,
discussions, announcements, the syllabus, quiz descriptions, quiz question
files and question-bank question files, and inside snippets included by any of
them, by both `update` and `publish`. They SHALL NOT be expanded in
frontmatter or in module files.

#### Scenario: Placeholder inside a snippet
- **WHEN** a block snippet contains `[x]{.replace_date_with}` and is included by `assignments/hw1.md` and `assignments/hw2.md`
- **THEN** each assignment shows its own due date

#### Scenario: publish
- **WHEN** `publish` renders a page with a resolvable placeholder
- **THEN** the MkDocs Markdown contains the formatted date and no span syntax

### Requirement: Files are re-uploaded when a quoted date changes

After a file with placeholders is uploaded, its manifest entry SHALL record, for
each placeholder, what it referred to and the text it produced. On a later
`update`, a file whose recorded placeholders now produce different text (because
a `due_dates` value, an entry's `only_if` result or the default format changed),
or no longer resolve, SHALL be treated as stale and re-converted and re-uploaded,
even when the file and its snippets are unchanged. A file whose placeholders
produce the same text SHALL NOT be re-uploaded on their account. Files without
placeholders SHALL NOT have the record. With `--verbose` the reason SHALL be
printed.

Re-uploads caused this way SHALL go through the newer-on-Canvas check, which for
every upload SHALL treat the Canvas copy as newer only when its `updated_at` is
later than both the local file's effective modification time (the file and its
snippets) and the entry's last successful upload. A Canvas `updated_at` set by
the tool's own previous upload therefore never blocks a re-upload whose cause is
not a local edit (a changed quoted date, or a course flag flip).

#### Scenario: generate-due-dates moves a date
- **WHEN** a discussion quotes `HW 1`'s due date, was uploaded, and `generate-due-dates` then changes `HW 1`'s `due_at`
- **THEN** the next `update` re-uploads the discussion with the new date, and a page that quotes only `HW 2` is not re-uploaded

#### Scenario: Unrelated due_dates change
- **WHEN** an entry no placeholder refers to changes
- **THEN** no body is re-uploaded on account of placeholders

#### Scenario: Our own last upload does not block the re-upload
- **WHEN** a quoted date changes, the file is unchanged since its last upload, and Canvas's `updated_at` is the time of that upload
- **THEN** the file is re-uploaded with the new date

#### Scenario: An edit made in Canvas still blocks the re-upload
- **WHEN** a quoted date changes and Canvas's `updated_at` is later than the last upload
- **THEN** the file is skipped as "Canvas is newer" and listed in the end-of-run summary, unless `--force-overwrite` is given

#### Scenario: Manifest from before this change
- **WHEN** a manifest entry has no placeholder record
- **THEN** the file's staleness is decided as before, and the record is written on its next upload
