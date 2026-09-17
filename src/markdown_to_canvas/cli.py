import os
import subprocess
import sys
import tomllib
from datetime import datetime
from functools import wraps
from pathlib import Path

import click
import pypandoc
import requests
from dotenv import find_dotenv, load_dotenv

# load_dotenv() must run before the local package imports below, because .config
# (imported transitively by canvas_api/sync/etc.) reads CANVAS_API_TOKEN from the
# environment at import time. That is why those imports deliberately come after
# this call rather than at the top of the file — ruff's E402 is ignored for this
# file in pyproject.toml for exactly this reason.
load_dotenv(find_dotenv(usecwd=True), override=True, verbose=True)


from .canvas_api import get_course, read_tab_configuration
from . import manifest as manifest_lib
from .clean_manifest import (
    apply_clean,
    plan_invalidate_all,
    print_plan,
    run_plan,
)
from .config import Config, find_repo_root
from .config import load as load_config
from .course_guard import CourseGuardError, check_course
from .imscc_import import run_import
from .local_orphans import find_local_orphans
from .local_orphans import print_report as print_local_orphan_report
from .mv import run_mv
from .orphans import find_orphans, print_report
from .publish import run_publish
from .sync import run_prune, run_sync, run_targeted_sync


# all commands must use die() for user-facing errors — no tracebacks, no raw exceptions.
def die(msg: str) -> None:
    click.secho(f"Error: {msg}", fg="red", err=True)
    sys.exit(1)


def _resolve_repo(repo: Path | None) -> Path:
    """Return the course repo to act on.

    An explicit path is used as given — no walking up — so a wrong path still
    reports the missing course_settings/ rather than silently acting on a parent.
    When omitted, walk up from the current directory to find the enclosing repo.
    """
    if repo is not None:
        return repo
    found = find_repo_root(Path.cwd())
    if found is None:
        die(
            "Not inside a course repo (no course_settings/course_settings.toml found "
            "in this directory or any parent). Pass the repo path explicitly."
        )
    return found


def _guard_course(repo: Path, cfg: Config, course, assume_yes: bool) -> None:
    """Stop unless the manifest's Canvas IDs belong to the configured course."""
    manifest_path = manifest_lib.migrate_legacy_manifest(repo, cfg.config_path)
    try:
        check_course(manifest_path, cfg, course.name, assume_yes=assume_yes)
    except CourseGuardError as e:
        die(str(e))


_YES_HELP = (
    "Answer yes to the course confirmation prompt — recording the course on a "
    "first sync, or changing it (which clears the manifest's Canvas IDs). Needed "
    "when there is no terminal to ask."
)


def _ensure_pandoc() -> None:
    try:
        pypandoc.get_pandoc_version()
    except OSError:
        die("Pandoc not found. Run `markdown-to-canvas setup` to install it.")


def _handle_cli_errors(func):
    """Decorator that catches common CLI errors and formats them for the user."""
    @wraps(func)
    def wrapper(*args, **kwargs):
        try:
            return func(*args, **kwargs)
        except FileNotFoundError as e:
            die(f"Config file not found: {e.filename}")
        except tomllib.TOMLDecodeError as e:
            die(f"Invalid canvas.toml: {e}")
        except (ValueError, KeyError) as e:
            die("KeyError or ValueError:" + str(e))
        except requests.exceptions.ConnectionError:
            die("could not connect to Canvas - are you offline?")
    return wrapper


class _FullHelpGroup(click.Group):
    """Show full summary sentences in the command listing instead of truncating."""

    def format_commands(self, ctx, formatter):
        commands = []
        for subcommand in self.list_commands(ctx):
            cmd = self.get_command(ctx, subcommand)
            if cmd is None or cmd.hidden:
                continue
            help_text = cmd.get_short_help_str(limit=300)
            commands.append((subcommand, help_text))

        if commands:
            with formatter.section("Commands"):
                formatter.write_dl(commands)


@click.group(cls=_FullHelpGroup, context_settings={"help_option_names": ["-h", "--help"]})
def main() -> None:
    """Manage Canvas LMS course content from a Markdown repo."""


