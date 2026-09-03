# Postgres SQL formatter — project handoff

## Goal

Build a Postgres SQL formatter that produces canonical output: the same
statement always formats identically regardless of how it was laid out
in the source. Primary use is as a Neovim `formatprg` (stdin → stdout).

## Why we're here

Evaluated existing tools. `pg_format`/pgFormatter was the previous best
but not configurable enough. Spent significant effort tuning **sqruff**
(Rust, sqlfluff-compatible rule engine, v0.40.0) and got close, but hit
a structural wall.

sqruff is a lint-and-fix tool, not a re-printer. Its defining property:
**it never removes a line break you gave it.** In its reflow engine
`single` spacing means "one space *or* a newline"; only the `:inline`
suffix forbids a newline. Consequences:

- Output depends on input layout. Worked around by writing a
  pre-processor that flattens the statement to one line and re-inserts
  breaks deterministically before feeding sqruff.
- **Forced collapse** is configurable (`spacing_within = single:inline`
  on a segment type).
- **Forced expansion** is not. `line_position = alone:strict` is parsed
  but the `strict` flag is only read in `reflow/rebreak.rs`, which runs
  for LT03/LT04/LT11/LT14 only. Clause line positions are handled in
  `reindent.rs`, where `strict` never appears — so `alone` on a clause
  is only a break-priority hint for over-length lines.
- **Indentation is not reachable at all.** Final blocker: with
  `allow_implicit_indents = False`, a WHERE clause containing a
  multi-line bracket indents differently depending on whether another
  clause follows it. `where x = (subq)` keeps the bracket at column 0;
  `where x = (subq) group by 1` shifts everything one level right.
  This is the untaken-indent optimization in `reindent.rs`. No config
  reaches it (swept all 9 `line_position` × `keyword_line_position`
  combinations). The pre-processor can't help because sqruff re-indents
  everything it receives.

Indentation should be a function of parse-tree depth. That requires a
real tree.

## Recommended approach

**pglast** — Python bindings over `libpg_query` (the actual PostgreSQL
grammar). Ships a `pgpp` CLI as a working baseline. Per-node printer
functions live in `pglast.printers`; serialization in `pglast.stream`.
Subclass the printers for constructs where our taste diverges and
inherit correct behavior for everything else.

Depesz took the same route in Perl for explain.depesz.com, falling back
to pgFormatter for constructs his code doesn't yet handle — a good
pattern to copy.

### Validate these two first, before building anything

1. **Comment preservation.** pglast's preserve-comments support has
   been described as rudimentary. Our SQL is commented. If comments
   can't be attached to nodes and re-emitted, the whole approach fails.
   Test this on day one.
2. **PL/pgSQL.** `libpg_query` parses plpgsql but has **no deparser**
   for it. Function bodies will need a different path — likely keep
   pgFormatter in the toolchain for those, or leave `$$ ... $$` bodies
   untouched.

## Formatting requirements (settled during sqruff tuning)

Style:
- Keywords and type names lowercase.
- 4-space indent, 80-column target.
- Trailing commas, no space before the comma.
- No forced final semicolon; no newline before a trailing semicolon.

Layout:
- `FROM` always starts a new line, even when the whole query would fit
  on one.
- A single-table FROM stays on the `from` line: `from tablea`.
- Multiple tables: first on the `from` line, wrap only under length
  pressure.
- Each JOIN on its own line, indented one level under FROM. Natural
  joins are used heavily — `natural left join x` must never split
  between its keywords.
- Long `ON` conditions break onto their own line at a nested indent.
- A single-condition WHERE stays on the `where` line.
- Compound WHERE: one condition per line. `BETWEEN x AND y` is a single
  condition and must not break at its `AND`.
- Subquery body indents exactly one level from the clause that opens
  it; closing paren returns to the opening clause's level:

  ```sql
  where activity_timepoint_id = (
      select max(activity_timepoint_id)
      from activity_timepoint
      where activity_id = activity_id
  )
  ```

