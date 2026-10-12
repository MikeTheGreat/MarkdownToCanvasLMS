"""Remove span and bracket debris from pandoc-flavoured Markdown.

Two callers share this code:

- import (`imscc_import._html_to_markdown`) runs `filter_pandoc_attrs()` with
  a policy that keeps only `id` and `style`, on freshly converted HTML.
- `fix-markdown` (`fix_markdown_repo()`) runs it on files already in a course
  repo, with a policy that only touches attribute blocks Word Online wrote,
  then repairs the stray brackets such blocks left behind in earlier imports.

The debris comes from how pandoc writes an HTML `<span>`: as
``[text]{.class key="val"}``. Word Online splits every paragraph into many
classed spans, so a sentence becomes::

    C[heck out our ]{.NormalTextRun .SCXW1}[Finding Data](https://a)[ and ]{.TextRun}

Dropping the ``{...}`` blocks and keeping the brackets (what import did before
it unwrapped emptied spans) leaves ``C[heck out our ][Finding Data](https://a)[ and ]``,
which pandoc renders with the brackets as visible text. Worse, ``[x][y](z)``
chains can parse as links with nonsense destinations.
"""

from __future__ import annotations

import difflib
import re
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path

import yaml

from .convert import apply_outside_fences, split_fenced_segments

# One attribute: #id, .class, or key=value. Pandoc writes double-quoted values
# with backslash escapes, and Word's values (ccp-props="{\"134233117\":false}")
# contain braces, so the quoted forms must be matched as a unit.
ATTR_TOKEN_RE = re.compile(
    r'''\#[^\s"'{}]+
      | \.[^\s"'{}]+
      | [A-Za-z_:][\w:.-]*=(?:"(?:[^"\\\n]|\\.)*"|'[^'\n]*'|[^\s{}"']+)
    ''',
    re.VERBOSE,
)
ATTR_BLOCK_RE = re.compile(
    r'''([ \t]*)\{((?:[^{}"'\n]|"(?:[^"\\\n]|\\.)*"|'[^'\n]*')*)\}'''
)
_FENCE_LINE_RE = re.compile(r"^([ \t]*)(:{3,})[ \t]*(.*?)[ \t]*$")
_FENCE_BARE_CLASS_RE = re.compile(
    r"^(?P<indent>[ \t]*)(?P<fence>:{3,})[ \t]+(?P<cls>[A-Za-z_][\w-]*)[ \t]*$"
)
_INLINE_CODE_RE = re.compile(r"(`+)(?:.|\n)+?\1")

TokenPolicy = Callable[[list[str]], list[str]]


def attr_tokens(content: str) -> list[str] | None:
    """Split an attribute block's contents into tokens.

    Returns None when the contents are not purely attributes (prose that
    happens to sit in braces), so the caller leaves the block alone.
    """
    tokens = ATTR_TOKEN_RE.findall(content)
    if ATTR_TOKEN_RE.sub("", content).strip():
        return None
    return tokens


# Style declarations that only restate what Canvas's stylesheet already does.
# Canvas's editor and Word wrap text in spans carrying them
# (``[[text]{style="font-size: 12pt;"}]{style="font-size: 12pt;"}``), and put
# them on headings, where a fixed font-size shrinks the heading. Declarations
# that change how the page looks (centering, background colours, banner
# colours, padding) are kept.
_NOISE_STYLE_PROPS = {"font-size", "font-family", "margin-bottom"}
# color: black inside a styled heading banner overrides the banner's white
# text; elsewhere it restates the default.
_BLACK_RE = re.compile(
    r"^(?:#000(?:000)?|black|rgb\(\s*0\s*,\s*0\s*,\s*0\s*\))$", re.IGNORECASE
)


def _is_noise_declaration(decl: str) -> bool:
    prop, _, value = decl.partition(":")
    prop = prop.strip().lower()
    value = value.strip()
    if prop in _NOISE_STYLE_PROPS:
        return True
    return prop == "color" and bool(_BLACK_RE.match(value))


def _clean_style_token(
    token: str, is_removed: Callable[[str], bool] = _is_noise_declaration
) -> str | None:
    """Remove the declarations is_removed picks (by default the noise ones)
    from a ``style=`` token; None if none are left. Other tokens are returned
    unchanged."""
    key, _, value = token.partition("=")
    if key.lower() != "style":
        return token
    quote = ""
    if len(value) >= 2 and value[0] == value[-1] and value[0] in "\"'":
        quote, value = value[0], value[1:-1]
    decls = [d.strip() for d in value.split(";") if d.strip()]
    kept = [d for d in decls if not is_removed(d)]
    if len(kept) == len(decls):
        return token
    if not kept:
        return None
    body = "; ".join(kept) + (";" if value.rstrip().endswith(";") else "")
    quote = quote or '"'
    return f"{key}={quote}{body}{quote}"


def drop_noise_styles(tokens: list[str]) -> list[str]:
    """Strip font-size, font-family, margin-bottom and black text colour
    from any style; a style left empty is dropped."""
    out = []
    for t in tokens:
        cleaned = _clean_style_token(t)
        if cleaned is not None:
            out.append(cleaned)
    return out


# ---------------------------------------------------------------------------
# Text colour: white text without a background, and contrast
# ---------------------------------------------------------------------------

# Canvas's body text colour, assumed where nothing sets one;
# var(--ic-brand-font-color-dark) is the theme variable that holds it.
CANVAS_TEXT_RGB = (0x2D, 0x3B, 0x45)
PAGE_BACKGROUND_RGB = (0xFF, 0xFF, 0xFF)
_WHITE_RGB = (0xFF, 0xFF, 0xFF)

_NAMED_COLORS = {
    "black": (0, 0, 0),
    "white": (255, 255, 255),
    "red": (255, 0, 0),
    "green": (0, 128, 0),
    "blue": (0, 0, 255),
    "yellow": (255, 255, 0),
    "orange": (255, 165, 0),
    "purple": (128, 0, 128),
    "gray": (128, 128, 128),
    "grey": (128, 128, 128),
    "silver": (192, 192, 192),
    "navy": (0, 0, 128),
    "maroon": (128, 0, 0),
    "teal": (0, 128, 128),
    "olive": (128, 128, 0),
    "lime": (0, 255, 0),
    "aqua": (0, 255, 255),
    "cyan": (0, 255, 255),
    "fuchsia": (255, 0, 255),
    "magenta": (255, 0, 255),
}
_HEX_COLOR_RE = re.compile(r"^#([0-9a-f]{3}|[0-9a-f]{6})$")
_RGB_COLOR_RE = re.compile(
    r"^rgba?\(\s*(\d{1,3})\s*,\s*(\d{1,3})\s*,\s*(\d{1,3})\s*(?:,\s*([\d.]+%?)\s*)?\)$"
)
# Background values that paint nothing.
_NO_BACKGROUND = {"", "transparent", "none", "inherit", "initial", "unset"}


