"""Printer overrides implementing the house layout rules.

These replace pglast's stock printers (via ``override=True``) for the
constructs where our taste diverges; everything else inherits stock
behavior.  The rules, from the project handoff:

- ``FROM`` always starts a new line; a single table stays on it.
- Each JOIN on its own line, one level under FROM; ``natural left
  join x`` never splits between its keywords (guaranteed here because
  the keywords are emitted with plain writes — no break opportunity).
- Long ``ON`` conditions break onto their own line at a nested indent.
- Compound WHERE/HAVING: first condition on the clause line, the rest
  one per line at one level, with a leading ``and``/``or``.
- Subquery bodies indent exactly one level from the clause that opens
  them; the closing paren returns to the opening clause's level.
- CTE bodies get the same block-paren treatment.

Every printer must also work when invoked from a measuring
:class:`~pglast.stream.RawStream` clone (where ``newline``/``indent``
are no-ops), so block layout is gated on the stream type.
"""

from pglast import ast, enums
from pglast.printers import node_printer
from pglast.printers.dml import (
    COL_NAME_KEYWORDS,
    _bool_expr_needs_to_be_wrapped_in_parens,
    _select_needs_to_be_wrapped_in_parens,
    cte_materialize_printer,
    get_string_value,
)

from .stream import INDENT_STEP, FourSpaceStream


def _is_block_stream(output) -> bool:
    return isinstance(output, FourSpaceStream)


def _print_block_parens(output, print_body) -> None:
    """Emit ``(``, the body one level deeper, ``)`` back at this level."""
    output.write('(')
    with output.push_indent(INDENT_STEP, relative=False):
        output.newline()
        print_body()
    output.newline()
    output.write(')')


def _print_clause_list(output, nodes) -> None:
    """A clause's item list: inline when it fits, else one per line."""
    if _is_block_stream(output):
        rendered = output.concat(nodes, ', ')
        if not output.fits_on_current_line(rendered):
            output.print_list(nodes, standalone_items=True)
            return
    output.print_list(nodes, standalone_items=False)


def _print_target_list(output, nodes) -> None:
    """SELECT's target list: on the keyword line when it fits, else
    every item on its own line one level in."""
    if _is_block_stream(output):
        rendered = output.concat(nodes, ', ')
        if not output.fits_on_current_line(' ' + rendered):
            with output.push_indent(INDENT_STEP, relative=False):
                output.newline()
                output.print_list(nodes, standalone_items=True)
            return
    output.write(' ')
    output.print_list(nodes, standalone_items=False)


def _print_from_clause(output, items) -> None:
    output.write('FROM ')
    if not _is_block_stream(output):
        output.print_list(items)
        return
    if len(items) == 1:
        item = items[0]
        if isinstance(item, ast.JoinExpr):
            # Establish the one-level indent the join lines hang at.
            with output.push_indent(INDENT_STEP, relative=False):
                output.print_node(item)
        else:
            output.print_node(item)
        return
    has_join = any(isinstance(item, ast.JoinExpr) for item in items)
    rendered = output.concat(items, ', ')
    if has_join or not output.fits_on_current_line(rendered):
        with output.push_indent(INDENT_STEP, relative=False):
            output.print_list(items, standalone_items=True)
    else:
        output.print_list(items, standalone_items=False)


def _left_setop_needs_parens(node) -> bool:
    return bool(node.sortClause or node.limitCount or node.limitOffset
                or node.lockingClause or node.withClause)


