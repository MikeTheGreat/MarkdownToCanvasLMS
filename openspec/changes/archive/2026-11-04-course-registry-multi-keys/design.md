# Design

## Context

See proposal.md for motivation. Current state:

- Eleven commands plus `cp` declare `COURSE_DIR` through
  `cli._course_dir_argument()` and each body calls `cli._resolve_course(course_dir, config)`,
  which calls `course_registry.resolve_course()` and returns one
  `(directory, config)`.
- `course_registry._parse_entry()` accepts a string or a `{path, config}` table
  and rejects anything else.
- Failures end in `die()` (`sys.exit(1)`), and `_handle_cli_errors` turns common
  exceptions into `die()` calls. Some commands also call `sys.exit(1)` directly
  for "problems found" (for example `update` after a sync with errors).
- `update` passes `course_dir` and the given config into
  `_move_check_commands(repo, course_dir, config_given)`, which builds the
  `mv --after` / `--new` suggestion text from them.
- A manifest is named after the config file, so the same repo run with two
  configs (13 and 14) has two manifests and the runs do not interfere.

## Goals / Non-Goals

**Goals:**

- Command bodies keep seeing exactly one course.
- One implementation of the fan-out for all `COURSE_DIR` commands, so `update`
  and `publish` cannot drift apart.

**Non-Goals:**

- Running members in parallel. Runs are sequential: output stays readable,
  prompts work, and 13 and 14 share a repo.
- Nested groups (see TODO.md).
- Any change to how `--config`, `-t`, `-s`, `--new` or `--yes` are parsed.

## Decisions

All of these were confirmed by the user in conversation unless listed under
Open Questions.

1. **A decorator on the command callback does the fan-out.** `_for_each_course`
   sits between `@main.command` and `@_handle_cli_errors`, so each member's
   `die()` has already happened inside the wrapped function and shows up as a
   `SystemExit`. The decorator reads `course_dir` and `config` from the call's
   keyword arguments, resolves `course_dir` to a list, and for a group calls the
   wrapped function once per member. Alternative rejected: making
   `_resolve_course` return a list, which would change every command body and
   conflicts with `die()` ending the process.

2. **Registry layer returns a list.** `course_registry` gains
   `resolve_courses(arg) -> list[ResolvedCourse]` (one element for a path or a
   non-group key, N for a group). `resolve_course` keeps its signature for the
   single-course callers and raises `RegistryError` for a group, so no caller
   can silently take the first member. `_parse_entry` is reused for table and
   string-path elements.

3. **How the body learns which member it is running.** The decorator stores the
   member (`ResolvedCourse`) in a module-level `ContextVar`; `_resolve_course`
   uses it instead of resolving the string again, and still prints
   `Course dir:` with `(course KEY)` for key members. This is needed because a
   member can be a path or an inline table that has no key to pass as a string.
   For `_move_check_commands`, the member's key, or its directory when it has no
   key, is used where `course_dir` is used today.

4. **Per-member result.** The wrapper catches `SystemExit` and counts a nonzero
   code (or a non-int code) as failed; code 0 or `None` is ok. `RegistryError` for
   an element is reported with the same `Error:` text as `die()` and counts as
   failed. `KeyboardInterrupt` and `click.Abort` are not caught, so Ctrl-C stops
   the whole command. Output goes to the same streams as today.

   Any other `Exception` from a member is printed as `Error: TYPE: message`,
   counts as a failed member, and does not stop the later members. Every
   `COURSE_DIR` command also carries `@_handle_cli_errors`, so the errors it
   knows get the same one-line messages in a group as in a single run.

5. **Output.** Group runs print `=== GROUP: MEMBER (i/N) ===` before each run and
   one `MEMBER: ok|failed, ...` summary line after the last, to stdout. The exit
   status is 1 if any member failed. Single-course runs print neither.

6. **`--config` and groups.** The decorator checks `--config` before any run
   starts: given together with a group `COURSE_DIR`, it dies. `_ConfigParam` and
   `resolve_config` die when the key names a group.

7. **Validation up front.** The whole group is parsed before the first run, so a
   nested group, an empty array or a malformed element is reported once and
   nothing runs. A member whose directory is missing is not an up-front error:
   it fails at its turn and the others continue (spec scenario).

8. **Every `COURSE_DIR` command accepts a group** (confirmed): none refuses
   one, including `cp` and `generate-due-dates`, for consistency. The only
   rejection is `--config KEY` when the key names a group.

9. **Heading line** (confirmed): each group run is preceded by
   `=== GROUP: MEMBER (i/N) ===`.

10. **String elements in a group** (confirmed): a registered key of a non-group
    entry first, then an absolute or `~` path; never resolved against the
    current directory.

11. **Format version.** The registry is a per-user file outside any course repo,
   and older registry files still parse unchanged, so `FORMAT_VERSION` and
   `MIGRATIONS` are untouched.

## Risks / Trade-offs

- [A member's `die()` mid-run leaves partial work (for example a half-updated
  Canvas course)] → Same as a single failed run today; the manifest is flushed
  after every write, and the summary names the failed member so it can be
  rerun alone.
- [Interactive prompts in a long group run are easy to miss] → The heading line
  names the member before its prompts.
- [`-t pages/week1.md` is resolved against the current directory for every
  member] → Accepted by the user; members of a group normally share a repo.
- [A decorator that swallows `SystemExit` could hide a bug in a command] →
  The failure is still counted, printed, and reflected in the exit status.
- [Module-level `ContextVar` is hidden state] → It is set and reset only by the
  decorator, in a `try/finally`, and `_resolve_course` falls back to normal
  resolution when it is unset (library and test callers).

## Canvas API behavior

None. The change does not call Canvas itself and adds no new Canvas request.
Nothing here deletes or overwrites Canvas content beyond what each wrapped
command already does for its single course, with the same confirmation prompts
per member. There is nothing to verify live.

## Migration Plan

None: no manifest or course repo format change. Existing registries keep working.

## Open Questions

These were not discussed with the user. The specs above assume the answer given.

- Declining a confirmation prompt in one member: counted as a failed member
  when it exits nonzero, and the other members still run (follows from the
  chosen failure policy).
- Duplicate elements in one group (`["13", "13"]`): proposed to run each listed
  element, as written, without de-duplicating.