def parse_css_color(value: str) -> tuple[int, int, int] | None:
    """(r, g, b) for a hex, rgb()/rgba() (opaque only), basic named colour or
    Canvas's text-colour variable; None for anything else."""
    v = value.strip().lower()
    v = re.sub(r"\s*!important$", "", v)
    if v.startswith("var(--ic-brand-font-color-dark"):
        return CANVAS_TEXT_RGB
    if v in _NAMED_COLORS:
        return _NAMED_COLORS[v]
    m = _HEX_COLOR_RE.match(v)
    if m:
        h = m.group(1)
        if len(h) == 3:
            h = "".join(c * 2 for c in h)
        return (int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16))
    m = _RGB_COLOR_RE.match(v)
    if m:
        alpha = m.group(4)
        if alpha is not None and alpha not in ("1", "1.0", "100%"):
            return None
        rgb = tuple(int(m.group(i)) for i in (1, 2, 3))
        return rgb if all(c <= 255 for c in rgb) else None  # type: ignore[return-value]
    return None


def style_declarations(tokens: list[str]) -> dict[str, str]:
    """Property → value for the ``style=`` tokens among tokens (later wins)."""
    decls: dict[str, str] = {}
    for token in tokens:
        key, _, value = token.partition("=")
        if key.lower() != "style":
            continue
        if len(value) >= 2 and value[0] == value[-1] and value[0] in "\"'":
            value = value[1:-1]
        for decl in value.split(";"):
            prop, sep, val = decl.partition(":")
            if sep:
                decls[prop.strip().lower()] = val.strip()
    return decls


def _background_value(decls: dict[str, str]) -> str | None:
    for prop in ("background-color", "background"):
        value = decls.get(prop)
        if value is not None and value.strip().lower() not in _NO_BACKGROUND:
            return value
    return None


def _parse_background(value: str) -> tuple[int, int, int] | None:
    """The colour in a background value; the ``background`` shorthand may hold
    other words (an image, a position), so each word is tried."""
    rgb = parse_css_color(value)
    if rgb is not None:
        return rgb
    for word in re.findall(r"rgba?\([^)]*\)|\S+", value):
        rgb = parse_css_color(word)
        if rgb is not None:
            return rgb
    return None


def _is_white_declaration(decl: str) -> bool:
    prop, _, value = decl.partition(":")
    return prop.strip().lower() == "color" and parse_css_color(value) == _WHITE_RGB


def drop_unbacked_white(tokens: list[str]) -> list[str]:
    """Remove a white text colour from a style that sets no background.

    White text on Canvas's white page is invisible. Callers apply this only to
    blocks that do not sit inside a span, heading or fenced div with a
    background (see `filter_pandoc_attrs`), where white is the banner text.
    """
    out = []
    for t in tokens:
        if _background_value(style_declarations([t])) is None:
            cleaned = _clean_style_token(t, _is_white_declaration)
            if cleaned is None:
                continue
            t = cleaned
        out.append(t)
    return out


def keep_id_and_style(tokens: list[str]) -> list[str]:
    """Import's policy: keep `id` (anchors may target it) and `style`
    (user-authored formatting); drop classes and other key=value cruft, and
    the style declarations that are only noise (drop_noise_styles)."""
    return drop_noise_styles(
        [t for t in tokens if t.startswith("#") or t.lower().startswith("style=")]
    )


# Markers that only Word / Word Online writes. A block carrying one of them was
# generated by Word, so everything in it except id and style is Word's too
# (.Selected, .Paragraph, lang, contrast, ...). Blocks without a marker are
# left exactly as they are.
_WORD_CLASS_RE = re.compile(
    r"^\.(?:SCXW\d+|BCX\d+|EOP|NormalTextRun|TextRun|EmptyTextRun|OutlineElement"
    r"|LineBreakBlob|BreakObjectBlob|ListContainerWrapper|WACImageContainer"
    r"|(?:Spelling|ContextualSpelling|Grammar|CommentHighlight|TrackChange)\w*)$"
)
_WORD_KEY_RE = re.compile(r"^(?:data-)?(?:ccp-[\w-]+|paraid|paraeid)=", re.IGNORECASE)


def is_word_marker(token: str) -> bool:
    return bool(_WORD_CLASS_RE.match(token) or _WORD_KEY_RE.match(token))


def strip_word_attrs(tokens: list[str]) -> list[str]:
    """fix-markdown's policy: only blocks Word wrote are reduced to id + style.
    Noise style declarations are removed from any block (drop_noise_styles)."""
    if not any(is_word_marker(t) for t in tokens):
        return drop_noise_styles(tokens)
    return keep_id_and_style(tokens)


# ---------------------------------------------------------------------------
# Scanning helpers
# ---------------------------------------------------------------------------


def _code_mask(text: str) -> list[bool]:
    """True at every index inside an inline code span."""
    mask = [False] * len(text)
    for m in _INLINE_CODE_RE.finditer(text):
        for i in range(m.start(), m.end()):
            mask[i] = True
    return mask


def _escaped(text: str, idx: int) -> bool:
    n = 0
    i = idx - 1
    while i >= 0 and text[i] == "\\":
        n += 1
        i -= 1
    return n % 2 == 1


def _is_bracket(text: str, idx: int, mask: list[bool]) -> bool:
    return text[idx] in "[]" and not mask[idx] and not _escaped(text, idx)


def _find_opener(text: str, close_idx: int, mask: list[bool]) -> int | None:
    """Index of the `[` matching the `]` at close_idx, within its paragraph."""
    depth = 0
    i = close_idx - 1
    while i >= 0:
        if text[i] == "\n" and i > 0 and text[i - 1] == "\n":
            return None
        if _is_bracket(text, i, mask):
            if text[i] == "]":
                depth += 1
            elif depth == 0:
                return i
            else:
                depth -= 1
        i -= 1
    return None


def _find_closer(text: str, open_idx: int, mask: list[bool]) -> int | None:
    depth = 0
    i = open_idx + 1
    while i < len(text):
        if text[i] == "\n" and i + 1 < len(text) and text[i + 1] == "\n":
            return None
        if _is_bracket(text, i, mask):
            if text[i] == "[":
                depth += 1
            elif depth == 0:
                return i
            else:
                depth -= 1
        i += 1
    return None


