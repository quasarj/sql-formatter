"""Normalize DBI ``?`` and psycopg2 ``%s`` placeholders to native ``$n``.

``$n`` is valid Postgres and parses fine; ``?`` and ``%s`` are not, so
they must be substituted before parsing and restored after formatting.
Synthetic parameter numbers start above any ``$n`` already present in
the input, so restoration can never touch a genuine asyncpg parameter.

The scanner skips opaque regions (string literals, quoted identifiers,
comments, dollar-quoted bodies) and leaves the jsonb operators ``?``,
``?|`` and ``?&`` alone.  The jsonb heuristic, inherited from the
regex-era tooling: a ``?`` followed by optional whitespace and a string
literal is an operator, not a placeholder.
"""

import re

_DOLLAR_TAG = re.compile(r"\$[A-Za-z_]*\$")
_PARAM = re.compile(r"\$(\d+)")


def _opaque_length(text: str, i: int) -> int | None:
    """Length of the verbatim construct starting at ``i``, or None."""
    c = text[i]
    if text.startswith("--", i):
        end = text.find("\n", i)
        return (len(text) if end < 0 else end) - i
    if text.startswith("/*", i):
        end = text.find("*/", i + 2)
        return (len(text) if end < 0 else end + 2) - i
    if c == "'":
        j = i + 1
        while j < len(text):
            if text[j] == "'":
                if not text.startswith("''", j):
                    return j - i + 1
                j += 1
            j += 1
        return len(text) - i
    if c == '"':
        end = text.find('"', i + 1)
        return (len(text) if end < 0 else end + 1) - i
    if c == "$":
        m = _DOLLAR_TAG.match(text, i)
        if m:
            tag = m.group(0)
            end = text.find(tag, m.end())
            return (len(text) if end < 0 else end + len(tag)) - i
    return None


def _is_jsonb_question_mark(text: str, i: int) -> bool:
    """True when the ``?`` at ``i`` is a jsonb operator, not a placeholder."""
    if text.startswith(("?|", "?&"), i):
        return True
    rest = text[i + 1 :].lstrip()
    return rest.startswith("'")


def normalize(text: str) -> tuple[str, dict[int, str]]:
    """Replace ``?``/``%s`` with ``$n``; return new text and the mapping."""
    next_param = max((int(m.group(1)) for m in _PARAM.finditer(text)), default=0) + 1
    substitutions: dict[int, str] = {}
    out: list[str] = []
    i = 0
    while i < len(text):
        n = _opaque_length(text, i)
        if n is not None:
            out.append(text[i : i + n])
            i += n
            continue
        original = None
        if text[i] == "?" and not _is_jsonb_question_mark(text, i):
            original = "?"
        elif text.startswith("%s", i):
            original = "%s"
        if original is not None:
            substitutions[next_param] = original
            out.append(f"${next_param}")
            next_param += 1
            i += len(original)
            continue
        out.append(text[i])
        i += 1
    return "".join(out), substitutions


def restore(text: str, substitutions: dict[int, str]) -> str:
    """Put the original placeholder text back in place of synthetic ``$n``."""
    if not substitutions:
        return text
    return _PARAM.sub(
        lambda m: substitutions.get(int(m.group(1)), m.group(0)), text
    )
