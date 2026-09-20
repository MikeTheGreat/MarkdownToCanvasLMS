# Proposal

## Why

Every command that acts on a course needs either a path argument or a current
directory inside the course. Someone who works on several courses has to `cd`
into each one or type its full path. A per-user registry of short course keys
(and short term names) lets `markdown-to-canvas update 142` run from any
directory. TODO.md's "Registry of courses, term" item asks for this.

The change also cleans up the course argument. The commands name it
inconsistently (`REPO`, `COURSE_DIR`), default it differently (walk up, `"."`,
required), and only some accept `--config`.

## What Changes

Existing mechanisms that cover part of this, and how the change relates to them:

- **Repo-root walk-up** (`update`, `publish`, `clean-manifest`, `upgrade`,
  `generate-due-dates`) already runs a command from any subdirectory of a
  course. It stays, and extends to the commands that currently default to `"."`.
  It cannot reach a course from outside it, which is what the registry adds.
- **`--config`** already selects one of several `canvas.toml` files in a repo.
  A registry entry may carry its own `config`, so each section gets its own key.
- **The term-file path argument** of `generate-due-dates` stays. A term name is
  an alternative way to name that file.
- **`install-completion`** already installs dynamic shell completion, so key and
  term-name completion needs no new install step.

Changes:

- New per-user registry `~/.config/markdown-to-canvas/course_registry.toml`,
  hand-edited, mapping a key to a course directory and, optionally, a `config`
  (relative to the course directory).
- New term directory `~/.config/markdown-to-canvas/terms/`; a term is named by
  its file name without `.toml`.
- **Course argument resolution.** When the argument is omitted, walk up from the
  current directory. `prune` is the exception and keeps a required argument.
  When it is given, try it as a path first; if no such directory exists, look it
  up as a registry key. A missing key is an error that lists the registered keys.
  A registered path that does not exist is an error naming the key.
- **Registry `config`.** When an argument resolves through the registry, the
  entry's `config` is used for that run. `--config` on the command line
  overrides it. An argument that resolves as a path, or an omitted argument,
  uses no registry config.
- **Rename.** `REPO` and `COURSE_DIR` both become `COURSE_DIR` in every
  command's arguments, help text and documentation.
- **Walk-up for more commands.** `find-canvas-orphans`, `find-local-orphans`,
  `list-titles` and `emit-workflow` walk up instead of defaulting to `"."`.
- **Resolved directory shown.** Every command that takes a course directory
  prints the resolved directory (and the registry key, when one was used) before
  acting.
- **`generate-due-dates`** keeps `TERM_FILE [COURSE_DIR]`. `TERM_FILE` is tried
  as a path first, then as a term name. `relative_table` is removed from the
  term file; `--table` selects the table and defaults to `default`.
  **BREAKING**: a term file that contains `relative_table` is rejected, and a
  section whose only table is not named `default` needs `--table`.
- **Format version.** Because the term file that `import` writes to
  `course_settings/term_dates.toml` and the table-selection rule change,
  `repo_format.FORMAT_VERSION` goes up by one, with a migration that removes
  `relative_table` from `course_settings/term_dates.toml` and renames a lone
  non-`default` table to `default`. Term files kept outside the repo are not
  reachable by the migration and must be edited by hand.
- **API token.** `~/.config/markdown-to-canvas/.env` is loaded as a fallback.
  Precedence is the `.env` in the current directory, then the shell
  environment, then the fallback file.
- **`install-completion`.** The course argument completes registry keys and the
  term argument completes term names.
- **`import --register KEY`** adds the new course to the registry, refusing to
  overwrite an existing key. The registry is otherwise hand-edited.
- **TODO.md.** Remove the "Registry of courses, term" item. Add a note about
  letting `-t`, `-s` and `mv` resolve paths relative to a registered course.

Core subcommands: `update` and `publish` gain key resolution and the rename.
`import` gains `--register` and the resolved-directory rule does not apply,
since its argument names a directory to create. `mv` takes only file paths and
derives its repo from them; it is deliberately left out, and the TODO.md note
records the gap.

## Capabilities

### New Capabilities

- `course-registry`: the registry and term-directory files, course-argument and
  term-name resolution, registry `config` entries, printing the resolved course
  directory, the `.env` fallback, key and term completion, and `import --register`.

### Modified Capabilities

- `generate-due-dates-command`: the term file argument accepts a term name; the
  repo argument becomes `COURSE_DIR` and resolves through the registry.
- `relative-due-dates`: `relative_table` is no longer a term-file key, and table
  selection is `--table`, else `default`.
- `repo-format-version`: a new migration removes `relative_table` from the
  in-repo term file and renames a lone non-`default` table; `upgrade`'s repo
  argument resolves through the registry.

## Impact

- Code: `cli.py` (argument declarations, `_resolve_repo`, `install-completion`,
  the `.env` load at import), `config.py` (`find_repo_root`, registry lookup),
  a new registry module, `relative_dates.py` and `generate_due_dates.py` (term
  file keys, table selection), `repo_format.py` (`FORMAT_VERSION`,
  `MIGRATIONS`), `imscc_import.py` (`--register`, the commented example term
  file).
- Docs: README.md, ARCHITECTURE.md (which still mentions a `--repo` flag that
  does not exist), TODO.md.
- Dependencies: none new; `tomlkit` is already used for writing TOML.
- Existing user files: term files containing `relative_table`, and repos whose
  only relative-due-dates table is not named `default`.