@main.command(name="setup")
def setup_cmd() -> None:
    """Download Pandoc into the current Python environment."""
    try:
        version = pypandoc.get_pandoc_version()
        path = pypandoc.get_pandoc_path()
        click.echo(f"Pandoc {version} already installed at {path}")
        return
    except OSError:
        pass

    bin_dir = Path(sys.executable).parent
    click.echo(f"Downloading Pandoc into {bin_dir} ...")
    try:
        pypandoc.download_pandoc(targetfolder=str(bin_dir))
        click.secho("Pandoc installed successfully.", fg="green")
    except Exception as e:
        die(f"Failed to download Pandoc: {e}")


def _detect_shell() -> str:
    shell_path = os.environ.get("SHELL", "")
    for name in ("zsh", "fish", "bash"):
        if name in shell_path:
            return name
    return "bash"


def _completion_path(shell: str, prog_name: str) -> Path:
    home = Path.home()
    if shell == "bash":
        return home / ".local/share/bash-completion/completions" / prog_name
    if shell == "zsh":
        return home / ".zfunc" / f"_{prog_name}"
    if shell == "fish":
        return home / ".config/fish/completions" / f"{prog_name}.fish"
    raise ValueError(f"Unsupported shell: {shell}")


@main.command(name="install-completion")
@click.option(
    "--shell",
    type=click.Choice(["bash", "zsh", "fish"]),
    default=None,
    help="Shell to install completion for (auto-detected from $SHELL if omitted).",
)
def install_completion(shell: str | None) -> None:
    """Install shell tab-completion for markdown-to-canvas."""
    from click.shell_completion import BashComplete, FishComplete, ZshComplete

    if shell is None:
        shell = _detect_shell()

    comp_cls = {"bash": BashComplete, "zsh": ZshComplete, "fish": FishComplete}[shell]

    prog_name = "markdown-to-canvas"
    complete_var = "_MARKDOWN_TO_CANVAS_COMPLETE"
    comp = comp_cls(cli=main, ctx_args={}, prog_name=prog_name, complete_var=complete_var)
    script = comp.source()

    if shell == "bash":
        # Click's bash template invokes the completion subprocess as "$1", which bash
        # sets to whatever word the user actually typed (e.g. a "gg" alias), not the
        # real executable — so it fails with "gg: No such file or directory" when
        # completion is registered against an alias. Hardcode the real prog_name so
        # completion works no matter what alias/function `complete -F` is bound to.
        script = script.replace(f"{complete_var}=bash_complete $1)", f"{complete_var}=bash_complete {prog_name})")

    dest = _completion_path(shell, prog_name)
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_text(script)

    click.secho(f"Completion script installed to {dest}", fg="green")
    if shell == "zsh":
        click.echo(
            "Make sure your .zshrc contains:\n"
            '  fpath+=~/.zfunc\n'
            '  autoload -Uz compinit && compinit'
        )
    click.echo("Restart your shell (or open a new tab) to activate.")


@main.command(name="mv", no_args_is_help=True)
@click.argument("src", type=click.Path(path_type=Path))
@click.argument("dest", type=click.Path(path_type=str))
@click.option(
    "--noop",
    "-n",
    is_flag=True,
    default=False,
    help="Show what would change without making any modifications.",
)
@click.option(
    "--verbose",
    "-v",
    is_flag=True,
    default=False,
    help="Print each individual change (moved file, updated link, etc.).",
)
def mv_cmd(src: Path, dest: str, noop: bool, verbose: bool) -> None:
    """Move or rename a file/directory, updating the manifest and all references.

    SRC is the file or directory to move. DEST is the new path, or an
    existing directory to move SRC into (keeping its name), just like the
    normal mv command. A trailing slash on DEST requires it to be an
    existing directory. Both must be within the same course repo and the
    same content-type directory (e.g. both under pages/, or both under
    assets/).

    Updates every .manifest-*.toml, all Markdown cross-references,
    snippet references, and module_order.toml as needed.

    Uses git mv when inside a git repository.
    """
    try:
        run_mv(src, dest, noop=noop, verbose=verbose)
    except ValueError as e:
        die(str(e))
    except subprocess.CalledProcessError as e:
        die(f"git mv failed: {e}")
    except Exception as e:
        die(str(e))


