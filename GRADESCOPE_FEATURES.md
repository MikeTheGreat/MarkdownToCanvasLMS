# Gradescope Features (exploration)

Tracking notes for a possible "upload to Gradescope" capability in this tool.

## Candidate library

- [nyuoss/gradescope-api](https://github.com/nyuoss/gradescope-api) — unofficial Python client for Gradescope, driven via an authenticated `requests.Session` (cookie-based, since Gradescope has no official API). Chosen as the best-maintained option among the unofficial Gradescope clients surveyed.

## Open questions

- What Gradescope content types would this tool create/update (assignments, rosters, rubrics, submissions)?
- How does auth/cookie handling fit into this tool's existing config model (`course_settings/`)?
- Does this become a new subcommand, or an extension of an existing one (e.g. `publish`)?
