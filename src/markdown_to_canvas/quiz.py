"""Parse quiz and question Markdown files."""
from __future__ import annotations

import re
from pathlib import Path
from typing import Any

from .conditionals import apply_conditionals
from .convert import (
    expand_frontmatter_snippets,
    iter_lines_with_fence_info,
    markdown_to_html,
    parse_frontmatter as _parse_frontmatter,
    preprocess_snippets,
    warn,
)
from .links import LINK_TEXT

_QUIZ_LINK_RE = re.compile(rf"^\s*\d+\.\s+\[({LINK_TEXT}+)\]\(([^)]+\.md)\)")
_ANSWER_ITEM_RE = re.compile(r"^\s*\d+\.\s+(.+)")
#: Question-file sections are H1 and feedback subsections H2 (format 6), so
#: the question text itself can use ## and deeper headings.
_SECTION_HEADING_RE = re.compile(r"^#\s+(.+)$", re.MULTILINE)
_SUBSECTION_HEADING_RE = re.compile(r"^##\s+(.+)$", re.MULTILINE)
_OLD_SECTION_HEADING_RE = re.compile(r"^(##|###)\s+(.+?)\s*$")
_PER_ANSWER_ITEM_RE = re.compile(r"^-\s*answer\s+(\d+):\s*(.*)$", re.IGNORECASE)


def parse_quiz_file(
    quiz_md: Path,
    snippets_dir: Path | None = None,
    flags: dict[str, bool] | None = None,
    source_desc: str | None = None,
    errors: list[str] | None = None,
    course_id: int | None = None,
) -> tuple[dict[str, Any], str, list[Path]]:
    """Parse a quiz-level .md file.

    Returns (frontmatter, description_html, question_paths_in_order).
    question_paths_in_order is a list of absolute Paths to question files,
    in the order they appear in the numbered list.

    When ``flags`` is given, course-flag conditionals are evaluated on the
    body (so a whole question-list entry can be conditional). A directive
    error is reported via ``errors`` and yields an empty body — callers
    detect the new error and skip the quiz.
    """
    text = quiz_md.read_text(encoding="utf-8")
    frontmatter, body = _parse_frontmatter(text)

    if snippets_dir is not None:
        frontmatter, body = expand_frontmatter_snippets(frontmatter, body, quiz_md, snippets_dir)
    if flags is not None:
        filtered = apply_conditionals(
            body, flags, source_desc or quiz_md.name, errors
        )
        body = "" if filtered is None else filtered
    if snippets_dir is not None:
        body = preprocess_snippets(
            body, quiz_md, snippets_dir, errors, flags=flags, course_id=course_id
        )

    description_md, question_files = split_quiz_body(body, quiz_md)
    desc_html = markdown_to_html(description_md) if description_md else ""

    return frontmatter, desc_html, question_files


def split_quiz_body(body: str, quiz_md: Path) -> tuple[str, list[Path]]:
    """Separate a quiz-level body into (description_md, question_paths).

    A numbered link inside a fenced code block is literal example text, not a
    question. Shared by the update pipeline (parse_quiz_file) and the publish
    study guide so both agree on what counts as a question.
    """
    question_files: list[Path] = []
    description_lines: list[str] = []
    for line, is_fenced in iter_lines_with_fence_info(body):
        m = None if is_fenced else _QUIZ_LINK_RE.match(line)
        if m:
            href = m.group(2)
            question_files.append((quiz_md.parent / href).resolve())
        else:
            description_lines.append(line)
    return "\n".join(description_lines).strip(), question_files


def _split_on_headings(body: str, heading_re: re.Pattern) -> dict[str, str]:
    """Split body at heading lines into {heading_lowercased: content}.

    The implicit first section (before any heading) is stored as "". Heading
    lookalikes inside fenced code blocks are content, not section boundaries.
    """
    sections: dict[str, str] = {}
    current = ""
    acc: list[str] = []
    for line, is_fenced in iter_lines_with_fence_info(body):
        m = None if is_fenced else heading_re.match(line)
        if m:
            sections[current] = "\n".join(acc)
            current = m.group(1).strip().lower()
            acc = []
        else:
            acc.append(line)
    sections[current] = "\n".join(acc)
    return sections


def _split_sections(body: str) -> dict[str, str]:
    """Split body into named sections keyed by # heading text (lowercased)."""
    return _split_on_headings(body, _SECTION_HEADING_RE)


#: The ``#`` sections a question file may have; any other is ignored.
_QUESTION_SECTIONS = ("question", "answers", "feedback", "sample solution")
#: The ``##`` subsections of ``# Feedback``.
_FEEDBACK_SUBSECTIONS = ("general", "correct", "incorrect", "per-answer")


