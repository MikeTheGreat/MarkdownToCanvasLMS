# Proposal

## Why

Instructions in assignment and discussion bodies often quote a due date as plain
text ("Complete Step 5 by Monday, October 27"). The `due_dates` table in
`course_settings.toml` is regenerated each term by `generate-due-dates`, but the
text in the bodies is not, so it goes stale. The College 101 discussion
`discussions/academic-skill-lab-1-habit-loop-option.md` shows this: its dates are
from 2025 (October 20, 2026 is a Tuesday, not a Monday). The body text should be
filled in from the same `due_dates` entries that set the Canvas dates.

## What Changes

- New body syntax: a Pandoc bracketed span with class `replace_date_with`, for
  example `[Oct 27]{.replace_date_with item="Career Exploration Assignment" field=due_at format="%B %-d"}`.
  On `update` and `publish` the tool replaces the whole span with a date taken
  from the `due_dates` entry it names. The text inside the brackets is ignored
  (it is there for the editor preview). The span's markup does not reach Canvas.
- Attributes: `item` (the `due_dates` entry's `name`; when omitted, the file's
  own entry, found the way the dates pass finds it), `type` (optional, to tell
  apart entries that share a name), `field` (`due_at` by default, or
  `unlock_at` / `lock_at`), `format` (strftime; when omitted, a course-wide
  default).
- Only entries in the `due_dates` list can be referenced. Entries are named by
  title, so moving files does not affect references.
- New top-level key in `course_settings.toml` holding the default format, with
  a one-line comment directly above it. Its default includes the time.
  `import` writes it; the upgrade migration adds it to existing repos.
- A date is shown in the clock time and UTC offset stored in the `due_dates`
  value (the course's local time for anything `generate-due-dates` wrote).
- A placeholder that does not resolve is an error: no matching entry, an
  ambiguous name, an omitted `item` in a file that has no entry, or a field
  whose value is `NONE`, `KEEP`, `""` or `CREATE_NONE_THEN_KEEP`. The file is
  not uploaded; the rest of the update continues; the run exits non-zero.
- Each file's manifest entry records the dates its placeholders resolved to, so
  a `due_dates` change re-uploads exactly the bodies that quote the changed
  value. Until now a `due_dates` edit sent only Canvas's date fields.
- `generate-due-dates` checks that every placeholder in the repo resolves
  against the `due_dates` it is about to write, and reports those that don't.
- `cp` warns when a copied file has a placeholder that names an entry the
  destination's `due_dates` lacks.
- **BREAKING (format):** `repo_format.FORMAT_VERSION` goes from 9 to 10, with
  migration 9 -> 10. Placeholders are written by the user, not the tool, so
  strictly no bump is required. The bump is chosen so an older tool refuses the
  repo instead of uploading the bracket text and span markup.

## Existing mechanisms this relates to

- The `snippets/inline/CANVAS_COURSE_REFERENCE.md` snippet is the only other
  place where body text is computed from configuration instead of copied from a
  file. Placeholders are expanded at the same stage, after snippet expansion,
  so a placeholder written inside a snippet works in every file that includes
  it.
- Course-flag staleness (`flags_used` in manifest entries, `manifest.flag_change`)
  is the model for the new date staleness record.
- The `due_dates` dates pass (`_apply_due_dates_only`) already resolves entries
  by title and type (`find_due_date_override`) and filters them by `only_if`
  (`filter_due_dates_by_flags`). Placeholders use the same matching and the
  same filtered list, so a placeholder sees exactly the dates Canvas gets.
- `generate-due-dates` already reports mismatched titles (`title_warnings`).
  The placeholder check is added beside it.
- `cp` already warns about course-specific values in copied files
  (`_plan_warnings`), including items with no `due_dates` entry.
- No TODO.md item describes this feature. The "Show due dates in the published
  MkDocs site" item is related: this change puts quoted dates into published
  pages, but it does not add a list of due dates to the site, so that item stays.

## Capabilities

### New Capabilities
- `date-placeholders`: the `replace_date_with` span syntax, how a span is
  resolved and formatted, the default-format setting, errors, where spans are
  expanded, and the staleness record that re-uploads files when a quoted date
  changes.

### Modified Capabilities
- `repo-format-version`: adds migration 9 -> 10.
- `generate-due-dates-command`: checks that every placeholder resolves.
- `copy-between-courses`: warns about placeholders the destination cannot resolve.

## Impact

Core subcommands:
- `update`: expands placeholders in every body it uploads; new staleness check;
  errors per file.
- `publish`: expands placeholders in the MkDocs output.
- `import`: writes the default-format key into the new `course_settings.toml`.
  It does not create placeholders (an export has only plain dates).
- `mv`: not affected. Placeholders reference `due_dates` names, not paths, and
  `mv` does not change titles.

Code: new module (e.g. `date_placeholders.py`); `sync.py` (the body conversion
paths, the syllabus, quiz descriptions and question files, staleness);
`manifest.py` (`needs_sync`); `publish.py`; `generate_due_dates.py`; `cp.py`;
`imscc_import.py`; `repo_format.py` (version 10, migration). Docs: README.md,
ARCHITECTURE.md. No new dependencies. No new Canvas API calls.
