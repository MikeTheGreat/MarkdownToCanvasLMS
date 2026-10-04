# Claude in Chrome for checking output in Canvas

Claude can use the Claude in Chrome extension to look at what this tool
produced in a real Canvas course, instead of the user checking by hand. As of
2026-09-30 this is set up and working; first used for a feature on 2026-10-03. Decide case by case which changes are worth a check in Canvas.

## Test course

- https://cascadia.instructure.com/courses/2758791, titled "TestGH2CCourse"
  ("Test GitHub To Canvas Course"; GitHub To Canvas was this tool's original
  name).
- It is unused and nearly empty. Its home page is the Modules page, with no
  modules yet.
- Claude may add, edit or delete anything in this course. Claude must not
  change any other course.

## Starting a session with the browser tools

- The `mcp__claude-in-chrome__*` tools exist only when Claude Code is launched
  with `claude --chrome` (or `claude --chrome --continue`, or
  `claude --chrome --resume <session-id>`). Without it, ToolSearch finds no
  chrome tools. Running `/chrome` in a session did not turn them on
  (2026-09-30); restarting with `--chrome` did.
- Chrome must be running with the Claude extension connected.
- Claude uses the user's existing Canvas sign-in. If Chrome was restarted the
  Canvas session may be gone and Canvas redirects to Microsoft SSO
  (login.microsoftonline.com). The user has to sign in; Claude does not enter
  passwords.
- Chrome shows a bar reading "'Claude' started debugging this browser" while
  the extension controls a tab. That is Chrome's normal notice for the
  extension's debugger access, not a breakpoint. Clicking its Cancel button
  disconnects the extension.
- If the extension reports "not connected" (for example after the laptop
  suspends), ask the user to reconnect it rather than retrying.

## Site access: the fix that made the tools work

The extension's "Site access" in `chrome://extensions` → Claude → Details is
set to "On specific sites". A site must be on that list or most tools fail on
it with timeouts that do not mention permissions:

- `get_page_text` and `read_page`: "Page still loading (executeScript waited
  45000ms for document_idle)", even when the page is fully loaded.
- `computer` screenshots: "Script injection timed out after 5000ms".

`navigate`, the tab tools, `javascript_tool` and `read_console_messages` still
work on an unlisted site, which makes the failure look like a slow page.
After the user added `https://cascadia.instructure.com/*` (and
`https://xkcd.com/*` for testing) on 2026-09-30, all of the tools worked on
the course home page: screenshot, `get_page_text` (the Modules page text) and
`read_page` (course navigation links with refs). The list also has
`https://www.gradescope.com/*` for the Placement_Test project.

If these timeouts come back, or Claude needs a new site (for example a
Panopto or other LTI domain inside Canvas), ask the user to check that list
before debugging anything else.

## Tips

- After `navigate`, don't run a screenshot or `get_page_text` in the same
  parallel batch. On 2026-09-30 those ran before the navigation finished and
  returned the previous page. Call them after `navigate` returns.
- `javascript_tool` can read the HTML Canvas actually stored and rendered,
  which is often the most direct way to check this tool's output. For
  example:

  ```js
  document.querySelector('#content')?.innerHTML
  ```

## Pushing content to the test course

Set up on 2026-10-03 and first used to check `dont_reschedule_dates_before`.

- The course repo is `CLAUDE_NOTES/sandbox_course/` (its `canvas.toml` points
  at course 2758791). It is kept between sessions on purpose: add content to
  it for each new feature instead of rebuilding it. Its README.md lists what
  each piece of content is there to test.
- The token is `CANVAS_API_TOKEN` in this repo's `.env` (gitignored; renewed
  2026-10-03). The tool does not read `.env` itself, so load it in the same
  shell command:

  ```bash
  set -a; . ./.env; set +a
  uv run markdown-to-canvas update CLAUDE_NOTES/sandbox_course
  ```

  A 401 from Canvas means the token has expired again; ask the user for a new
  one rather than creating one in Canvas.
- The first `update` from a new manifest needs `--yes` when there is no
  terminal (it asks to record the course).
- To check what Canvas stored, `javascript_tool` on any course page can call
  the API with the user's session, no token needed. Canvas prefixes JSON with
  `while(1);`:

  ```js
  const r = await fetch('/api/v1/courses/2758791/assignments?per_page=50');
  JSON.parse((await r.text()).replace(/^while\(1\);/, ''))
  ```

  The assignments list includes graded discussions and quizzes, and its
  `updated_at` shows which items an `update` actually touched.

## Related

The Placement_Test project
(`~/Dropbox/Work/Misc/2026-2027/Placement_Test/CLAUDE.md`, section
"Definition of done: check on Gradescope") uses the same approach with
Gradescope. Its note on hidden Dropzone file inputs (give the input an
`aria-label` with JavaScript so `find` returns a ref, then use `file_upload`)
may apply to Canvas file uploads too.
