"""Date placeholders: ``[TEXT]{.replace_date_with ...}`` spans in body text.

A placeholder is replaced, before Pandoc runs, with a date taken from the
centralized ``due_dates`` table of ``course_settings.toml``. ``TEXT`` is only a
fallback for editor previews and never reaches the output. Attributes:

- ``item``: the ``name`` of a ``due_dates`` entry; omitted means the entry of
  the file being converted (its own title and content type).
- ``type``: ``assignment``, ``discussion`` or ``quiz``; restricts the match.
- ``field``: ``due_at`` (default), ``unlock_at`` or ``lock_at``.
- ``format``: a strftime format; omitted means the course-wide default
  (``replace_date_with_format``).

Dates are formatted in the clock time and offset stored in ``due_dates``, with
no time-zone conversion. Every expansion returns records of what each
placeholder referred to and produced; ``update`` stores them in the manifest
(``dates_used``) and re-uploads a file when re-resolving them gives different
text (``stale_record``).
"""

from __future__ import annotations

import contextlib
import io
import re
from dataclasses import dataclass, replace
from datetime import date, datetime
from typing import Any

from .convert import split_fenced_segments, warn

#: The span class that marks a placeholder.
PLACEHOLDER_CLASS = "replace_date_with"

#: Top-level course_settings.toml key holding the default format.
FORMAT_KEY = "replace_date_with_format"

#: The format used when FORMAT_KEY is absent (and the value import writes).
DEFAULT_FORMAT = "%A, %B %-d by %-I:%M %p"

#: The comment written on the line directly above FORMAT_KEY.
FORMAT_COMMENT = (
    "# Date format (strftime) for [text]{.replace_date_with} placeholders "
    "that give no format="
)

_FIELDS = ("due_at", "unlock_at", "lock_at")
_TYPES = ("assignment", "discussion", "quiz")
_ATTRIBUTES = ("item", "type", "field", "format")
_SENTINELS = {"none", "keep", "create_none_then_keep"}

# [TEXT]{ATTRS}: TEXT has no brackets, ATTRS no braces or newline. Whether it is
# a placeholder is decided by the class in ATTRS (_is_placeholder_attrs).
_SPAN_RE = re.compile(r"\[([^\[\]]*)\]\{([^{}\n]*)\}")

# One Pandoc attribute: .class, #id, or key=value (value bare, "double" or
# 'single' quoted; \" escapes a quote inside double quotes).
_ATTR_TOKEN_RE = re.compile(
    r"""\s*(?:\.(?P<cls>[^\s{}"'=]+)"""
    r"""|\#(?P<id>[^\s{}"'=]+)"""
    r"""|(?P<key>[\w-]+)=(?:"(?P<dq>(?:[^"\\]|\\.)*)"|'(?P<sq>[^']*)'|(?P<bare>[^\s"']+)))"""
)

_CLASS_TOKEN_RE = re.compile(rf"(?:^|\s)\.{PLACEHOLDER_CLASS}(?=\s|$)")

# A span left behind (one _SPAN_RE could not match, e.g. brackets in its text).
_LEFTOVER_MD_RE = re.compile(rf"\{{[^{{}}]*\.{PLACEHOLDER_CLASS}\b")
_LEFTOVER_HTML_RE = re.compile(rf"""class=["'][^"']*\b{PLACEHOLDER_CLASS}\b""")

# Runs of backticks open and close an inline code span of the same length.
_INLINE_CODE_RE = re.compile(r"(`+)(?:.|\n)*?(?<!`)\1(?!`)")

_NO_PAD_RE = re.compile(r"%(-?)(.)", re.DOTALL)

_MD_ESCAPE_RE = re.compile(r"([\\`*_\[\]])")


class PlaceholderError(Exception):
    """A placeholder that cannot be resolved; the message says why."""


