# Spec Delta

## Purpose

Lets a course repo describe a Canvas checkpointed discussion (a graded discussion split into a reply-to-topic part and a reply-to-others part, each with its own points and due date) in the discussion's own file, upload it to Canvas, and import it from an IMSCC export.

## ADDED Requirements

### Requirement: The checkpoints frontmatter block

A discussion file's frontmatter MAY contain a `checkpoints` mapping. When present it SHALL contain exactly two keys, `reply_to_topic` and `reply_to_others`, each a mapping. Each SHALL have `points_possible` (a number greater than or equal to 0) and MAY have `due_at` (a date in the format accepted for a discussion's `due_at`). `reply_to_others` SHALL also have `replies_required` (an integer of at least 1). Any other key, at any level of the block, SHALL be an error naming the file and the key. A file whose `checkpoints` is present SHALL be a graded discussion: the parent's points are the sum of the two `points_possible` values.

#### Scenario: Valid block
- **WHEN** a discussion has `checkpoints: {reply_to_topic: {points_possible: 1, due_at: "2026-11-02T23:59:00-08:00"}, reply_to_others: {points_possible: 1, replies_required: 2, due_at: "2026-11-03T23:59:00-08:00"}}`
- **THEN** `update` uploads it as a checkpointed discussion worth 2 points, with the reply-to-topic part due 2026-11-02 23:59, the reply-to-others part due 2026-11-03 23:59, and 2 required replies

#### Scenario: Missing replies_required
- **WHEN** `reply_to_others` has no `replies_required`
- **THEN** `update` reports an error naming the file and `replies_required`, and does not upload the discussion

#### Scenario: Unknown key
- **WHEN** the block contains `reply_to_entry` (or `reply_to_topic` contains `lock_at`)
- **THEN** `update` reports an error naming the file and the key, and does not upload the discussion

#### Scenario: Block outside a discussion
- **WHEN** an assignment, page or quiz file has `checkpoints`
- **THEN** `update` reports an error naming the file and saying checkpoints apply only to discussions, and does not upload that file

### Requirement: Keys that conflict with checkpoints

In a discussion with `checkpoints`, a top-level `points_possible` or `due_at` SHALL be an error naming the file and the key, and the discussion SHALL NOT be uploaded. Top-level `unlock_at` and `lock_at` SHALL be allowed and SHALL apply to both checkpoints. In a discussion without `checkpoints`, `points_possible` and `due_at` SHALL behave as they do today.

#### Scenario: Top-level points with checkpoints
- **WHEN** a discussion has both `checkpoints` and `points_possible: 2`
- **THEN** `update` reports an error naming the file and `points_possible`, and does not upload the discussion

#### Scenario: Shared availability dates
- **WHEN** a discussion has `checkpoints`, `unlock_at` and `lock_at`
- **THEN** both checkpoints are uploaded with that `unlock_at` and `lock_at`

#### Scenario: No checkpoints
- **WHEN** a discussion has `points_possible` and `due_at` and no `checkpoints`
- **THEN** it is uploaded as a plain graded discussion, as before this change

### Requirement: Checkpoint dates in due_dates

A `due_dates` entry in `course_settings.toml` MAY have `reply_to_topic_due_at` and `reply_to_others_due_at`. Each SHALL accept the values `due_at` accepts (a date, `NONE`, `KEEP`, `CREATE_NONE_THEN_KEEP`) with the same meanings, applied to that checkpoint's due date. When the entry matches a discussion with `checkpoints`, these values SHALL override the checkpoints' `due_at` values from the frontmatter, as an entry's `due_at` overrides a file's `due_at`, and the entry's `unlock_at` and `lock_at` SHALL apply to both checkpoints. The following SHALL each be an error naming the entry and the file, and the discussion SHALL NOT be uploaded and its dates SHALL NOT be sent:
- the entry matches a discussion with `checkpoints` and has a `due_at` key;
- the entry has `reply_to_topic_due_at` or `reply_to_others_due_at` and matches a discussion without `checkpoints`, or matches an item that is not a discussion.