@node_printer(ast.SelectStmt, override=True)
def select_stmt(node, output):
    with output.push_indent():
        if node.withClause:
            output.write('WITH ')
            output.print_node(node.withClause)
            output.newline()

        so = enums.SetOperation

        if node.valuesLists:
            with output.expression(isinstance(node.ancestors[0], ast.RangeSubselect)):
                output.write('VALUES ')
                output.print_lists(node.valuesLists)
        elif node.op != so.SETOP_NONE and (node.larg or node.rarg):
            with output.push_indent():
                if node.larg:
                    # Set operations parse left-associative, so a plain
                    # nested set-op on the left re-parses identically
                    # without parens; only an attached ORDER BY/LIMIT/
                    # WITH forces them.  Keeps union chains flat.
                    with output.expression(_left_setop_needs_parens(node.larg)):
                        output.print_node(node.larg)
                output.newline()
                if node.op == so.SETOP_UNION:
                    output.write('UNION')
                elif node.op == so.SETOP_INTERSECT:
                    output.write('INTERSECT')
                elif node.op == so.SETOP_EXCEPT:
                    output.write('EXCEPT')
                if node.all:
                    output.write(' ALL')
                output.newline()
                if node.rarg:
                    with output.expression(_select_needs_to_be_wrapped_in_parens(node.rarg)):
                        output.print_node(node.rarg)
                    if node.sortClause or node.limitCount or node.limitOffset \
                       or node.lockingClause:
                        output.newline()
        else:
            output.write('SELECT')
            if node.distinctClause:
                output.write(' DISTINCT')
                if node.distinctClause[0]:
                    output.write(' ON ')
                    with output.expression(True):
                        output.print_list(node.distinctClause)
            if node.targetList:
                _print_target_list(output, node.targetList)
            if node.intoClause:
                output.newline()
                output.write('INTO ')
                if node.intoClause.rel.relpersistence == enums.RELPERSISTENCE_UNLOGGED:
                    output.write('UNLOGGED ')
                elif node.intoClause.rel.relpersistence == enums.RELPERSISTENCE_TEMP:
                    output.write('TEMPORARY ')
                output.print_node(node.intoClause)
            if node.fromClause:
                output.newline()
                _print_from_clause(output, node.fromClause)
            if node.whereClause:
                output.newline()
                output.write('WHERE ')
                output.print_node(node.whereClause)
            if node.groupClause:
                output.newline()
                output.write('GROUP BY ')
                if node.groupDistinct:
                    output.write('DISTINCT ')
                _print_clause_list(output, node.groupClause)
            if node.havingClause:
                output.newline()
                output.write('HAVING ')
                output.print_node(node.havingClause)
            if node.windowClause:
                output.newline()
                output.write('WINDOW ')
                output.print_list(node.windowClause)
        if node.sortClause:
            output.newline()
            output.write('ORDER BY ')
            _print_clause_list(output, node.sortClause)
        if node.limitCount:
            output.newline()
            if node.limitOption == enums.LimitOption.LIMIT_OPTION_COUNT:
                output.write('LIMIT ')
            elif node.limitOption == enums.LimitOption.LIMIT_OPTION_WITH_TIES:
                output.write('FETCH FIRST ')
            if isinstance(node.limitCount, ast.A_Const) and node.limitCount.isnull:
                output.write('ALL')
            else:
                with output.expression(isinstance(node.limitCount, ast.A_Expr)
                                       and node.limitCount.kind
                                       == enums.A_Expr_Kind.AEXPR_OP):
                    output.print_node(node.limitCount)
            if node.limitOption == enums.LimitOption.LIMIT_OPTION_WITH_TIES:
                output.write(' ROWS WITH TIES ')
        if node.limitOffset:
            output.newline()
            output.write('OFFSET ')
            output.print_node(node.limitOffset)
        if node.lockingClause:
            output.newline()
            output.write('FOR ')
            output.print_list(node.lockingClause)


def _is_clause_root(node) -> bool:
    """Is this BoolExpr the whole condition of a WHERE/HAVING clause?"""
    return isinstance(node.ancestors[0],
                      (ast.SelectStmt, ast.UpdateStmt, ast.DeleteStmt))


@node_printer(ast.BoolExpr, override=True)
def bool_expr(node, output):
    bet = enums.BoolExprType
    if node.boolop == bet.NOT_EXPR:
        output.writes('NOT')
        with output.expression(_bool_expr_needs_to_be_wrapped_in_parens(node.args[0])):
            output.print_node(node.args[0])
        return

    keyword = 'AND' if node.boolop == bet.AND_EXPR else 'OR'
    if _is_block_stream(output) and _is_clause_root(node):
        # One condition per line: the first stays on the clause line,
        # the rest hang one level in with a leading and/or.  An AND
        # nested directly under a clause-root OR binds tighter anyway,
        # so its conditions are flattened onto lines of their own
        # rather than parenthesized (matching the sqruff-era style of
        # breaking before every query-level and/or).
        with output.push_indent(INDENT_STEP, relative=False):
            first = True
            for arg, arg_keyword in _flattened_conditions(node, keyword):
                if not first:
                    output.newline()
                    output.write(arg_keyword)
                    output.write(' ')
                first = False
                with output.expression(_bool_expr_needs_to_be_wrapped_in_parens(arg)):
                    output.print_node(arg)
    else:
        # Nested groups and join quals: inline when they fit the line
        # target, otherwise one operand per line with a leading and/or
        # (standalone_items=None lets the stream measure).
        output.print_list(node.args, keyword, standalone_items=None,
                          item_needs_parens=_bool_expr_needs_to_be_wrapped_in_parens)


def _flattened_conditions(node, keyword: str):
    """Yield ``(condition, leading_keyword)`` pairs, one per line.

    ANDs nested under an OR are expanded in place; precedence
    reconstructs the same tree on re-parse, so no parens are needed.
    """
    bet = enums.BoolExprType
    for arg in node.args:
        if (keyword == 'OR' and isinstance(arg, ast.BoolExpr)
                and arg.boolop == bet.AND_EXPR):
            for i, sub in enumerate(arg.args):
                yield sub, 'AND' if i else keyword
        else:
            yield arg, keyword


