# Spec Delta

## MODIFIED Requirements

### Requirement: Repo-reading operations refuse a mismatched version

The format check SHALL be part of the tool's library operations, not only of
the command-line layer, so that every code path that reads a course repo
performs it. The operations behind `update` (including `--check-all`),
`mv`, `publish`, `prune`, `clean-manifest`, `find-local-orphans`,
`find-canvas-orphans`, `list-titles`, `generate-due-dates` and `cp` SHALL check the format version of
the repo and of every `.manifest-*.toml` in it (for `cp`, both the source and the
destination repo) before reading content files,
writing any file, or making any change on Canvas. If any of them differs from
the tool's current format version, the operation SHALL fail with an error
(the command exits with a non-zero status) and change nothing. `import`,
`setup`, `install-completion`, `create-tool-aliases` and `emit-workflow`
SHALL NOT perform this check. `upgrade` performs its own version handling
(see its requirement).

#### Scenario: Repo older than the tool
- **WHEN** the repo's format version is lower than the tool's
- **THEN** the command exits with an error that states both versions and tells the user to run `markdown-to-canvas upgrade`

#### Scenario: Repo newer than the tool
- **WHEN** the repo's format version is higher than the tool's
- **THEN** the command exits with an error that states both versions and tells the user to update the tool

#### Scenario: Manifest older than the repo
- **WHEN** `course_settings.toml` has the current format version but a `.manifest-*.toml` in the repo does not
- **THEN** the command exits with an error naming that manifest and telling the user to run `upgrade`

#### Scenario: Matching versions
- **WHEN** the repo and all of its manifests have the tool's current format version
- **THEN** the command runs as it did before this change

#### Scenario: Library call without the CLI
- **WHEN** code calls the library operation behind `update` (or any other listed command) directly on a version-0 repo
- **THEN** the operation raises the format error before reading content or writing any file

#### Scenario: generate-due-dates on an old repo
- **WHEN** a user runs `generate-due-dates` on a version-1 repo
- **THEN** the command exits with an error telling the user to run `upgrade`, and writes nothing

#### Scenario: cp with an old destination
- **WHEN** a user runs `cp` from a current source repo into a destination repo at an older format version
- **THEN** the command exits with an error naming the destination repo and telling the user to run `upgrade`, and writes nothing in either repo
