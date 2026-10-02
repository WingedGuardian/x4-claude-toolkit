"""Post-review verification. Real inputs are read-only; writes use audit-output.

Do not reuse the historical audit summary as a repair verdict. Baseline corpus
files must be preserved before running exercise.py corpus again.
"""
import argparse
from collections import Counter
import hashlib
import json
import time
from pathlib import Path
import driver as D
import exercise
import extra
import summarize

CAT = Path(D.LOCAL['reviewed_x4cat'])
DEV = Path(D.LOCAL['reviewed_dev'])


def before():
    summarize.protected('before-repair-final-controls')
    files = [*D.PKG.joinpath('x4validate').glob('*.py'),
             *D.BASEX.glob('*.py'), *CAT.joinpath('x4_catalog').glob('*.py'),
             DEV/'_tools/deploy.py']
    D.write(D.OUT/'repair-tested-bytes.json', json.dumps({str(p): hashlib.sha256(p.read_bytes()).hexdigest()
                                                       for p in files}, indent=2))


def scratch():
    exercise.fixtures()
    extra.load_controls()
    extra.basex_fixture()
    env = D.environment(False)
    env['PYTHONPATH'] = str(CAT)
    cli = lambda label, args, codes=(0,): D.run('repair-cat-'+label,
        [D.PYTHON, '-m', 'x4_catalog', *args], codes, env=env, cwd=CAT)
    root = D.OUT/('repair-archives-'+str(time.time_ns()))
    root.mkdir()
    template = CAT/'templates/extension_poc'
    empty = root/'empty-template'; empty.mkdir()
    target = root/'invalid-mod'
    cli('invalid-template', ['init', 'audit_invalid', '-o', target, '--template-dir', empty], (2,))
    exercise.check('invalid template creates no output', False, target.exists())
    target = root/'valid-mod'
    cli('valid-template', ['init', 'audit_valid', '-o', target, '--template-dir', template])
    exercise.check('valid scaffold contains renamed MD and manifest', True,
        (target/'content.xml').is_file() and (target/'src/md/audit_valid.xml').is_file())
    source = root/'source'
    D.write(source/'libraries/audit.xml', '<audit><node value="42"/></audit>')
    cat = root/'ext_01.cat'
    official = D.MODDING/'tools/XTools_1.11/XRCatTool.exe'
    D.run('repair-official-pack', [official, '-in', source, '-out', cat], env=env, cwd=root)
    result = cli('reader', ['list', root, '--prefix', 'ext_', '--glob', 'libraries/audit.xml'])
    exercise.check('repair reader sees official XML path', True,
                   'libraries/audit.xml' in result['stdout'])
    dest = root/'extracted'; dest.mkdir()
    D.run('repair-official-unpack', [official, '-in', cat, '-out', dest], env=env, cwd=root)
    exercise.check('repair official archive bytes', True,
        (source/'libraries/audit.xml').read_bytes() == (dest/'libraries/audit.xml').read_bytes())
    game = root/'indexed'; game.mkdir()
    cli('pack', ['pack', D.OUT/'fixture/reference', '-o', game/'01.cat'])
    db = root/'index.sqlite'
    cli('index', ['index', game, '-o', db, '--refresh'])
    for command, name, expected in [('search', 'ore', 'solid avg:10'),
            ('inspect', 'ore', 'Price: 5 / 10 / 15'),
            ('inspect', 'audit_ship_macro', 'hull.max: 1000')]:
        result = cli(command+'-'+name, ['--db', db, command, name])
        exercise.check('repair indexed '+command+' '+name, True, expected in result['stdout'])
    D.run('repair-deploy-suite', [D.PYTHON, '-m', 'pytest', '_tools/test_deploy.py', '-q'], cwd=DEV, env=env)
    D.run('repair-cat-suite', [D.PYTHON, '-m', 'pytest', 'tests', '-q', '-rs'], cwd=CAT, env=env)


def basex():
    D.basex_build()
    for db in ('x4raw', 'x4eff'):
        for label, args, codes in [
            ('refs', ['refs', 'ore', '--limit', '5'], (0,3)),
            ('attr', ['attr', 'name', '--limit', '5', '--offset', '2'], (0,3)),
            ('invalid', ['attr', 'name[false()]'], (2,)),
            ('positive', ['xq', f"collection('{db}')//ware", '--limit', '3'], (0,3)),
            ('uncertified', ['xq', f"collection('{db}')[if (true()) then 1 else 2]//__repair_absent__"], (4,)),
        ]:
            D.run('repair-basex-'+db+'-'+label, [D.PYTHON, D.BASEX/'ask.py', *args, '--db', db],
                  codes, cwd=D.BASEX)


