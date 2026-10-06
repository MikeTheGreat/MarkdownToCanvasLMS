# Tasks

## 1. Resolver module

- [x] 1.1 Create `src/markdown_to_canvas/date_placeholders.py` with the span regex, attribute parsing (quoted and bare values; unknown attribute, extra class or id, bad `field`/`type` are errors) and `find_placeholders(text)`; verify with unit tests in `tests/test_date_placeholders.py` covering quoted/bare values, each invalid case, and that fenced code blocks and inline code spans are skipped
- [x] 1.2 Add `DatePlaceholderContext` and resolution against a `due_dates` list (exact `name`, `type` filter, own title/type when `item` is omitted, ambiguous name, no match, sentinels `NONE`/`KEEP`/`CREATE_NONE_THEN_KEEP`/`""`, missing key, unparsable value, omitted `item` with no own entry); verify each spec scenario under "Only due_dates entries can be referenced", "The file's own entry" and "Unresolved placeholders are errors" with unit tests
- [x] 1.3 Add formatting in the stored clock time and offset with no conversion, and the tool's own handling of `%-d`, `%-m`, `%-H`, `%-I`, `%-M`, `%-j`; verify with unit tests (`11:59 PM` from `-07:00`, naive value shown as written, every no-padding directive, default format output `Tuesday, October 27 at 11:59 PM`)
- [x] 1.4 Add `expand(text, context, errors)` that replaces each span with Markdown-escaped date text outside code, keeping surrounding markup, and returns the `dates_used` records; add `check_leftovers_html(html)` and a Markdown leftover check; verify with unit tests, including the nested `[**... [x]{.replace_date_with}**]{style=...}` case and a span with brackets in its text being reported as an error

## 2. Settings key, import and format version

- [x] 2.1 Load `replace_date_with_format` (default when absent, whole-run error when not a string) and add it to `sync._NON_METADATA_SETTINGS_KEYS`; verify with unit tests and a `test_sync.py` test that editing the key does not upload course settings
- [x] 2.2 Make `import` write the key with its one-line comment directly above it, before `due_dates` (or the first table header); verify with an import test that parses the file and checks the key is top-level and the comment is on the line above
- [x] 2.3 Set `repo_format.FORMAT_VERSION = 10` and add `_migrate_9_to_10` (text-level insert with the same comment, skip and report when the key is set, re-parse comparison with a notice on mismatch, stamp manifests); verify with tests for each scenario in the `repo-format-version` delta (upgrade, key already present, noop, older tool refuses), updating tests that hard-code version 9

## 3. update

- [x] 3.1 Build the run-level part of the context once in `run_sync` (flag-filtered `due_dates` and the default format) and store it on `SyncContext`; verify with an existing sync test still passing and a new test that an `only_if`-removed entry does not resolve
- [x] 3.2 Call `expand` after `preprocess_snippets` in the content path (pages, assignments, discussions, announcements), and run the HTML leftover check after `markdown_to_html`; on error skip the upload and leave the entry unsynced; verify with `test_sync.py` tests: placeholder replaced in the uploaded body, error file skipped while another file uploads, run exits non-zero
- [x] 3.3 Do the same for the syllabus, quiz descriptions, quiz question files (own entry = the quiz) and question-bank question files; verify with one `test_sync.py` test per path
- [x] 3.4 Record `dates_used` in the manifest entry on upload (absent when the file has no placeholders), including quizzes, whose record covers the description and all question files; verify by asserting the manifest contents after a sync
- [x] 3.5 Add the `current_dates` check to `manifest.needs_sync` and `_quiz_needs_sync` (stale when any record's text differs or no longer resolves; `--verbose` prints the reason); verify with tests: `due_dates` change re-uploads only the file quoting it, unrelated change re-uploads nothing, default-format change re-uploads files that rely on it, entry without a record behaves as before, re-upload still respects the newer-on-Canvas check

## 4. publish, generate-due-dates, cp

- [x] 4.1 Call `expand` in `publish.render_page_markdown` (and the quiz study-guide path) before `_strip_pandoc_syntax`, collect errors, and stop `run_publish` before writing when any occur; verify with publish tests: date in the Markdown, no span syntax, no files written on an error
- [x] 4.2 In `generate_due_dates.plan_generation`, build the post-plan entry list and check every placeholder in the repo (snippets expanded, conditionals not applied, `only_if` ignored, `.canvasignore` honored), adding failures to `plan.errors`; verify with tests for the three scenarios in the `generate-due-dates-command` delta, including `--noop`
- [x] 4.3 In `cp._plan_warnings`, warn for each placeholder with an explicit `item` (in copied files and their snippets) that the destination's `due_dates` lacks; verify with cp tests for missing and present entries

## 5. Documentation and verification

- [x] 5.1 Document the placeholder syntax, attributes, default-format key, errors and re-upload behavior in README.md (near the due_dates and snippets sections, with the Habit Loop example), and confirm the README table of contents links to it
- [x] 5.2 Document the resolver, the expansion stage, the `dates_used` manifest record, migration 9 -> 10 and the `generate-due-dates`/`cp` hooks in ARCHITECTURE.md; check TODO.md and BUGS.md for items to update (the MkDocs due-dates item stays)
- [x] 5.3 Run the full test suite (`uv run pytest`) and confirm it passes
- [x] 5.4 Verify live in the sandbox course 2758791 per CLAUDE_NOTES/CLAUDE-IN-CHROME.md: add a placeholder to a sandbox discussion, `update`, check the rendered text and that the HTML has no `replace_date_with` span; change the entry's `due_at`, `update` again, and confirm only that discussion's body was re-uploaded with the new date
