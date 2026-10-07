# update-noop Specification

## Purpose

Lets a user see what `update` would do to the configured Canvas course in its
current state, without changing Canvas or any local file, and names the offline
empty-course check after what it simulates.

## Requirements

### Requirement: update --noop makes no changes

`update` SHALL accept `--noop` (short form `-n`). With `--noop`, `update` SHALL
make no change to the Canvas course: it SHALL NOT create, update, delete,
publish, unpublish, reorder or upload anything. It SHALL NOT write any local
file: the manifest of the config in use SHALL be byte-identical after the run,
and no file under the course repo SHALL be created, modified or deleted.
`update --noop` SHALL require the same configuration as a real `update`,
including an API token, because it reads the course.

#### Scenario: Stale page is not uploaded
- **WHEN** `pages/week1.md` was edited after its `last_synced` time and `update --noop` runs
- **THEN** the page on Canvas is unchanged and the manifest file is byte-identical afterwards

#### Scenario: New file is not created
- **WHEN** `assignments/hw9.md` has no manifest entry and `update --noop` runs
- **THEN** no assignment is created on Canvas and no entry for `assignments/hw9.md` is written to the manifest

#### Scenario: No API token
- **WHEN** `canvas.toml` has no API token and `update --noop` runs
- **THEN** it stops with the same error a real `update` gives

### Requirement: update --noop reports what a real update would do

With `--noop`, `update` SHALL decide what to report from the manifest on disk and
the current state of the course, the same way a real `update` with the same
options decides what to do: a file that a real run would skip as up to date
SHALL be reported as skipped (with `--verbose`) or not reported; a file a real
run would upload SHALL be reported with a "Would ..." line in place of the
action line a real run prints; an item that is newer on Canvas SHALL be
reported in the same "newer on Canvas" summary a real run prints. Problems a
real run would report (broken links, unknown rubric or assignment-group names,
malformed frontmatter, and the like) SHALL be reported the same way. `Link:`
lines SHALL NOT be printed for items that do not exist on Canvas.

#### Scenario: Only changed files are listed
- **WHEN** the repo has 40 content files, 2 of which were edited since their last sync, and `update --noop` runs
- **THEN** the output has a "Would upload" line for each of the 2 edited files and none for the other 38

#### Scenario: Newer on Canvas
- **WHEN** an assignment was edited on Canvas after its last sync, its local file was also edited, and `update --noop` runs without `--force-overwrite`
- **THEN** the assignment is listed in the "newer on Canvas" summary and has no "Would upload" line

#### Scenario: Unchanged course settings
- **WHEN** `course_settings/rubrics.toml` has not changed since the last sync and `update --noop` runs
- **THEN** no rubric is reported as one that would be created or updated

#### Scenario: Problem found
- **WHEN** a page links to a file that does not exist and `update --noop` runs
- **THEN** the broken link is reported as it would be by a real `update`

### Requirement: update --noop combines with the other update options

`--noop` SHALL be accepted together with `-t`/`--target-recursively`,
`-s`/`--single-target`, `--force-uploads`, `--force-overwrite`, `--verbose`,
`--new`, `--config` and `--yes`, and SHALL report what `update` with the same
options would do. `--noop` SHALL NOT be accepted together with
`--check-as-new-course`; that combination SHALL stop with an error before
anything is read from Canvas.

#### Scenario: Targeted noop
- **WHEN** `update --noop -t pages/week3.md` runs
- **THEN** it reports `pages/week3.md` and the files it transitively references that a real `update -t pages/week3.md` would upload, and nothing else

#### Scenario: Forced uploads
- **WHEN** `update --noop --force-uploads` runs on a repo where no file changed since the last sync
- **THEN** every file a real `update --force-uploads` would re-upload has a "Would upload" line

#### Scenario: Both check options
- **WHEN** `update --noop --check-as-new-course` runs
- **THEN** it stops with an error saying the two options cannot be combined, and contacts Canvas for nothing

### Requirement: update --noop runs the unrecorded-move check

With `--noop`, `update` SHALL run the unrecorded-move check exactly as a real
`update` with the same options does, and when it finds a matching pair it SHALL
print the same report and exit non-zero. With `--new PATH`, the matching
manifest entries SHALL be forgotten for the rest of the run only; the manifest
file SHALL NOT be changed.

#### Scenario: Unrecorded move stops the noop run
- **WHEN** `pages/old.md` is gone from disk, `pages/new.md` has no entry and the same title, and `update --noop` runs
- **THEN** the `OLD → NEW` report and the `mv --after` command are printed, nothing else is reported, and the exit status is non-zero

#### Scenario: --new under noop
- **WHEN** `update --noop --new pages/new.md` runs in the same situation
- **THEN** the run continues and reports `pages/new.md` as a file that would be created, and the manifest file still has the `pages/old.md` entry afterwards

### Requirement: update --noop runs the course guard

With `--noop`, `update` SHALL check that the manifest belongs to the configured
course as a real `update` does, and SHALL NOT write the manifest while doing
so. When the manifest records the configured course, the run SHALL continue.
When the manifest records no course, `update --noop` SHALL print the message a
real `update` prints, SHALL NOT ask for confirmation, SHALL NOT record the
course, and SHALL continue. When the manifest records a different course,
`update --noop` SHALL print the message a real `update` prints, SHALL NOT ask
for confirmation or clear the manifest, and SHALL stop with a non-zero exit
status.

#### Scenario: Same course
- **WHEN** the manifest records the configured course and `update --noop` runs
- **THEN** the run continues with no prompt

#### Scenario: Different course
- **WHEN** the manifest records course 111 and `canvas.toml` names course 222
- **THEN** `update --noop` prints the different-course message, does not prompt, does not change the manifest, and exits non-zero

#### Scenario: No course recorded
- **WHEN** the manifest records no course and `update --noop` runs
- **THEN** no prompt is shown, the manifest still records no course afterwards, and the run continues

### Requirement: update --noop output and exit status

With `--noop`, `update` SHALL print a banner before the run saying that nothing
will be changed in Canvas and the manifest will not be modified. At the end of
the run it SHALL print a summary with the number of items that would be
created, the number that would be updated, the number skipped because they are
up to date, the number not overwritten because they are newer on Canvas, and
the number of problems found. `update --noop` SHALL exit with status 1 when any
error or warning was collected, and with status 0 otherwise.

#### Scenario: Clean noop run
- **WHEN** `update --noop` runs on a repo with 2 edited files, 1 new file and no problems
- **THEN** the summary shows 1 would be created and 2 would be updated, and the exit status is 0

#### Scenario: Noop run with a problem
- **WHEN** `update --noop` finds a broken link
- **THEN** the summary counts the problem and the exit status is 1

### Requirement: --check-all is renamed --check-as-new-course

`update --check-as-new-course` SHALL behave as `update --check-all` did: a
simulation of a first sync of the whole repo to an empty course that contacts
Canvas for nothing, needs no API token, writes nothing, and exits non-zero when
problems are found. Its existing restrictions SHALL be kept: it SHALL NOT be
accepted together with `-t`, `-s`, `--force-uploads`, `--force-overwrite` or
`--new`, and the error messages SHALL name `--check-as-new-course`. `update`
SHALL NOT accept `--check-all` or `-ca`; click's unknown-option error is
reported.

#### Scenario: New name
- **WHEN** `update --check-as-new-course` runs on a repo with a broken link
- **THEN** the broken link is reported, Canvas is not contacted, and the exit status is 1

#### Scenario: Old name rejected
- **WHEN** `update --check-all` runs
- **THEN** it fails with an unknown-option error and nothing is checked