@dataclass(frozen=True)
class DatePlaceholderContext:
    """What a placeholder resolves against.

    ``due_dates`` is the flag-filtered list for ``update`` and ``publish``;
    ``own_title``/``own_type`` identify the converted file's own entry, or are
    None for files that have no due date (pages, the syllabus, ...).
    """

    due_dates: tuple[dict[str, Any], ...]
    default_format: str = DEFAULT_FORMAT
    own_title: str | None = None
    own_type: str | None = None

    def for_file(self, own_title: str | None, own_type: str | None) -> DatePlaceholderContext:
        return replace(self, own_title=own_title, own_type=own_type)


def own_entry(canvas_type: str | None, title: str) -> tuple[str | None, str | None]:
    """(own title, own type) for placeholders without item=: only assignments,
    discussions and quizzes have a due_dates entry of their own."""
    if canvas_type in _TYPES:
        return title, canvas_type
    return None, None


def make_context(
    due_dates: list[dict[str, Any]], settings: dict[str, Any] | None
) -> DatePlaceholderContext:
    """Run-level context: the due_dates list and the default format."""
    return DatePlaceholderContext(
        due_dates=tuple(e for e in due_dates if isinstance(e, dict)),
        default_format=load_default_format(settings or {}),
    )


def load_default_format(settings: dict[str, Any]) -> str:
    """The ``replace_date_with_format`` value, or DEFAULT_FORMAT when absent.

    A non-string value raises ValueError (a whole-run configuration error).
    """
    value = settings.get(FORMAT_KEY, DEFAULT_FORMAT)
    if not isinstance(value, str):
        raise ValueError(
            f"course_settings.toml: {FORMAT_KEY} must be a string (a strftime "
            f"format), got {value!r}"
        )
    return value


# ---------------------------------------------------------------------------
# Parsing
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class Placeholder:
    item: str | None
    type: str | None
    field: str
    format: str | None
    source: str  # the span as written, for messages

    def describe(self) -> str:
        return self.source


def _is_placeholder_attrs(attrs: str) -> bool:
    return bool(_CLASS_TOKEN_RE.search(attrs.strip()))


def parse_attributes(attrs: str, source: str) -> Placeholder:
    """Parse a placeholder's attribute text (between the braces)."""
    values: dict[str, str] = {}
    pos = 0
    text = attrs.strip()
    while pos < len(text):
        m = _ATTR_TOKEN_RE.match(text, pos)
        if m is None or m.end() == pos:
            raise PlaceholderError(f"cannot read the attributes {{{attrs}}}")
        pos = m.end()
        if m.group("cls") is not None:
            if m.group("cls") != PLACEHOLDER_CLASS:
                raise PlaceholderError(
                    f"unexpected class .{m.group('cls')} (a placeholder has only "
                    f".{PLACEHOLDER_CLASS})"
                )
            continue
        if m.group("id") is not None:
            raise PlaceholderError(f"unexpected id #{m.group('id')}")
        key = m.group("key")
        if key not in _ATTRIBUTES:
            raise PlaceholderError(
                f"unknown attribute {key!r} (expected {', '.join(_ATTRIBUTES)})"
            )
        if key in values:
            raise PlaceholderError(f"attribute {key!r} given twice")
        if m.group("dq") is not None:
            value = re.sub(r"\\(.)", r"\1", m.group("dq"))
        elif m.group("sq") is not None:
            value = m.group("sq")
        else:
            value = m.group("bare")
        values[key] = value
    field = values.get("field", "due_at")
    if field not in _FIELDS:
        raise PlaceholderError(f"field={field!r} is not one of {', '.join(_FIELDS)}")
    ptype = values.get("type")
    if ptype is not None and ptype not in _TYPES:
        raise PlaceholderError(f"type={ptype!r} is not one of {', '.join(_TYPES)}")
    item = values.get("item")
    if item is not None and not item.strip():
        raise PlaceholderError("item is empty")
    fmt = values.get("format")
    if fmt is not None and not fmt:
        raise PlaceholderError("format is empty")
    return Placeholder(item=item, type=ptype, field=field, format=fmt, source=source)


