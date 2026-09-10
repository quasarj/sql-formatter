"""The formatting pipeline: stdin text in, canonical SQL out.

Per statement: substitute foreign placeholders, parse with the real
Postgres grammar, re-print through :class:`FourSpaceStream` with the
house printers, lowercase keywords, restore placeholders.  A statement
that fails to parse is echoed back verbatim — never a partial rewrite.
"""

import pglast
from pglast import Error as PglastError
from pglast import parse_sql

from . import printers as _printers  # noqa: F401  (registers the overrides)
from .comments import extract_comments, reinsert_comments
from .lowercase import lowercase_keywords
from .placeholders import normalize, restore
from .stream import FourSpaceStream

def format_sql(text: str) -> str:
    """Format a buffer of one or more SQL statements."""
    if not text.strip():
        return text
    normalized, substitutions = normalize(text)
    formatted = _format_statements(normalized)
    result = restore(formatted, substitutions)
    if not result.endswith('\n'):
        result += '\n'
    return result


def _format_statements(text: str) -> str:
    slices = _statement_slices(text)
    parts: list[str] = []
    prev_stop = 0
    for i, sl in enumerate(slices):
        chunk = text[sl].strip()
        if not chunk:
            prev_stop = sl.stop
            continue
        is_last = i + 1 == len(slices)
        gap = text[sl.stop:len(text) if is_last else slices[i + 1].start]
        if _is_comment_only(chunk):
            same_line = parts and '\n' not in text[prev_stop:sl.start]
            if same_line:
                parts[-1] += '  ' + chunk
            else:
                parts.append(chunk)
        else:
            piece, was_formatted = _format_one(chunk)
            if not is_last or ';' in gap:
                # a kept semicolon goes on its own line, but not when the
                # statement was echoed verbatim
                piece += '\n;' if was_formatted else ';'
            trailer = _gap_comments(gap)
            if trailer:
                piece += '  ' + trailer
            parts.append(piece)
        prev_stop = sl.stop
    return '\n\n'.join(parts)


def _statement_slices(text: str) -> list[slice]:
    """Scanner-based statement boundaries; tolerant of unparseable SQL.

    The scanner refuses to slice text it cannot tokenize into balanced
    statements (unbalanced parens, stray garbage), silently dropping the
    tail.  Anything it left uncovered becomes one final slice so the
    verbatim-fallback path still sees it.
    """
    try:
        slices = list(pglast.split(text, with_parser=False, only_slices=True))
    except PglastError:
        slices = []
    covered = slices[-1].stop if slices else 0
    remainder = text[covered:]
    tail = remainder.lstrip('; \t\r\n')
    if tail:
        slices.append(slice(covered + len(remainder) - len(tail), len(text)))
    return slices


def _is_comment_only(chunk: str) -> bool:
    """True when the chunk holds no actual statement, only comments."""
    try:
        return not parse_sql(chunk)
    except PglastError:
        return False


def _gap_comments(gap: str) -> str:
    """Whatever sits between two statements besides the separator."""
    return gap.replace(';', ' ', 1).strip()


def _format_one(statement: str) -> tuple[str, bool]:
    """Format a single statement, falling back to the verbatim input.

    Returns the text and whether it was actually formatted (False means
    a verbatim echo, which the caller must not touch up further).
    """
    try:
        bare, comments = extract_comments(statement)
        tree = parse_sql(bare)
        if not tree:  # nothing but comments
            return statement, False
        stream = FourSpaceStream(special_functions=True, comma_at_eoln=True)
        formatted = lowercase_keywords(stream(tree))
        return reinsert_comments(formatted, comments), True
    except PglastError:
        return statement, False