def _apply_edits(text: str, edits: list[tuple[int, int, str]]) -> str:
    """Apply non-overlapping (start, end, replacement) edits."""
    out: list[str] = []
    pos = 0
    for start, end, repl in sorted(edits):
        if start < pos:
            continue
        out.append(text[pos:start])
        out.append(repl)
        pos = end
    out.append(text[pos:])
    return "".join(out)


# ---------------------------------------------------------------------------
# Attribute blocks
# ---------------------------------------------------------------------------


def _is_attr_context(text: str, brace_pos: int) -> bool:
    line_start = text.rfind("\n", 0, brace_pos) + 1
    line_prefix = text[line_start:brace_pos]
    if re.match(r"^\s*(#{1,6}\s|:{3,}\s*$)", line_prefix):
        return True
    prev = line_prefix.rstrip()
    return bool(prev) and prev[-1] in ")]`"


def _filter_blocks(
    text: str,
    policy: TokenPolicy,
    bg_ranges: list[tuple[int, int]] | None = None,
) -> str:
    """Rewrite every attribute block in text by policy.

    With bg_ranges (the spans of text that sit on a background), a block
    outside all of them first loses any white text colour (drop_unbacked_white).

    A span (``[text]{...}``) whose block is emptied is unwrapped to ``text``;
    leaving ``[text]`` behind would render the brackets.
    """
    mask = _code_mask(text)
    edits: list[tuple[int, int, str]] = []
    for m in ATTR_BLOCK_RE.finditer(text):
        ws, content = m.group(1), m.group(2)
        brace_pos = m.start() + len(ws)
        if mask[brace_pos] or not _is_attr_context(text, brace_pos):
            continue
        tokens = attr_tokens(content)
        if tokens is None:
            continue
        if bg_ranges is not None and not any(s <= brace_pos < e for s, e in bg_ranges):
            kept = policy(drop_unbacked_white(tokens))
        else:
            kept = policy(tokens)
        if kept == tokens:
            continue
        if kept:
            edits.append((m.start(), m.end(), ws + "{" + " ".join(kept) + "}"))
            continue
        edits.append((m.start(), m.end(), ""))
        close = m.start() - 1
        if (
            not ws
            and close >= 0
            and text[close] == "]"
            and _is_bracket(text, close, mask)
        ):
            opener = _find_opener(text, close, mask)
            if opener is not None and not (opener > 0 and text[opener - 1] == "!"):
                edits.append((opener, opener + 1, ""))
                edits.append((close, close + 1, ""))
    return _apply_edits(text, edits)


def _fenced_code_lines(markdown: str) -> set[int]:
    """Indices of the lines that belong to fenced code blocks."""
    fenced_lines: set[int] = set()
    idx = 0
    for is_fenced, seg in split_fenced_segments(markdown):
        n = seg.count("\n")
        if is_fenced:
            fenced_lines.update(range(idx, idx + n + (0 if seg.endswith("\n") else 1)))
        idx += n
    return fenced_lines


def _fenced_div_pairs(lines: list[str], fenced_lines: set[int]) -> dict[int, int]:
    """Open line → close line of every fenced div (``:::``).

    Only fenced-div opens carry attributes (pandoc writes an attribute-less
    div as raw HTML), so pairing opens (trailing content) with closes (none)
    is unambiguous.
    """
    stack: list[int] = []
    pairs: dict[int, int] = {}
    for i, line in enumerate(lines):
        if i in fenced_lines:
            continue
        m = _FENCE_LINE_RE.match(line)
        if not m:
            continue
        if m.group(3):
            stack.append(i)
        elif stack:
            pairs[stack.pop()] = i
    return pairs


def _plain_segments(markdown: str, skip_code_blocks: bool) -> list[tuple[int, bool, str]]:
    """(offset, is_fenced, segment) for the whole text, or for each stretch
    between fenced code blocks and each code block."""
    if not skip_code_blocks:
        return [(0, False, markdown)]
    out = []
    offset = 0
    for is_fenced, seg in split_fenced_segments(markdown):
        out.append((offset, is_fenced, seg))
        offset += len(seg)
    return out


def filter_pandoc_attrs(
    markdown: str,
    policy: TokenPolicy,
    skip_code_blocks: bool = True,
    drop_white_text: bool = False,
) -> str:
    """Rewrite pandoc's curly-brace attribute blocks according to policy.

    Pandoc attaches ``{#id .class key="val"}`` blocks to headings, links,
    images, spans, code and fenced divs (``:::``). policy maps a block's tokens
    to the ones to keep. A span or fenced div left with no attributes is
    unwrapped (a bare ``[text]`` renders its brackets; a bare div is a
    meaningless container). With skip_code_blocks, fenced code blocks are left
    untouched.

    With drop_white_text, a white text colour is removed from every block that
    has no background of its own and is not inside a span, heading or fenced
    div that has one (white heading-banner text is kept).
    """
    lines = markdown.split("\n")
    fenced_lines = _fenced_code_lines(markdown) if skip_code_blocks else set()
    pairs = _fenced_div_pairs(lines, fenced_lines)

    bg_ranges = None
    if drop_white_text:
        bg_ranges = [
            (el.start, el.end)
            for el in styled_elements(markdown, skip_code_blocks)
            if _background_value(el.decls) is not None
        ]

    parts = []
    for offset, is_fenced, seg in _plain_segments(markdown, skip_code_blocks):
        if is_fenced:
            parts.append(seg)
            continue
        seg_ranges = None
        if bg_ranges is not None:
            seg_ranges = [
                (s - offset, e - offset)
                for s, e in bg_ranges
                if s < offset + len(seg) and e > offset
            ]
        parts.append(_filter_blocks(seg, policy, seg_ranges))
    markdown = "".join(parts)

    lines = markdown.split("\n")
    for i, line in enumerate(lines):
        if i in fenced_lines:
            continue
        m = _FENCE_BARE_CLASS_RE.match(line)
        if m and not policy(["." + m.group("cls")]):
            lines[i] = m.group("indent") + m.group("fence")

    to_remove = {
        idx
        for open_idx, close_idx in pairs.items()
        if not _FENCE_LINE_RE.match(lines[open_idx]).group(3)
        for idx in (open_idx, close_idx)
    }
    return "\n".join(line for i, line in enumerate(lines) if i not in to_remove)


