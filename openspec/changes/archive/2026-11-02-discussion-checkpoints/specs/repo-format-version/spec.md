# Spec Delta

## ADDED Requirements

### Requirement: Migration 15 to 16

Format version 16 adds the optional `checkpoints` block to discussion frontmatter (see the `discussion-checkpoints` capability), the optional `reply_to_topic_due_at` and `reply_to_others_due_at` keys to `due_dates` entries, and the optional `reply_to_topic_offsets` key to `[relative_due_dates]` items. An older tool would upload a discussion with `checkpoints` as a plain graded discussion without a due date, and would ignore the two `due_dates` keys, which is why the version changes. Migration 15 -> 16 SHALL record format version 16 in `course_settings.toml` and in every `.manifest-*.toml`, and SHALL NOT change anything else.

#### Scenario: Upgrade a version-15 repo
- **WHEN** `upgrade` runs on a version-15 repo
- **THEN** `format_version` becomes 16, every manifest records 16, and no other content of any file changes

#### Scenario: Older tool meets a version-16 repo
- **WHEN** a tool whose format version is 15 runs `update` on a version-16 repo
- **THEN** it refuses to run, as it does for any repo newer than the tool
