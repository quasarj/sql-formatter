from sql_formatter import format_sql


def test_canonical_subquery_layout_from_handoff() -> None:
    sql = ('select * from t where activity_timepoint_id = '
           '(select max(activity_timepoint_id) from activity_timepoint '
           'where activity_id = activity_id)')
    assert format_sql(sql) == (
        'select *\n'
        'from t\n'
        'where activity_timepoint_id = (\n'
        '    select max(activity_timepoint_id)\n'
        '    from activity_timepoint\n'
        '    where activity_id = activity_id\n'
        ')\n'
    )


def test_input_independence() -> None:
    """Differently laid-out copies of one statement format identically."""
    variants = [
        'select a,b from t where x=1 and y=2',
        'SELECT a, b\n  FROM t\n WHERE x = 1\n   AND y = 2',
        'select\na\n,b\nfrom\nt\nwhere\nx\n=\n1\nand y = 2',
    ]
    outputs = {format_sql(v) for v in variants}
    assert len(outputs) == 1


def test_idempotence() -> None:
    sql = ('select a, b, count(*) as n from ta natural left join tb '
           'where a between 1 and 10 and b = 2 group by a, b order by n')
    once = format_sql(sql)
    assert format_sql(once) == once


def test_unparseable_input_is_echoed_verbatim() -> None:
    bad = 'select from from where nothing makes sense ((('
    assert format_sql(bad) == bad + '\n'


def test_unparseable_statement_does_not_poison_the_buffer() -> None:
    text = 'select 1;\nthis is not sql;\nselect 2'
    out = format_sql(text)
    assert 'select 1;' in out
    assert 'this is not sql;' in out
    assert 'select 2' in out


def test_from_always_on_its_own_line() -> None:
    assert format_sql('select a from t') == 'select a\nfrom t\n'


def test_single_table_stays_on_from_line() -> None:
    assert 'from tablea\n' in format_sql('select x from tablea')


def test_each_join_on_its_own_line_indented() -> None:
    out = format_sql('select a from t1 join t2 on t1.id = t2.t1_id '
                     'left join t3 on t3.x = t2.x')
    assert out == (
        'select a\n'
        'from t1\n'
        '    inner join t2 on t1.id = t2.t1_id\n'
        '    left join t3 on t3.x = t2.x\n'
    )


def test_natural_join_never_splits() -> None:
    out = format_sql('select * from ta natural left join tb natural join tc')
    assert '    natural left join tb\n' in out
    assert '    natural join tc\n' in out


def test_long_on_condition_breaks_to_nested_line() -> None:
    out = format_sql(
        'select a from long_table_name_one join long_table_name_two on '
        'long_table_name_one.some_long_column = long_table_name_two.some_long_column '
        'and long_table_name_one.other_col = long_table_name_two.other_col')
    assert ('    inner join long_table_name_two\n'
            '        on ') in out


def test_single_condition_where_stays_on_where_line() -> None:
    assert 'where x = 1\n' in format_sql('select a from t where x = 1')


def test_compound_where_one_condition_per_line() -> None:
    out = format_sql('select a from t where x = 1 and y = 2 and z = 3')
    assert out == (
        'select a\n'
        'from t\n'
        'where x = 1\n'
        '    and y = 2\n'
        '    and z = 3\n'
    )


def test_mixed_and_or_flattens_without_parens() -> None:
    """and binds tighter than or, so query-level and/or chains break
    one per line without parenthesizing (the sqruff-era style)."""
    out = format_sql('select a from t where x = 1 and y = 2 or z = 3')
    assert out == (
        'select a\n'
        'from t\n'
        'where x = 1\n'
        '    and y = 2\n'
        '    or z = 3\n'
    )


def test_or_nested_in_and_keeps_parens_inline() -> None:
    out = format_sql('select a from t where x = 1 and (y = 2 or z = 3)')
    assert 'where x = 1\n' in out
    assert '    and (y = 2 or z = 3)\n' in out


def test_between_does_not_break_at_its_and() -> None:
    out = format_sql('select a from t where x between 1 and 10 and y = 2')
    assert 'where x between 1 and 10\n' in out
    assert '    and y = 2\n' in out


def test_between_placeholders_do_not_break_at_and() -> None:
    out = format_sql('select a from t where created between ? and ? and y = %s')
    assert 'where created between ? and ?\n' in out
    assert '    and y = %s\n' in out