# ---------------------------------------------------------------------------
# Styled spans, headings and divs; contrast
# ---------------------------------------------------------------------------

_HEADING_LINE_RE = re.compile(r"^[ ]{0,3}#{1,6}[ \t]")


@dataclass
class StyledElement:
    """A span, ATX heading or fenced div whose attribute block has a style.

    start/end is the stretch of the text it covers: the span from ``[`` to
    its closing ``}``, the heading's whole line, the div from its opening
    ``:::`` line through its closing one.
    """

    start: int
    end: int
    decls: dict[str, str]
    heading: bool
    text: str


def styled_elements(markdown: str, skip_code_blocks: bool = True) -> list[StyledElement]:
    """Every styled span, heading and fenced div, in document order. Links,
    images and code are not included; inline code and (with
    skip_code_blocks) fenced code blocks are skipped."""
    found: list[StyledElement] = []
    for offset, is_fenced, seg in _plain_segments(markdown, skip_code_blocks):
        if is_fenced:
            continue
        mask = _code_mask(seg)
        for m in ATTR_BLOCK_RE.finditer(seg):
            ws, content = m.group(1), m.group(2)
            brace_pos = m.start() + len(ws)
            if mask[brace_pos] or not _is_attr_context(seg, brace_pos):
                continue
            tokens = attr_tokens(content)
            if tokens is None:
                continue
            decls = style_declarations(tokens)
            if not decls:
                continue
            line_start = seg.rfind("\n", 0, brace_pos) + 1
            line_end = seg.find("\n", brace_pos)
            line_end = len(seg) if line_end == -1 else line_end
            on_heading = bool(_HEADING_LINE_RE.match(seg[line_start:line_end]))
            prev = seg[m.start() - 1] if m.start() else ""
            if not ws and prev == "]" and _is_bracket(seg, m.start() - 1, mask):
                opener = _find_opener(seg, m.start() - 1, mask)
                if opener is None or (opener > 0 and seg[opener - 1] == "!"):
                    continue
                found.append(
                    StyledElement(
                        offset + opener,
                        offset + m.end(),
                        decls,
                        on_heading,
                        seg[opener + 1 : m.start() - 1],
                    )
                )
            elif on_heading and (ws or prev not in ")]`"):
                title = re.sub(r"^[ ]{0,3}#{1,6}[ \t]+", "", seg[line_start : m.start()])
                found.append(
                    StyledElement(offset + line_start, offset + line_end, decls, True, title)
                )

    lines = markdown.split("\n")
    starts = [0]
    for line in lines:
        starts.append(starts[-1] + len(line) + 1)
    fenced_lines = _fenced_code_lines(markdown) if skip_code_blocks else set()
    for open_idx, close_idx in _fenced_div_pairs(lines, fenced_lines).items():
        attrs = _FENCE_LINE_RE.match(lines[open_idx]).group(3)
        if not (attrs.startswith("{") and attrs.endswith("}")):
            continue
        tokens = attr_tokens(attrs[1:-1])
        decls = style_declarations(tokens) if tokens else {}
        if not decls:
            continue
        body = next((ln.strip() for ln in lines[open_idx + 1 : close_idx] if ln.strip()), "")
        found.append(
            StyledElement(
                starts[open_idx], starts[close_idx] + len(lines[close_idx]), decls, False, body
            )
        )
    found.sort(key=lambda el: (el.start, -el.end))
    return found


def _relative_luminance(rgb: tuple[int, int, int]) -> float:
    def channel(c: int) -> float:
        s = c / 255
        return s / 12.92 if s <= 0.04045 else ((s + 0.055) / 1.055) ** 2.4

    r, g, b = (channel(c) for c in rgb)
    return 0.2126 * r + 0.7152 * g + 0.0722 * b


def contrast_ratio(a: tuple[int, int, int], b: tuple[int, int, int]) -> float:
    """WCAG 2 contrast ratio, from 1 (same colour) to 21 (black on white)."""
    la, lb = sorted((_relative_luminance(a), _relative_luminance(b)), reverse=True)
    return (la + 0.05) / (lb + 0.05)


# WCAG 2 AA minimums. Headings count as large text; the font sizes that
# would make other text large are removed as noise, so they are not used.
MIN_CONTRAST_TEXT = 4.5
MIN_CONTRAST_LARGE = 3.0


@dataclass
class ContrastWarning:
    line: int
    text: str
    color: str
    background: str
    ratio: float
    required: float


def _effective(
    el: StyledElement, elements: list[StyledElement], prop: str
) -> tuple[str | None, tuple[int, int, int] | None] | None:
    """(value, rgb) of the text colour (prop "color") or background (prop
    "background") el shows: its own, else the innermost enclosing element's.
    None if nothing sets it; rgb None if the value cannot be parsed."""
    enclosing = [o for o in elements if o.start <= el.start and el.end <= o.end]
    enclosing.sort(key=lambda o: (o is not el, o.end - o.start))
    for o in enclosing:
        if prop == "color":
            value = o.decls.get("color")
            if value is not None:
                return value, parse_css_color(value)
        else:
            value = _background_value(o.decls)
            if value is not None:
                return value, _parse_background(value)
    return None


def find_low_contrast(markdown: str) -> list[ContrastWarning]:
    """Styled spans, headings and divs whose text colour against their
    background is below WCAG AA (4.5:1, or 3:1 for headings).

    Only elements that set a text colour or a background are checked. A
    colour not set anywhere is Canvas's text colour on a white page. Elements
    with an unrecognised colour value, or no visible text, are skipped. A
    nested element that repeats an outer one's colours on the same line is
    reported once.
    """
    elements = styled_elements(markdown)
    warnings: list[ContrastWarning] = []
    seen: set[tuple[int, str, str]] = set()
    for el in elements:
        if "color" not in el.decls and _background_value(el.decls) is None:
            continue
        text = re.sub(r"(?<!\\)[\[\]*_`]|\{[^{}]*\}", "", el.text)
        text = " ".join(re.sub(r"\\(.)", r"\1", text).split())
        if not text:
            continue
        fg = _effective(el, elements, "color") or ("Canvas text colour", CANVAS_TEXT_RGB)
        bg = _effective(el, elements, "background") or ("white page", PAGE_BACKGROUND_RGB)
        if fg[1] is None or bg[1] is None:
            continue
        ratio = contrast_ratio(fg[1], bg[1])
        required = MIN_CONTRAST_LARGE if el.heading else MIN_CONTRAST_TEXT
        if ratio >= required:
            continue
        line = markdown.count("\n", 0, el.start) + 1
        key = (line, fg[0], bg[0])
        if key in seen:
            continue
        seen.add(key)
        if len(text) > 60:
            text = text[:57] + "..."
        warnings.append(ContrastWarning(line, text, fg[0], bg[0], ratio, required))
    return warnings


