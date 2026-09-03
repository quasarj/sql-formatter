from sql_formatter.placeholders import normalize, restore


def test_dbi_question_mark_is_substituted() -> None:
    text, subs = normalize('select * from t where id = ?')
    assert text == 'select * from t where id = $1'
    assert subs == {1: '?'}


def test_psycopg2_percent_s_is_substituted() -> None:
    text, subs = normalize('select * from t where id = %s and n = %s')
    assert text == 'select * from t where id = $1 and n = $2'
    assert subs == {1: '%s', 2: '%s'}


def test_native_parameters_are_left_alone() -> None:
    text, subs = normalize('select * from t where id = $1')
    assert text == 'select * from t where id = $1'
    assert subs == {}


def test_synthetic_numbers_start_above_existing() -> None:
    text, subs = normalize('select * from t where id = $3 and n = ?')
    assert text == 'select * from t where id = $3 and n = $4'
    assert subs == {4: '?'}


def test_jsonb_operators_are_not_placeholders() -> None:
    sql = "select * from t where data ? 'key' and tags ?| array['a'] and x ?& y"
    text, subs = normalize(sql)
    assert text == sql
    assert subs == {}


def test_question_mark_in_string_is_opaque() -> None:
    sql = "select 'what?' from t where id = ?"
    text, subs = normalize(sql)
    assert text == "select 'what?' from t where id = $1"


def test_percent_s_in_string_is_opaque() -> None:
    sql = "select 'fmt %s' from t where id = %s"
    text, subs = normalize(sql)
    assert text == "select 'fmt %s' from t where id = $1"


def test_placeholders_in_comments_are_opaque() -> None:
    sql = 'select 1 -- what about ? or %s\nfrom t'
    text, subs = normalize(sql)
    assert text == sql
    assert subs == {}


def test_dollar_quoted_bodies_are_opaque() -> None:
    sql = 'create function f() returns int as $$ select ?; $$ language sql'
    text, subs = normalize(sql)
    assert text == sql


def test_restore_round_trips() -> None:
    sql = "select * from t where id = ? and data ? 'k' and n = %s and p = $1"
    text, subs = normalize(sql)
    assert restore(text, subs) == sql
