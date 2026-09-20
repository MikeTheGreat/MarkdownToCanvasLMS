# Design

## Context

See proposal.md for motivation. Current state that shapes the approach:

- `cli.py:_resolve_repo()` takes an optional path and otherwise walks up via
  `config.find_repo_root()`. Only `update`, `publish`, `clean-manifest`,
  `upgrade` and `generate-due-dates` use it. `find-canvas-orphans`,
  `find-local-orphans`, `list-titles` and `emit-workflow` default to `"."`, and
  `prune` requires the argument. The argument is declared as
  `click.Path(exists=True, file_okay=False)` in every command, which rejects a
  registry key before any code runs.
- `--config` exists on `update`, `publish`, `prune`, `clean-manifest`,
  `find-canvas-orphans` and `list-titles`. The manifest name derives from the
  config's file name, so choosing a config also chooses a manifest.
- `cli.py:19` runs `load_dotenv(find_dotenv(usecwd=True), override=True)` before
  the package imports, because `config.py` reads `CANVAS_API_TOKEN` at import.
- Six commands print `Repo:` (`prune`, `find-local-orphans`, `clean-manifest`,
  `upgrade`, `generate-due-dates`, `update`); `publish`, `list-titles`,
  `find-canvas-orphans` and `emit-workflow` do not.
- `install-completion` installs Click's own script, which calls back into the
  program on each Tab press, so completion candidates are computed live.
- `relative_dates.select_table()` and `load_term()` implement the
  `relative_table` rule; `_TERM_KEYS` rejects unknown term keys.
- `repo_format.FORMAT_VERSION` is 2. A migration receives an `UpgradeState`
  holding the settings document and the manifests; there is no slot for a third
  file.
- No Canvas API behavior is involved. Nothing here reads or writes Canvas, so
  there is no Canvas behavior to verify, and no operation deletes or overwrites
  Canvas content.

## Goals / Non-Goals

**Goals:**

- One resolution routine for the course argument, shared by every command, so
  behavior cannot drift between commands again.
- A registry that a person can read and edit without the tool.
- No change to how a course directory that is named as a path behaves today.

**Non-Goals:**

- Key syntax for `-t`, `-s` and `mv` paths (`142:pages/a.md`); recorded in
  TODO.md instead.
- Registry management commands (`courses list/add/remove`). Only `import
  --register` writes the file.
- Any change to manifests. They gain no fields; migration 2 -> 3 only stamps
  version 3 on them, as earlier migrations did.

## Decisions

These were confirmed by the user in conversation.

- **Registry file** is `~/.config/markdown-to-canvas/course_registry.toml`;
  term files are in `~/.config/markdown-to-canvas/terms/`; the token fallback is
  `~/.config/markdown-to-canvas/.env`.
- **Resolution order.** An argument is tried as a path first, then as a key. An
  omitted argument walks up, except for `prune`, which requires it. A directory
  named like a key in the current directory therefore wins; no extra prompt is
  added for `prune`, and the printed course directory is the safeguard.
- **Every command that takes `COURSE_DIR` prints the resolved directory**
  before acting.
- **Rename** `REPO`/`COURSE_DIR` to `COURSE_DIR` everywhere.
- **`generate-due-dates TERM_FILE [COURSE_DIR]`** keeps its order. The term is a
  path or a term name.
- **`relative_table` leaves the term file.** `--table` selects a table and
  defaults to `default`. This is handled as a format-version bump with a
  migration (option (a) from the exploration), not a warning period.
- **Each registry entry may carry its own `config`.**
- **`.env` precedence**: the `.env` from the current directory, then the shell,
  then the fallback file.
- **Completion** covers keys and term names.
- **`import --register KEY`** adds an entry. The registry is otherwise
  hand-edited.

Shape of the implementation (structure only; the requirements are in the specs):

- A new module `course_registry.py` holds: reading and validating the registry;
  `resolve_course(arg) -> ResolvedCourse(path, key, config)`; term-name
  lookup; the two completion callbacks; and `add_entry()` for `import`. It has
  no Click dependency apart from the completion helpers, so it can be unit
  tested without invoking the CLI.
- `cli.py` declares the argument with a shared decorator (`type=str`,
  `shell_complete=...`) instead of `click.Path(exists=True)`, and calls one
  helper that resolves, applies the config precedence (`--config` > entry
  config > default), prints `Course dir:` and returns the pair. `_resolve_repo`
  is replaced by that helper; `find_repo_root` stays in `config.py`.
