"""`x4effective attr` must reject an unknown kind/prop instead of printing a zero.

`_reject_unknown_kind` was written for exactly this and its docstring says so --
"without this an unknown kind reads as a confident empty answer" -- but it is wired
into `ls`, `show` and `who-sets` and NOT into `attr`. MEASURED 2026-08-27 against
the live store:

    x4effective attr zzznotakind hull.max      -> "0 value(s) for hull.max"  rc 0
    x4effective attr macro properties.hull.max -> "0 value(s) ..."           rc 0

`who-sets` already gets the prop case right (`no prop 'x' on y`, rc 1), so `attr`
is the lone hole, and both arguments can be individually plausible while the pair
matches nothing.

The prop case has a specific, expensive wrong guess behind it: for MACRO entities
the store strips the `<properties>` wrapper (`hull.max`, not `properties.hull.max`)
because emitting both was F9. A parallel session hand-rolled a flatten that kept
the wrapper, matched only the keys living OUTSIDE `<properties>`, and reported
**2.6%** where the answer was **65.4%** -- a plausible, self-consistent number.

BUT THE STRIP IS NOT UNIVERSAL, which is why the suggestion must be derived from
the store rather than hard-coded. MEASURED over the same store: **6,842 rows carry
a `properties.` prefix, all of them kind='mapdataset'** (`properties.area.sunlight`),
and there are **0 duplicate pairs**, so F9 has not regressed -- those keys are real.
A blanket "the store strips `properties.`" rule would be wrong for every one of them.
"""

import sqlite3

from x4validate import _effective


def _store(tmp_path):
    db = tmp_path / "eff.sqlite"
    con = sqlite3.connect(db)
    con.executescript(_effective._SCHEMA)
    con.execute("INSERT INTO meta VALUES ('schema_version','1')")
    con.execute("INSERT INTO meta VALUES ('active_mods','112')")
    # a macro: the <properties> wrapper is STRIPPED
    con.execute("INSERT INTO entities VALUES (1,'macro','ship_x_macro','ship_s','a.xml','base',NULL)")
    con.execute("INSERT INTO attrs VALUES (1,'hull.max','100',100.0,'base',NULL)")
    con.execute("INSERT INTO entities VALUES (2,'macro','ship_y_macro','ship_m','a.xml','base',NULL)")
    con.execute("INSERT INTO attrs VALUES (2,'hull.max','200',200.0,'vro',NULL)")
    # a mapdataset: the wrapper is PRESERVED -- 6,842 real rows look like this
    con.execute("INSERT INTO entities VALUES (3,'mapdataset','cluster_01','','m.xml','base',NULL)")
    con.execute("INSERT INTO attrs VALUES (3,'properties.area.sunlight','1.4',1.4,'base',NULL)")
    con.commit()
    con.row_factory = sqlite3.Row
    return con


def _args(kind, prop, klass=None):
    return type("A", (), {"kind": kind, "prop": prop, "klass": klass,
                          "sort": "name", "limit": 200})()


def test_attr_rejects_an_unknown_kind_instead_of_printing_zero(tmp_path, capsys):
    con = _store(tmp_path)
    rc = _effective._cmd_attr(con, _args("zzznotakind", "hull.max"))
    cap = capsys.readouterr()
    assert rc != 0, "an unknown kind must not exit 0 with a clean-looking zero"
    assert "0 value(s)" not in cap.out, "a zero over a kind that does not exist is not a finding"
    assert "macro" in cap.err, "the rejection must name the kinds that DO exist"


def test_attr_rejects_an_unknown_prop_instead_of_printing_zero(tmp_path, capsys):
    con = _store(tmp_path)
    rc = _effective._cmd_attr(con, _args("macro", "zzznotaprop"))
    cap = capsys.readouterr()
    assert rc != 0, "a prop no macro carries must not exit 0"
    assert "0 value(s)" not in cap.out
    assert "zzznotaprop" in cap.err


def test_attr_names_the_stripped_key_when_the_guess_kept_the_wrapper(tmp_path, capsys):
    """The 2.6%-vs-65.4% case: the suggestion is what makes the rejection useful."""
    con = _store(tmp_path)
    rc = _effective._cmd_attr(con, _args("macro", "properties.hull.max"))
    err = capsys.readouterr().err
    assert rc != 0
    assert "hull.max" in err, "the key that DOES exist must be named, not merely 'no such prop'"


def test_a_prop_that_really_does_keep_the_wrapper_is_answered_normally(tmp_path, capsys):
    """6,842 mapdataset rows keep `properties.` -- a blanket strip rule would be wrong."""
    con = _store(tmp_path)
    rc = _effective._cmd_attr(con, _args("mapdataset", "properties.area.sunlight"))
    cap = capsys.readouterr()
    assert rc == 0, "this key exists; rejecting it would install a new wrong belief"
    assert "1.4" in cap.out


def test_a_TRUE_zero_is_still_reported_as_zero(tmp_path, capsys):
    """Falsification twin: the prop exists for the kind, the --class filter excludes it.

    Without this the guard could 'pass' by rejecting everything that returns no rows,
    which would turn a real, correct absence into an error.
    """
    con = _store(tmp_path)
    rc = _effective._cmd_attr(con, _args("macro", "hull.max", klass="ship_xl"))
    cap = capsys.readouterr()
    assert rc == 0, "no XL ship carries it is a genuine answer, not a bad query"
    assert "0 value(s)" in cap.out


def test_the_guard_does_not_fire_on_a_prop_that_exists(tmp_path, capsys):
    con = _store(tmp_path)
    rc = _effective._cmd_attr(con, _args("macro", "hull.max"))
    cap = capsys.readouterr()
    assert rc == 0
    assert "100" in cap.out and "200" in cap.out


def test_a_prop_that_lives_under_ANOTHER_kind_names_that_kind(tmp_path, capsys):
    """The sharpest miss: both arguments are individually real, the pair is not.

    MEASURED against the live store: `attr ship hull.max` matches nothing, because
    hull.max is carried by kind='macro' (1,973 values) while kind='ship' exists too
    and holds 31 other props. Rejecting without naming where the prop DOES live
    leaves the caller exactly as stuck as the confident zero did.
    """
    con = _store(tmp_path)
    con.execute("INSERT INTO entities VALUES (4,'ware','ore','minerals','w.xml','base',NULL)")
    con.execute("INSERT INTO attrs VALUES (4,'price.min','50',50.0,'base',NULL)")
    con.commit()
    rc = _effective._cmd_attr(con, _args("macro", "price.min"))
    err = capsys.readouterr().err
    assert rc != 0
    assert "ware" in err, "name the kind that DOES carry it, or the rejection is a dead end"


def test_the_cross_kind_hint_stays_silent_when_no_other_kind_has_it(tmp_path, capsys):
    """Falsification twin: a prop nothing carries must not invent a kind."""
    con = _store(tmp_path)
    rc = _effective._cmd_attr(con, _args("macro", "zzznotaprop"))
    err = capsys.readouterr().err
    assert rc != 0
    assert "carried by kind" not in err