def _heading_list(level: str, names: tuple[str, ...]) -> str:
    return ", ".join(f"{level} {n[0].upper() + n[1:]}" for n in names)


def _warn_ignored_sections(body: str, sections: dict[str, str], where: str) -> None:
    """Warn about question-file text that is never sent to Canvas, or that
    uses the section headings from before format 6.

    That is every ``#`` section not in _QUESTION_SECTIONS, the text above the
    first heading when a ``# Question`` section replaces it, a ``##`` heading
    in ``# Feedback`` that is not a subsection, and a ``##`` heading named like
    a section (or, in ``# Feedback``, a ``###`` heading named like a
    subsection), which is now ordinary content.
    """
    no_text = not sections.get("question", sections.get("", "")).strip()
    current = ""
    for line, is_fenced in iter_lines_with_fence_info(body):
        if is_fenced:
            continue
        m = _SECTION_HEADING_RE.match(line)
        if m:
            current = m.group(1).strip().lower()
        if m and current not in _QUESTION_SECTIONS:
            print(
                f"  WARNING: {where}: '# {m.group(1).strip()}' is not a question-file "
                f"section ({_heading_list('#', _QUESTION_SECTIONS)}), so it and the "
                f"text under it are ignored"
                f"{' and the question has no text' if no_text else ''}. Put the "
                f"question text under # Question or above the first # heading, and "
                f"use ## or deeper for headings inside it"
            )
            continue
        old = _OLD_SECTION_HEADING_RE.match(line)
        if not old:
            continue
        level, name = old.group(1), old.group(2)
        if level == "###" and current != "feedback":
            continue
        names = _QUESTION_SECTIONS if level == "##" else _FEEDBACK_SUBSECTIONS
        if name.lower() in names:
            print(
                f"  WARNING: {where}: '{level} {name}' is ordinary content, not a "
                f"{'section' if level == '##' else 'feedback subsection'}; since "
                f"format version 6 it is written '{level[1:]} {name}'"
            )
        elif level == "##" and current == "feedback" and name.lower() not in _FEEDBACK_SUBSECTIONS:
            print(
                f"  WARNING: {where}: '## {name}' in # Feedback is not a feedback "
                f"subsection ({_heading_list('##', _FEEDBACK_SUBSECTIONS)}), so it and "
                f"the text under it are ignored; use ### or deeper for headings "
                f"inside feedback"
            )
    if "question" in sections and sections.get("", "").strip():
        print(
            f"  WARNING: {where}: the text above the first # heading is ignored "
            f"because the file has a # Question section; move it under # Question"
        )


def _parse_per_answer_feedback(text: str) -> dict[int, str]:
    """Parse `- answer N: text` items into {1-based index: feedback text}.

    Lines after an item that aren't themselves a new `- answer N:` item are
    treated as continuation of that item's feedback (matching how `import`
    writes multi-paragraph feedback under a single bullet).
    """
    result: dict[int, str] = {}
    current: int | None = None
    buf: list[str] = []
    for line, is_fenced in iter_lines_with_fence_info(text):
        m = None if is_fenced else _PER_ANSWER_ITEM_RE.match(line)
        if m:
            if current is not None:
                result[current] = "\n".join(buf).strip()
            current = int(m.group(1))
            buf = [m.group(2).strip()]
        elif current is not None:
            buf.append(line)
    if current is not None:
        result[current] = "\n".join(buf).strip()
    return result


def _parse_feedback_section(feedback_body: str) -> dict[str, Any]:
    """Parse ## General/Correct/Incorrect/Per-answer subsections from a # Feedback section."""
    result: dict[str, Any] = {}
    for subheading, raw in _split_on_headings(feedback_body, _SUBSECTION_HEADING_RE).items():
        content = raw.strip()
        if subheading == "general" and content:
            result["neutral_comments"] = content
        elif subheading == "correct" and content:
            result["correct_comments"] = content
        elif subheading == "incorrect" and content:
            result["incorrect_comments"] = content
        elif subheading == "per-answer" and content:
            per_answer = _parse_per_answer_feedback(content)
            if per_answer:
                result["per_answer_comments"] = per_answer
    return result


def _parse_answers_section(answers_text: str, correct, question_type: str) -> list[dict[str, Any]]:
    """Parse numbered answer list into answer dicts for MCQ or multiple_answers."""
    answer_texts: list[str] = []
    for line, is_fenced in iter_lines_with_fence_info(answers_text):
        am = None if is_fenced else _ANSWER_ITEM_RE.match(line)
        if am:
            answer_texts.append(am.group(1).strip())

    if question_type == "multiple_answers_question":
        correct_set = set(correct) if isinstance(correct, list) else set()
        return [
            {"text": text, "weight": 100 if (i + 1) in correct_set else 0}
            for i, text in enumerate(answer_texts)
        ]
    # multiple_choice_question
    return [
        {"text": text, "weight": 100 if (i + 1) == correct else 0}
        for i, text in enumerate(answer_texts)
    ]