# ---------------------------------------------------------------------------
# Stray brackets
# ---------------------------------------------------------------------------

_REF_DEF_RE = re.compile(r"^[ ]{0,3}\[([^\]\n]+)\]:", re.MULTILINE)
_TASK_RE = re.compile(r"^[ \t]*(?:[-*+]|\d+[.)])[ \t]+\[[ xX]\]")
_SWAPPED_LINK_RE = re.compile(
    r"(?<![\\\]])\[([^\[\]\n]*)\]\[(https?://[^\s\[\]()<>]+)\](?:\(([^()\n]*)\))?"
)


def _norm_label(label: str) -> str:
    return " ".join(label.split()).casefold()


def reference_labels(markdown: str) -> set[str]:
    """Normalised labels of every `[label]: url` definition."""
    return {_norm_label(m.group(1)) for m in _REF_DEF_RE.finditer(markdown)}


def repair_swapped_links(markdown: str, labels: set[str]) -> str:
    """``[Label][https://url]( text )`` → ``[Label](https://url) text ``.

    This is a link whose ``(...)`` and ``[...]`` got swapped: pandoc reads the
    URL as link text and `` text `` as the destination.
    """

    def _fix(m: re.Match) -> str:
        if _norm_label(m.group(2)) in labels:
            return m.group(0)
        return f"[{m.group(1)}]({m.group(2)})" + (m.group(3) or "")

    return apply_outside_fences(markdown, lambda s: _SWAPPED_LINK_RE.sub(_fix, s))


def _paren_close(text: str, open_idx: int) -> int | None:
    depth = 0
    for i in range(open_idx, len(text)):
        ch = text[i]
        if ch == "\n" and i + 1 < len(text) and text[i + 1] == "\n":
            return None
        if ch == "(" and not _escaped(text, i):
            depth += 1
        elif ch == ")" and not _escaped(text, i):
            depth -= 1
            if depth == 0:
                return i
    return None


def _structural_brackets(text: str, mask: list[bool], labels: set[str]) -> set[int]:
    """Indices of brackets that are real Markdown syntax: links, images,
    attributed spans, reference links and definitions, footnotes, task boxes."""
    keep: set[int] = set()

    for m in _REF_DEF_RE.finditer(text):
        keep.update((m.start(1) - 1, m.end(1)))
    for line_m in re.finditer(r"^.*$", text, re.MULTILINE):
        t = _TASK_RE.match(line_m.group(0))
        if t:
            end = line_m.start() + t.end()
            keep.update((end - 3, end - 1))

    for i, ch in enumerate(text):
        if not _is_bracket(text, i, mask):
            continue
        if ch == "[" and i + 1 < len(text) and text[i + 1] == "^":
            close = _find_closer(text, i, mask)
            if close is not None:
                keep.update((i, close))
            continue
        if ch != "]" or i in keep:
            continue
        nxt = text[i + 1] if i + 1 < len(text) else ""
        opener = _find_opener(text, i, mask)
        if opener is None:
            continue
        own_label = _norm_label(text[opener + 1 : i])
        if nxt == "(" and _paren_close(text, i + 1) is not None:
            keep.update((opener, i))
        elif nxt == "{":
            b = ATTR_BLOCK_RE.match(text, i + 1)
            if b and attr_tokens(b.group(2)) is not None:
                keep.update((opener, i))
        elif nxt == "[" and _is_bracket(text, i + 1, mask):
            close2 = _find_closer(text, i + 1, mask)
            if close2 is None:
                continue
            ref = _norm_label(text[i + 2 : close2]) or own_label
            if ref in labels:
                keep.update((opener, i, i + 1, close2))
        elif own_label in labels:
            keep.update((opener, i))
    return keep


def _has_whitespace(group: str) -> bool:
    return any(c.isspace() for c in group)


def _repair_paragraph(para: str, labels: set[str]) -> str:
    mask = _code_mask(para)
    keep = _structural_brackets(para, mask, labels)
    stray = [
        i for i in range(len(para)) if _is_bracket(para, i, mask) and i not in keep
    ]
    stray_set = set(stray)

    # A paragraph qualifies only if it holds a seam: a stray "]" directly
    # followed by "[", with text containing whitespace on one side. That shape
    # is Word debris; "a[i][j]" written in prose has no whitespace and is left
    # alone.
    qualifies = False
    for i in stray:
        if para[i] != "]" or i + 1 >= len(para) or para[i + 1] != "[":
            continue
        left_start = max(
            (j for j in range(i) if _is_bracket(para, j, mask)), default=-1
        )
        right_end = next(
            (j for j in range(i + 2, len(para)) if _is_bracket(para, j, mask)),
            len(para),
        )
        if _has_whitespace(para[left_start + 1 : i]) or _has_whitespace(
            para[i + 2 : right_end]
        ):
            qualifies = True
            break
    if not qualifies:
        return para
    return "".join(c for i, c in enumerate(para) if i not in stray_set)


def remove_stray_brackets(markdown: str, labels: set[str]) -> str:
    """Delete brackets that belong to no Markdown construct, in paragraphs that
    show the ``][`` seam Word debris leaves. Other paragraphs are untouched."""

    def _segment(seg: str) -> str:
        parts = re.split(r"(\n[ \t]*\n)", seg)
        return "".join(
            p if k % 2 else _repair_paragraph(p, labels) for k, p in enumerate(parts)
        )

    return apply_outside_fences(markdown, _segment)


# ---------------------------------------------------------------------------
# Escaped quotes and trailing backslashes
# ---------------------------------------------------------------------------

# Places where a backslash before a quote is needed or literal: inline code,
# attribute blocks (style="font-family: \"Arial\""), link destinations and
# titles, raw HTML tags, and $...$ math (\' is a LaTeX accent).
_QUOTE_PROTECT_RES = (
    _INLINE_CODE_RE,
    ATTR_BLOCK_RE,
    re.compile(r"\]\((?:[^()\n]|\([^()\n]*\))*\)"),
    re.compile(r"<[A-Za-z/!][^<>\n]*>"),
    re.compile(r"(?<!\\)\$[^$\n]+(?<!\\)\$"),
)
_ESCAPED_QUOTE_RE = re.compile(r"\\(['\"])")


