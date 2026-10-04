"""Real BaseX execution in a disposable DB, never the user's corpus."""
from pathlib import Path
import shutil
import pytest
import ask
import staleness


@pytest.fixture(scope='module')
def basex_home(tmp_path_factory):
    jar = Path(ask.__file__).parent/'basex'/'BaseX.jar'
    if not jar.is_file() or not shutil.which('java'):
        pytest.skip('real BaseX query tests require the vendored jar and Java')
    home = tmp_path_factory.mktemp('ask-basex')
    shutil.copyfile(jar, home/'BaseX.jar')
    (home/'.basexhome').touch()
    (home/'.basex').write_text(f'DBPATH = {(home/"data").as_posix()}\nREPOPATH = {(home/"repo").as_posix()}\n', encoding='utf-8')
    original = ask.BASEX_DIR
    ask.BASEX_DIR = home
    try:
        ask.run_xq("db:create('x4raw', (<r><cue name='AuditCue'/><ware id='ore' ware='ore' name='a'/></r>, "
                   "<r><ware id='ore' ware='ore' name='b'/></r>), ('a.xml', 'b.xml'))")
    finally:
        ask.BASEX_DIR = original
    return home


@pytest.fixture
def real_db(monkeypatch, basex_home):
    monkeypatch.setattr(ask, 'BASEX_DIR', basex_home)
    monkeypatch.setattr(ask.preflight, 'check', lambda *a, **k: [])
    monkeypatch.setattr(ask, 'load_coverage', lambda db: {
        'status': 'complete', 'supports_negative_claim': True,
        'indexed': {'total': 2}, 'expected': {'total': 2}})
    monkeypatch.setattr(ask, 'staleness_verdict', lambda db: staleness.Verdict(True, [], db))
    monkeypatch.delenv('MSYSTEM', raising=False)


def test_real_conditional_predicate_refuses_false_certificate(real_db, capsys):
    assert ask.main(['xq', "collection('x4raw')//cue[@name='AuditCue']"]) == 0
    assert 'AuditCue' in capsys.readouterr().out
    assert ask.main(['xq', "collection('x4raw')[if (true()) then 2 else 1]//cue[@name='AuditCue']"]) == 4
    assert 'NEGATIVE CONFIRMED' not in capsys.readouterr().out


def test_real_attr_and_content_zero(real_db, capsys):
    assert ask.main(['attr', 'name[false()]']) == 2
    capsys.readouterr()
    assert ask.main(['attr', 'name']) == 0
    assert '3 item(s)' in capsys.readouterr().out
    assert ask.main(['xq', "collection('x4raw')//ware[@id='absent']"]) == 0
    assert 'NEGATIVE CONFIRMED over 2 of 2' in capsys.readouterr().out


def test_page_contains_whole_multiline_nodes(real_db, capsys):
    q = "(<r><a/>\n<b/></r>, <r><c/></r>, <r><d/></r>)"
    assert ask.main(['xq', q, '--limit', '1', '--offset', '1']) == 0
    out = capsys.readouterr().out
    assert '<c/>' in out and '<a/>' not in out and '<d/>' not in out
    assert '1 displayed of 3' in out


def test_page_beyond_end_is_not_negative(real_db, capsys):
    assert ask.main(['xq', "collection('x4raw')//ware", '--limit', '1', '--offset', '99']) == 0
    out = capsys.readouterr().out
    assert '0 displayed of 2' in out and 'NEGATIVE CONFIRMED' not in out


@pytest.mark.parametrize('mode,arg,total', [('refs', 'ore', 2), ('attr', 'name', 3)])
def test_structured_page_has_full_total(real_db, capsys, mode, arg, total):
    assert ask.main([mode, arg, '--limit', '1']) == 0
    assert f'1 displayed of {total}' in capsys.readouterr().out


@pytest.mark.parametrize('q', ['false()', '0', '""', '("", "")'])
def test_page_cannot_hide_semantic_nonanswer(real_db, capsys, q):
    assert ask.main(['xq', q, '--limit', '1', '--offset', '99']) == 4
    assert 'NEGATIVE CONFIRMED' not in capsys.readouterr().out


def test_page_empty_sequence_certifies_full_search(real_db, capsys):
    assert ask.main(['xq', "collection('x4raw')//missing", '--limit', '1']) == 0
    assert 'NEGATIVE CONFIRMED over 2 of 2' in capsys.readouterr().out


def test_prolog_works_unlimited_but_limited_is_refused(real_db, capsys):
    q = "declare namespace a='urn:a'; <a:r/>"
    assert ask.main(['xq', q]) == 0
    assert 'item count unavailable' in capsys.readouterr().out
    assert ask.main(['xq', q, '--limit', '1']) == 2
    assert 'omit' in capsys.readouterr().err


def test_limit_zero_preserves_unlimited(real_db, capsys):
    assert ask.main(['xq', '(1, 2, 3)', '--limit', '0']) == 0
    out = capsys.readouterr().out
    assert '3 item(s)' in out and 'displayed' not in out


@pytest.mark.parametrize('flag,value', [('--limit', '-1'), ('--offset', '-1'), ('--limit', '1.5')])
def test_invalid_paging_arguments_refused(real_db, flag, value):
    with pytest.raises(SystemExit) as exc:
        ask.main(['xq', '(1,2)', flag, value])
    assert exc.value.code == 2


def test_offset_without_limit_and_empty_item_page(real_db, capsys):
    assert ask.main(['xq', '(1, 2, 3)', '--offset', '1']) == 0
    assert '2 displayed of 3' in capsys.readouterr().out
    assert ask.main(['xq', '(1, "")', '--limit', '1', '--offset', '1']) == 0
    assert '1 displayed of 2' in capsys.readouterr().out


def test_a_page_of_ATTRIBUTE_nodes_is_counted_not_refused(real_db, capsys):
    """v4.0.0 review R5-5: the paging wrapper called serialize() on every item, and an
    attribute node cannot be serialized standalone (SENR0001) -- so `--limit` over any
    `//@attr` query was refused as 'cannot safely count and page this query'."""
    rc = ask.main(['xq', "collection('x4raw')//ware/@id", '--limit', '1'])
    out = capsys.readouterr()
    assert rc == 0, (out.out, out.err)
    assert 'cannot safely count' not in out.err
    assert 'ore' in out.out