def _apply_per_answer_comments(
    answers: list[dict[str, Any]], per_answer_comments: dict[int, str]
) -> None:
    """Attach `answer_comments` to answers by their 1-based position."""
    for i, ans in enumerate(answers, start=1):
        if i in per_answer_comments:
            ans["answer_comments"] = per_answer_comments[i]


def parse_question_file(
    q_path: Path,
    snippets_dir: Path | None = None,
    flags: dict[str, bool] | None = None,
    source_desc: str | None = None,
    errors: list[str] | None = None,
    course_id: int | None = None,
) -> dict[str, Any]:
    """Parse a quiz question .md file.

    Returns a dict with: title, question_type, points_possible, question_text (HTML),
    answers (list of {text, weight} for MCQ/T-F/multiple_answers; empty for essay;
    each answer may also carry answer_comments for MCQ/T-F/multiple_answers),
    and optionally neutral_comments, correct_comments, incorrect_comments.
    rel_path is NOT set here — callers add it.

    When ``flags`` is given, course-flag conditionals are evaluated on the
    body. A directive error is reported via ``errors`` and yields an empty
    body — callers detect the new error and skip the quiz/bank.
    """
    text = q_path.read_text(encoding="utf-8")
    frontmatter, body = _parse_frontmatter(text)

    if snippets_dir is not None:
        frontmatter, body = expand_frontmatter_snippets(frontmatter, body, q_path, snippets_dir)
    if flags is not None:
        filtered = apply_conditionals(body, flags, source_desc or q_path.name, errors)
        body = "" if filtered is None else filtered
    if snippets_dir is not None:
        body = preprocess_snippets(
            body, q_path, snippets_dir, errors, flags=flags, course_id=course_id
        )

    question_type = frontmatter.get("question_type", "essay_question")
    points = frontmatter.get("points_possible", 0)
    title = frontmatter.get("title", q_path.stem)
    correct = frontmatter.get("correct")
    if question_type == "multiple_response_question":
        warn(
            f"ERROR: {source_desc or q_path.name}: question_type multiple_response_question "
            f"was renamed to multiple_answers_question in repo format 5; change it "
            f"(Canvas does not recognise the old name)",
            errors,
        )

    sections = _split_sections(body)
    _warn_ignored_sections(body, sections, source_desc or q_path.name)
    feedback_section = sections.get("feedback", "")
    feedback = _parse_feedback_section(feedback_section) if feedback_section.strip() else {}
    per_answer_comments: dict[int, str] = feedback.pop("per_answer_comments", {})

    # Question text: prefer # Question section, fall back to implicit first section
    desc = sections.get("question", sections.get("", "")).strip()
    question_text_html = markdown_to_html(desc) if desc else ""

    if question_type == "true_false_question":
        answers = [
            {"text": "True", "weight": 100 if correct is True else 0},
            {"text": "False", "weight": 100 if correct is False else 0},
        ]
        _apply_per_answer_comments(answers, per_answer_comments)
        return {
            "title": title,
            "question_type": question_type,
            "points_possible": points,
            "question_text": question_text_html,
            "answers": answers,
            **feedback,
        }

    if question_type in ("multiple_choice_question", "multiple_answers_question"):
        answers_text = sections.get("answers", "")
        answers = _parse_answers_section(answers_text, correct, question_type)
        _apply_per_answer_comments(answers, per_answer_comments)
        return {
            "title": title,
            "question_type": question_type,
            "points_possible": points,
            "question_text": question_text_html,
            "answers": answers,
            **feedback,
        }

    if question_type == "fill_in_blank_question":
        accepted = frontmatter.get("answers", [])
        answers = [{"text": a, "weight": 100} for a in accepted]
        return {
            "title": title,
            "question_type": "short_answer_question",
            "points_possible": points,
            "question_text": question_text_html,
            "answers": answers,
            **feedback,
        }

    if question_type == "pattern_match_question":
        patterns = frontmatter.get("answers", [])
        answers = [{"text": patterns[0], "weight": 100}] if patterns else []
        return {
            "title": title,
            "question_type": "short_answer_question",
            "points_possible": points,
            "question_text": question_text_html,
            "answers": answers,
            **feedback,
        }

    # essay_question or any other type — no structured answers
    # §11: Sample Solution → neutral_comments
    sample_solution = sections.get("sample solution", "").strip()
    if sample_solution and "neutral_comments" not in feedback:
        feedback["neutral_comments"] = sample_solution

    return {
        "title": title,
        "question_type": question_type,
        "points_possible": points,
        "question_text": question_text_html,
        "answers": [],
        **feedback,
    }