@node_printer(ast.JoinExpr, override=True)
def join_expr(node, output):
    if not _is_block_stream(output):
        _raw_join_expr(node, output)
        return
    with output.expression(bool(node.alias)):
        output.print_node(node.larg)
        output.newline()
        _write_join_keywords(node, output)
        with output.expression(isinstance(node.rarg, ast.JoinExpr)
                               and not bool(node.rarg.alias)):
            output.print_node(node.rarg)
        _print_join_condition(node, output)
    if node.alias:
        output.writes(' AS ')
        output.print_name(node.alias)


def _write_join_keywords(node, output) -> None:
    if node.isNatural:
        output.write('NATURAL ')
    jt = enums.JoinType
    if node.jointype == jt.JOIN_INNER:
        if node.isNatural:
            pass  # "natural join x", never "natural inner join x"
        elif not node.usingClause and not node.quals:
            output.write('CROSS')
        else:
            output.write('INNER')
    elif node.jointype == jt.JOIN_LEFT:
        output.write('LEFT')
    elif node.jointype == jt.JOIN_FULL:
        output.write('FULL')
    elif node.jointype == jt.JOIN_RIGHT:
        output.write('RIGHT')
    output.swrite('JOIN ')


def _print_join_condition(node, output) -> None:
    if node.usingClause:
        output.swrite('USING ')
        with output.expression(True):
            output.print_name(node.usingClause, ',')
        if node.join_using_alias:
            output.write(' AS ')
            output.print_node(node.join_using_alias)
    elif node.quals:
        if _is_block_stream(output):
            rendered = ' ON ' + output.concat([node.quals])
            if not output.fits_on_current_line(rendered):
                with output.push_indent(INDENT_STEP, relative=False):
                    output.newline()
                    output.write('ON ')
                    output.print_node(node.quals)
                return
        output.swrite('ON ')
        output.print_node(node.quals)


def _raw_join_expr(node, output) -> None:
    """Inline rendering used when measuring with a RawStream clone."""
    with output.expression(bool(node.alias)):
        output.print_node(node.larg)
        output.write(' ')
        _write_join_keywords(node, output)
        with output.expression(isinstance(node.rarg, ast.JoinExpr)
                               and not bool(node.rarg.alias)):
            output.print_node(node.rarg)
        _print_join_condition(node, output)
    if node.alias:
        output.writes(' AS ')
        output.print_name(node.alias)


# Wrapping a call whose argument list renders shorter than this can't
# meaningfully shorten the line (think count(*), min(x)); the overflow
# is elsewhere and block parens would just add noise.
_MIN_WRAPPABLE_ARGS_LENGTH = 16


def _call_args_should_wrap(node, output, args) -> bool:
    """Break a call's parens block-style when the line will overflow.

    The call alone can fit while the full select-list item still
    overflows because of its ``as alias`` suffix, so when the call is a
    target-list item's value the whole item is measured instead.
    """
    if not _is_block_stream(output) or not args:
        return False
    if len(output.concat(list(args), ', ')) < _MIN_WRAPPABLE_ARGS_LENGTH:
        return False
    parent = node.ancestors[0]
    target = parent if isinstance(parent, ast.ResTarget) else node
    return not output.fits_on_current_line(output.concat([target]))


def _print_call_parens(node, output, args, print_interior) -> None:
    if _call_args_should_wrap(node, output, args):
        _print_block_parens(output, print_interior)
    else:
        with output.expression(True):
            print_interior()


def _print_func_call_interior(node, output) -> None:
    if node.agg_distinct:
        output.writes('DISTINCT')
    if node.args is None:
        if node.agg_star:
            output.write('*')
    elif node.func_variadic:
        if len(node.args) > 1:
            output.print_list(node.args[:-1])
            output.write(', ')
        output.write('VARIADIC ')
        output.print_node(node.args[-1])
    else:
        output.print_list(node.args)
    if node.agg_order:
        if not node.agg_within_group:
            output.swrites('ORDER BY')
            output.print_list(node.agg_order)
        else:
            output.writes(') WITHIN GROUP (ORDER BY')
            output.print_list(node.agg_order)


@node_printer(ast.FuncCall, override=True)
def func_call(node, output):
    name = '.'.join(n.sval for n in node.funcname)
    special_printer = output.get_printer_for_function(name, node)
    if special_printer is not None:
        special_printer(node, output)
        return

    if output.special_functions and name in COL_NAME_KEYWORDS:
        output.write(f'"{name}"')
    else:
        output.print_name(node.funcname)

    wrappable_args = None if node.agg_within_group else node.args
    _print_call_parens(node, output, wrappable_args,
                       lambda: _print_func_call_interior(node, output))

    if node.agg_filter:
        def print_filter_interior() -> None:
            output.write('WHERE ')
            output.print_node(node.agg_filter)

        output.swrite('FILTER ')
        _print_call_parens(node, output, [node.agg_filter], print_filter_interior)
    if node.over:
        output.swrite('OVER ')
        output.print_node(node.over)


