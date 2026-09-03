"""The ``pgfmt`` entry point.

Two modes:

- No arguments: stdin → stdout filter, safe for use as a Neovim
  ``formatprg``.  Only formatted SQL ever reaches stdout; any failure
  echoes the input back verbatim; the exit status is always 0, because
  Vim treats a non-zero exit from ``formatprg`` as an error.
- File arguments: each file is formatted in place, rewritten only when
  its contents change.  Directories are not walked — use find:
  ``find . -name '*.sql' -exec pgfmt {} +``.  Exits 1 if any file could
  not be read or written; unparseable SQL is not an error (it passes
  through verbatim, same as filter mode).
"""

import argparse
import sys
from pathlib import Path


def _safe_format(text: str) -> str:
    try:
        from .formatter import format_sql

        return format_sql(text)
    except Exception as exc:  # never a partial rewrite, whatever broke
        print(f'pgfmt: falling back to verbatim input: {exc}', file=sys.stderr)
        return text


def _format_stdin() -> int:
    sys.stdout.write(_safe_format(sys.stdin.read()))
    return 0


def _format_file_in_place(path: Path) -> bool:
    try:
        original = path.read_text(encoding='utf-8')
    except OSError as exc:
        print(f'pgfmt: {exc}', file=sys.stderr)
        return False
    formatted = _safe_format(original)
    if formatted == original:
        return True
    try:
        path.write_text(formatted, encoding='utf-8')
    except OSError as exc:
        print(f'pgfmt: {exc}', file=sys.stderr)
        return False
    print(f'pgfmt: reformatted {path}', file=sys.stderr)
    return True


def main() -> int:
    parser = argparse.ArgumentParser(
        prog='pgfmt',
        description='Canonical Postgres SQL formatter.',
        epilog="With no FILEs, formats stdin to stdout (formatprg mode). "
               "With FILEs, rewrites each in place. For directories, use "
               "find . -name '*.sql' -exec pgfmt {} +",
    )
    parser.add_argument('files', nargs='*', type=Path, metavar='FILE',
                        help='SQL files to format in place')
    args = parser.parse_args()
    if not args.files:
        return _format_stdin()
    results = [_format_file_in_place(path) for path in args.files]
    return 0 if all(results) else 1


if __name__ == '__main__':
    sys.exit(main())
