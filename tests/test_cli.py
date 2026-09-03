import subprocess
import sys
from pathlib import Path


def run_pgfmt(text: str, *argv: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, '-m', 'sql_formatter.cli', *argv],
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


def test_formats_file_in_place(tmp_path: Path) -> None:
    target = tmp_path / 'query.sql'
    target.write_text('select a,b from t')
    proc = run_pgfmt('', str(target))
    assert proc.returncode == 0
    assert proc.stdout == ''
    assert 'reformatted' in proc.stderr
    assert target.read_text() == 'select a, b\nfrom t\n'


def test_already_formatted_file_is_left_alone(tmp_path: Path) -> None:
    target = tmp_path / 'query.sql'
    formatted = 'select a, b\nfrom t\n'
    target.write_text(formatted)
    before = target.stat().st_mtime_ns
    proc = run_pgfmt('', str(target))
    assert proc.returncode == 0
    assert proc.stderr == ''
    assert target.stat().st_mtime_ns == before


def test_multiple_files_and_bad_sql_in_place(tmp_path: Path) -> None:
    good = tmp_path / 'good.sql'
    good.write_text('select 1;select 2')
    bad = tmp_path / 'bad.sql'
    bad.write_text('not sql at all (((\n')
    proc = run_pgfmt('', str(good), str(bad))
    assert proc.returncode == 0
    assert good.read_text() == 'select 1;\n\nselect 2\n'
    assert bad.read_text() == 'not sql at all (((\n'


def test_missing_file_exits_nonzero(tmp_path: Path) -> None:
    present = tmp_path / 'present.sql'
    present.write_text('select a,b from t')
    proc = run_pgfmt('', str(tmp_path / 'absent.sql'), str(present))
    assert proc.returncode == 1
    assert 'absent.sql' in proc.stderr
    # the other file is still processed
    assert present.read_text() == 'select a, b\nfrom t\n'
