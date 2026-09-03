"""stdin → stdout entry point, safe for use as a Neovim ``formatprg``.

Non-negotiables (see the project handoff): only formatted SQL ever
reaches stdout; any failure echoes the input back verbatim; the exit
status is always 0, because Vim treats a non-zero exit from
``formatprg`` as an error.
"""

import sys


def main() -> int:
    text = sys.stdin.read()
    try:
        from .formatter import format_sql

        output = format_sql(text)
    except Exception as exc:  # never a partial rewrite, whatever broke
        print(f'pgfmt: falling back to verbatim input: {exc}', file=sys.stderr)
        output = text
    sys.stdout.write(output)
    return 0


if __name__ == '__main__':
    sys.exit(main())
