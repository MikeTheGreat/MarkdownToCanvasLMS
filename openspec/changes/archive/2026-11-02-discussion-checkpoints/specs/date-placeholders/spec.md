# Spec Delta

## ADDED Requirements

### Requirement: Placeholders for checkpointed discussions

When a placeholder selects `due_at` (explicitly or by default) and the matched `due_dates` entry has `reply_to_others_due_at` and no `due_at`, the placeholder SHALL use the value of `reply_to_others_due_at`, with the same rules for sentinel values and formatting as `due_at`. `field` SHALL NOT accept `reply_to_topic_due_at` or `reply_to_others_due_at` (it remains `due_at`, `unlock_at` or `lock_at`).

#### Scenario: Default field on a checkpointed discussion
- **WHEN** a placeholder without `field` refers to the entry of "Unit 02 Forum", which has `reply_to_topic_due_at = "2026-11-01T23:59:00-08:00"` and `reply_to_others_due_at = "2026-11-03T23:59:00-08:00"`
- **THEN** it shows November 3 at 11:59 PM in the default format

#### Scenario: Required-replies date is KEEP
- **WHEN** that entry's `reply_to_others_due_at` is `KEEP`
- **THEN** the placeholder is an unresolved-placeholder error, as for a `due_at` of `KEEP`