def test_keywords_and_types_are_lowercase() -> None:
    out = format_sql('SELECT CAST(X AS INTEGER) FROM T WHERE Y IS NOT NULL')
    assert out == ('select cast(x as integer)\n'
                   'from t\n'
                   'where y is not null\n')


def test_from_inside_function_calls() -> None:
    out = format_sql("select extract(month from d), substring(s from 1 for 3) from t")
    assert 'extract(month from d)' in out
    assert 'substring(s from 1 for 3)' in out


def test_dollar_quoted_body_passes_through_untouched() -> None:
    body = '\nbegin\n    IF a > 0 THEN return a; end if;\nend;\n'
    sql = f'create function f(a int) returns int language plpgsql as $${body}$$'
    assert f'$${body}$$' in format_sql(sql)


def test_string_literal_with_keywords_and_escaping() -> None:
    out = format_sql("select 'SELECT '' FROM x' from t")
    assert "'SELECT '' FROM x'" in out


def test_quoted_identifiers_survive() -> None:
    out = format_sql('select "Weird Name" from "MyTable"')
    assert '"Weird Name"' in out
    assert '"MyTable"' in out


def test_multiple_statements_separated() -> None:
    out = format_sql('select 1; select 2;')
    assert out == 'select 1;\n\nselect 2;\n'


def test_no_semicolon_added_when_input_has_none() -> None:
    assert format_sql('select 1') == 'select 1\n'


def test_placeholders_round_trip_through_formatting() -> None:
    out = format_sql('select * from t where id = ? and n = %s and p = $1')
    assert out == ('select *\n'
                   'from t\n'
                   'where id = ?\n'
                   '    and n = %s\n'
                   '    and p = $1\n')


def test_jsonb_operators_survive_formatting() -> None:
    out = format_sql("select * from t where data ? 'key' and tags ?| array['a', 'b']")
    assert "data ? 'key'" in out
    assert "tags ?| array['a', 'b']" in out


def test_standalone_comment_is_preserved() -> None:
    out = format_sql('-- pick the latest\nselect max(id) from t')
    assert '-- pick the latest' in out
    assert 'select max(id)' in out


def test_block_comment_is_preserved() -> None:
    out = format_sql('/* header */ select 1')
    assert '/* header */' in out


def test_long_select_list_breaks_one_item_per_line() -> None:
    out = format_sql(
        'select verylongcolumnnameone, verylongcolumnnametwo, '
        'verylongcolumnnamethree, verylongcolumnnamefour from t')
    assert out == (
        'select\n'
        '    verylongcolumnnameone,\n'
        '    verylongcolumnnametwo,\n'
        '    verylongcolumnnamethree,\n'
        '    verylongcolumnnamefour\n'
        'from t\n'
    )


def test_cte_gets_block_layout() -> None:
    out = format_sql('with recent as (select id from events where ts > now()) '
                     'select * from recent')
    assert out == (
        'with recent as (\n'
        '    select id\n'
        '    from events\n'
        '    where ts > now()\n'
        ')\n'
        'select *\n'
        'from recent\n'
    )


def test_subquery_in_from_gets_block_layout() -> None:
    out = format_sql('select * from (select a from t) as sub')
    assert out == (
        'select *\n'
        'from (\n'
        '    select a\n'
        '    from t\n'
        ') as sub\n'
    )


def test_in_subquery_gets_block_layout() -> None:
    out = format_sql('select a from t where id in (select id from other)')
    assert out == (
        'select a\n'
        'from t\n'
        'where id in (\n'
        '    select id\n'
        '    from other\n'
        ')\n'
    )


def test_union_chain_stays_flat() -> None:
    out = format_sql('select 1 union select 2 union all select 3')
    assert out == 'select 1\nunion\nselect 2\nunion all\nselect 3\n'


def test_trailing_comment_after_final_semicolon() -> None:
    assert format_sql('select 1; -- done') == 'select 1;  -- done\n'


def test_standalone_comment_between_statements() -> None:
    out = format_sql('select 1;\n\n-- section two\nselect 2')
    assert out == 'select 1;\n\n-- section two\nselect 2\n'


def test_long_or_group_wraps_at_80() -> None:
    out = format_sql(
        "select a from t where status = 'ok' and (category = 'first_category' "
        "or category = 'second_category' or category = 'third_category' "
        "or category = 'fourth_category')")
    assert all(len(line) <= 80 for line in out.splitlines())
    assert "    and (category = 'first_category'\n" in out
    assert "        or category = 'second_category'\n" in out


