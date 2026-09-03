"""Comment extraction and re-insertion with correct attachment.

pglast can carry comments through serialization, but it attaches every
comment to the *following* parse node, so a trailing comment jumps
forward past the next keyword (``select * -- x`` / ``from a`` came back
as ``from -- x`` / ``a``).  Instead we own placement: comments are
stripped before parsing and re-inserted into the formatted output,
anchored by token identity.

- A *trailing* comment (something else precedes it on its source line)
  re-attaches to the token that preceded it: ``--`` comments go to the
  end of that token's output line, ``/* */`` comments directly after
  the token.
- A *standalone* comment (alone on its source line) is emitted on its
  own line directly above the output line of the token that followed
  it, at that line's indentation.

Tokens are matched between input and output by (lowercased text, Nth
occurrence).  The formatter may add or drop tokens (explicit ``inner``,
redundant parens), so several neighboring tokens are kept as candidate
anchors; if none can be found the comment falls back to the start or
end of the statement — it is never lost.

All offsets from ``parser.scan`` are byte offsets, so the machinery
works on the UTF-8 encoding throughout.
"""

from dataclasses import dataclass

from pglast import parser

_COMMENT_TOKEN_NAMES = frozenset({'SQL_COMMENT', 'C_COMMENT'})
_N_ANCHOR_CANDIDATES = 3


@dataclass
class AnchoredComment:
    text: str
    is_line_comment: bool
    standalone: bool
    # (token_text, occurrence) candidates, nearest neighbor first.
    anchors: list[tuple[str, int]]


def _scan_tokens(data: bytes, sql: str) -> list[tuple[str, int, int, str]]:
    """(lowercased text, start, end, name) for every token."""
    return [
        (data[t.start:t.end + 1].decode('utf-8').lower(), t.start, t.end, t.name)
        for t in parser.scan(sql)
    ]


def _is_start_of_line(data: bytes, pos: int) -> bool:
    line_start = data.rfind(b'\n', 0, pos) + 1
    return not data[line_start:pos].strip()


def _occurrence_anchors(tokens: list[tuple[str, int, int, str]],
                        index: int, step: int) -> list[tuple[str, int]]:
    """Nearest non-comment neighbors of ``tokens[index]``, walking by
    ``step`` (-1 = preceding, +1 = following), as (text, occurrence)."""
    counts: dict[str, int] = {}
    occurrence_of: dict[int, int] = {}
    for i, (text, _, _, name) in enumerate(tokens):
        if name in _COMMENT_TOKEN_NAMES:
            continue
        occurrence_of[i] = counts.get(text, 0)
        counts[text] = occurrence_of[i] + 1
    anchors: list[tuple[str, int]] = []
    i = index + step
    while 0 <= i < len(tokens) and len(anchors) < _N_ANCHOR_CANDIDATES:
        if tokens[i][3] not in _COMMENT_TOKEN_NAMES:
            anchors.append((tokens[i][0], occurrence_of[i]))
        i += step
    return anchors


def extract_comments(sql: str) -> tuple[str, list[AnchoredComment]]:
    """Strip comments out of ``sql``; return the bare SQL and the
    anchored comments in source order."""
    data = sql.encode('utf-8')
    tokens = _scan_tokens(data, sql)
    comments: list[AnchoredComment] = []
    stripped = bytearray()
    prev_end = 0
    for i, (_, start, end, name) in enumerate(tokens):
        if name not in _COMMENT_TOKEN_NAMES:
            continue
        standalone = _is_start_of_line(data, start)
        anchors = (_occurrence_anchors(tokens, i, +1) if standalone
                   else _occurrence_anchors(tokens, i, -1))
        if not anchors:  # comment with no neighbor on its side
            anchors = (_occurrence_anchors(tokens, i, -1) if standalone
                       else _occurrence_anchors(tokens, i, +1))
        comments.append(AnchoredComment(
            text=data[start:end + 1].decode('utf-8'),
            is_line_comment=(name == 'SQL_COMMENT'),
            standalone=standalone,
            anchors=anchors,
        ))
        stripped += data[prev_end:start] + b' '
        prev_end = end + 1
    stripped += data[prev_end:]
    return stripped.decode('utf-8'), comments


def reinsert_comments(formatted: str, comments: list[AnchoredComment]) -> str:
    """Insert ``comments`` back into comment-free ``formatted`` SQL."""
    if not comments:
        return formatted
    data = formatted.encode('utf-8')
    positions: dict[str, list[tuple[int, int]]] = {}
    for text, start, end, name in _scan_tokens(data, formatted):
        positions.setdefault(text, []).append((start, end))

    insertions = [(*_placement(data, positions, comment), i)
                  for i, comment in enumerate(comments)]
    # Apply back-to-front; at equal positions the later comment goes in
    # first so the earlier one ends up before it, preserving source order.
    result = bytearray(data)
    for pos, chunk, _ in sorted(insertions, key=lambda ins: (ins[0], ins[2]),
                                reverse=True):
        result[pos:pos] = chunk
    return result.decode('utf-8')


def _find_anchor(positions: dict[str, list[tuple[int, int]]],
                 comment: AnchoredComment) -> tuple[int, int] | None:
    for text, occurrence in comment.anchors:
        spans = positions.get(text, [])
        if occurrence < len(spans):
            return spans[occurrence]
    return None


def _placement(data: bytes, positions: dict[str, list[tuple[int, int]]],
               comment: AnchoredComment) -> tuple[int, bytes]:
    encoded = comment.text.encode('utf-8')
    anchor = _find_anchor(positions, comment)
    if anchor is None:  # anchors vanished in formatting; never lose it
        if comment.standalone:
            return 0, encoded + b'\n'
        return len(data.rstrip()), b'  ' + encoded
    start, end = anchor
    if comment.standalone:
        line_start = data.rfind(b'\n', 0, start) + 1
        line_prefix = data[line_start:start]
        indent = line_prefix[:len(line_prefix) - len(line_prefix.lstrip())]
        return line_start, indent + encoded + b'\n'
    if comment.is_line_comment:
        eol = data.find(b'\n', end + 1)
        return (len(data) if eol < 0 else eol), b'  ' + encoded
    return end + 1, b' ' + encoded