def _outside_code(text: str, transform) -> str:
    """Apply ``transform`` to the parts of ``text`` outside fenced code blocks
    and inline code spans."""

    def _plain(segment: str) -> str:
        out: list[str] = []
        pos = 0
        for m in _INLINE_CODE_RE.finditer(segment):
            out.append(transform(segment[pos : m.start()]))
            out.append(m.group(0))
            pos = m.end()
        out.append(transform(segment[pos:]))
        return "".join(out)

    return "".join(
        seg if fenced else _plain(seg) for fenced, seg in split_fenced_segments(text)
    )


def find_placeholders(text: str) -> list[Placeholder | PlaceholderError]:
    """Every placeholder outside code, parsed; a span that does not parse is
    returned as its PlaceholderError."""
    found: list[Placeholder | PlaceholderError] = []

    def _scan(segment: str) -> str:
        for m in _SPAN_RE.finditer(segment):
            if not _is_placeholder_attrs(m.group(2)):
                continue
            try:
                found.append(parse_attributes(m.group(2), m.group(0)))
            except PlaceholderError as exc:
                found.append(PlaceholderError(f"{m.group(0)}: {exc}"))
        return segment

    _outside_code(text, _scan)
    return found


# ---------------------------------------------------------------------------
# Resolution and formatting
# ---------------------------------------------------------------------------


def _target(ph: Placeholder, ctx: DatePlaceholderContext) -> tuple[str, str | None]:
    """The (entry name, type filter) a placeholder refers to."""
    if ph.item is not None:
        return ph.item, ph.type
    if ctx.own_title is None:
        raise PlaceholderError(
            "needs item= because this file has no due_dates entry of its own "
            "(only assignments, discussions and quizzes do)"
        )
    return ctx.own_title, ph.type or ctx.own_type


def find_entry(
    due_dates: tuple[dict[str, Any], ...] | list[dict[str, Any]],
    name: str,
    entry_type: str | None,
) -> dict[str, Any]:
    """The single due_dates entry named ``name`` (and matching ``entry_type``
    when given: an entry with that type or with none)."""
    matches = [
        e
        for e in due_dates
        if e.get("name") == name
        and (entry_type is None or not e.get("type") or e.get("type") == entry_type)
    ]
    if not matches:
        where = f" with type {entry_type}" if entry_type else ""
        raise PlaceholderError(f"no due_dates entry named {name!r}{where}")
    if len(matches) > 1:
        if entry_type is None:
            raise PlaceholderError(
                f"{len(matches)} due_dates entries are named {name!r}; add type= "
                f"to choose one"
            )
        raise PlaceholderError(
            f"{len(matches)} due_dates entries named {name!r} match type {entry_type}"
        )
    return matches[0]


def _as_datetime(value: Any, name: str, field: str) -> datetime:
    if isinstance(value, datetime):
        return value
    if isinstance(value, date):
        return datetime(value.year, value.month, value.day)
    if not isinstance(value, str) or not value.strip():
        raise PlaceholderError(f"due_dates entry {name!r} has no {field}")
    if value.strip().lower() in _SENTINELS:
        raise PlaceholderError(
            f"due_dates entry {name!r} has no date for {field} ({value})"
        )
    try:
        return datetime.fromisoformat(value.strip())
    except ValueError:
        raise PlaceholderError(
            f"due_dates entry {name!r}: {field} {value!r} is not a date-time"
        ) from None


def format_date(when: datetime, fmt: str) -> str:
    """strftime, with %-d, %-m, %-H, %-I, %-M and %-j handled here so the
    no-padding forms work on every platform."""
    no_pad = {
        "d": when.day,
        "m": when.month,
        "H": when.hour,
        "I": when.hour % 12 or 12,
        "M": when.minute,
        "j": when.timetuple().tm_yday,
    }

    def _sub(m: re.Match) -> str:
        if m.group(1) == "-" and m.group(2) in no_pad:
            return str(no_pad[m.group(2)])
        return m.group(0)

    return when.strftime(_NO_PAD_RE.sub(_sub, fmt))


