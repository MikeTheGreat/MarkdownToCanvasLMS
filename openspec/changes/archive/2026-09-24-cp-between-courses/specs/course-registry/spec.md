# Spec Delta

## MODIFIED Requirements

### Requirement: Course argument resolution

Every subcommand that acts on an existing course directory (`update`, `publish`,
`prune`, `clean-manifest`, `upgrade`, `generate-due-dates`, `list-titles`,
`find-canvas-orphans`, `find-local-orphans`, `emit-workflow` and `cp`) SHALL take its
argument under the name `COURSE_DIR`. For `cp`, `COURSE_DIR` names the
destination course and follows its `SRC` arguments. When the argument is given, the tool SHALL
first treat it as a path, and use it as typed, without walking up, if a
directory exists there. If no directory exists at that path, the tool SHALL look
the argument up as a registry key. If it is not a key either, the command SHALL
fail with an error that says the argument is neither a directory nor a
registered course and lists the registered keys. A registered path that is not
an existing directory SHALL fail with an error naming the key and the path.

When the argument is omitted, every one of these subcommands except `prune`
and `cp` SHALL walk up from the current directory to the nearest directory containing
`course_settings/course_settings.toml`, and fail with an error asking for the
argument when there is none. `prune` and `cp` SHALL keep `COURSE_DIR` as a required
argument. `find-canvas-orphans`, `find-local-orphans`, `list-titles` and
`emit-workflow` SHALL walk up like the others instead of defaulting to the
current directory.

`mv` and `import` are not covered: `mv` derives its course directory from the
paths it is given, and `import` names a directory to create. `cp` derives its
source course directory from its `SRC` paths in the same way as `mv`.

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

#### Scenario: cp requires a destination
- **WHEN** the user runs `cp pages/intro.md` with no destination
- **THEN** the command exits with a usage error and writes nothing

#### Scenario: cp destination by key
- **WHEN** the registry has key `143` and no directory `143` exists in the current directory
- **THEN** `cp pages/intro.md 143` copies into the registered directory and prints `Course dir:` with that directory and key

#### Scenario: Help text
- **WHEN** the user runs `--help` for any of the listed subcommands
- **THEN** the argument is shown as `COURSE_DIR` and the word `REPO` does not appear as an argument name