@main.command(name="import", no_args_is_help=True)
@click.argument("imscc_path", type=click.Path(exists=True, path_type=Path))
@click.argument("output_dir", type=click.Path(path_type=Path))
def import_cmd(imscc_path: Path, output_dir: Path) -> None:
    """Import a Canvas course from a local .imscc file into a Markdown repo.

    IMSCC_PATH is the path to a .imscc zip file or an already-extracted directory.
    OUTPUT_DIR is where the course repo will be written (must be empty or new).
    """
    try:
        run_import(imscc_path, output_dir)
    except ValueError as e:
        die(str(e))
    except Exception as e:
        die(str(e))


def _flags_config(repo: Path, config: Path | None) -> Config | None:
    """Load a canvas.toml for its [course_flags] table only.

    Used by the subcommands that never contact Canvas (`publish`,
    `list-titles`): an explicit --config must exist, while the default
    <repo>/course_settings/canvas.toml is optional — a repo that only
    publishes need not have one. No API token and no base_url/course_id
    required (see config.load's require_course).
    """
    if config is None:
        config = repo / "course_settings" / "canvas.toml"
        if not config.exists():
            return None
    elif not config.exists():
        die(f"Config file not found: {config}")
    return load_config(config, require_token=False, require_course=False)


@main.command(name="publish")
@click.argument(
    "course_dir",
    required=False,
    default=None,
    type=click.Path(exists=True, file_okay=False, path_type=Path),
)
@click.option(
    "--output-dir",
    default="site",
    type=click.Path(path_type=Path),
    help="Where `mkdocs build` writes the static HTML (default: site/).",
)
@click.option(
    "--config",
    default=None,
    type=click.Path(path_type=Path),
    help=(
        "Path to canvas.toml, read only for its [course_flags] table "
        "(default: <repo>/course_settings/canvas.toml, if present)."
    ),
)
def publish(
    course_dir: Path | None, output_dir: Path, config: Path | None
) -> None:
    """Generate a public MkDocs static site from the course repo.

    COURSE_DIR is the course content repo. If omitted, the enclosing repo is
    found by walking up from the current directory. --config selects which
    section's course flags the site is built with; Canvas is never contacted.
    """
    course_dir = _resolve_repo(course_dir)
    cfg = _flags_config(course_dir, config)
    try:
        run_publish(course_dir, output_dir, cfg)
    except ValueError as e:
        die(str(e))
    except Exception as e:
        die(str(e))


@main.command(name="emit-workflow")
@click.argument(
    "course_dir",
    default=".",
    type=click.Path(exists=True, file_okay=False, path_type=Path),
)
def emit_workflow_cmd(course_dir: Path) -> None:
    """Write a GitHub Actions workflow for publishing to GitHub Pages.

    COURSE_DIR is the course content repo (defaults to the current directory).
    """
    from .publish import emit_workflow

    try:
        emit_workflow(Path(course_dir).resolve())
    except Exception as e:
        die(str(e))


@main.command(name="prune", no_args_is_help=True)
@click.argument(
    "repo",
    type=click.Path(exists=True, file_okay=False, path_type=Path),
)
@click.option(
    "--config",
    default=None,
    type=click.Path(path_type=Path),
    help="Path to canvas.toml (default: <repo>/course_settings/canvas.toml)",
)
@click.option(
    "--delete",
    "mode",
    flag_value="delete",
    help="Delete the orphaned items from Canvas.",
)
@click.option(
    "--unpublish",
    "mode",
    flag_value="unpublish",
    help="Unpublish (set published=False) the orphaned items on Canvas.",
)
@click.option(
    "--manifest-only",
    "mode",
    flag_value="manifest",
    help="Remove orphaned entries from the local manifest only; never touch Canvas.",
)
@click.option("--yes", "-y", "assume_yes", is_flag=True, default=False, help=_YES_HELP)
@_handle_cli_errors
def prune(repo: Path, config: Path | None, mode: str | None, assume_yes: bool) -> None:
    """Delete or unpublish Canvas items whose local source file no longer exists.

    REPO is the course content repo. An item is pruned when its manifest entry's
    local file is gone (deleted or renamed). Exactly one of --delete / --unpublish /
    --manifest-only is required. --manifest-only just drops the stale manifest
    entries without contacting Canvas; the others apply changes immediately.
    """
    if mode is None:
        die("Exactly one of --delete, --unpublish, or --manifest-only is required.")
    if config is None:
        config = repo / "course_settings" / "canvas.toml"
    cfg = load_config(config)

    click.echo(f"Repo:      {repo.resolve()}")
    click.echo(f"Course ID: {cfg.course_id}  ({cfg.base_url})")

    if mode != "manifest":
        course = get_course(cfg)
        click.echo(f"Course:    {course.name}")
        _guard_course(repo, cfg, course, assume_yes)

    had_errors = run_prune(cfg, repo, mode)

    if had_errors:
        click.secho(
            "Prune complete; please check warnings listed above.", fg="yellow"
        )
    else:
        click.secho("Prune successful", fg="green")


