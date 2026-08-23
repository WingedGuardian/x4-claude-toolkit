"""F10: DLC enumeration must go through Config, not `reference / "extensions"`.

`_xref.build_index` and `_similarity._collect_all` each hand-rolled a walk over
`reference/extensions/ego_dlc_*`. The two mini-DLC (Hyperion Pack, Envoy Pack) are
never unpacked into `reference\\` -- their content lives in `ext_*.cat` inside the
game install -- so both tools were blind to them, while `Config.dlc_dirs()` has
returned all 8 correctly for weeks.

MEASURED cost before the fix:
  x4xref     13 md/aiscript files -> 0 indexed rows. That specifically breaks
             NEGATIVES ("nobody calls X"), which is the one thing x4xref exists
             to make admissible.
  x4similar  3 ship macros invisible: the Hyperion
             (ship_par_l_expeditionary_01_a_macro) and 2 Envoy corvettes.

The shared readers (`_scan.iter_mod_xml`) were ALREADY packed-aware -- only the
directory list was wrong -- so these tests pin the enumeration, not the reading.
"""

from pathlib import Path

from x4validate import _similarity, _xref


def _dlc_with_script(root: Path, name: str) -> Path:
    """A DLC directory holding one md/ cue, placed wherever the caller wants."""
    d = root / name
    (d / "md").mkdir(parents=True)
    (d / "md" / "story.xml").write_bytes(
        f'<mdscript name="{name}_script"><cues>'
        f'<cue name="{name}_OnStart"><actions/></cue>'
        f"</cues></mdscript>".encode())
    return d


def _dlc_with_ship(root: Path, name: str, macro: str) -> Path:
    d = root / name
    macros = d / "assets" / "units" / "size_l" / "macros"
    macros.mkdir(parents=True)
    (macros / f"{macro}.xml").write_bytes(
        f'<macros><macro name="{macro}" class="ship_l"><properties>'
        f'<purpose primary="fight"/><hull max="50000"/><people capacity="20"/>'
        f'<cargo max="4000"/></properties></macro></macros>'.encode())
    return d


def test_xref_indexes_a_dlc_outside_the_reference_extensions_folder(tmp_path):
    """The packed mini-DLC live in the game install, NOT reference/extensions."""
    reference = tmp_path / "reference"
    (reference / "md").mkdir(parents=True)
    (reference / "md" / "base.xml").write_bytes(
        b'<mdscript name="base_script"><cues><cue name="BaseCue"><actions/></cue></cues></mdscript>')
    elsewhere = tmp_path / "gameinstall" / "extensions"
    elsewhere.mkdir(parents=True)
    mini = _dlc_with_script(elsewhere, "ego_dlc_mini_01")

    rows = _xref.build_index(reference, tmp_path / "nomods", dlc_dirs=[mini])

    sources = {r.source for r in rows}
    assert "base" in sources, "base game must still be indexed"
    assert "dlc:ego_dlc_mini_01" in sources, (
        "a DLC outside reference/extensions was not indexed -- enumeration is "
        "still hand-rolled off the reference tree")
    assert any(r.name == "ego_dlc_mini_01_OnStart" for r in rows)


def test_similar_sees_a_ship_from_a_dlc_outside_reference_extensions(tmp_path):
    reference = tmp_path / "reference"
    (reference / "assets").mkdir(parents=True)
    elsewhere = tmp_path / "gameinstall" / "extensions"
    elsewhere.mkdir(parents=True)
    mini = _dlc_with_ship(elsewhere, "ego_dlc_mini_01", "ship_par_l_expeditionary_01_a_macro")

    vectors = _similarity._collect_all(reference, tmp_path / "nomods", dlc_dirs=[mini])

    names = {v.macro_name for v in vectors}
    assert "ship_par_l_expeditionary_01_a_macro" in names, (
        "the Hyperion is invisible to x4similar -- 'is this a duplicate of a ship "
        "I own?' can never flag it")
    assert {v.source for v in vectors} == {"dlc:ego_dlc_mini_01"}


def test_dlc_dirs_defaults_to_config_not_a_hand_rolled_walk(tmp_path, monkeypatch):
    """Omitting dlc_dirs must consult Config.dlc_dirs(), which already knows about
    the packed mini-DLC, rather than re-deriving the list from the reference tree."""
    reference = tmp_path / "reference"
    (reference / "md").mkdir(parents=True)
    elsewhere = tmp_path / "elsewhere"
    elsewhere.mkdir()
    mini = _dlc_with_script(elsewhere, "ego_dlc_mini_02")

    from x4validate import _merge
    monkeypatch.setattr(_merge.Config, "dlc_dirs", lambda self: [mini], raising=False)

    rows = _xref.build_index(reference, tmp_path / "nomods")
    assert "dlc:ego_dlc_mini_02" in {r.source for r in rows}


