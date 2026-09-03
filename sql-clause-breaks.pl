#!/usr/bin/perl
#
# SQL clause-break pre-processor, intended to be piped into sqruff:
#
#     sql-clause-breaks.pl | sqruff fix --format none - || true
#
# sqruff preserves any line break it is handed and will not remove one,
# so its output depends on how the input was already laid out. This
# script removes that dependency: it first flattens the statement to a
# single line, then inserts breaks before clause keywords at query
# level. The result is the same regardless of the input's formatting.
#
# Because flattening would swallow "--" comments, they are rewritten as
# "/* ... */" first. String literals, quoted identifiers, block comments
# and dollar-quoted bodies are passed through untouched, and function
# argument lists such as extract(month FROM d) are left alone.

use strict;
use warnings;

my @KEYWORDS = qw(
    from where group having order limit offset
    union intersect except and or
);
my %KEYWORDS = map { $_ => 1 } @KEYWORDS;

my $sql = do { local $/; <STDIN> };
$sql = flatten($sql);
$sql = add_breaks($sql);
$sql .= "\n" unless $sql =~ /\n\z/;
print $sql;

# ---------------------------------------------------------------------
# Shared scanning helpers.
#
# Each returns the length of the construct starting at $i, or undef if
# no construct of that kind starts there.
# ---------------------------------------------------------------------

sub len_line_comment {
    my ($s, $i, $len) = @_;
    return undef unless substr($s, $i, 2) eq '--';
    my $j = index($s, "\n", $i);
    return ($j < 0 ? $len : $j) - $i;
}

sub len_block_comment {
    my ($s, $i, $len) = @_;
    return undef unless substr($s, $i, 2) eq '/*';
    my $j = index($s, '*/', $i + 2);
    return ($j < 0 ? $len : $j + 2) - $i;
}

sub len_dollar_quote {
    my ($s, $i, $len) = @_;
    return undef unless substr($s, $i, 1) eq '$';
    return undef unless substr($s, $i) =~ /^(\$[A-Za-z_]*\$)/;
    my $tag = $1;
    my $j = index($s, $tag, $i + length $tag);
    return ($j < 0 ? $len : $j + length $tag) - $i;
}

sub len_string {
    my ($s, $i, $len) = @_;
    return undef unless substr($s, $i, 1) eq "'";
    my $j = $i + 1;
    while ($j < $len) {
        if (substr($s, $j, 1) eq "'") {
            last if substr($s, $j + 1, 1) ne "'";   # '' is an escaped quote
            $j++;
        }
        $j++;
    }
    return ($j < $len ? $j : $len - 1) - $i + 1;
}

sub len_quoted_ident {
    my ($s, $i, $len) = @_;
    return undef unless substr($s, $i, 1) eq '"';
    my $j = index($s, '"', $i + 1);
    return ($j < 0 ? $len - 1 : $j) - $i + 1;
}

# Anything that must be copied through verbatim.
sub len_opaque {
    my ($s, $i, $len) = @_;
    for my $f (\&len_block_comment, \&len_dollar_quote,
               \&len_string, \&len_quoted_ident) {
        my $n = $f->($s, $i, $len);
        return $n if defined $n;
    }
    return undef;
}

# ---------------------------------------------------------------------
# Pass 1: rewrite "--" comments as block comments and collapse the
# statement onto a single line.
# ---------------------------------------------------------------------

sub flatten {
    my ($s) = @_;
    my $len = length $s;
    my $out = '';
    my $i   = 0;

    while ($i < $len) {
        if (defined(my $n = len_line_comment($s, $i, $len))) {
            my $text = substr($s, $i + 2, $n - 2);
            $text =~ s/\s+\z//;
            $text =~ s{\*/}{* /}g;          # can't nest a terminator
            $out .= "/*$text */";
            $i   += $n;
            next;
        }
        if (defined(my $n = len_opaque($s, $i, $len))) {
            $out .= substr($s, $i, $n);
            $i   += $n;
            next;
        }
        if (substr($s, $i, 1) =~ /\s/) {
            $i++ while $i < $len && substr($s, $i, 1) =~ /\s/;
            $out .= ' ';
            next;
        }
        $out .= substr($s, $i, 1);
        $i++;
    }

    $out =~ s/\A\s+//;
    $out =~ s/\s+\z//;
    return $out;
}

# ---------------------------------------------------------------------
# Pass 2: insert a break before each clause keyword at query level.
# ---------------------------------------------------------------------

# Look ahead past whitespace, comments and opening parens for the next
# bare word, lowercased. Used to decide whether a "(" opens a subquery.
sub peek_word {
    my ($s, $p, $end) = @_;
    while ($p < $end) {
        my $c = substr($s, $p, 1);
        if ($c =~ /\s/ || $c eq '(') { $p++; next }
        my $n = len_line_comment($s, $p, $end);
        $n = len_block_comment($s, $p, $end) unless defined $n;
        if (defined $n) { $p += $n; next }
        last;
    }
    my ($w) = substr($s, $p) =~ /^(\w+)/;
    return defined $w ? lc $w : '';
}

sub add_breaks {
    my ($s) = @_;
    my $len = length $s;
    my $out = '';
    my $i   = 0;

    # Per-paren-level state. ctx: 1 = a query, breaks allowed here;
    # 0 = an argument or column list, breaks suppressed. between: the
    # next AND belongs to a BETWEEN and must not be broken on.
    my @ctx     = (1);
    my @between = (0);

    while ($i < $len) {
        my $c = substr($s, $i, 1);

        if (defined(my $n = len_line_comment($s, $i, $len))) {
            $out .= substr($s, $i, $n);
            $i   += $n;
            next;
        }
        if (defined(my $n = len_opaque($s, $i, $len))) {
            $out .= substr($s, $i, $n);
            $i   += $n;
            next;
        }

        if ($c eq '(') {
            my $w = peek_word($s, $i + 1, $len);
            push @ctx, ($w eq 'select' || $w eq 'with' || $w eq 'values') ? 1 : 0;
            push @between, 0;
            $out .= $c;
            $i++;
            next;
        }
        if ($c eq ')') {
            if (@ctx > 1) { pop @ctx; pop @between }
            $out .= $c;
            $i++;
            next;
        }

        # Keep statements on separate lines.
        if ($c eq ';') {
            $out .= ';';
            $i++;
            $i++ while $i < $len && substr($s, $i, 1) =~ /\s/;
            $out .= "\n" if $i < $len;
            next;
        }

        if ($ctx[-1] && $c =~ /\s/) {
            my ($w) = substr($s, $i) =~ /^\s+(\w+)/;
            my $lw = defined $w ? lc $w : '';
            if ($lw eq 'between') {
                $between[-1] = 1;
            }
            elsif ($lw eq 'and' && $between[-1]) {
                $between[-1] = 0;
            }
            elsif ($KEYWORDS{$lw}) {
                $i++ while $i < $len && substr($s, $i, 1) =~ /\s/;
                $out .= "\n";
                next;
            }
        }

        $out .= $c;
        $i++;
    }

    return $out;
}
