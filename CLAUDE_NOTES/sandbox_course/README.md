# Sandbox course repo

A scratch course repo for trying markdown-to-canvas changes against the
sandbox Canvas course 2758791 (see ../CLAUDE-IN-CHROME.md). Kept between
sessions on purpose; add content for each new feature as needed.

Load the token before running the tool, from the project root:

    set -a; . ./.env; set +a
    uv run markdown-to-canvas update CLAUDE_NOTES/sandbox_course

## Contents and what they test

- dont_reschedule_dates_before (2026-10-03): assignments Problem Set 1-4,
  Lab 1, Week 1 Discussion, Quiz 1, scheduled from course_settings/term_dates.toml.
- default_unlock_time / default_lock_time: Problem Set 4 (unlock moves to
  00:00) and Problem Set 5 (explicit 17:00 due time, so its unlock and lock
  stay at 17:00).
- Lab 1 is deliberately left inconsistent with the table, so every
  generate-due-dates run reports an error for it and exits 1.
- External-link publish fix (2026-10-04): modules/week-1.md has an
  ExternalUrl item and a page item. Canvas creates ExternalUrl module items
  unpublished, so the tool must send a follow-up publish PUT.
- Module-only publish (2026-10-04): toggling `published` in modules/week-1.md
  must change only the module; the external link and the page keep their
  own state (set `published: false` on the page to check it stays
  unpublished when the module is republished).
- Date placeholders (2026-10-05): discussions/week-1-discussion.md quotes its
  own due_at (default format, inside a highlighted span) and lock_at (explicit
  format); pages/week-1-homepage.md quotes Quiz 1's due_at by item= and type=.
  Changing an entry's due_at in due_dates and running update must re-upload
  only the files that quote it.