@main.command(name="find-canvas-orphans")
@click.argument(
    "repo",
    default=".",
    type=click.Path(exists=True, file_okay=False, path_type=Path),
)
@click.option(
    "--config",
    default=None,
    type=click.Path(path_type=Path),
    help="Path to canvas.toml (default: <repo>/course_settings/canvas.toml)",
)
@_handle_cli_errors
def find_canvas_orphans_cmd(repo: Path, config: Path | None) -> None:
    """Find Canvas resources not referenced by any other resource in the course.

    Queries the live Canvas course: scans all pages, assignments, discussions,
    and quizzes for internal links, checks module item membership, and
    identifies the front page. Resources with zero inbound references are
    reported. See find-local-orphans for the repo-side equivalent.

    REPO is the course content repo (defaults to the current directory).
    """
    if config is None:
        config = repo / "course_settings" / "canvas.toml"
    cfg = load_config(config)

    click.echo(f"Course ID: {cfg.course_id}  ({cfg.base_url})")

    course = get_course(cfg)
    click.echo(f"Course:    {course.name}")
    click.echo()

    orphans = find_orphans(course)
    print_report(orphans, cfg.base_url)


@main.command(name="find-local-orphans")
@click.argument(
    "repo",
    default=".",
    type=click.Path(exists=True, file_okay=False, path_type=Path),
)
@click.option(
    "-v",
    "--verbose",
    is_flag=True,
    help="Also list every referenced file and what refers to it, before the "
    "unreferenced ones.",
)
@_handle_cli_errors
def find_local_orphans_cmd(repo: Path, verbose: bool) -> None:
    """Find files in the course repo that nothing else in the repo references.

    Reads the repo on disk only — no Canvas call, no API token needed. Scans
    content files, modules, snippets, quizzes, question banks, the syllabus and
    course_settings.toml for local links, then reports the assets, content files
    and quizzes with zero inbound references.

    Deliberately conservative: snippets, modules, course settings and question
    banks are never reported, pinned resources count as referenced, and links
    inside inactive course-flag branches still count. See find-canvas-orphans
    for the live-course equivalent.

    With -v, the referenced files and their referrers are listed first, so the
    unreferenced ones end up at the bottom of the output.

    REPO is the course content repo (defaults to the current directory).
    """
    _ensure_pandoc()
    repo = repo.resolve()
    click.echo(f"Repo: {repo}")
    click.echo()

    print_local_orphan_report(find_local_orphans(repo), verbose=verbose)


