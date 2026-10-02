"""Store failures are actionable rc 2; user SQL mistakes remain rc 1."""
import sqlite3
import pytest
from x4validate import _effective, _effectivecli, _freshness


def store(path):
    with sqlite3.connect(path) as con:
        con.executescript(_effective._SCHEMA)
        con.execute('INSERT INTO meta VALUES (?,?)', ('schema_version', str(_effective.SCHEMA_VERSION)))
        con.execute("INSERT INTO entities VALUES (1, 'ware', 'ore', 'solid', 'libraries/wares.xml', 'base', NULL)")
    return path


@pytest.mark.parametrize('failure', ['missing', 'text', 'truncated', 'empty-schema', 'version', 'missing-column'])
@pytest.mark.parametrize('command', [('ls', 'ware'), ('sql', 'SELECT 1')])
def test_bad_store_is_rc2(tmp_path, capsys, failure, command):
    path = tmp_path/'bad.sqlite'
    if failure == 'text':
        path.write_bytes(b'not sqlite')
    elif failure == 'truncated':
        store(path); path.write_bytes(path.read_bytes()[:101])
    elif failure == 'empty-schema':
        sqlite3.connect(path).close()
    elif failure == 'version':
        store(path)
        with sqlite3.connect(path) as con:
            con.execute("UPDATE meta SET value='999' WHERE key='schema_version'")
    elif failure == 'missing-column':
        store(path)
        with sqlite3.connect(path) as con:
            con.execute('DROP INDEX idx_ent_kind_klass')
            con.execute('ALTER TABLE entities DROP COLUMN klass')
    assert _effectivecli.main(['--db', str(path), *command]) == 2
    err = capsys.readouterr().err
    assert str(path) in err and 'build' in err


def test_valid_store_readonly_and_sql_errors_preserved(tmp_path, capsys):
    path = store(tmp_path/'store # with spaces.sqlite')
    before = path.read_bytes()
    assert _effectivecli.main(['--db', str(path), 'ls', 'ware']) == 0
    assert 'ore' in capsys.readouterr().out
    assert _effectivecli.main(['--db', str(path), 'sql', 'SELECT * FROM nonexistent']) == 1
    assert _effectivecli.main(['--db', str(path), 'sql', 'DELETE FROM entities']) == 2
    assert path.read_bytes() == before


@pytest.mark.parametrize('detail', [['invalid'], [{}], [{'folder': []}]])
@pytest.mark.parametrize('command', [('ls', 'ware'), ('sql', 'SELECT 1')])
def test_malformed_freshness_metadata_refused(tmp_path, capsys, monkeypatch, detail, command):
    path = store(tmp_path/'bad-metadata.sqlite')
    with sqlite3.connect(path) as con:
        _freshness.stamp_sqlite(con, dict(content='before', engine='engine',
            reference='before-reference', detail=detail))
    monkeypatch.setattr(_freshness, 'fingerprint', lambda *a, **kw:
        dict(content='now', engine='engine', reference='now-reference',
             detail=[dict(folder='current', root='root', files=0)]))
    before = path.read_bytes()
    assert _effectivecli.main(['--db', str(path), *command]) == 2
    err = capsys.readouterr().err
    assert 'freshness metadata' in err and 'Rebuild' in err and 'Traceback' not in err
    assert path.read_bytes() == before


def test_valid_stale_metadata_remains_readable(tmp_path, capsys, monkeypatch):
    path = store(tmp_path/'stale-metadata.sqlite')
    with sqlite3.connect(path) as con:
        _freshness.stamp_sqlite(con, dict(content='before', engine='engine',
            reference='before-reference', detail=[dict(folder='previous', root='root', files=0)]))
    monkeypatch.setattr(_freshness, 'fingerprint', lambda *a, **kw:
        dict(content='now', engine='engine', reference='now-reference',
             detail=[dict(folder='current', root='root', files=0)]))
    before = path.read_bytes()
    assert _effectivecli.main(['--db', str(path), 'ls', 'ware']) == 0
    cap = capsys.readouterr()
    assert 'ore' in cap.out and 'STALE' in cap.err
    assert path.read_bytes() == before
