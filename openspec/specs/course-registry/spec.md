# course-registry Specification

## Purpose

Lets a user name courses and terms by short keys kept in per-user files, so a
command can act on a course from any working directory, and makes the course
argument behave the same way in every command that takes one.

## Requirements

### Requirement: The course registry file

The tool SHALL read a per-user registry from
`~/.config/markdown-to-canvas/course_registry.toml`. The tool SHALL NOT create
or change the file except when `import --register` adds an entry. The file has
a `[courses]` table that maps a key to an entry. An entry is either a string
(the course directory) or an inline table with a required `path` and an optional
`config`. A leading `~` in a path is expanded to the home directory; any other
non-absolute path SHALL be an error naming the key. `config` is a path relative
to the course directory and names the `canvas.toml` to use. Any other key in an
entry, or a `config` or `path` that is not a string, SHALL be an error naming the
key and the file. A missing registry file is an error only when a key has to be
looked up.

#### Scenario: String entry
- **WHEN** the registry has `142 = "/home/me/courses/it143"` and the user runs `update 142` from an unrelated directory
- **THEN** the command acts on `/home/me/courses/it143`

#### Scenario: Entry with its own config
- **WHEN** the registry has `142a = { path = "/home/me/courses/it143", config = "course_settings/canvas-sec-a.toml" }` and the user runs `update 142a`
- **THEN** the command acts on `/home/me/courses/it143` using `course_settings/canvas-sec-a.toml` inside it, and the manifest is the one named after that config

#### Scenario: Unknown entry key
- **WHEN** an entry is `{ path = "/x", cfg = "y" }`
- **THEN** any command that looks up that key fails with an error naming the key `cfg`, the entry and the allowed keys, and changes nothing

#### Scenario: Relative registered path
- **WHEN** an entry's path is `courses/it143`
- **THEN** a command that looks up that key fails with an error saying the path must be absolute or start with `~`

### Requirement: Course argument resolution

Every subcommand that acts on an existing course directory (`update`, `publish`,
`prune`, `clean-manifest`, `upgrade`, `generate-due-dates`, `list-titles`,
`find-canvas-orphans`, `find-local-orphans` and `emit-workflow`) SHALL take its
argument under the name `COURSE_DIR`. When the argument is given, the tool SHALL
first treat it as a path, and use it as typed, without walking up, if a
directory exists there. If no directory exists at that path, the tool SHALL look
the argument up as a registry key. If it is not a key either, the command SHALL
fail with an error that says the argument is neither a directory nor a
registered course and lists the registered keys. A registered path that is not
an existing directory SHALL fail with an error naming the key and the path.

When the argument is omitted, every one of these subcommands except `prune`
SHALL walk up from the current directory to the nearest directory containing
`course_settings/course_settings.toml`, and fail with an error asking for the
argument when there is none. `prune` SHALL keep `COURSE_DIR` as a required
argument. `find-canvas-orphans`, `find-local-orphans`, `list-titles` and
`emit-workflow` SHALL walk up like the others instead of defaulting to the
current directory.

`mv` and `import` are not covered: `mv` derives its course directory from the
paths it is given, and `import` names a directory to create.

#### Scenario: Path wins over a key
- **WHEN** the registry has key `142` and the current directory contains a directory named `142`
- **THEN** `update 142` acts on the directory `./142`

#### Scenario: Key used when no such directory exists
- **WHEN** no directory `142` exists in the current directory and the registry has key `142`
- **THEN** `update 142` acts on the registered directory

#### Scenario: Unknown course
- **WHEN** the argument is `999`, no directory `999` exists, and the registry has keys `142` and `143`
- **THEN** the command fails with a non-zero status, an error naming `999`, and the keys `142` and `143`, and changes nothing

#### Scenario: Registered directory missing
- **WHEN** the registry maps `142` to a directory that has been deleted
- **THEN** the command fails with an error naming key `142` and the missing path

#### Scenario: Omitted argument walks up
- **WHEN** the user runs `find-local-orphans` with no argument from `pages/` inside a course
- **THEN** the command acts on the enclosing course directory

#### Scenario: prune requires an argument
- **WHEN** the user runs `prune --delete` from inside a course with no `COURSE_DIR`
- **THEN** the command exits with a usage error and contacts nothing

#### Scenario: Help text
- **WHEN** the user runs `--help` for any of the listed subcommands
- **THEN** the argument is shown as `COURSE_DIR` and the word `REPO` does not appear as an argument name

### Requirement: A registry entry's config applies to that run

When a course argument resolves through the registry and the entry has a
`config`, subcommands that accept `--config` SHALL use the entry's config for
that run. `--config` on the command line SHALL take precedence. An argument that
resolves as a path, and an omitted argument, SHALL use no registry config, even
when the directory is also registered.

#### Scenario: Entry config used
- **WHEN** `142a` has `config = "course_settings/canvas-sec-a.toml"` and the user runs `update 142a`
- **THEN** `canvas-sec-a.toml` is read and `.manifest-canvas-sec-a.toml` is the manifest