def unescape_quotes(markdown: str) -> str:
    """``\\'`` → ``'`` and ``\\"`` → ``"`` in prose.

    Pandoc escapes straight quotes when writing Markdown so that the smart
    reader keeps them straight. Unescaped, the tool's ``markdown+smart`` reader
    turns them into curly quotes (’ “ ”), which is how the text renders after
    the next update.
    """

    def _segment(seg: str) -> str:
        protected = [False] * len(seg)
        for rx in _QUOTE_PROTECT_RES:
            for m in rx.finditer(seg):
                for i in range(m.start(), m.end()):
                    protected[i] = True
        edits = [
            (m.start(), m.start() + 1, "")
            for m in _ESCAPED_QUOTE_RE.finditer(seg)
            if not protected[m.start()] and not _escaped(seg, m.start())
        ]
        return _apply_edits(seg, edits)

    return apply_outside_fences(markdown, _segment)


_LONE_IMAGE_RE = re.compile(
    r"^(?:(?:[-*+]|\d+[.)])\s+)?!\[[^\n]*\]\([^\n]*\)(?:\{[^\n]*\})?$"
)


def _ends_with_hard_break(line: str) -> bool:
    stripped = line.rstrip(" \t")
    return stripped.endswith("\\") and not _escaped(stripped, len(stripped) - 1)


def drop_final_hard_breaks(markdown: str) -> str:
    """Remove a trailing-backslash hard break that ends its paragraph.

    A backslash at the end of a line is a ``<br>``. Before a blank line (or the
    end of the text) it becomes ``<br>`` just before ``</p>`` or ``</li>``,
    which browsers do not draw, so removing it changes nothing on the page.
    Breaks mid-paragraph are kept. So is a line that is only a backslash
    directly after another break: the pair draws a visible empty line. So is
    the break after an image alone in its paragraph: without it, pandoc makes
    the image a figure and shows its alt text as a caption.
    """

    def _segment(seg: str) -> str:
        lines: list[str | None] = seg.split("\n")
        for i, line in enumerate(lines):
            if line is None or not _ends_with_hard_break(line):
                continue
            next_blank = i + 1 >= len(lines) or not lines[i + 1].strip()
            if not next_blank:
                continue
            body = line.rstrip(" \t")[:-1]
            prev = lines[i - 1] if i > 0 else None
            if not body.strip() and prev is not None and _ends_with_hard_break(prev):
                continue
            start = i
            while start > 0 and lines[start - 1] is not None and lines[start - 1].strip():
                start -= 1
            para = " ".join([*lines[start:i], body]).strip()
            if _LONE_IMAGE_RE.match(para):
                continue
            lines[i] = body.rstrip(" \t") if body.strip() else None
        return "\n".join(line for line in lines if line is not None)

    return apply_outside_fences(markdown, _segment)


# ---------------------------------------------------------------------------
# Empty paragraphs made of backslash lines
# ---------------------------------------------------------------------------

_LIST_MARKER_RE = re.compile(r"^[ \t]*(?:[-*+]|\d+[.)])[ \t]+")
# A line that would start a different kind of block if a blank line came
# before it (so it cannot simply become the first line of a new paragraph).
_BLOCK_START_RE = re.compile(r"^(?: {4,}|\t|[ ]{0,3}(?:[-*+]|\d+[.)])[ \t]|[ ]{0,3}(?:#|>|:::|```|~~~|\|))")


def _is_break_only(line: str) -> bool:
    return line.strip() == "\\"


def _inline_open(text: str) -> bool:
    """True if a span/link bracket or a ** run is still open at the end of
    text, so a paragraph break there would cut it in two."""
    mask = _code_mask(text)
    depth = 0
    for i, ch in enumerate(text):
        if _is_bracket(text, i, mask):
            depth += 1 if ch == "[" else -1
    stars = [m for m in _STAR_RUN_RE.finditer(text) if not mask[m.start()] and len(m.group(0)) >= 2]
    return depth > 0 or len(stars) % 2 == 1


def split_empty_break_paragraphs(markdown: str) -> str:
    """Replace Word's empty paragraphs, written as ``text\\`` + a line holding
    only ``\\``, with a real paragraph break.

    The two ``<br>`` draw an empty line. In an ordinary paragraph the
    backslash-only line(s) become one blank line, splitting it into two
    paragraphs (the earlier line's trailing ``\\`` then ends a paragraph and
    `drop_final_hard_breaks` removes it). Inside a list item a blank line would
    make the whole list loose (every item wrapped in ``<p>``), so there the
    backslash-only line(s) are deleted instead: the line break before them
    stays unless it now ends the item. They are also deleted, not turned into a
    blank line, where a span, link or ``**`` is still open (Word often puts
    the empty paragraph inside a styled span), or where the next line would
    start a different block (list, heading, code) after a blank line.
    """

    def _segment(seg: str) -> str:
        lines = seg.split("\n")
        out: list[str] = []
        i = 0
        while i < len(lines):
            line = lines[i]
            if not (
                _is_break_only(line)
                and out
                and out[-1].strip()
                and not _is_break_only(out[-1])
                and _ends_with_hard_break(out[-1])
            ):
                out.append(line)
                i += 1
                continue
            j = i
            while j < len(lines) and _is_break_only(lines[j]):
                j += 1
            nxt = lines[j] if j < len(lines) else ""
            start = len(out) - 1
            while start > 0 and out[start - 1].strip():
                start -= 1
            first = out[start]
            in_list = bool(_LIST_MARKER_RE.match(first)) or first[:1] in (" ", "\t")
            if not in_list and nxt.strip() and not _BLOCK_START_RE.match(nxt) and not _inline_open(
                "\n".join(out[start:])
            ):
                out.append("")
            elif not nxt.strip() or (in_list and _LIST_MARKER_RE.match(nxt)):
                # The break before the run now ends its paragraph or item.
                prev = out[-1].rstrip(" \t")
                if not _LONE_IMAGE_RE.match(prev[:-1].strip()):
                    out[-1] = prev[:-1].rstrip()
            i = j
        return "\n".join(out)

    return apply_outside_fences(markdown, _segment)


# ---------------------------------------------------------------------------
# Emphasis markers with a space on the wrong side
# ---------------------------------------------------------------------------

