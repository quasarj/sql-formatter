"""The non-negotiables, checked across a varied corpus:

- idempotence: formatting formatted output is a no-op;
- fidelity: the output parses to exactly the same AST as the input.
"""

import pytest
from pglast import parse_sql

from sql_formatter import format_sql

CORPUS = [
    "update t set a = 1, b = 2 where id = 5 and status = 'open'",
    "delete from t where x in (select x from old) and y < now()",
    "insert into t (a, b) values (1, 'x'), (2, 'y')",
    "insert into t select a, b from s where a > 0",
    "select 1 union select 2 union all select 3 order by 1",
    "select distinct on (a) a, b from t order by a, b desc",
    "select case when a > 1 then 'big' when a = 1 then 'one' else 'small' end from t",
    "select count(*) filter (where x > 0) over (partition by g order by ts) from t",
    "with a as (select 1 as x), b as (select x + 1 as y from a) select * from a, b",
    "select coalesce(a, b, 0), nullif(x, ''), greatest(1, 2) from t",
    "select array_agg(x order by y), string_agg(n, ', ') from t group by g",
    "select * from generate_series(1, 10) as g(n)",
    "select (select count(*) from u where u.tid = t.id) as cnt from t",
    "select a::text, cast(b as numeric(10, 2)) from t",
    "select * from t where ts >= current_date - interval '7 days'",
    "select jsonb_build_object('a', 1) -> 'a', data #>> '{x,y}' from t",
    "select * from t1 full outer join t2 using (id) right join t3 on t3.a = t2.b",
    "select * from t where exists (select 1 from u where u.tid = t.id)",
    "select * from t where x = any(array[1, 2, 3]) and y is distinct from z",
    "select * from t order by a nulls last, b desc nulls first limit 10 offset 20",
    "select grouping(a), a, sum(b) from t group by rollup (a)",
    "values (1, 'a'), (2, 'b')",
    "select 'it''s' || \"Weird\" || $tag$ raw $ stuff $tag$ from \"T\"",
    "-- leading\nselect a /* mid */ from t -- trail\nwhere b = 1",
    ("select * from a join b on a.id = b.aid join c on c.bid = b.id "
     "join d on d.cid = c.id where a.x = 1 and b.y = 2 order by a.id"),
    "select 1 union (select 2 union all select 3)",
    "(select 1 order by 1) union select 2",
]


@pytest.mark.parametrize('sql', CORPUS)
def test_idempotent(sql: str) -> None:
    once = format_sql(sql)
    assert format_sql(once) == once


@pytest.mark.parametrize('sql', CORPUS)
def test_ast_is_unchanged(sql: str) -> None:
    assert parse_sql(format_sql(sql)) == parse_sql(sql)