@main.command(name="clean-manifest")
@click.argument(
    "repo",
    required=False,
    default=None,
    type=click.Path(exists=True, file_okay=False, path_type=Path),
)
@click.option(
    "--config",
    default=None,
    type=click.Path(path_type=Path),
    help="Path to canvas.toml (default: <repo>/course_settings/canvas.toml)",
)
@click.option(
    "--apply",
    is_flag=True,
    default=False,
    help="Make the changes. Without it, only report what would change.",
)
@click.option(
    "--no-canvas-check",
    "no_canvas_check",
    is_flag=True,
    default=False,
    help=(
        "Do not check Canvas; treat every entry as invalid. For a deliberate course "
        "switch, where no ID can match anyway."
    ),
)
@click.option(
    "--yes",
    "-y",
    "assume_yes",
    is_flag=True,
    default=False,
    help="With --apply, skip the confirmation when the manifest records a different course.",
)
@_handle_cli_errors
def clean_manifest_cmd(
    repo: Path | None,
    config: Path | None,
    apply: bool,
    no_canvas_check: bool,
    assume_yes: bool,
) -> None:
    """Remove manifest entries whose Canvas object is not in the configured course.

    Checks every manifest entry's Canvas ID against the live course (by type),
    and reports entries that point at something missing: deleted in Canvas,
    belonging to a different course (canvas.toml's course_id was changed), or
    recorded as the wrong type. Files that link to a removed entry are marked
    for re-sync so the next update re-renders their links. Canvas is only read,
    never changed.

    Without --apply this is a report. --apply edits the manifest and records the
    configured course as the manifest's course (see update's course check).

    --no-canvas-check skips the Canvas lookups and treats every entry as invalid,
    which is what a deliberate move to a different course means: Canvas object IDs
    are unique per object, so none of the recorded IDs can exist in the new course.

    REPO is the course content repo. If omitted, the enclosing repo is found by
    walking up from the current directory.
    """
    if not no_canvas_check:
        _ensure_pandoc()
    repo = _resolve_repo(repo).resolve()
    if config is None:
        config = repo / "course_settings" / "canvas.toml"
    cfg = load_config(config)

    click.echo(f"Repo:      {repo}")
    click.echo(f"Course ID: {cfg.course_id}  ({cfg.base_url})")
    course = get_course(cfg)
    click.echo(f"Course:    {course.name}")

    if no_canvas_check:
        manifest_path = manifest_lib.migrate_legacy_manifest(repo, cfg.config_path)
        manifest = manifest_lib.load(manifest_path)
        plan = plan_invalidate_all(manifest)
    else:
        try:
            manifest, manifest_path, plan = run_plan(cfg, repo, course)
        except requests.exceptions.ConnectionError:
            raise
        except Exception as e:
            die(f"could not list the course's contents on Canvas ({e}); nothing was changed.")
    stored = manifest_lib.get_course_identity(manifest)
    switching = stored is not None and not manifest_lib.same_course(
        stored, cfg.base_url, cfg.course_id
    )

    if not apply:
        print_plan(plan, applied=False)
        click.echo()
        if plan.has_changes or switching or stored is None:
            click.echo(f"Nothing changed. Re-run with --apply to update {manifest_path.name}.")
        return

    if switching and not assume_yes:
        if not sys.stdin.isatty():
            die(
                f"{manifest_path.name} records course {stored['course_id']} "
                f"('{stored.get('course_name', '')}'); re-run with --yes to switch it "
                f"to {cfg.course_id} ('{course.name}')."
            )
        print_plan(plan, applied=False)
        click.echo()
        if not click.confirm(
            f"Switch {manifest_path.name} from course {stored['course_id']} "
            f"('{stored.get('course_name', '')}') to {cfg.course_id} ('{course.name}')?",
            default=False,
        ):
            die("Stopped; nothing was changed.")

    apply_clean(manifest, manifest_path, plan, cfg, course.name)
    print_plan(plan, applied=True)
    click.echo()
    click.secho(
        f"{manifest_path.name} updated; it now records course {cfg.course_id} "
        f"('{course.name}'). Run update to upload what was removed.",
        fg="green",
    )


def _parse_canvas_url(url: str) -> tuple[str, int]:
    """Extract (base_url, course_id) from a Canvas course URL.

    Accepts URLs like ``https://school.instructure.com/courses/12345`` or
    ``https://school.instructure.com/courses/12345/rubrics``.
    """
    from urllib.parse import urlparse

    parsed = urlparse(url)
    if not parsed.scheme or not parsed.netloc:
        raise click.BadParameter(
            f"Not a valid Canvas URL: {url!r}\n"
            "Expected something like https://school.instructure.com/courses/12345"
        )
    parts = parsed.path.strip("/").split("/")
    try:
        idx = parts.index("courses")
        course_id = int(parts[idx + 1])
    except (ValueError, IndexError):
        raise click.BadParameter(
            f"Could not find /courses/<id> in URL: {url!r}\n"
            "Expected something like https://school.instructure.com/courses/12345"
        )
    base_url = f"{parsed.scheme}://{parsed.netloc}"
    return base_url, course_id


def _format_tab_configuration(tab_config: list[dict]) -> str:
    """Format tab_configuration as an inline TOML array of inline tables."""
    lines = ["tab_configuration = ["]
    for entry in tab_config:
        parts = []
        if "label" in entry:
            parts.append(f'label = "{entry["label"]}"')
        parts.append(f'id = "{entry["id"]}"')
        if entry.get("hidden"):
            parts.append("hidden = true")
        lines.append(f"    {{ {', '.join(parts)} }},")
    lines.append("]")
    return "\n".join(lines) + "\n"