_STAR_RUN_RE = re.compile(r"(?<![*\\])\*+(?!\*)")
_EMPH_PROTECT_RES = (
    _INLINE_CODE_RE,
    ATTR_BLOCK_RE,
    re.compile(r"\]\((?:[^()\n]|\([^()\n]*\))*\)"),
    re.compile(r"<[A-Za-z/!][^<>\n]*>"),
    re.compile(r"(?<!\\)\$[^$\n]+(?<!\\)\$"),
)


def _fix_emphasis_paragraph(para: str) -> str:
    protected = [False] * len(para)
    for rx in _EMPH_PROTECT_RES:
        for m in rx.finditer(para):
            for k in range(m.start(), m.end()):
                protected[k] = True
    runs = [m for m in _STAR_RUN_RE.finditer(para) if not protected[m.start()]]
    if any(len(m.group(0)) > 2 for m in runs) or "\\*" in para:
        return para  # *** mixes bold and italic, \* is a literal star: too ambiguous
    edits: list[tuple[int, int, str]] = []
    for width in (2, 1):
        is_open = False
        fixes: list[tuple[int, int, str]] = []
        for m in runs:
            if len(m.group(0)) != width:
                continue
            start, end = m.start(), m.end()
            before = para[start - 1] if start else "\n"
            after = para[end] if end < len(para) else "\n"
            ws_before, ws_after = before.isspace(), after.isspace()
            if ws_before and ws_after:
                if is_open and width == 2 and after == "\n":
                    # "**Respond: **" at the end of a line: drop the space.
                    fixes.append((start - 1, start, ""))
                    is_open = False
                continue  # a bullet or "5 * 3", not emphasis
            if width == 1 and _LIST_MARKER_RE.match(para[para.rfind("\n", 0, start) + 1 : end + 1]):
                continue
            if not is_open:
                if ws_after:
                    fixes = []
                    is_open = None  # an opener that cannot open: give up
                    break
                is_open = True
            else:
                if ws_before:
                    # "**Scenario: **In": move the space outside the closer.
                    fixes.append((start - 1, end, m.group(0) + before))
                is_open = False
        if is_open is False:
            edits.extend(fixes)
    return _apply_edits(para, edits)


def fix_emphasis_spaces(markdown: str) -> str:
    """``**Scenario: **In`` → ``**Scenario:** In``.

    Word splits text into runs at formatting changes and the space often lands
    inside the bold run. A ``**`` with a space before it cannot close emphasis,
    so pandoc shows the asterisks. Within each paragraph, ``**`` (then ``*``)
    runs are paired in order; a closer with a space before it gets the space
    moved after it. A paragraph whose runs do not pair up, or that holds a
    ``***`` run, is left alone.
    """

    def _segment(seg: str) -> str:
        # Units are paragraphs and list items: emphasis cannot span either.
        parts = re.split(r"(\n[ \t]*\n|\n(?=[ \t]*(?:[-*+]|\d+[.)])[ \t]))", seg)
        return "".join(
            p if k % 2 else _fix_emphasis_paragraph(p) for k, p in enumerate(parts)
        )

    return apply_outside_fences(markdown, _segment)


# ---------------------------------------------------------------------------
# Doubled list markers
# ---------------------------------------------------------------------------

_STACKED_MARKERS_RE = re.compile(
    r"^(?P<indent>[ \t]*)(?P<extra>(?:(?:[-*+]|\d+[.)])[ \t]+)+)(?P<last>(?:[-*+]|\d+[.)])[ \t]+)(?=\S)"
)


_THEMATIC_BREAK_RE = re.compile(r"^[ \t]*([-*_])(?:[ \t]*\1){2,}[ \t]*$")


def flatten_stacked_list_markers(markdown: str) -> str:
    """``- - - text`` → ``- text`` and ``1.  1.  text`` → ``1.  text``.

    Word's multi-level lists arrive as items that hold nothing but another
    list, so each line starts with a stack of markers and the page shows a
    stack of bullets. Only the last marker is kept, and the lines that belong
    to it (indented at least as far as its content) lose the same indentation.
    """

    def _segment(seg: str) -> str:
        lines = seg.split("\n")
        i = 0
        while i < len(lines):
            m = _STACKED_MARKERS_RE.match(lines[i])
            if not m or "\t" in m.group("extra") or _THEMATIC_BREAK_RE.match(lines[i]):
                i += 1
                continue
            removed = len(m.group("extra"))
            base = len(m.group("indent"))
            lines[i] = m.group("indent") + lines[i][m.end("extra") :]
            j = i + 1
            while j < len(lines):
                line = lines[j]
                if not line.strip():
                    k = j
                    while k < len(lines) and not lines[k].strip():
                        k += 1
                    if k >= len(lines) or _indent(lines[k]) < base + removed:
                        break
                    j = k
                    continue
                if _indent(line) < base + removed:
                    break
                lines[j] = line[removed:]
                j += 1
            i = j
        return "\n".join(lines)

    return apply_outside_fences(markdown, _segment)


def _indent(line: str) -> int:
    return len(line) - len(line.lstrip(" "))


_LONG_RULE_RE = re.compile(r"^([ ]{0,3})-{4,}[ \t]*$")


def _rule_boundary(line: str) -> bool:
    """A blank line or a fenced-div line: neither can be heading or table text."""
    return not line.strip() or bool(_FENCE_LINE_RE.match(line))


def shorten_horizontal_rules(markdown: str) -> str:
    """A horizontal rule written as a long line of dashes (pandoc writes 72)
    becomes ``---``.

    Only a dash line with a blank line, a ``:::`` div fence, or the text's
    start or end on both sides is a rule: directly under text it is a setext heading underline, and
    pandoc's multiline tables open and close with a dash line next to table
    text.
    """

    def _segment(seg: str) -> str:
        lines = seg.split("\n")
        for i, line in enumerate(lines):
            m = _LONG_RULE_RE.match(line)
            if not m:
                continue
            before = lines[i - 1] if i > 0 else ""
            after = lines[i + 1] if i + 1 < len(lines) else ""
            if _rule_boundary(before) and _rule_boundary(after):
                lines[i] = m.group(1) + "---"
        return "\n".join(lines)

    return apply_outside_fences(markdown, _segment)


def repair_prose(markdown: str) -> str:
    """The repairs that import and fix-markdown both apply after attribute
    cleanup: stacked list markers, empty backslash paragraphs, final hard
    breaks, misplaced emphasis spaces, escaped quotes, long horizontal rules."""
    markdown = shorten_horizontal_rules(markdown)
    markdown = flatten_stacked_list_markers(markdown)
    markdown = split_empty_break_paragraphs(markdown)
    markdown = drop_final_hard_breaks(markdown)
    markdown = fix_emphasis_spaces(markdown)
    return unescape_quotes(markdown)


