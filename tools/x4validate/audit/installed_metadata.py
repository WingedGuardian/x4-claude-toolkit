"""Verify installed metadata refusal and valid stale reads on disposable copies."""
import hashlib
import json
from pathlib import Path
import shutil
import sqlite3
import time
import driver as D
from exercise import check


def main():
    installed = D.SOURCE/'tools/x4validate'
    reviewed = D.PKG/'x4validate/_effectivecli.py'
    actual = installed/'x4validate/_effectivecli.py'
    check('installed metadata handler equals reviewed source', True,
          actual.read_bytes().replace(b'\r\n', b'\n') ==
          reviewed.read_bytes().replace(b'\r\n', b'\n'))
    env = D.environment(False); env.pop('PYTHONPATH', None)
    root = D.OUT/('installed-metadata-'+str(time.time_ns())); root.mkdir()
    for label, value in [('string-record', ['invalid']), ('missing-folder', [{}]),
                         ('unhashable-folder', [{'folder': []}]), ('valid-stale', None)]:
        path = root/(label+'.sqlite')
        shutil.copy2(D.OUT/'fixture/effective.sqlite', D.inside(path))
        with sqlite3.connect(path) as con:
            con.executemany('UPDATE meta SET value=? WHERE key=?',
                [('changed', 'fingerprint_content'), ('changed', 'fingerprint_reference')])
            if value is not None:
                con.execute('UPDATE meta SET value=? WHERE key=?',
                            (json.dumps(value), 'fingerprint_detail'))
        digest = hashlib.sha256(path.read_bytes()).hexdigest()
        result = D.run('installed-metadata-'+label,
            ['uv', 'run', '--frozen', '--no-sync', 'x4effective', '--db', path,
             'show', 'ware', 'ore'], (0,) if value is None else (2,), env=env, cwd=installed)
        check('installed metadata '+label+' is read-only', digest,
              hashlib.sha256(path.read_bytes()).hexdigest())
        if value is None:
            check('installed valid stale store remains readable', True,
                  'ore' in result['stdout'] and 'STALE' in result['stderr'])
        else:
            check('installed malformed '+label+' gives rebuild guidance', True,
                  'freshness metadata' in result['stderr'] and 'Rebuild' in result['stderr'])
    return bool(D.ISSUES)


if __name__ == '__main__':
    raise SystemExit(main())