@main.command(name="create-tool-aliases", no_args_is_help=True)
@click.argument("course_url")
@_handle_cli_errors
def create_tool_aliases(course_url: str) -> None:
    """Read navigation tabs from a Canvas course and print a tab_configuration block.

    COURSE_URL is any Canvas URL containing /courses/<id>, e.g.
    https://school.instructure.com/courses/12345 or
    https://school.instructure.com/courses/12345/rubrics.

    The API token is read from the CANVAS_API_TOKEN environment variable.

    The output is a TOML tab_configuration block with external-tool labels
    filled in, ready to paste into course_settings/course_settings.toml.
    """
    base_url, course_id = _parse_canvas_url(course_url)
    api_token = os.environ.get("CANVAS_API_TOKEN", "")
    if not api_token:
        die("CANVAS_API_TOKEN environment variable is not set.")

    cfg = Config(base_url=base_url, course_id=course_id, api_token=api_token)

    click.echo(f"Course ID: {cfg.course_id}  ({cfg.base_url})", err=True)

    course = get_course(cfg)
    click.echo(f"Course:    {course.name}", err=True)

    tab_config = read_tab_configuration(course)
    click.echo(_format_tab_configuration(tab_config))


@main.command(name="list-titles")
@click.argument(
    "repo",
    default=".",
    type=click.Path(exists=True, file_okay=False, path_type=Path),
)
@click.option(
    "--config",
    default=None,
    type=click.Path(path_type=Path),
    help=(
        "Path to canvas.toml, read only for its [course_flags] table "
        "(default: <repo>/course_settings/canvas.toml, if present)."
    ),
)
def list_titles(repo: Path, config: Path | None) -> None:
    """List all assignments, discussions, and quizzes with their due dates and file paths.

    REPO is the course content repo (defaults to the current directory).
    Items are sorted by due date (earliest first), then items without
    a due date are listed alphabetically by title. --config selects which
    section's course flags apply to due_dates `only_if` entries.
    """
    from .sync import (
        filter_due_dates_by_flags,
        find_due_date_override,
        iter_gradeable_content,
        load_course_flags,
        load_due_dates,
        parse_frontmatter,
    )

    repo = repo.resolve()
    cfg = _flags_config(repo, config)
    try:
        due_dates = filter_due_dates_by_flags(
            load_due_dates(repo), load_course_flags(repo, config=cfg)
        )
    except ValueError as e:
        die(str(e))

    items: list[tuple[str | None, str, str]] = []  # (due_at, title, path)

    # list-titles deliberately does not apply the ignore matcher (matcher=None).
    for local_key, md_path, ctype in iter_gradeable_content(repo, matcher=None):
        fm, _ = parse_frontmatter(md_path.read_text())
        title = fm.get("title", md_path.stem)
        override = find_due_date_override(due_dates, title, ctype)
        due_at = (override or {}).get("due_at") or fm.get("due_at") or None
        items.append((due_at if due_at else None, title, local_key))

    if not items:
        click.echo("No assignments, discussions, or quizzes found.")
        return

    # Sort: items with due dates first (by date), then items without (alphabetical by title)
    with_dates = [(d, t, p) for d, t, p in items if d]
    without_dates = [(d, t, p) for d, t, p in items if not d]
    with_dates.sort(key=lambda x: x[0])
    without_dates.sort(key=lambda x: x[1].lower())

    # Calculate column widths
    all_sorted = with_dates + without_dates
    max_title = max(len(t) for _, t, _ in all_sorted)
    max_date = 16  # "YYYY-MM-DD HH:MM"

    for due_at, title, path in all_sorted:
        if due_at:
            date_str = _format_concise_date(due_at)
        else:
            date_str = ""
        click.echo(f"{title:<{max_title}}  {date_str:<{max_date}}  {path}")


def _format_concise_date(iso_date: str) -> str:
    """Format an ISO 8601 date string as 'YYYY-MM-DD HH:MM'."""
    try:
        # Strip trailing timezone info for display
        clean = iso_date.replace("Z", "+00:00")
        dt = datetime.fromisoformat(clean)
        return dt.strftime("%Y-%m-%d %H:%M")
    except (ValueError, TypeError):
        return iso_date[:16] if len(iso_date) >= 16 else iso_date