def _render(
    ctx: DatePlaceholderContext, name: str, entry_type: str | None, field: str, fmt: str | None
) -> str:
    entry = find_entry(ctx.due_dates, name, entry_type)
    when = _as_datetime(entry.get(field), name, field)
    return format_date(when, fmt or ctx.default_format)


def resolve(ph: Placeholder, ctx: DatePlaceholderContext) -> tuple[str, dict[str, str]]:
    """The text a placeholder produces and the record describing it."""
    name, entry_type = _target(ph, ctx)
    text = _render(ctx, name, entry_type, ph.field, ph.format)
    record = {
        "item": name,
        "type": entry_type or "",
        "field": ph.field,
        "format": ph.format or "",  # "" = the course default, re-read each run
        "text": text,
    }
    return text, record


def stale_record(record: dict[str, Any], ctx: DatePlaceholderContext) -> str | None:
    """Why a recorded placeholder is out of date (None when it is not)."""
    try:
        text = _render(
            ctx,
            str(record.get("item", "")),
            record.get("type") or None,
            str(record.get("field", "due_at")),
            record.get("format") or None,
        )
    except PlaceholderError as exc:
        return f"date placeholder no longer resolves ({exc})"
    if text != record.get("text"):
        return (
            f"date for {record.get('item')!r} ({record.get('field')}) changed "
            f"{record.get('text')!r} → {text!r}"
        )
    return None


def first_stale_reason(
    records: list[dict[str, Any]] | None, ctx: DatePlaceholderContext
) -> str | None:
    for record in records or []:
        reason = stale_record(record, ctx)
        if reason is not None:
            return reason
    return None


# ---------------------------------------------------------------------------
# Expansion
# ---------------------------------------------------------------------------


def _escape(text: str) -> str:
    return _MD_ESCAPE_RE.sub(r"\\\1", text)


def expand(
    text: str,
    ctx: DatePlaceholderContext,
    source_desc: str,
    errors: list[str] | None,
) -> tuple[str, list[dict[str, str]]]:
    """Replace every placeholder outside code with its date.

    Returns the new text and one record per resolved placeholder (duplicates
    removed). Each failure is reported via ``warn`` as an ``ERROR:`` naming
    ``source_desc`` and the span, and the span is left in place. A span that
    could not be matched at all (brackets in its text) is reported too.
    """
    records: list[dict[str, str]] = []

    def _report(msg: str) -> None:
        warn(f"ERROR: {source_desc}: date placeholder {msg}", errors)

    def _replace(m: re.Match) -> str:
        if not _is_placeholder_attrs(m.group(2)):
            return m.group(0)
        try:
            ph = parse_attributes(m.group(2), m.group(0))
            value, record = resolve(ph, ctx)
        except PlaceholderError as exc:
            _report(f"{m.group(0)}: {exc}")
            return m.group(0)
        if record not in records:
            records.append(record)
        return _escape(value)

    def _segment(segment: str) -> str:
        segment = _SPAN_RE.sub(_replace, segment)
        for left in _LEFTOVER_MD_RE.finditer(_SPAN_RE.sub("", segment)):
            _report(
                f"near {left.group(0)!r} could not be read (its text must not "
                f"contain [ or ])"
            )
        return segment

    return _outside_code(text, _segment), records


def check_leftovers_html(html: str, source_desc: str, errors: list[str] | None) -> bool:
    """Report a placeholder span that survived into the HTML; True if found."""
    if _LEFTOVER_HTML_RE.search(html):
        warn(
            f"ERROR: {source_desc}: a {PLACEHOLDER_CLASS} span was not replaced "
            f"(check that its text has no [ or ] and its attributes are on one line)",
            errors,
        )
        return True
    return False