An entry with `virtual = true` SHALL NOT have either key.

#### Scenario: Central dates override frontmatter
- **WHEN** a checkpointed discussion's frontmatter has `reply_to_others.due_at` of 2026-11-03 and its `due_dates` entry has `reply_to_others_due_at = "2026-11-04T23:59:00-08:00"`
- **THEN** the reply-to-others part is due 2026-11-04 23:59

#### Scenario: KEEP leaves one checkpoint date alone
- **WHEN** the entry has `reply_to_topic_due_at = "KEEP"` and a date for `reply_to_others_due_at`
- **THEN** the reply-to-topic due date in Canvas is unchanged and the reply-to-others due date is set

#### Scenario: Plain due_at for a checkpointed discussion
- **WHEN** the entry for a discussion with `checkpoints` has `due_at`
- **THEN** `update` reports an error naming the entry and the file, and neither uploads the discussion nor sends its dates

#### Scenario: Checkpoint keys without checkpoints
- **WHEN** the entry for a discussion without `checkpoints` has `reply_to_others_due_at`
- **THEN** `update` reports an error naming the entry and the file, and neither uploads the discussion nor sends its dates

### Requirement: The course must have checkpoints turned on

Before uploading any discussion with `checkpoints`, `update` SHALL find out whether the course's account has the Canvas `discussion_checkpoints` feature turned on. This check SHALL also run under `--noop`. When the feature is off, `update` SHALL NOT upload any discussion with `checkpoints` and SHALL report, once per such discussion, an error that names the file, says that this course's Canvas account does not have Discussion Checkpoints turned on (so checkpoints cannot be used in this course), and suggests commenting out the `checkpoints` block and using instead:
- `points_possible` with the combined points;
- `due_at` with the reply-to-others date (or `due_at` in the `due_dates` entry, in place of the two checkpoint keys);
- `require_initial_post: true`;

and writing the earlier reply-to-topic deadline into the discussion's body with a `replace_date_with` date placeholder. Content other than checkpointed discussions SHALL still be uploaded, and the run SHALL end with a nonzero exit status as for other upload errors.

#### Scenario: Feature off
- **WHEN** the course's account has Discussion Checkpoints off and the repo has one checkpointed discussion and ten pages
- **THEN** `update` uploads the ten pages, does not create or change the discussion in Canvas, prints the error with the suggested alternatives for that file, and exits with a nonzero status

#### Scenario: Feature on
- **WHEN** the course's account has Discussion Checkpoints on
- **THEN** checkpointed discussions are uploaded

#### Scenario: No checkpointed discussions
- **WHEN** no discussion in the run has `checkpoints`
- **THEN** `update` does not look up the feature

### Requirement: Uploading checkpoints

For a discussion with `checkpoints`, `update` SHALL make Canvas hold: both checkpoints with the points and due dates from the file (after `due_dates` overrides), the number of required replies, both checkpoints' `unlock_at` and `lock_at` from the file, and a parent assignment whose points are the sum and which has no due date of its own. Every other setting `update` sends for a graded discussion (title, body, published state, `require_initial_post`, assignment group, group set/group category, rubric) SHALL be sent as for a discussion without checkpoints. The same SHALL hold when the discussion is created, when an existing plain discussion in the manifest gains `checkpoints`, and when only its dates change (the dates-only pass). The manifest's cached date resolution for a checkpointed discussion SHALL record `unlock_at`, `reply_to_topic_due_at`, `reply_to_others_due_at` and `lock_at`, so that a change to either checkpoint date is sent on the next run.

#### Scenario: New checkpointed discussion
- **WHEN** a checkpointed discussion with no manifest entry is uploaded
- **THEN** Canvas has one discussion with two checkpoints matching the file, and the manifest records its id