@node_printer(ast.CoalesceExpr, override=True)
def coalesce_expr(node, output):
    output.write('COALESCE')
    _print_call_parens(node, output, node.args,
                       lambda: output.print_list(node.args))


@node_printer(ast.MinMaxExpr, override=True)
def min_max_expr(node, output):
    if node.op == enums.MinMaxOp.IS_GREATEST:
        output.write('GREATEST')
    else:
        output.write('LEAST')
    _print_call_parens(node, output, node.args,
                       lambda: output.print_list(node.args))


@node_printer(ast.CaseExpr, override=True)
def case_expr(node, output):
    # Block layout: one WHEN per line one level under CASE, END back at
    # the CASE level.  On a measuring RawStream the newlines and indents
    # are no-ops, so this same shape degrades to a single line.
    if _is_block_stream(output):
        rendered = output.concat([node])
        if output.fits_on_current_line(rendered):
            output.write(rendered)
            return
    output.write('CASE')
    if node.arg:
        output.write(' ')
        output.print_node(node.arg)
    with output.push_indent(INDENT_STEP, relative=False):
        for when in node.args:
            output.newline()
            output.print_node(when)
        if node.defresult:
            output.newline()
            output.write('ELSE ')
            output.print_node(node.defresult)
    output.newline()
    output.write('END')


@node_printer(ast.CaseWhen, override=True)
def case_when(node, output):
    output.write('WHEN ')
    output.print_node(node.expr)
    if _is_block_stream(output):
        rendered = ' THEN ' + output.concat([node.result])
        if not output.fits_on_current_line(rendered):
            with output.push_indent(INDENT_STEP, relative=False):
                output.newline()
                output.write('THEN ')
                output.print_node(node.result)
            return
    output.write(' THEN ')
    output.print_node(node.result)


@node_printer(ast.SubLink, override=True)
def sub_link(node, output):
    slt = enums.SubLinkType
    if node.subLinkType == slt.EXISTS_SUBLINK:
        output.write('EXISTS ')
    elif node.subLinkType == slt.ALL_SUBLINK:
        output.print_node(node.testexpr)
        output.write(' ')
        output.write(get_string_value(node.operName))
        output.write(' ALL ')
    elif node.subLinkType == slt.ANY_SUBLINK:
        output.print_node(node.testexpr)
        if node.operName:
            output.write(' ')
            output.write(get_string_value(node.operName))
            output.write(' ANY ')
        else:
            output.write(' IN ')
    elif node.subLinkType == slt.EXPR_SUBLINK:
        pass
    elif node.subLinkType == slt.ARRAY_SUBLINK:
        output.write('ARRAY')
    else:  # pragma: no cover
        raise NotImplementedError(f'SubLink of type {node.subLinkType} not supported')

    if _is_block_stream(output):
        _print_block_parens(output, lambda: output.print_node(node.subselect))
    else:
        with output.expression(True):
            output.print_node(node.subselect)


@node_printer(ast.RangeSubselect, override=True)
def range_subselect(node, output):
    if node.lateral:
        output.write('LATERAL')
    output.maybe_write_space()
    if _is_block_stream(output):
        _print_block_parens(output, lambda: output.print_node(node.subquery))
    else:
        with output.expression(True):
            output.print_node(node.subquery)
    if node.alias:
        output.write(' AS ')
        output.print_name(node.alias)


@node_printer(ast.CommonTableExpr, override=True)
def common_table_expr(node, output):
    output.print_name(node.ctename)
    if node.aliascolnames:
        with output.expression(True):
            output.print_name(node.aliascolnames, ',')
    output.swrite('AS')
    cte_materialize_printer(node.ctematerialized, node, output)
    output.space(force=True)
    if _is_block_stream(output):
        _print_block_parens(output, lambda: output.print_node(node.ctequery))
    else:
        with output.expression(True):
            output.print_node(node.ctequery)
    if node.search_clause:
        output.newline()
        output.print_node(node.search_clause)
    if node.cycle_clause:
        output.newline()
        output.print_node(node.cycle_clause)


@node_printer(ast.WithClause, override=True)
def with_clause(node, output):
    # Emitted by hand rather than through print_list, whose automatic
    # mid-line indent push would shift every CTE body one level right.
    if node.recursive:
        output.write('RECURSIVE ')
    for i, cte in enumerate(node.ctes):
        if i:
            output.write(',')
            output.newline()
        output.print_node(cte)
