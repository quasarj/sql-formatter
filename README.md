# sql-formatter

A canonical Postgres SQL formatter built on
[pglast](https://github.com/lelit/pglast) (Python bindings over
`libpg_query`, the actual PostgreSQL grammar). The same statement always
formats identically regardless of how it was laid out in the source —
indentation is a function of parse-tree depth, which is the property no
lint-and-fix tool (sqruff, sqlfluff) could deliver. Background in
`sql-formatter-handoff.md`.

## Usage

```sh
uv run pgfmt < query.sql        # stdin → stdout
uv run pgfmt query.sql other.sql   # format files in place
find . -name '*.sql' -exec pgfmt {} +   # whole tree, via find
```

In-place mode rewrites a file only when formatting changes it, reports
`reformatted <file>` on stderr, and exits 1 only when a file cannot be
read or written — unparseable SQL passes through verbatim, as in
filter mode.

As a Neovim `formatprg`:

```vim
" after `uv tool install .` (or point at .venv/bin/pgfmt)
setlocal formatprg=pgfmt
```

Guarantees relied on by `formatprg`:

- only formatted SQL is written to stdout;
- exit status is always 0;
- a statement that cannot be parsed is echoed back **verbatim** — never
  a partial rewrite. Other statements in the same buffer still format.

## Behavior

- Keywords and type names lowercase; 4-space indents; 80-column target;
  trailing commas; no forced final semicolon (an existing one is kept).
- `from` always on its own line; a single table stays on the `from`
  line; each join on its own line one level under `from`; `natural left
  join x` never splits; long `on` conditions break to a nested line.
- Single-condition `where` stays on the `where` line; compound `where`
  breaks one condition per line with leading `and`/`or` (`between x and
  y` never breaks at its `and`).
- Subquery and CTE bodies indent exactly one level from the clause that
  opens them; the closing paren returns to the opening clause's level.
- DBI `?` and psycopg2 `%s` placeholders are rewritten to `$n` before
  parsing and restored afterwards; jsonb `?`/`?|`/`?&` operators are
  left alone (a `?` followed by a string literal is an operator).
- `$$ ... $$` / `$tag$ ... $tag$` bodies pass through untouched
  (`libpg_query` has no PL/pgSQL deparser, so function bodies are
  deliberately not reformatted).

## Architecture

```
src/sql_formatter/
  cli.py           stdin → stdout, exit 0, whole-buffer verbatim fallback
  formatter.py     statement splitting, per-statement parse/print/fallback
  placeholders.py  ? and %s → $n and back (opaque-region scanner)
  stream.py        FourSpaceStream: level-based indents instead of
                   pglast's column-aligned ones; lists break by
                   measured 80-column fit
  comments.py      comment extraction/re-insertion anchored by token
                   occurrence, so trailing comments stay with the token
                   they followed (pglast's own comment support attaches
                   them to the next node instead)
  printers.py      overrides of pglast's stock printers for the house
                   layout rules (SELECT clauses, joins, bool exprs,
                   subqueries, CTEs, set operations)
  lowercase.py     keyword lowercasing by re-scanning formatted output
                   with the real lexer (pglast hard-codes uppercase)
```

`tests/test_invariants.py` enforces the two non-negotiables across a
corpus: idempotence, and that output parses to a byte-identical AST.

## Known limitations

- **Comment anchoring is by token occurrence.** Comments are never
  lost, but when the formatter adds or removes tokens near a comment's
  anchor (explicit `inner`, dropped redundant parens) the comment can
  land one token off; a comment whose anchors all vanish falls back to
  the start or end of its statement.
- Lines exceed 80 columns only when a single unbreakable expression is
  itself too long (e.g. one very long comparison); lists, boolean
  chains, `on` conditions, `case` arms, function-call parens, and
  `||` chains (greedy fill, breaking before the operator) all wrap.
- Semantic normalizations the sqruff config performed (dropping unused
  aliases, reordering join operands, inserting explicit `AS`) are not
  implemented; pglast reprints the tree it parsed. Postgres itself
  normalizes a bare `join` to `inner join` and `full outer join` to
  `full join` in our printers' output.
- `pglast` is pinned loosely (`>=8.4`); printer overrides copy stock
  printer bodies, so a major pglast upgrade needs a diff against
  `pglast/printers/dml.py`.