Semantics we *want* kept (sqruff rules we deliberately enabled):
- Drop unused table aliases (sqruff AL05).
- Normalize join condition operand order to put the earlier table first
  (sqruff ST09).
- Insert explicit `AS` for table aliases.

## Edge cases the new tool must handle

These were all found the hard way; they make a good initial test corpus.

- **Placeholders.** SQL is embedded in Perl (DBI `?`), Python asyncpg
  (`$1`), and psycopg2 (`%s`). `$1` is native Postgres and parses fine.
  `?` and `%s` are not valid SQL and must be substituted before parsing
  and restored after. Suggested: rewrite `?`/`%s` to `$n` pre-parse,
  map back post-print.
- **jsonb operators `?`, `?|`, `?&`** collide with DBI placeholders
  textually. With a real parser this mostly resolves itself — the
  grammar knows the difference — but the placeholder substitution step
  above must not eat them. Heuristic used previously: a placeholder `?`
  is not followed by `\s*'`.
- **`FROM` inside function calls**: `extract(month from d)`,
  `substring(s from 1 for 3)`. A parse tree handles these for free;
  noted because the regex-era tooling did not.
- **Dollar-quoted bodies** (`$$ ... $$`, `$tag$ ... $tag$`) must pass
  through untouched.
- **Comments**: `--` line comments and `/* */` block comments, both
  standalone and trailing.
- **String literals** containing SQL keywords, with `''` escaping.
- **Quoted identifiers.**
- Multiple statements in one buffer, separated by `;`.

## Non-negotiable behaviors

- Idempotent: formatting formatted output is a no-op.
- Input-independent: three differently-laid-out copies of the same
  statement produce byte-identical output.
- Reads stdin, writes only formatted SQL to stdout, nothing on stdout
  but the SQL.
- Exits 0 on success. Vim reports non-zero exit as an error from
  `formatprg`.
- On a statement it cannot parse, echo the input back **verbatim**
  rather than emitting a partial rewrite. This is the safety property
  that made sqruff usable and it must be preserved.

## Prior artifacts

Two files from the sqruff phase, both worth keeping as reference:

- `.sqruff` — the tuned config (below). Its layout sections document
  which decisions we made and why.
- `sql-clause-breaks.pl` — the flatten-and-rebreak pre-processor. Its
  scanner (paren-context classification to distinguish a subquery from
  a function argument list, BETWEEN tracking, opaque-region handling
  for literals/comments/dollar-quotes) is a compact catalogue of the
  edge cases above. Obsolete once a real parser is in place, but its
  test cases carry over.

```ini
[sqruff]
dialect = postgres
rules = all
exclude_rules = AM04, ST06
max_line_length = 80
templater = placeholder

[sqruff:indentation]
indent_unit = space
tab_space_size = 4
indented_joins = True
indented_ctes = True
allow_implicit_indents = False
trailing_comments = before

[sqruff:layout:type:comma]
line_position = trailing
spacing_before = touch

[sqruff:rules:capitalisation.keywords]
capitalisation_policy = lower

[sqruff:rules:capitalisation.types]
extended_capitalisation_policy = lower

[sqruff:rules:convention.terminator]
require_final_semicolon = False
multiline_newline = False

[sqruff:templater:placeholder]
param_regex = (?<![:\w\\])\?(?![|&])(?!\s*')|(?<![:\w\\])%s

[sqruff:layout:type:from_clause]
line_position = alone
spacing_within = single:inline
```

## Suggested first steps

1. `pip install pglast`; run `pgpp` over a representative corpus of our
   real queries and diff against the sqruff output. See how far the
   stock printers already get.
2. Test comment round-tripping. Decide go/no-go on pglast.
3. Build the placeholder normalize/restore wrapper.
4. Subclass printers for the FROM/JOIN/WHERE layout rules above.
5. Wire up `formatprg` with the verbatim-passthrough-on-parse-failure
   guarantee.
