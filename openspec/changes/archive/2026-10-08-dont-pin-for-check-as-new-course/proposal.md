# Proposal

## Why

`update --check-as-new-course` simulates a first sync to an empty course, but
it honors `pinned_resources`, so every pinned file is skipped without being
converted or checked. The content most likely to be pinned (a quiz students
have started) is the content the check never validates, and every module
that lists a pinned item reports that some items could not be added. A course
repo with pins cannot get a clean check run today.

## What Changes

- New `update` option `--ignore-pinned-resources`. With it,
  `--check-as-new-course` treats every `pinned_resources` entry as unpinned
  for that run, so pinned content is converted and checked like all other
  content.
- `--ignore-pinned-resources` is an error unless `--check-as-new-course` is
  also given (so not with a plain `update` or `--noop`). This may be relaxed
  later; for now it only exists for the check.
- Without the new option, `--check-as-new-course` keeps honoring pins exactly
  as it does now.
- `pinned_resources` entries are still validated with the option (a malformed
  entry is still a hard error, since a real `update` would stop on it), and
  the warning for entries that match nothing on disk still prints.
- When the course has pins, check mode prints one note after the CHECK MODE
  banner:
  - with `--ignore-pinned-resources`: that N entries are temporarily
    unpinned for this simulated run (with `--verbose`, each entry is listed);
  - without it: a hint that N entries will be skipped and that
    `--ignore-pinned-resources` checks them too.
- The College 101 course repo's CLAUDE.md
  (`/home/mike/Dropbox/Work/Courses/_COLL_101/mpanitz-OL-College101/CLAUDE.md`)
  is updated to pass the new option in its check command and to drop its
  "that error is expected" explanation. The user asked for this edit in
  another repo.

## Existing mechanisms

- `pinned_resources` (course_settings.toml) blocks uploads in `update` and
  protects items from `prune`. `mv` rewrites pin entries. None of these has
  a way to turn pins off for one run. The only current workaround is to
  comment out `pinned_resources` before checking and restore it afterwards.
- `update --noop` simulates the next update against the real course and must
  keep honoring pins, because it reports what a real update would do. That is
  why the option is restricted to `--check-as-new-course`.
- `update --check-as-new-course` already rejects `-t`, `-s`, `--noop`,
  `--new`, `--force-uploads` and `--force-overwrite`. The new restriction is
  added alongside those checks.

No TODO.md item covers this.

## Core subcommands

Only `update` changes. `import` and `publish` never upload to Canvas and do
not consult pins for uploading. `mv` rewrites pin entries but does not decide
whether anything is uploaded. None of them has a check-as-new-course mode.

## Capabilities

### New Capabilities

- `ignore-pinned-resources`: the `update --ignore-pinned-resources` option,
  its restriction to `--check-as-new-course`, and the pin notes printed in
  check mode.

### Modified Capabilities

None. `update-noop` describes `--check-as-new-course` only by reference to the
old `--check-all`; its requirements do not change.

## Impact

- `src/markdown_to_canvas/cli.py`: new option and combination check.
- `src/markdown_to_canvas/sync.py`: `run_sync` new-course path (empty the pin
  list when asked; print the notes).
- `tests/test_check_as_new_course.py`: new tests.
- README.md, ARCHITECTURE.md: documentation.
- The College 101 course repo's CLAUDE.md (outside this repo).
- No repo-format change: no file is read differently.