# --- the guard that stops a FIFTH copy ---------------------------------------

def test_no_module_hand_rolls_the_dlc_directory_walk():
    """Enumerating DLC by walking a directory for `ego_dlc_*` is banned outside
    `_merge`, which is where `Config.dlc_dirs()` is implemented.

    This exact mistake has now been made FIVE times -- `_input.py` and
    `_migration.py` carry comments about the first two, `_effective.py` was the
    third (fixed in 57a982c), `_xref`/`_similarity` were the fourth, and
    `gates/similar_audit.py` was the fifth. Every copy is blind to the packed
    mini-DLC, and every copy fails silently. One implementation, asked for by
    everyone else.

    **Scope is deliberately `x4validate/` only, NOT `gates/`.** A gate is an
    independent re-implementation on purpose -- reusing the tool's enumeration
    would make it verify the tool against itself. Gates are held correct by their
    own counters instead: `similar_audit` scores any pair it cannot locate as
    UNRESOLVED and exits non-zero, which is exactly how its copy of this bug was
    caught (8 unresolved, now 0). Linting gates would trade a strong check for a
    weak one.
    """
    import ast
    from pathlib import Path as P

    pkg = P(__file__).resolve().parent.parent / "x4validate"
    # `_merge` is where Config.dlc_dirs() is implemented. `scan_installed`
    # EXCLUDES ego_dlc_* from the mod list, which is the opposite operation and
    # correct -- the AST heuristic below cannot tell "filter for" from "filter
    # out", so it is named here rather than papered over with a cleverer regex.
    allowed = {("_merge.py", None), ("_registry.py", "scan_installed")}
    offenders = []
    for src in sorted(pkg.glob("*.py")):
        if (src.name, None) in allowed:
            continue
        tree = ast.parse(src.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                continue
            body = ast.dump(node)
            walks = "iterdir" in body or "'glob'" in body or '"glob"' in body
            filters = "ego_dlc_" in body and "startswith" in body
            if walks and filters and (src.name, node.name) not in allowed:
                offenders.append(f"{src.name}:{node.lineno} {node.name}")
    assert not offenders, (
        "these enumerate DLC directories by hand instead of calling "
        "Config.dlc_dirs(), so they cannot see the packed mini-DLC:\n  "
        + "\n  ".join(offenders))


def test_no_module_hardcodes_a_dlc_NAME_LIST_without_consulting_config():
    """The other shape of the same mistake — and the one the walk-guard misses.

    `tools/basex/stage.py` carried a literal
    `MINI_DLC = ("ego_dlc_mini_01", "ego_dlc_mini_02")` (a SIXTH copy). It has no
    `iterdir`/`glob`, so the guard above could never have seen it. A hardcoded
    list is wrong only on the day a DLC is added — and on that day nothing would
    have said so, which is precisely why it survived five prior fixes.

    The rule is not "no literal ever" — a documented fallback is fine. It is that
    a module naming DLC must also ASK (`dlc_dirs` / `packed_dlc_names`), so the
    literal can never be the primary source of truth.

    Scope covers `tools/basex/` too: the previous guard deliberately stopped at
    `x4validate/`, which is how the sixth copy was written in a directory nothing
    was linting.
    """
    import ast
    from pathlib import Path as P

    roots = [P(__file__).resolve().parent.parent / "x4validate",
             P(__file__).resolve().parent.parent.parent / "basex"]
    # _merge implements the lookup, so it is where the names legitimately live.
    allowed_files = {"_merge.py"}
    # `scan_installed` EXCLUDES ego_dlc_* from the MOD list -- the opposite
    # operation, and correct: a new DLC must not become a mod. Named here for the
    # same reason the walk-guard names it, rather than weakening the check.
    allowed_funcs = {("_registry.py", "scan_installed")}
    offenders = []
    for pkg in roots:
        if not pkg.is_dir():
            continue
        for src in sorted(pkg.glob("*.py")):
            if src.name in allowed_files or src.name.startswith("test_"):
                continue
            text = src.read_text(encoding="utf-8")
            if "dlc_dirs" in text or "packed_dlc_names" in text:
                continue  # names a DLC but ASKS Config -- fallback, not source of truth
            tree = ast.parse(text)
            enclosing = {}
            for node in ast.walk(tree):
                if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                    for child in ast.walk(node):
                        enclosing[id(child)] = node.name
            for n in ast.walk(tree):
                if not (isinstance(n, ast.Constant) and isinstance(n.value, str)
                        and n.value.startswith("ego_dlc_")):
                    continue
                if (src.name, enclosing.get(id(n))) in allowed_funcs:
                    continue
                offenders.append(f"{pkg.name}/{src.name}:{n.lineno}")
                break
    assert not offenders, (
        "these hardcode DLC names without ever consulting Config, so they cannot "
        "notice a DLC being added:\n  " + "\n  ".join(offenders))
