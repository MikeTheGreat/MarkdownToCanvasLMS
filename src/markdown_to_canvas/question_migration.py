"""Format migration 5 -> 6: question-file sections become H1.

Before format 6 a question file's sections were ``## Question``, ``## Answers``,
``## Feedback`` and ``## Sample Solution``, with ``### General`` /
``### Correct`` / ``### Incorrect`` / ``### Per-answer`` under Feedback, and any
other ``##`` heading started a section that was silently dropped (which is how
imported question text starting with an ``<h2>`` uploaded as empty). From
format 6 the sections are H1 and the feedback subsections H2, so ``##`` and
deeper headings are ordinary content (see ``quiz.parse_question_file``).

This module promotes the section headings of every question file by one level.
Other ``##`` headings are left as they are and so become content of the section
they sit in; that is the intended fix under ``## Question`` (or in the text
above the first section), and is reported with a notice anywhere else, since
the text under them was ignored before and will now be read as answers,
feedback or a sample solution. An existing H1 in the body is reported too: it
would become a section heading.
"""
from __future__ import annotations

import re
from pathlib import Path

from .convert import split_fenced_segments
from .quiz import split_quiz_body

_OLD_SECTIONS = ("question", "answers", "feedback", "sample solution")
_OLD_SUBSECTIONS = ("general", "correct", "incorrect", "per-answer")

_H1_RE = re.compile(r"^#\s+(.+?)\s*$")
_H2_RE = re.compile(r"^##\s+(.+?)\s*$")
_H3_RE = re.compile(r"^###\s+(.+?)\s*$")


def _visible(path: Path, repo: Path) -> bool:
    try:
        rel = path.relative_to(repo)
    except ValueError:
        return False
    return path.is_file() and not any(part.startswith(".") for part in rel.parts)


def _split_frontmatter(text: str) -> tuple[str, str]:
    """(frontmatter block including its delimiters, body), split as
    ``convert.parse_frontmatter`` splits it."""
    if text.startswith("---\n"):
        end = text.find("\n---\n", 4)
        if end != -1:
            return text[: end + 5], text[end + 5 :]
    return "", text


def find_question_files(repo: Path) -> list[Path]:
    """Every question file: those the quizzes list, plus every .md in a
    ``questions/`` folder of a quiz or question bank. Hidden paths are skipped;
    ``.canvasignore`` is not consulted (an ignored quiz still has to be
    readable once un-ignored)."""
    found: set[Path] = set()
    quizzes = repo / "quizzes"
    if quizzes.is_dir():
        for folder in sorted(d for d in quizzes.iterdir() if d.is_dir()):
            main = folder / f"{folder.name}.md"
            if main.is_file():
                try:
                    text = main.read_text(encoding="utf-8")
                except (OSError, UnicodeDecodeError):
                    text = ""
                _, refs = split_quiz_body(_split_frontmatter(text)[1], main)
                found.update(p for p in refs if _visible(p, repo.resolve()))
    for parent in ("quizzes", "question_banks"):
        base = repo / parent
        if base.is_dir():
            found.update(
                p.resolve() for p in base.glob("*/questions/*.md") if _visible(p, repo)
            )
    return sorted(found)


def migrate_question_text(text: str) -> tuple[str, list[str]]:
    """(new text, notices) for one question file."""
    frontmatter, body = _split_frontmatter(text)
    notices: list[str] = []
    old_section = ""    # the section the old parser was in (any ## heading)
    kept_section = ""   # the section the new parser will be in (known ## only)
    out: list[str] = []
    # Walk the same segments and line breaks as quiz._split_on_headings.
    for is_fenced, segment in split_fenced_segments(body):
        if is_fenced:
            out.append(segment)
            continue
        for line in segment.splitlines(keepends=True):
            stripped = line.rstrip("\r\n")
            if m := _H1_RE.match(stripped):
                notices.append(
                    f"'# {m.group(1)}' is a heading in the text; from format 6 it "
                    f"would start a (misnamed) section, so change it to "
                    f"'## {m.group(1)}'"
                )
            elif m := _H2_RE.match(stripped):
                name = m.group(1).lower()
                old_section = name
                if name in _OLD_SECTIONS:
                    kept_section = name
                    line = line[1:]
                elif kept_section not in ("", "question"):
                    notices.append(
                        f"'## {m.group(1)}' under ## {kept_section.title()} was "
                        f"ignored before; it is now read as part of that section. "
                        f"Move it and its text under # Question, or delete it"
                    )
            elif (m := _H3_RE.match(stripped)) and old_section == "feedback" \
                    and m.group(1).lower() in _OLD_SUBSECTIONS:
                line = line[1:]
            out.append(line)
    return frontmatter + "".join(out), notices


def migrate_question_sections(repo: Path) -> tuple[dict[Path, str], list[str]]:
    """({path: new text}, report lines) for every question file in ``repo``."""
    writes: dict[Path, str] = {}
    report: list[str] = []
    changed = 0
    for path in find_question_files(repo):
        rel = path.relative_to(repo.resolve()).as_posix()
        try:
            text = path.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError):
            report.append(f"NOTICE: {rel}: could not be read as UTF-8; not converted")
            continue
        new_text, notices = migrate_question_text(text)
        if new_text != text:
            writes[path] = new_text
            changed += 1
        report.extend(f"NOTICE: {rel}: {n}" for n in notices)
    report.insert(0, f"Promote question-file section headings to H1 in {changed} file(s)")
    return writes, report