def schema():
    env = D.environment(); env['PYTHONPATH'] = str(CAT)
    code = ('import pytest; from pathlib import Path; import tests.test_schema_extract as t; '
            f't._GAME_DIR=Path({str(D.GAME)!r}); t._HAS_GAME=True; '
            # This decorator captured the absent foreign path at module import.
            'assert t._GAME_DIR.is_dir(); '
            't.TestScriptPropertiesExtraction.test_real_scriptproperties.pytestmark=[]; '
            'raise SystemExit(pytest.main(["tests/test_schema_extract.py", "-q", "-rs"]))')
    D.run('repair-cat-real-schema-suite', [D.PYTHON, '-c', code], env=env, cwd=CAT, timeout=600)


def archives():
    root = D.OUT/('installed-archive-proof-'+str(time.time_ns())); root.mkdir()
    source = root/'source'
    D.write(source/'libraries/audit.xml', '<audit><node value="42"/></audit>')
    cat = root/'ext_01.cat'
    env = D.environment(False); env.pop('PYTHONPATH', None)
    official = D.MODDING/'tools/XTools_1.11/XRCatTool.exe'
    D.run('installed-official-pack-proof', [official, '-in', source, '-out', cat], env=env, cwd=root)
    installed = D.MODDING/'tools/x4cat-spike'
    args = ['uv', 'run', '--frozen', '--no-sync', 'x4cat']
    result = D.run('installed-reader-path-proof',
        [*args, 'list', root, '--prefix', 'ext_', '--glob', 'libraries/audit.xml'], env=env, cwd=installed)
    exercise.check('installed reader sees exactly one official packed XML', True,
        'libraries/audit.xml' in result['stdout'] and '1 file(s)' in result['stdout'])
    dest = root/'extracted'
    D.run('installed-reader-extraction-proof', [*args, 'extract', root,
          '--prefix', 'ext_', '--glob', 'libraries/audit.xml', '-o', dest], env=env, cwd=installed)
    exercise.check('installed homegrown extraction equals official packed input', True,
        (dest/'libraries/audit.xml').read_bytes() == (source/'libraries/audit.xml').read_bytes())


def after():
    summarize.protected('after-repair-final-controls')
    before = json.loads((D.OUT/'protected-before-repair-final-controls.json').read_text())
    after = json.loads((D.OUT/'protected-after-repair-final-controls.json').read_text())
    differences = [p for p in before.keys()|after.keys() if before.get(p) != after.get(p)]
    fingerprints = json.loads((D.OUT/'repair-tested-bytes.json').read_text())
    changed_code = [p for p, digest in fingerprints.items()
                    if hashlib.sha256(Path(p).read_bytes()).hexdigest() != digest]
    records = list(map(json.loads, (D.OUT/'corpus.jsonl').read_text().splitlines()))
    counts = Counter((r['mod'], r['mode']) for r in records)
    duplicates = [list(key) for key, count in counts.items() if count != 1]
    baseline = {(r['mod'], r['mode']):r for r in map(json.loads,
                (D.OUT/'before-fixes-corpus.jsonl').read_text().splitlines())}
    current = {(r['mod'], r['mode']):r for r in records}
    population_then = json.loads((D.OUT/'before-fixes-population.json').read_text())
    population_now = json.loads((D.OUT/'population.json').read_text())
    def population(pop):
        return {'folders': sorted(pop['folders']),
                **{kind: sorted((r['path'], r['id'], r['enabled']) for r in pop[kind])
                   for kind in ('installed', 'active')}}
    population_changed = population(population_then) != population(population_now)
    def stable(row):
        row = dict(row); row.pop('seconds', None)
        report = dict(row.get('report', {})); report.pop('timings', None)
        row['report'] = report
        return row
    corpus_deltas = [list(key) for key in baseline.keys()|current.keys()
                     if key not in baseline or key not in current or stable(baseline[key]) != stable(current[key])]
    result = dict(protected_interval_differences=differences, tested_code_differences=changed_code,
                  corpus_rows=len(records), corpus_deltas=corpus_deltas,
                  duplicate_pairs=duplicates, population_changed=population_changed,
                  crashes=[list(k) for k,r in current.items() if 'crash' in r])
    D.write(D.OUT/'repair-final-comparison.json', json.dumps(result, indent=2))
    print(json.dumps(result, indent=2), flush=True)
    if (differences or changed_code or corpus_deltas or duplicates or population_changed
            or result['crashes'] or len(records) != 250 or len(current) != 250):
        D.ISSUES.append('final comparison requires investigation')


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('mode', choices=['before', 'scratch', 'basex', 'schema', 'archives', 'after'])
    globals()[parser.parse_args().mode]()
    raise SystemExit(bool(D.ISSUES))