#### Scenario: Plain discussion gains checkpoints
- **WHEN** a discussion already uploaded without checkpoints, with no replies, gets a `checkpoints` block
- **THEN** after `update` the same Canvas discussion has the two checkpoints, its points are their sum and it has no parent due date

#### Scenario: Only a checkpoint date changed
- **WHEN** only `reply_to_others_due_at` in the discussion's `due_dates` entry changes
- **THEN** the dates-only pass sends the new date, the other checkpoint keeps its date, and the parent assignment's points and due date are not changed

#### Scenario: Body edit
- **WHEN** only the body of a checkpointed discussion changes
- **THEN** the new body is uploaded and both checkpoints are unchanged in Canvas

### Requirement: Turning checkpoints off

When a discussion in the manifest has checkpoints in Canvas and its file no longer has `checkpoints`, `update` SHALL turn checkpoints off for that Canvas discussion and then upload it as a plain graded discussion with the file's `points_possible` and dates. The turn-off SHALL happen before any parent assignment points or dates are sent. If the discussion has replies, `update` SHALL NOT turn checkpoints off, SHALL leave the discussion unchanged, and SHALL report an error naming the file and saying that checkpoints cannot be removed from a discussion with replies through the tool.

#### Scenario: Block removed, no replies
- **WHEN** a checkpointed discussion with no replies has its `checkpoints` block replaced by `points_possible: 2` and `due_at`
- **THEN** after `update` the Canvas discussion has no checkpoints, is worth 2 points and has that due date

#### Scenario: Block removed, replies exist
- **WHEN** a checkpointed discussion with student replies loses its `checkpoints` block
- **THEN** `update` reports the error for that file and the Canvas discussion keeps its checkpoints

### Requirement: Adding checkpoints after replies

When a discussion in the manifest has no checkpoints in Canvas, has replies, and its file gains `checkpoints`, `update` SHALL NOT change the discussion and SHALL report an error naming the file and saying that Canvas does not allow checkpoints to be added to a discussion that already has replies.

#### Scenario: Checkpoints added after replies
- **WHEN** a plain graded discussion with replies gets a `checkpoints` block
- **THEN** `update` reports the error and the discussion in Canvas is unchanged

### Requirement: Importing checkpoints

When `import` converts a discussion whose IMSCC topic metadata has checkpoints (a `sub_assignments` element inside its `assignment`, with `sub_assignment` elements tagged `reply_to_topic` and `reply_to_entry`), it SHALL write a `checkpoints` block with `reply_to_topic` and `reply_to_others` (from `reply_to_entry`), each with that checkpoint's `points_possible`, and `replies_required` from the topic's `reply_to_entry_required_count` (1 when absent). The line immediately above `reply_to_others:` SHALL be a comment saying that these are students' replies to other students' posts. It SHALL NOT write a top-level `points_possible` or `due_at`. Following the existing pattern for dates, it SHALL write the checkpoints' due dates into the discussion's `due_dates` entry as `reply_to_topic_due_at` and `reply_to_others_due_at` (with `unlock_at` and `lock_at` from the parent assignment, and no `due_at`), and SHALL write each checkpoint's `due_at` as a commented-out line in the frontmatter. A discussion without `sub_assignments` SHALL be imported as before.

#### Scenario: Sample export
- **WHEN** importing the topic "Discussion Checkpoints Experiment" whose checkpoints are `reply_to_topic` (1 point, due 2026-11-03T07:59:59) and `reply_to_entry` (1 point, due 2026-11-04T07:59:59) with `reply_to_entry_required_count` 1
- **THEN** its file has a `checkpoints` block with those points and `replies_required: 1`, a comment line directly above `reply_to_others:`, no top-level `points_possible` or `due_at`, and its `due_dates` entry has `reply_to_topic_due_at` and `reply_to_others_due_at` with those dates

#### Scenario: Round trip
- **WHEN** a course with a checkpointed discussion is imported and then uploaded with `update` to a course whose account has checkpoints on
- **THEN** the uploaded discussion has the same checkpoint points, due dates and reply-to-others count as the exported one
