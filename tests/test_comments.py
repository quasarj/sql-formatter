"""Comment attachment: trailing comments stay with the token they
followed; standalone comments stay on their own line above what they
preceded.  (pglast's own comment support attaches everything to the
*next* node, which made trailing comments jump forward one token.)"""

from sql_formatter import format_sql


def test_trailing_comment_stays_on_its_line() -> None:
    out = format_sql('select * -- things\nfrom a')
    assert out == 'select *  -- things\nfrom a\n'


def test_trailing_comment_on_where_condition() -> None:
    out = format_sql('select * from t\nwhere x = 1 -- boundary\n  and y = 2')
    assert out == ('select *\n'
                   'from t\n'
                   'where x = 1  -- boundary\n'
                   '    and y = 2\n')


def test_leading_comment_stays_first() -> None:
    out = format_sql('-- pick the latest\nselect max(id) from t')
    assert out == '-- pick the latest\nselect max(id)\nfrom t\n'


def test_standalone_comment_between_clauses_keeps_its_own_line() -> None:
    out = format_sql('select a\n-- filters below\nfrom t where x = 1')
    assert out == ('select a\n'
                   '-- filters below\n'
                   'from t\n'
                   'where x = 1\n')


def test_standalone_comment_indented_with_its_line() -> None:
    out = format_sql('select a from t where x = 1\n'
                     '-- second filter\n'
                     'and y = 2')
    assert out == ('select a\n'
                   'from t\n'
                   'where x = 1\n'
                   '    -- second filter\n'
                   '    and y = 2\n')


def test_inline_block_comment_follows_its_token() -> None:
    out = format_sql('select a /* the key */ , b from t')
    assert 'a /* the key */' in out


def test_two_trailing_comments_keep_source_order() -> None:
    out = format_sql('select a, -- first\n b -- second\nfrom t')
    assert out.index('-- first') < out.index('-- second')


def test_comments_are_stable_under_reformatting() -> None:
    src = ('-- lead\nselect a, -- first\n b /* mid */\n'
           '-- standalone\nfrom t -- trail\nwhere x = 1')
    once = format_sql(src)
    assert format_sql(once) == once
    for marker in ('-- lead', '-- first', '/* mid */', '-- standalone', '-- trail'):
        assert marker in once


def test_comment_survives_when_anchor_token_disappears() -> None:
    # The formatter drops the redundant parens the comment trailed.
    out = format_sql('select a from t where (x = 1) -- kept\n and y = 2')
    assert '-- kept' in out
