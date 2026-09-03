"""IndentedStream subclass producing fixed-width, level-based indents.

pglast's stock IndentedStream aligns continuation lines to the current
column (``FROM tablea\\n     NATURAL LEFT JOIN ...``).  Our style wants
indentation to be a function of nesting depth alone: every indent is a
multiple of four spaces.  The trick is in :meth:`indent`: a relative
(column-based) indent request made mid-line becomes "one level deeper
than the enclosing line"; at the start of a line it keeps the current
level instead of aligning.
"""

from pglast.stream import IndentedStream

INDENT_STEP = 4
MAX_LINE_LENGTH = 80


class FourSpaceStream(IndentedStream):
    def indent(self, amount: int = 0, relative: bool = True) -> None:
        self.indentation_stack.append(self.current_indent)
        if relative:
            if self.current_column > 0:
                self.current_indent += INDENT_STEP
        else:
            self.current_indent = max(self.current_indent + amount, 0)

    def print_list(self, nodes, sep=',', relative_indent=None, standalone_items=None,
                   are_names=False, is_symbol=False, item_needs_parens=None):
        # The stock stream breaks a list one-item-per-line whenever any
        # item is structurally non-trivial (a function call, a $n param,
        # an arithmetic expression...).  Decide by measured width
        # instead: inline when the whole list fits the line target.
        # This is also what keeps `between $1 and $2` on one line.
        if standalone_items is None:
            rendered = self._concat_nodes(nodes, sep, are_names, item_needs_parens)
            standalone_items = not self.fits_on_current_line(rendered)
        super().print_list(nodes, sep, relative_indent, standalone_items,
                           are_names, is_symbol, item_needs_parens)

    def fits_on_current_line(self, rendered: str) -> bool:
        """Would ``rendered`` fit within the line-length target here?"""
        return self.current_column + len(rendered) <= MAX_LINE_LENGTH

    def concat(self, nodes, sep: str = ", ") -> str:
        """Render ``nodes`` compactly on one line, for fit measurement."""
        return self._concat_nodes(nodes, sep)
