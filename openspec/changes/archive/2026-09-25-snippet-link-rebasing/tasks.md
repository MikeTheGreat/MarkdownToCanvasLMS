# Tasks

## 1. Shared link module

- [x] 1.1 Move `transform_links` and its helpers (`_MD_LINK_RE`, HTML attr regexes, `_split_url_title`, `_resolve_repo_relative`, `_compute_relative`) from `mv.py` into a new shared module; `mv.py` imports them. Verify: `uv run pytest tests/test_mv.py` passes unchanged.
- [x] 1.2 Replace the `http://`/`https://`/`mailto:` check with a general scheme check (`^[A-Za-z][A-Za-z0-9+.-]*:`). Verify: new tests show `data:`, `tel:` and `HTTPS:` URLs are left unchanged when a file moves, and existing mv tests still pass.
- [x] 1.3 Add an optional callback to `transform_links` that is called with each relative link that resolves outside the repo from the old folder. Verify: unit test that the callback receives `../../x.png` from `snippets/` and that output is unchanged when no callback is given.

## 2. Rebasing in snippet expansion

- [x] 2.1 In `convert.preprocess_snippets._replace`, rebase the pasted block-snippet content from the snippet's folder to the including file's folder using the shared function, applied outside fenced code. Leave `_replace_inline` alone. Verify: tests in `tests/test_convert.py` for every scenario in the `snippet-links` requirements "Snippet links are relative to the snippet file" and "Links that are not rebased".
- [x] 2.2 Report a link that escapes the repo from the snippet's folder as an error through `errors` (message names includer, snippet and link). Verify: a `test_convert.py` test for the message, and a `tests/test_sync.py` test (Canvas mocked) that the including page is skipped with "Skipping upload due to errors" while another page in the same run uploads.
- [x] 2.3 Verify `update --check-all` exits non-zero for such a snippet link (test in `tests/test_check_all.py`).
- [x] 2.4 Verify through `sync` with mocked Canvas that a page two folders deep including a snippet with `![](../assets/logo.png)` uploads HTML whose image points at the Canvas file for `assets/logo.png`, and that a quiz question file including the same snippet does too.

## 3. Core subcommands and other consumers

- [x] 3.1 update: covered by section 2; confirm that the staleness/ref probes in `sync.py` (~1670, ~3135, ~3152) and targeted sync (`-s`/`-t`) follow the rebased links. Verify: a targeted-sync test where `-t` on a deep page pulls in an asset linked only from its snippet.
- [x] 3.2 publish: in `publish.collect_reachable`, expand block snippets (with the same `flags`) before extracting refs. Verify: `tests/test_publish.py` tests for both scenarios in "publish stages files linked from snippets", plus a test that a snippet error stops `publish` before the build.
- [x] 3.3 publish: verify a staged deep page's snippet image link resolves in the staged `docs/` tree (test on staged Markdown text).
- [x] 3.4 mv: verify the two mv scenarios in "Commands agree on the snippet-relative reading" (`tests/test_mv.py`): moving an includer leaves the snippet file untouched; moving a snippet's target rewrites the snippet's link.
- [x] 3.5 import: confirm no change is needed (it writes only the inline `CANVAS_COURSE_REFERENCE` snippet and stamps `FORMAT_VERSION`). Verify: existing `tests/test_imscc_import.py` passes and a new import records `format_version = 4`.
- [x] 3.6 find-local-orphans: verify the orphan scenario (`tests/test_local_orphans.py`).
- [x] 3.7 cp: verify the cp scenario with a deep includer (`tests/test_cp.py`).

## 4. Format version 4 and migration 3 -> 4

- [x] 4.1 Add `pending_writes` to `repo_format.UpgradeState`, written by `run_upgrade` after each step unless `--noop`. Verify: unit test with a fake migration that a pending write happens normally and not with `noop=True`.
- [x] 4.2 Implement the snippet-link scanner: collect includers (every `.md` outside `snippets/` and hidden folders, `.canvasignore`d included; block refs outside fences only; not `PASTE_SNIPPET_INTO_FRONTMATTER` or inline refs), then classify each rebasable link per the four rules in "Migration 3 to 4". Verify: unit tests for each rule, using the shared link module's parsing.
- [x] 4.3 Add `_migrate_3_to_4` (rewrites via `pending_writes`, `NOTICE:` lines for unconverted links and unused snippets with missing targets, stamps manifests, acts on snippet files only when the settings version is below 4), register it in `MIGRATIONS`, and set `FORMAT_VERSION = 4`. Verify: `tests/test_repo_format.py` tests for every scenario in the `repo-format-version` delta, including byte-for-byte preservation of the rest of the snippet file and `--noop`.
- [x] 4.4 Update tests and fixtures that hard-code version 3 (`tests/fixtures/course_settings/course_settings.toml`, `tests/test_clean_manifest.py`, `tests/test_check_all.py`, `tests/test_generate_due_dates.py`, and any others `grep -rn "format_version = 3" tests` finds). Verify: full `uv run pytest` passes.
- [x] 4.5 Update the "Upgrade an old repo" example in `openspec/specs/repo-format-version/spec.md` if it should name version 4, or leave it (it is conditional on the tool's version). Verify: `openspec validate snippet-link-rebasing --strict` passes.

## 5. Whole-suite check

- [x] 5.1 Run `uv run pytest` and confirm everything passes; confirm no test makes outbound HTTP (the suite blocks it).
- [x] 5.2 Run `upgrade --noop` and then `update --check-all` on a copy of a real course repo the user names, and report the migration's rewrites and notices to the user before running `upgrade` for real.

## 7. Follow-up from the College101 trial

- [x] 7.1 Change the migration rule so the working includers' reading wins over includers that resolved to nothing. Verify: `test_migration_3_to_4_working_includers_win_over_broken_ones`.
- [x] 7.2 Expand snippets inside snippets recursively (block and inline), relative to the containing snippet, with a 10-level limit and an error naming the chain. Verify: nested-snippet tests in `tests/test_convert.py`.
- [x] 7.3 Make `find_referenced_snippets` follow nesting so staleness, `flags_used` and `cp` see nested snippets. Verify: `test_find_referenced_snippets_follows_nesting`, `test_staleness_probe_includes_nested_snippets`.
- [x] 7.4 Migration converts `$...$` and block refs to other snippets inside snippet files. Verify: `test_migration_3_to_4_converts_refs_to_other_snippets`.
- [x] 7.5 Snippet-ref detection ignores non-path links (fixes false nested-include errors) and multi-line link text. Verify: `test_non_file_links_in_a_snippet_are_not_snippet_refs`, `test_unevaluated_inline_snippet_inside_block_snippet_is_not_a_path`.
- [x] 7.6 Re-run the College101 comparison: old tool 17 errors, new tool after `upgrade` 0 errors, on the same snapshot.

## 6. Documentation

- [x] 6.1 README.md: in the Snippets section, state that links inside a snippet are written relative to the snippet file and are adjusted for each includer; list the forms that are not rebased; describe the escape error. Update the format-version error examples (around line 2942) to version 4 and describe what migration 3 -> 4 changes and its notices.
- [x] 6.2 ARCHITECTURE.md: replace the Snippets bullet that says links are handled by the post-Pandoc step with the rebasing description; document the shared link module, the scheme check, the `publish.collect_reachable` change, `UpgradeState.pending_writes`, and migration 3 -> 4.
- [x] 6.3 BUGS.md: remove the publish reachability entry; add an entry that `mv` rewrites links inside fenced code blocks.
- [x] 6.4 TODO.md: check for items this change completes or affects (none known) and update them.
