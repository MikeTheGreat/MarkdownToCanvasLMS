# Spec Delta

## ADDED Requirements

### Requirement: Writing checkpointed-discussion dates

For an item with `reply_to_topic_offsets` (see the `relative-due-dates` capability), `generate-due-dates` SHALL write the item's `due_dates` entry with `unlock_at`, `reply_to_topic_due_at`, `reply_to_others_due_at` and `lock_at`, and without `due_at`; when the existing entry has `due_at`, the key SHALL be removed. For an item without `reply_to_topic_offsets` whose existing entry has `reply_to_topic_due_at` or `reply_to_others_due_at`, the command SHALL remove those keys and write `due_at` as usual. The plan shown to the user SHALL list the two checkpoint dates of such an item, and the removal of a key, like other changed fields. `dont_reschedule_dates_before` SHALL apply to each of `reply_to_topic_due_at` and `reply_to_others_due_at` separately, as it does to `due_at`. The check of an entry's date order SHALL require `unlock_at` <= `reply_to_topic_due_at` <= `reply_to_others_due_at` <= `lock_at` for every pair of these that are dates.

#### Scenario: New checkpointed item
- **WHEN** the table has an item "Unit 02 Forum" with `reply_to_topic_offsets` and `due_dates` has no entry for it
- **THEN** the command adds an entry with `unlock_at`, `reply_to_topic_due_at`, `reply_to_others_due_at` and `lock_at`, and no `due_at`

#### Scenario: Item becomes checkpointed
- **WHEN** an item gains `reply_to_topic_offsets` and its existing entry has `due_at`
- **THEN** the plan shows `due_at` removed and the two checkpoint dates added, and the written entry has no `due_at`

#### Scenario: Cutoff keeps the earlier checkpoint
- **WHEN** the cutoff is 2026-11-02, the existing `reply_to_topic_due_at` is 2026-11-01 and the existing `reply_to_others_due_at` is 2026-11-03
- **THEN** `reply_to_topic_due_at` is kept and `reply_to_others_due_at` is rescheduled