# ---------------------------------------------------------------------------
# Whole-file cleaning for fix-markdown
# ---------------------------------------------------------------------------


def _tidy_changed_lines(before: str, after: str, drop_emptied: bool = True) -> str:
    """Strip whitespace the cleaning left at line ends, and (with
    drop_emptied) drop lines it emptied: an empty line would split a paragraph
    that was one before."""
    old = before.split("\n")
    new = after.split("\n")
    sm = difflib.SequenceMatcher(a=old, b=new, autojunk=False)
    out: list[str] = []
    for tag, i1, i2, j1, j2 in sm.get_opcodes():
        if tag == "equal":
            out.extend(new[j1:j2])
            continue
        old_block, new_block = old[i1:i2], new[j1:j2]
        old_blank = all(not line.strip() for line in old_block)
        paired = len(old_block) == len(new_block)
        for k, line in enumerate(new_block):
            orig = old_block[k] if paired else None
            if line == orig:
                out.append(line)
                continue
            if drop_emptied and not line.strip() and not old_blank:
                continue
            # Whitespace the line already ended with (possibly a two-space
            # hard break) is left alone; only a changed ending is trimmed.
            if orig is not None and _trailing_ws(orig) == _trailing_ws(line):
                out.append(line)
            else:
                out.append(line[: len(line) - len(_trailing_ws(line))])
    return "\n".join(out)


def _trailing_ws(line: str) -> str:
    # [^\S\n] includes the no-break space Word puts in its empty spans.
    m = re.search(r"[^\S\n]+$", line)
    return m.group(0) if m else ""


def clean_markdown_body(body: str) -> str:
    """Remove Word debris from a Markdown body (no frontmatter)."""
    labels = reference_labels(body)
    cleaned = repair_swapped_links(body, labels)
    # Strays first: the Word attribute blocks still anchor their spans, so a
    # "[ ][ ]{.EOP}" tail is recognised as a seam before the block goes.
    cleaned = remove_stray_brackets(cleaned, labels)
    cleaned = filter_pandoc_attrs(cleaned, strip_word_attrs, drop_white_text=True)
    if cleaned != body:
        cleaned = _tidy_changed_lines(body, cleaned)
    # The prose repairs add blank lines on purpose, so they are tidied without
    # dropping emptied lines.
    repaired = repair_prose(cleaned)
    if repaired != cleaned:
        repaired = _tidy_changed_lines(cleaned, repaired, drop_emptied=False)
    return repaired


def split_frontmatter_raw(text: str) -> tuple[str, str]:
    """Return (frontmatter including its --- lines, body), unparsed."""
    if text.startswith("---\n"):
        end = text.find("\n---\n", 4)
        if end != -1:
            return text[: end + 5], text[end + 5 :]
    return "", text


# Matches import's `_build_frontmatter`, which writes its commented-out keys
# with this indent.
FRONTMATTER_COMMENT_INDENT = "    "


def indent_frontmatter_comments(front: str) -> str:
    """Indent frontmatter lines that start with ``#`` by four spaces.

    VS Code reads a column-0 ``# ...`` line in frontmatter as a Markdown H1.
    YAML ignores whitespace before a comment, but an indented ``#`` line
    after a block scalar (``key: |``) would join the scalar's text, so the
    change is kept only if the frontmatter parses to the same data.
    """
    lines = front.split("\n")
    # lines[0] and the last "---" line are the delimiters.
    changed = [
        FRONTMATTER_COMMENT_INDENT + line if line.startswith("#") else line
        for line in lines
    ]
    if changed == lines:
        return front
    try:
        before = yaml.safe_load("\n".join(lines[1:-2]))
        after = yaml.safe_load("\n".join(changed[1:-2]))
    except yaml.YAMLError:
        return front
    return "\n".join(changed) if before == after else front


def clean_markdown_file_text(text: str) -> str:
    front, body = split_frontmatter_raw(text)
    return indent_frontmatter_comments(front) + clean_markdown_body(body)


@dataclass
class FileFix:
    path: Path
    before: str
    after: str

    def diff_lines(self) -> list[str]:
        # Skip the two file-header lines only: a removed "---" rule is
        # "----" in the diff and must still be shown.
        return list(
            difflib.unified_diff(
                self.before.split("\n"), self.after.split("\n"), lineterm="", n=0
            )
        )[2:]


@dataclass
class FixMarkdownPlan:
    fixes: list[FileFix] = field(default_factory=list)
    errors: list[tuple[Path, str]] = field(default_factory=list)
    contrast: list[tuple[Path, ContrastWarning]] = field(default_factory=list)
    scanned: int = 0


def plan_fix_markdown(files: list[Path]) -> FixMarkdownPlan:
    plan = FixMarkdownPlan()
    for path in files:
        try:
            text = path.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError) as e:
            plan.errors.append((path, str(e)))
            continue
        plan.scanned += 1
        cleaned = clean_markdown_file_text(text)
        if cleaned != text:
            plan.fixes.append(FileFix(path, text, cleaned))
        # Checked after cleaning: that is what the page will show.
        front, body = split_frontmatter_raw(cleaned)
        front_lines = front.count("\n")
        for w in find_low_contrast(body):
            w.line += front_lines
            plan.contrast.append((path, w))
    return plan


def apply_fix_markdown(plan: FixMarkdownPlan) -> None:
    for fix in plan.fixes:
        fix.path.write_text(fix.after, encoding="utf-8")


def collect_markdown_files(repo_root: Path) -> list[Path]:
    """Every Markdown file in the course that the tool renders: content
    folders, modules, snippets, quizzes and question banks (including their
    question files), and the syllabus. Hidden and .canvasignore'd paths are
    skipped."""
    from . import repo_format
    from .ignore import load_ignore_matcher
    from .local_orphans import _content_dirs, _walk_files

    repo_format.check_repo_format(repo_root)
    matcher = load_ignore_matcher(repo_root)
    files: list[Path] = []
    for content_dir in _content_dirs(repo_root, matcher):
        files.extend(_walk_files(content_dir, repo_root, matcher, suffix=".md"))
    for name in ("modules", "snippets", "quizzes", "question_banks"):
        d = repo_root / name
        if d.exists():
            files.extend(_walk_files(d, repo_root, matcher, suffix=".md"))
    syllabus = repo_root / "course_settings" / "syllabus.md"
    if syllabus.exists():
        files.append(syllabus)
    return files
