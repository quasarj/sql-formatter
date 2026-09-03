"""Lowercase SQL keywords in already-formatted output.

pglast's printers hard-code uppercase keywords; there is no
serialization option for case.  Rather than overriding every printer,
re-scan the formatted output with the real lexer and lowercase exactly
the spans it reports as keyword tokens.  String literals, quoted
identifiers, comments and dollar-quoted bodies are separate token kinds
and are never touched.

The scanner reports byte offsets, so the transformation works on the
UTF-8 encoding; keywords are pure ASCII, making the byte-level
``lower()`` safe.
"""

from pglast import parser

_KEYWORD_KINDS = frozenset({
    'RESERVED_KEYWORD',
    'UNRESERVED_KEYWORD',
    'TYPE_FUNC_NAME_KEYWORD',
    'COL_NAME_KEYWORD',
})


def lowercase_keywords(sql: str) -> str:
    """Return ``sql`` with every keyword token lowercased."""
    data = bytearray(sql.encode('utf-8'))
    for token in parser.scan(sql):
        if token.kind in _KEYWORD_KINDS:
            span = data[token.start:token.end + 1]
            if not span.startswith(b'"'):
                data[token.start:token.end + 1] = span.lower()
    return data.decode('utf-8')