# ---------------------------------------------------------------------------
# Checking without expanding (generate-due-dates, cp)
# ---------------------------------------------------------------------------


def problems(text: str, ctx: DatePlaceholderContext, source_desc: str) -> list[str]:
    """``ERROR:`` messages for every placeholder in ``text`` that does not
    resolve against ``ctx`` (nothing is printed or replaced)."""
    messages: list[str] = []
    for found in find_placeholders(text):
        if isinstance(found, PlaceholderError):
            messages.append(f"ERROR: {source_desc}: date placeholder {found}")
            continue
        try:
            resolve(found, ctx)
        except PlaceholderError as exc:
            messages.append(f"ERROR: {source_desc}: date placeholder {found.source}: {exc}")

    def _leftovers(segment: str) -> str:
        for left in _LEFTOVER_MD_RE.finditer(_SPAN_RE.sub("", segment)):
            messages.append(
                f"ERROR: {source_desc}: date placeholder near {left.group(0)!r} could "
                f"not be read (its text must not contain [ or ])"
            )
        return segment

    _outside_code(text, _leftovers)
    return messages


_CONTENT_FOLDERS = ("pages", "assignments", "discussions", "announcements")


def iter_sources(repo, matcher=None):
    """``(path, own_title, own_type)`` for every file whose body placeholders
    are expanded: content files, the syllabus, quiz files and question files
    (a quiz question's own entry is its quiz's), and question-bank question
    files. Files and folders matched by ``matcher`` are skipped."""
    from pathlib import Path

    from .convert import parse_frontmatter

    repo = Path(repo)

    def _ignored(path) -> bool:
        return matcher is not None and matcher.is_excluded(path, repo)

    def _title(path, default: str) -> str:
        try:
            frontmatter, _ = parse_frontmatter(path.read_text(encoding="utf-8"))
        except Exception:
            frontmatter = {}
        return str(frontmatter.get("title", default))

    for folder in _CONTENT_FOLDERS:
        for path in sorted((repo / folder).rglob("*.md")):
            if _ignored(path):
                continue
            ctype = folder[:-1]  # pages -> page, ...
            yield (path, *own_entry(ctype, _title(path, path.stem)))
    syllabus = repo / "course_settings" / "syllabus.md"
    if syllabus.exists():
        yield syllabus, None, None
    quizzes = repo / "quizzes"
    for folder in sorted(d for d in quizzes.iterdir() if d.is_dir()) if quizzes.exists() else []:
        quiz_md = folder / f"{folder.name}.md"
        if _ignored(folder) or not quiz_md.exists():
            continue
        title = _title(quiz_md, folder.name)
        yield quiz_md, title, "quiz"
        for q in sorted((folder / "questions").glob("*.md")):
            if not _ignored(q):
                yield q, title, "quiz"
    banks = repo / "question_banks"
    for folder in sorted(d for d in banks.iterdir() if d.is_dir()) if banks.exists() else []:
        if _ignored(folder):
            continue
        for q in sorted((folder / "questions").glob("*.md")):
            if not _ignored(q):
                yield q, None, None


def check_repo(repo, ctx: DatePlaceholderContext, matcher=None) -> list[str]:
    """Problems with every placeholder in the repo, snippets expanded and
    course-flag conditionals not applied (so every branch is checked)."""
    from pathlib import Path

    from .convert import parse_frontmatter, preprocess_snippets

    repo = Path(repo)
    messages: list[str] = []
    for path, own_title, own_type in iter_sources(repo, matcher):
        try:
            _, body = parse_frontmatter(path.read_text(encoding="utf-8"))
        except Exception:
            continue
        # Snippet problems are update's to report; keep this check quiet.
        with contextlib.redirect_stdout(io.StringIO()):
            body = preprocess_snippets(body, path, repo / "snippets")
        rel = path.relative_to(repo).as_posix()
        messages.extend(problems(body, ctx.for_file(own_title, own_type), rel))
    return messages
