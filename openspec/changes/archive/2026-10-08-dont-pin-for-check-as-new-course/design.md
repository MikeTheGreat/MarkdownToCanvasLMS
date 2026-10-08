# Design

## Context

See proposal.md (Why). Pins are loaded and validated once per run in
`run_sync` (`load_pinned_resources`, before phase 0), stored on
`SyncContext.pinned`, and consulted by `_skip_if_pinned()` in every upload
path. `--check-as-new-course` reaches `run_sync` with `mode="new_course"`; it
already rejects `-t`/`-s`, so `run_targeted_sync` is never involved.
`check_pinned_resources_coverage()` runs at the end of `run_sync` against the
pin list.

## Goals / Non-Goals

**Goals:**
- One switch that makes the empty-course check process pinned content.

**Non-Goals:**
- Changing pin behavior in a real `update`, `--noop`, `prune` or `mv`.
- Ignoring pins automatically when a real `update` targets a new (empty
  manifest) course. A real deploy to a new course still skips pinned content;
  the user clears `pinned_resources` for that.

## Decisions

Decisions 1, 2, 4 and 5 were confirmed by the user in the explore
conversation. Decisions 3 and 6 are implementation choices that were not
discussed; see Open Questions.

1. **Opt-in flag, not a change to check mode.** `--check-as-new-course` alone
   keeps honoring pins, so its output still matches what a real first deploy
   with the same settings would do. `--ignore-pinned-resources` turns pins off.
   Alternative considered: always ignore pins in check mode. Rejected because
   check mode would then pass content that a real fresh deploy skips.

2. **Restricted to `--check-as-new-course` for now.** The flag is rejected in
   `cli.py` next to the existing check-mode combination errors, before config
   loading. `--noop` must report what a real update does, so it keeps pins.

3. **Validate, then empty.** `run_sync` gets a keyword argument (e.g.
   `ignore_pinned: bool = False`). It still calls `load_pinned_resources`, so a
   bad entry dies as before. Then, when the flag is set, it passes an empty
   list as `SyncContext.pinned`. No `_skip_if_pinned()` call site changes.
   Alternative: a flag on `SyncContext` checked inside `_skip_if_pinned()`.
   Rejected as more surface for the same effect.

4. **Coverage warning keeps the real list.** `check_pinned_resources_coverage`
   is called with the loaded (unemptied) list, so a typo in an entry is still
   reported.

5. **Notes.** Printed in `run_sync` right after `_setup_mode` prints the CHECK
   MODE banner and pins are loaded, only in `new_course` mode with a non-empty
   list. The ignore note lists entries only with `--verbose`. Without the flag,
   a one-line hint names `--ignore-pinned-resources`.

6. **No repo-format bump.** No file is read differently and nothing new is
   written.

## Risks / Trade-offs

- [A clean check with the flag can hide that a real deploy to a new course
  would skip pinned items] → The ignore note says the unpinning is only for
  this simulated run; README states that a real deploy still honors pins.
- [`run_sync` gains another mode-specific parameter] → It is a single boolean
  that only matters for `new_course`. `run_sync` could assert that it is not
  set in other modes, but the CLI check already prevents that.

## Canvas API behavior

None. Check mode never contacts Canvas.

## Migration Plan

None. The flag is new and off by default.

## Open Questions

- Decision 3 (empty the pin list passed to `SyncContext` rather than add a
  flag checked in `_skip_if_pinned()`) and decision 6 (no format-version
  bump) were not explicitly confirmed. Either alternative leaves the specs and
  the task list unchanged.
