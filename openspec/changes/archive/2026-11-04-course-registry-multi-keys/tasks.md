## 1. Registry parsing

- [x] 1.1 In `course_registry.py`, accept an array entry in `_read_courses`/entry parsing: each element a string (registered non-group key, else absolute or `~` path, never cwd-relative) or a `{path, config}` table, reusing `_parse_entry`
- [x] 1.2 Reject an empty array, an array element that is an array or names a group key, and any other element type, with an error naming the group key and the registry file
- [x] 1.3 Add `resolve_courses(arg) -> list[ResolvedCourse]` (path wins over key, as before; non-group key gives one element; group gives N); make `resolve_course` raise `RegistryError` for a group key
- [x] 1.4 Make `resolve_config` raise `RegistryError` when the key names a group
- [x] 1.5 Update `_unknown_course_message` and the module docstring; keep `list_keys`/completion offering group keys

## 2. Fan-out decorator

- [x] 2.1 Add `_for_each_course` in `cli.py`: resolve `course_dir` to the member list, die if `--config` is given with a group, run the wrapped command per member, catch `SystemExit` and `RegistryError` per member, let `KeyboardInterrupt`/`click.Abort` through
- [x] 2.2 Print the `=== GROUP: MEMBER (i/N) ===` heading and the final `13: ok, 14: failed` summary only for groups; exit 1 if any member failed
- [x] 2.3 Add the `ContextVar` for the current member; make `_resolve_course` use it when set (still printing `Course dir:` with `(course KEY)` for key members) and fall back to normal resolution otherwise
- [x] 2.4 Apply the decorator (above `_handle_cli_errors`) to `update`, `publish`, `prune`, `fix-manifest`, `fix-markdown`, `upgrade`, `generate-due-dates`, `list-titles`, `find-canvas-orphans`, `find-local-orphans`, `emit-workflow` and `cp`
- [x] 2.5 Make `update` pass the member's key (or directory) to `_move_check_commands` instead of the raw `course_dir`

## 3. Tests (Canvas mocked; outbound HTTP is blocked)

- [x] 3.1 Registry parsing: group of keys, mixed elements, string element not resolved against cwd, nested group, empty array, wrong element type, bad table inside a group
- [x] 3.2 `resolve_courses`/`resolve_course`/`resolve_config` behaviors for group keys, including a directory named like a group key winning
- [x] 3.3 Decorator with a fake command: order of runs, headings, summary text, exit status when all ok, one failed, all failed, an unresolvable element, and `SystemExit(0)`; Ctrl-C stops the run
- [x] 3.4 `--config` with a group `COURSE_DIR`, and `--config GROUPKEY`, fail before any run
- [x] 3.5 `update 101` end to end with mocked Canvas: both members synced with their own config and manifest; options such as `--noop` and `-t` reach each member; a failing first member does not stop the second
- [x] 3.6 `prune` with a group and no `--yes`: each member prompts separately
- [x] 3.7 A single key or path prints no heading or summary; one smoke test per remaining decorated command that a group reaches every member

## 4. Keep the core subcommands in sync

- [x] 4.1 Confirm `update` and `publish` both go through the decorator and behave the same for groups (test both)
- [x] 4.2 Confirm `import` and `mv` need no change (they take no course key); note it in ARCHITECTURE.md

## 5. Documentation

- [x] 5.1 README.md "Naming a course"/"The course registry": group entries, the mixed-element form, headings and summary, `--config` restriction, per-member prompts, no nesting
- [x] 5.2 ARCHITECTURE.md: the decorator, `resolve_courses`, the member `ContextVar`, failure and exit-status rules, and registry file format (`[courses]` table row)
- [x] 5.3 Add "nested groups" to TODO.md as possible future work (cycle detection, de-dup by key); check whether other TODO.md items need updating, including "Let `-t`, `-s` and `mv` use the course registry"
- [x] 5.4 Update the `course_registry.toml` header comment in README examples if it describes only the string/table forms
