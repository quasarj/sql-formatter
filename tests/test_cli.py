import subprocess
import sys


def run_pgfmt(text: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, '-m', 'sql_formatter.cli'],
        input=text, capture_output=True, text=True,
    )


def test_formats_stdin_to_stdout_and_exits_zero() -> None:
    proc = run_pgfmt('select a,b from t')
    assert proc.returncode == 0
    assert proc.stdout == 'select a, b\nfrom t\n'


def test_bad_sql_is_echoed_verbatim_with_exit_zero() -> None:
    garbage = 'not sql at all ((('
    proc = run_pgfmt(garbage)
    assert proc.returncode == 0
    assert proc.stdout == garbage + '\n'


def test_stdout_carries_nothing_but_sql() -> None:
    proc = run_pgfmt('select 1')
    assert proc.stdout == 'select 1\n'
    assert proc.stderr == ''
