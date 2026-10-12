# Proposal

## Why

`update` and `publish` read only the `due_dates` array; the `[relative_due_dates]`
section is read only by `generate-due-dates`. When the relative table is edited
and `generate-due-dates` is not run afterwards, `update` silently sends the old
dates. This happened in IT-CS 142: the midterm's relative rule gained
`"13:15 ABS_TIME"`, `due_dates` still said 23:59, and Canvas kept showing the
11:59 PM due date with no warning.

## What Changes

- `generate-due-dates` records a fingerprint of the parsed `[relative_due_dates]`
  section (all keys and tables except the fingerprint itself) as
  `last_generated_hash` at the top level of that section. It records it on every
  run that finishes cleanly and is not `--noop` or declined at the prompt,
  including runs where every date already matches ("Nothing to change"); in that
  case it writes only the fingerprint, without asking, and says so.
- `update` (every mode: full, targeted `-t`/`-s`, `--noop`,
  `--check-as-new-course`) and `publish` compute the same fingerprint and print a
  warning when it differs from `last_generated_hash`, or a different warning when
  `last_generated_hash` is absent. The warning is printed only when some table in
  `[relative_due_dates.tables]` has at least one item. It is printed twice: next
  to the due-dates output and again after the command's final status line.
- **BREAKING** (repo format): `FORMAT_VERSION` goes from 14 to 15, because a tool
  at format 14 rejects `last_generated_hash` as an unknown key in
  `[relative_due_dates]`. The 14 -> 15 migration records the new version only; it
  does not write a fingerprint, so an upgraded repo that uses relative dates
  warns until `generate-due-dates` is run.

### Existing mechanisms this relates to

- `generate-due-dates --noop` already computes the dates and shows the
  differences from `due_dates` without writing. It is the manual way to detect
  the same problem; this change makes `update` and `publish` prompt for it.
- `update`'s "Checking due_dates coverage..." step checks only that `due_dates`
  names match content files. It does not look at `[relative_due_dates]`.
- `update`'s course-settings section hashes (`_section_hash` in `sync.py`)
  already exclude `relative_due_dates`, so writing the fingerprint does not make
  any Canvas settings look stale.
- `cp` can copy items into `[relative_due_dates]`; such an edit changes the
  fingerprint and correctly triggers the warning until `generate-due-dates` runs.

No TODO.md item covers this; none is affected.

### Core subcommands

- `update`: prints the warning.
- `publish`: prints the warning (it reads `due_dates` for date placeholders).
- `import`: unaffected. It writes an empty default table, which has no items, so
  no warning applies and no fingerprint is needed.
- `mv`: unaffected. It does not read or write `due_dates` or
  `[relative_due_dates]`.

## Capabilities

### New Capabilities

- `stale-relative-due-dates-warning`: the `last_generated_hash` fingerprint, when
  `generate-due-dates` records it, and the warnings `update` and `publish` print
  when it is missing or out of date.

### Modified Capabilities

- `generate-due-dates-command`: a run that finishes cleanly also records
  `last_generated_hash`, and a "Nothing to change" run writes the fingerprint
  alone.
- `relative-due-dates`: `last_generated_hash` becomes an allowed section-level key
  of `[relative_due_dates]` (not allowed inside a table).

## Impact

- Code: `relative_dates.py` (allowed keys, fingerprint function, warning check),
  `generate_due_dates.py` and `cli.py` (recording the fingerprint),
  `sync.py` (warning in `_phase_due_dates` and the targeted run), `cli.py`
  (warning after the update status lines), `publish.py` (warning in
  `run_publish`), `repo_format.py` (`FORMAT_VERSION = 15`, migration 14 -> 15).
- Course repos: one new key in `course_settings.toml`, written by
  `generate-due-dates`. Repos must be upgraded with `upgrade` before the new tool
  will run on them, as with every format bump.
- No Canvas API behavior is involved; nothing new is sent to Canvas.
- Docs: README.md, ARCHITECTURE.md.
