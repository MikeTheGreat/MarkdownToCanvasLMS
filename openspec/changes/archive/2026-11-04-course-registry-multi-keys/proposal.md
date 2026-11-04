# Proposal

## Why

One Canvas course repo can feed several Canvas courses (College 101 sections 13
and 14 share a repo and differ only in `canvas.toml`), and a term often means
running the same command against several registered courses. Today that takes
one invocation per key. A registry entry that stands for a list of other
entries lets `update 101` do the whole set.

## What Changes

- A `[courses]` entry may be an array. Each element is a registry key, an
  absolute or `~` path string, or an inline table `{ path, config }`. Example:
  `101 = ["13", "14"]`.
- A command that takes `COURSE_DIR` and is given an array key runs once per
  element, in order, and continues past an element that fails. After the last
  element it prints a summary (for example `13: ok, 14: failed`) and exits
  nonzero if any element failed.
- Each element's run is preceded by a heading line such as `=== 101: 13 (1/2) ===`.
- An array may not contain another array (no nesting). It is an error naming the
  key. Nesting is recorded in TODO.md as possible future work.
- `--config` / `-c` combined with an array key is an error, and a `--config`
  value that names an array key is an error.
- All other options (`-t`, `-s`, `--new`, `--noop`, `--force-*`, `--yes`) apply
  unchanged to every element. Confirmation prompts stay per element.
- The fan-out is one decorator applied to the command callbacks, so the command
  bodies still see a single course.
- No change to course repo files, so no `repo_format.FORMAT_VERSION` bump and no
  migration (the registry is a per-user file outside any repo).

### Existing features that overlap

- Nothing in the tool repeats a command over several courses today. The
  workaround is a shell loop (`for k in 13 14; do gg update $k; done`), which
  has no summary and no registry awareness.
- `--config KEY` and the entry `config` already let two keys share one repo;
  this change builds on that and does not alter it.
- TODO.md "Let `-t`, `-s` and `mv` use the course registry" (`KEY:path`) is
  related but not implemented by this change, and does not conflict with it.

### Core subcommands

- `update` and `publish` take `COURSE_DIR`, so both gain group support through
  the shared decorator and behave identically.
- `import` and `mv` take no course key (`import` names a directory to create;
  `mv` derives its course from file paths), so they need no change.
  `import --register KEY` only writes a plain key and is unchanged.
- The other `COURSE_DIR` commands (`prune`, `fix-manifest`, `fix-markdown`,
  `upgrade`, `generate-due-dates`, `list-titles`, `find-canvas-orphans`,
  `find-local-orphans`, `emit-workflow`, `cp`) get it from the same decorator.

## Capabilities

### New Capabilities

None.

### Modified Capabilities

- `course-registry`: the registry entry shape (arrays), `COURSE_DIR`
  resolution (a group key expands to several courses), the `--config` rule for
  group keys, and a new requirement for running a command once per element with
  headings and a summary.

## Impact

- `src/markdown_to_canvas/course_registry.py`: parse array entries and return a
  list of resolved courses; group-aware `resolve_config` error.
- `src/markdown_to_canvas/cli.py`: the fan-out decorator; `_resolve_course`
  honours the member being run; the `COURSE_DIR` commands are decorated.
- Tests (Canvas mocked), README.md "Naming a course", ARCHITECTURE.md, and
  TODO.md (nested groups added).
- Shell completion already offers every key, so group keys appear without work.
