Goal: reuse the existing "calculate absolute, real dates from start of quarter + relative offsets here in markdown-to-canvas

Basic approach:

- Copy and adapt code from MikesGradingTool
  - Found in /home/mike/Dropbox/Work/Courses/MikesGradingTool/
- Use ~/mikesgradingtool/config.json courses.142 and courses.143 for examples

New array of tables in course_settings.toml:

- import should always put an empty, default listing in the course_settings.toml
- list out the options for each setting
- Going to need a different key - use the assignment title (like in the absolute due dates array)

new CLI subcommand

- add a new command so we don't accidentally run it as part of a different command
- make sure to confirm that the user is ok before changing
- have a noop mode
- optionally update the absolute due dates array

Related work to do:

- Code (maybe a script?  maybe part of markdown-to-canvas?)  to gather  up info from original config & print results, suitable for pasting into  course_settings.toml

- AI skill to set up relative date system from an existing course due dates array in course_settings.toml
  - Tell it what to use as 'backbone' assignments, and everything else is relative to those?