def test_long_on_condition_wraps_at_its_ands() -> None:
    out = format_sql(
        'select a.x from first_long_table as a join second_long_table as b on '
        'a.first_key_column = b.first_key_column '
        'and a.second_key_column = b.second_key_column')
    assert all(len(line) <= 80 for line in out.splitlines())
    assert '        on a.first_key_column = b.first_key_column\n' in out
    assert '            and a.second_key_column = b.second_key_column\n' in out


def test_short_case_stays_inline() -> None:
    out = format_sql("select case when a = 1 then 'one' else 'other' end from t")
    assert "select case when a = 1 then 'one' else 'other' end\n" in out


def test_long_case_gets_block_layout() -> None:
    out = format_sql(
        "select case when account_status = 'active' then 'engaged' "
        "when account_status = 'dormant' then 'dormant_label_here' "
        "else 'inactive' end as engagement from accounts")
    assert all(len(line) <= 80 for line in out.splitlines())
    assert '    case\n' in out
    assert "        when account_status = 'active' then 'engaged'\n" in out
    assert "        else 'inactive'\n" in out
    assert '    end as engagement\n' in out


def test_function_call_wraps_when_item_overflows() -> None:
    """The call alone fits, but the `as alias` suffix pushes the line
    over 80, so the parens break block-style."""
    out = format_sql(
        "select date_trunc('day', min(coalesce(file_import_time, import_time))) "
        "as earliest_import_day from dicom_file")
    assert out == (
        'select\n'
        '    date_trunc(\n'
        "        'day', min(coalesce(file_import_time, import_time))\n"
        '    ) as earliest_import_day\n'
        'from dicom_file\n'
    )


def test_wrapped_call_with_long_args_breaks_one_per_line() -> None:
    out = format_sql(
        'select coalesce(first_extremely_long_column_name, '
        'second_extremely_long_column_name, third_extremely_long_column_name, '
        "'the_default_fallback_value') as resolved_contact from t")
    assert all(len(line) <= 80 for line in out.splitlines())
    assert '    coalesce(\n' in out
    assert '        first_extremely_long_column_name,\n' in out
    assert '    ) as resolved_contact\n' in out


def test_trivial_args_never_wrap() -> None:
    """Wrapping count(*) can't shorten anything; the filter clause is
    what wraps instead."""
    out = format_sql(
        "select count(*) filter (where import_status = 'complete' "
        "and file_type = 'dicom') as completed_dicom_file_count_for_reporting "
        'from dicom_file')
    assert all(len(line) <= 80 for line in out.splitlines())
    assert '    count(*) filter (\n' in out
    assert '    ) as completed_dicom_file_count_for_reporting\n' in out


def test_short_calls_stay_inline() -> None:
    out = format_sql("select count(*) filter (where x > 0) as n, "
                     'coalesce(a, b) as c from t')
    assert out == 'select count(*) filter (where x > 0) as n, coalesce(a, b) as c\nfrom t\n'


def test_concat_chain_breaks_greedily_at_operator() -> None:
    out = format_sql(
        "select first_name_part || ' ' || middle_name_part || ' ' || "
        "last_name_part || ' (' || suffix_part || ')' as full_display_name "
        'from people')
    assert all(len(line) <= 80 for line in out.splitlines())
    assert ("    first_name_part || ' ' || middle_name_part || ' ' || "
            "last_name_part || ' ('\n") in out
    assert "        || suffix_part || ')' as full_display_name\n" in out


def test_concat_chain_in_comparison_reserves_the_suffix() -> None:
    out = format_sql(
        "select a from t where root_path || '/' || file_location.rel_path "
        "|| '/' || file_basename_column = full_path_parameter_value")
    assert all(len(line) <= 80 for line in out.splitlines())
    assert '    || file_basename_column) = full_path_parameter_value\n' in out


def test_short_concat_chain_stays_inline() -> None:
    out = format_sql("select root_path || '/' || rel_path as path from t")
    assert "select root_path || '/' || rel_path as path\n" in out


def test_parenthesized_concat_group_keeps_its_parens() -> None:
    out = format_sql('select a || (b || c) as grouped from t')
    assert 'a || (b || c)' in out


def test_empty_input_is_returned_unchanged() -> None:
    assert format_sql('') == ''
    assert format_sql('   \n') == '   \n'