#### Scenario: Command line overrides
- **WHEN** the user runs `update 142a --config course_settings/canvas-sec-b.toml`
- **THEN** `canvas-sec-b.toml` is used

#### Scenario: Path argument ignores the registry
- **WHEN** the user runs `update /home/me/courses/it143` and that directory is registered as `142a` with a config
- **THEN** the default `course_settings/canvas.toml` is used

### Requirement: The resolved course directory is printed

Every subcommand that takes `COURSE_DIR` SHALL print the resolved absolute
course directory, labelled `Course dir:`, before it reads or changes anything
else, and SHALL name the registry key in the same line when the directory came
from a key. `prune` SHALL do so before it asks for confirmation or contacts
Canvas.

#### Scenario: Directory found by walking up
- **WHEN** the user runs `update` from a subdirectory of a course
- **THEN** the first line of output is `Course dir:` followed by the absolute path of the enclosing course

#### Scenario: Directory found by key
- **WHEN** the user runs `prune 142 --delete`
- **THEN** the output shows the absolute path with the key `142` before any prompt or Canvas call

### Requirement: Term names

`generate-due-dates` SHALL accept its `TERM_FILE` argument as a path or as a
term name. When a file exists at the path as typed, it SHALL be used. Otherwise
the tool SHALL look for `~/.config/markdown-to-canvas/terms/<argument>.toml`. If
neither exists, the command SHALL fail with an error that names both locations
tried and lists the term names available.

#### Scenario: Term by name
- **WHEN** `~/.config/markdown-to-canvas/terms/2026Fall.toml` exists, no file `2026Fall` exists in the current directory, and the user runs `generate-due-dates 2026Fall 142`
- **THEN** the command reads that term file for the course registered as `142`

#### Scenario: Path wins
- **WHEN** a file `./2026Fall` exists and a term named `2026Fall` also exists
- **THEN** the file `./2026Fall` is used

#### Scenario: Unknown term
- **WHEN** the argument is `2027Spring` and no such file or term exists
- **THEN** the command fails with an error that lists the terms found, and changes nothing

### Requirement: API token fallback file

At startup the tool SHALL load `.env` from the current directory (or the nearest
parent that has one), and its values SHALL override the shell environment, as
before. It SHALL then load `~/.config/markdown-to-canvas/.env` without
overriding any variable that is already set. The precedence for a variable is
therefore the `.env` found from the current directory, then the shell
environment, then the fallback file. A missing file is not an error.

#### Scenario: Token from the fallback
- **WHEN** no `.env` is found from the current directory, `CANVAS_API_TOKEN` is not set in the shell, and the fallback file sets it
- **THEN** `update 142` from an unrelated directory uses that token

#### Scenario: Shell beats fallback
- **WHEN** the shell sets `CANVAS_API_TOKEN` and the fallback file sets a different value
- **THEN** the shell's value is used

#### Scenario: Local .env beats both
- **WHEN** a `.env` in the current directory sets `CANVAS_API_TOKEN`
- **THEN** its value is used, whatever the shell and the fallback file hold

### Requirement: Shell completion of keys and term names

The completion installed by `install-completion` SHALL offer the registry keys
for a `COURSE_DIR` argument, in addition to directory names, and SHALL offer the
term names for `generate-due-dates`'s `TERM_FILE` argument, in addition to file
names. The candidates SHALL be read when Tab is pressed, so a key added to the
registry later is offered without reinstalling. A missing or unreadable registry
SHALL yield no key candidates and no error message.

#### Scenario: Key offered
- **WHEN** the registry has keys `142` and `143` and the user presses Tab after `markdown-to-canvas update `
- **THEN** `142` and `143` are among the candidates

#### Scenario: New key without reinstall
- **WHEN** the user adds key `144` to the registry after installing completion
- **THEN** `144` is offered at the next Tab press

#### Scenario: Term names offered
- **WHEN** the terms directory holds `2026Fall.toml` and the user presses Tab after `markdown-to-canvas generate-due-dates `
- **THEN** `2026Fall` is among the candidates

### Requirement: import can register the new course

`import` SHALL accept `--register KEY`. After the course directory is written
successfully, it SHALL add `KEY` to the `[courses]` table of the registry with
the absolute path of the new directory, creating the registry file and its
directory when they do not exist, and SHALL print the key and path it added.
When `KEY` already exists, `import` SHALL fail before writing anything, and SHALL
NOT overwrite the entry. Comments and other entries in the registry SHALL be
preserved. An `import` that fails SHALL NOT register the key.

#### Scenario: New key
- **WHEN** the user runs `import cartridge.imscc ~/courses/it143 --register 143`
- **THEN** the course is imported and the registry maps `143` to the absolute path of `~/courses/it143`

#### Scenario: Key already taken
- **WHEN** the registry already has `143` and the user passes `--register 143`
- **THEN** the command exits with an error naming the existing entry, and the output directory is not created

#### Scenario: Registry comments kept
- **WHEN** the registry contains hand-written comments and another course
- **THEN** after `--register` those comments and that entry are unchanged

#### Scenario: Import fails
- **WHEN** the import fails partway
- **THEN** the registry is unchanged