- The fallback `.env` is loaded on the line after the existing `load_dotenv`
  call, with `override=False`, so the import-order constraint is unchanged.
- `imscc_import.py` gets the `--register` option, checks the key before writing
  anything, and registers after the import succeeds. It writes the registry with
  `tomlkit` so comments survive.

## Risks / Trade-offs

- [A stray directory named like a key redirects a destructive command] →
  Accepted by the user. The `Course dir:` line is printed before `prune` asks
  anything or contacts Canvas, and `prune` still requires the argument.
- [The migration cannot reach term files kept outside the repo] → The
  `relative_table` rejection error names the key and says to use `--table`, so
  the edit is one line. Term files in `~/.config/.../terms/` are the likely
  case, and the user has said they are the only person affected.
- [Renaming or dropping a table in `course_settings.toml` may disturb comments
  or layout] → Migration tests run against a fixture with comments, blank lines
  and both inline and `[[...items]]` item layouts, and compare the rest of the
  file byte for byte.
- [The completion callback runs on every Tab press and must not fail] → It
  catches every exception from reading the registry and returns no candidates.
- [`.env` loaded from a wrong directory is now more likely, since users run from
  anywhere] → Unchanged rule (current directory upward); the fallback file is
  the documented place for the token when running from anywhere.
- [Changing four commands from `"."` to walk-up alters a case that used to
  work: a directory with no `course_settings/course_settings.toml`, such as a
  bare content folder] → Those commands now fail with the walk-up error unless
  the path is given explicitly. An explicit path is still used as typed.
- [Registry `config` is ignored by commands with no `--config` (`upgrade`,
  `generate-due-dates`, `find-local-orphans`, `emit-workflow`, `mv`)] → Those
  commands do not read a `canvas.toml` for their work, so nothing is lost;
  the docs say so.

## Migration Plan

- Bump `repo_format.FORMAT_VERSION` from 2 to 3 and add `MIGRATIONS[2]`
  (see the `repo-format-version` delta for its behavior).
- `UpgradeState` gains an optional document for
  `course_settings/term_dates.toml`, written at the same point as the settings
  document, so `--noop` and failure handling behave as they do now.
- Users run `upgrade` once per repo and per machine holding a manifest, as they
  do for any format bump. Term files outside the repo are edited by hand.
- Rollback: the registry and term directory are new and additive, so removing
  them restores the old behavior. A repo already upgraded to version 3 is
  refused by an older tool, as with any earlier bump.
- The commented example that `import` writes to `course_settings/term_dates.toml`
  drops its `relative_table` lines.

## Open Questions

These are proposed defaults that the user has not confirmed. Each is already
written into the specs, so a different answer changes a spec line, not the
approach.

1. **Registry entry shape.** The spec allows a bare string or an inline table
   `{ path, config }`; a relative path is an error; `config` is relative to the
   course directory. The user asked for a `config` per entry but did not fix the
   syntax.
2. **Migration edge cases.** The empty-`default`-plus-one-table case is handled
   by dropping the empty table and renaming the other. This matters because
   migration 1 -> 2 adds an empty `default`, so a repo that used a named table
   after upgrading has exactly that shape. Anything else with several tables is
   left alone with a notice.
3. **Config location.** The spec fixes `~/.config/...`. It does not honor
   `XDG_CONFIG_HOME`.
4. **Output label.** The spec names it `Course dir:`. Today's label is `Repo:`.
5. **Term name lookup.** `2026Fall` maps to `terms/2026Fall.toml`; an argument
   ending in `.toml` that is not an existing path is not looked up as a name.
6. **Registry errors are lazy.** A malformed registry is reported only when a
   command needs a key, so a path argument or walk-up still works with a broken
   registry file.
7. **Migration rewriting method.** Prefer rewriting the
   `[relative_due_dates.tables.<name>...]` table headers as text over moving a
   `tomlkit` table under a new key, because a header rewrite keeps both item
   layouts intact. The choice is invisible to users if the tests pass.
8. **`.env` load message.** The existing call passes `verbose=True`; the fallback
   load should stay quiet when the file is absent, or every user without one sees
   a warning at startup.