@main.command()
@click.argument(
    "repo",
    required=False,
    default=None,
    type=click.Path(exists=True, file_okay=False, path_type=Path),
)
@click.option(
    "--config",
    default=None,
    type=click.Path(path_type=Path),
    help="Path to canvas.toml (default: <repo>/course_settings/canvas.toml)",
)
@click.option(
    "--force-uploads",
    is_flag=True,
    default=False,
    help="Re-upload all files even if unchanged since last sync.",
)
@click.option(
    "--force-overwrite",
    is_flag=True,
    default=False,
    help=(
        "Upload even if Canvas has a newer version. Skips the Canvas timestamp check entirely "
        "(faster; avoids extra API calls)."
    ),
)
@click.option(
    "--target-recursively",
    "-t",
    default=None,
    metavar="FILE[,FILE...]",
    help=(
        "Comma-separated files to sync. Each file and all resources it transitively "
        "references are synced (BFS). Skips the full course sync."
    ),
)
@click.option(
    "--single-target",
    "-s",
    default=None,
    metavar="FILE[,FILE...]",
    help=(
        "Comma-separated files to sync without traversing their references. "
        "Runs after --target-recursively; manifest timestamps updated by -t prevent "
        "redundant re-uploads. Skips the full course sync."
    ),
)
@click.option(
    "--verbose",
    "-v",
    is_flag=True,
    default=False,
    help="Print messages for items that are skipped (up-to-date or newer on Canvas).",
)
@click.option(
    "--check-all",
    "check_all",
    is_flag=True,
    default=False,
    help=(
        "Validate the whole repo as if uploading it for the first time to a "
        "brand-new empty Canvas course (broken links, missing rubrics, malformed "
        "frontmatter, ...). Contacts Canvas for nothing and writes nothing "
        "(no Canvas changes, no manifest changes); no API token "
        "needed. Exits nonzero if any problems are found."
    ),
)
@click.option("--yes", "-y", "assume_yes", is_flag=True, default=False, help=_YES_HELP)
@_handle_cli_errors
def update(
    repo: Path | None,
    config: Path | None,
    force_uploads: bool,
    force_overwrite: bool,
    target_recursively: str | None,
    single_target: str | None,
    verbose: bool,
    check_all: bool,
    assume_yes: bool,
) -> None:
    """Sync a Markdown course repo to Canvas LMS.

    REPO is the course content repo. If omitted, the enclosing repo is found by
    walking up from the current directory.
    """
    _ensure_pandoc()
    repo = _resolve_repo(repo)
    if check_all and (target_recursively or single_target):
        die("--check-all always checks the whole repo; it cannot be combined with -t/--target-recursively or -s/--single-target.")
    if check_all and (force_uploads or force_overwrite):
        die("--check-all already treats every file as new and never consults Canvas; drop --force-uploads/--force-overwrite.")
    if config is None:
        config = repo / "course_settings" / "canvas.toml"
    cfg = load_config(config, require_token=not check_all)

    click.echo(f"Repo:      {repo.resolve()}")
    click.echo(f"Course ID: {cfg.course_id}  ({cfg.base_url})")

    if check_all:
        had_errors = run_sync(cfg, repo, verbose=verbose, check_all=True)
        if had_errors:
            click.secho(
                "Check complete; please fix the problems listed above.", fg="yellow"
            )
            sys.exit(1)
        click.secho("Check successful — no problems found (nothing uploaded)", fg="green")
        return

    course = get_course(cfg)
    click.echo(f"Course:    {course.name}")
    _guard_course(repo, cfg, course, assume_yes)

    if target_recursively or single_target:
        recursive_list = (
            [p.strip() for p in target_recursively.split(",") if p.strip()]
            if target_recursively
            else []
        )
        single_list = (
            [p.strip() for p in single_target.split(",") if p.strip()]
            if single_target
            else []
        )
        had_errors = run_targeted_sync(
            cfg, repo, recursive_list, single_list, force_uploads, force_overwrite,
            verbose=verbose,
        )
    else:
        had_errors = run_sync(
            cfg, repo, force_uploads=force_uploads, force_overwrite=force_overwrite,
            verbose=verbose,
        )

    if had_errors:
        click.secho(
            "Update complete; please check errors listed above.", fg="yellow"
        )
    else:
        click.secho("Update successful", fg="green")
