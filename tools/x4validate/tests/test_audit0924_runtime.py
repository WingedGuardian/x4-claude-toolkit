"""AUDIT-2026-09-24 Phase 1 -- runtime tools (RT-*) and registry/paths (RG-*).

Every test here is `xfail(strict=True)`: it FAILS on the audited code for the reason named in
its `reason=`, and turns into an XPASS -> hard failure the moment a fix lands, so the marker
must be removed together with the fix.

Transport is the only thing stubbed: the live pipe (`_livecli._live_open`) and
`urllib.request.urlopen` in `_nexus`. No test here touches the game, the profile, or the
network. RT-6 additionally stubs the effective-STORE accessors (`effective_db`, `_connect`,
`store_freshness`) with an in-memory sqlite of the real schema, because the finding is in the
oracle's bucketing, not in the store; `_store_props` and the comparison run for real.
"""
from __future__ import annotations

import contextlib
import gzip
import io
import json
import re
import sqlite3
import types
import urllib.error
from datetime import datetime, timezone
from pathlib import Path

import pytest

from x4validate import (_check, _debugcli, _debuglog, _effective, _ffinames, _livecli,
                        _livepipe, _modlist, _nexus, _paths, _registry, _savecli)

TAB, BS = chr(9), chr(92)


# --------------------------------------------------------------------------- helpers

def _write_save(path: Path, patches_xml: str, body: bytes = b"<universe/>") -> Path:
    head = ('<?xml version="1.0" encoding="UTF-8"?><savegame><info>'
            '<save name="t" date="1"/><game id="X4" version="900" build="1" time="0" '
            'start="s"/><player name="p" money="0"/>'
            f"<patches>{patches_xml}</patches></info>").encode()
    with gzip.open(path, "wb") as fh:
        fh.write(head + body + b"</savegame>")
    return path


class _FakeLive:
    """Stands in for the pipe. `answer(verb, args, seq)` returns a Reply or raises."""

    def __init__(self, answer):
        self.path = r"\\.\pipe\fake"
        self._answer = answer
        self.seq = 0
        self.calls: list[tuple[str, tuple]] = []

    def ask(self, verb, *args):
        self.seq += 1
        self.calls.append((verb, args))
        return self._answer(verb, args, self.seq)


def _stub_live(monkeypatch, fake):
    @contextlib.contextmanager
    def _open(pipe, timeout):
        yield fake
    monkeypatch.setattr(_livecli, "_live_open", _open)


class _Resp(io.BytesIO):
    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


def _meta_json(name="Cool Mod", version="2.0"):
    ts = int(datetime(2026, 6, 1, tzinfo=timezone.utc).timestamp())
    return json.dumps({"name": name, "version": version, "updated_timestamp": ts,
                       "status": "published", "author": "a"}).encode()


def _pinned_row(mod_id, nexus_id, **auto):
    e = _registry._new_entry(mod_id, True)
    e["auto"]["installed"] = True
    e["auto"].update(auto)
    e["human"]["nexus_id"] = nexus_id
    return e


def _refresh_args(regp, **kw):
    base = dict(registry=str(regp), ids=None, seeded=False, limit=None, force=True,
                no_resolve=True)
    base.update(kw)
    return types.SimpleNamespace(**base)


# --------------------------------------------------------------------------- RT-1

def test_rt1_crosscheck_keeps_the_patch_file_in_the_key():
    sel = "//ware[@id='energycells']/price/@max"
    # The ENGINE skipped the op in libraries/wares ...
    parsed = _debuglog.ParsedLog(total=1, unclassified=[], entries=[_debuglog.DebugError(
        ident_kind="path", folder="mymod", vpath="libraries/wares", script_name="", line=0,
        message="No matching node", severity="error", sel=sel, cardinality="none")])
    # ... and WE predicted the same selector failing in a different file.
    report = _check.Report()
    report.add("error", "sel", f"sel matched nothing: {sel}", vpath="libraries/jobs.xml",
               sel=sel)
    r = _debugcli.compare_ops(_debugcli.observed_ops(parsed, "mymod"),
                              _debugcli.predicted_ops(report))
    assert not r.clean, (
        "an op the engine skipped in wares.xml was 'agreed' with a prediction about "
        "jobs.xml -- the file was dropped from the comparison key")


# --------------------------------------------------------------------------- RT-2

def test_rt2_an_updated_extension_is_not_reported_as_not_loaded(tmp_path):
    save = _write_save(tmp_path / "s.xml.gz",
                       '<patch extension="ws_1" version="200" name="A"/>'
                       '<history><patch extension="ws_1" version="100" name="A"/></history>')
    buf = io.StringIO()
    assert _savecli.cmd_info(save, out=buf) == 0
    out = buf.getvalue()
    gone = out.split("NOT loaded now", 1)[1] if "NOT loaded now" in out else ""
    assert "ws_1" not in gone.split("! This is NOT")[0], out


def test_rt2_history_only_extension_is_not_asserted_unloaded(tmp_path):
    # Shape of the real autosave_03 header: 10 current patches, and ego_dlc_ventures v127 in
    # <history> only, while that DLC is installed with enabled="1" save="1".
    save = _write_save(tmp_path / "s.xml.gz",
                       '<patch extension="ego_dlc_boron" version="900" name="KE"/>'
                       '<history><patch extension="ego_dlc_boron" version="900" name="KE"/>'
                       '<patch extension="ego_dlc_ventures" version="127" name="MTS"/>'
                       '</history>')
    buf = io.StringIO()
    _savecli.cmd_info(save, out=buf)
    assert "NOT loaded" not in buf.getvalue(), (
        "the save records what was BAKED, not what loaded (the module's own docstring); "
        "the section heading asserts a load state the source cannot support")


# --------------------------------------------------------------------------- RT-3

def test_rt3_reference_near_a_chunk_boundary_is_counted_once(tmp_path):
    tag = b'<component macro="m_boundary_macro"/>'
    first = b" " * (_savecli._CHUNK - 200 - len(tag)) + tag + b" " * 200
    assert len(first) == _savecli._CHUNK
    p = tmp_path / "s.xml.gz"
    with gzip.open(p, "wb") as fh:
        fh.write(first + b" " * 5000)
    assert _savecli.extract_refs(p)["m_boundary_macro"] == 1


# --------------------------------------------------------------------------- RT-4

@pytest.mark.xfail(strict=True, reason="AUDIT-2026-09-24 RT-4: harvest stops at 40 globals pages "
                   "but reports the engine's claimed page total with no truncation notice")
def test_rt4_harvest_states_when_the_globals_walk_was_capped(tmp_path, monkeypatch):
    def answer(verb, args, seq):
        if verb == "probe":
            return _livepipe.Reply(seq, "OK", "build=1")
        if verb == "globals":
            return _livepipe.Reply(seq, "OK", f"pages=50 matched=5000{TAB}name{args[1]}")
        return _livepipe.Reply(seq, "ABSENT", "")
    fake = _FakeLive(answer)
    _stub_live(monkeypatch, fake)
    buf, dest = io.StringIO(), tmp_path / "h.tsv"
    _livecli.cmd_harvest(None, 1.0, str(dest), out=buf)
    asked = sum(1 for v, _ in fake.calls if v == "globals")
    assert asked == 40                                   # the cap the finding is about
    text = buf.getvalue() + dest.read_text(encoding="utf-8")
    assert re.search(r"40 of 50|truncat|capped|incomplete", text, re.I), (
        "40 of 50 pages were fetched and the output says '... over 50 page(s)':\n"
        + buf.getvalue())


# --------------------------------------------------------------------------- RT-5

@pytest.mark.xfail(strict=True, reason="AUDIT-2026-09-24 RT-5: the '*' row is split on the "
                   "two-char escape BEFORE unescaping, so an escaped backslash + 't' cuts a value")
def test_rt5_all_fields_value_with_backslash_t_survives(tmp_path):
    def esc(x):   # the writer's escaping, as `cmd_groundtruth._gesc` does it
        return x.replace(BS, BS * 2).replace(TAB, BS + "t").replace(chr(10), BS + "n")
    path_value = "C:" + BS + "temp" + BS + "x"           # C:\temp\x
    star = f"name={path_value}{TAB}hull=5"
    row = TAB.join(esc(c) for c in ("weapons_lasers", "w_macro", "*", star))
    gt = tmp_path / "gt.tsv"
    gt.write_text("# x4live groundtruth\nlibrarytype\tmacro\tfield\tengine_value\n"
                  + row + "\n", encoding="utf-8")
    entries, _ = _livecli._entries_from_groundtruth(gt)
    got = entries[("weapons_lasers", "w_macro")]
    assert got.get("hull") == "5"
    assert got.get("name") == path_value, got


# --------------------------------------------------------------------------- RT-6

@pytest.mark.xfail(strict=True, reason="AUDIT-2026-09-24 RT-6: a MAPPED field whose store prop is "
                   "absent is counted as 'not mapped yet', hiding a possible disagreement")
def test_rt6_mapped_but_absent_is_not_counted_as_unmapped(tmp_path, monkeypatch):
    assert _livecli._mapping_for("shieldgentypes", "hull") == ("hull.max", "identity")
    con = sqlite3.connect(":memory:")
    con.row_factory = sqlite3.Row
    con.executescript("CREATE TABLE entities(id INTEGER PRIMARY KEY, kind TEXT, name TEXT);"
                      "CREATE TABLE attrs(entity_id INTEGER, prop TEXT, value TEXT);"
                      "INSERT INTO entities VALUES (1,'macro','shield_x_macro');"
                      "INSERT INTO attrs VALUES (1,'recharge.max','100');")
    db = tmp_path / "eff.db"
    db.write_bytes(b"")
    monkeypatch.setattr(_effective, "effective_db", lambda: db)
    monkeypatch.setattr(_effective, "_connect", lambda p: con)
    monkeypatch.setattr(_effective, "store_freshness",
                        lambda c, config=None: types.SimpleNamespace(fresh=True))
    gt = tmp_path / "gt.tsv"
    gt.write_text("librarytype\tmacro\tfield\tengine_value\n"
                  "shieldgentypes\tshield_x_macro\thull\t25000\n", encoding="utf-8")
    buf = io.StringIO()
    _livecli.cmd_oracle(None, out=buf, groundtruth=str(gt))
    m = re.search(r"not mapped yet\s+(\d+)", buf.getvalue())
    assert m and m.group(1) == "0", buf.getvalue()


# --------------------------------------------------------------------------- RT-7

def _names_filling(total: int) -> list[str]:
    """Unique identifiers <= 100 bytes whose tab-joined length is exactly *total*."""
    k = -(-(total + 1) // 100)
    body = total - (k - 1)
    base, extra = divmod(body, k)
    out = []
    for i in range(k):
        n = base + (1 if i < extra else 0)
        out.append((f"F{i:03d}" + "x" * n)[:n])
    assert len(TAB.join(out)) == total and len(set(out)) == k
    return out


@pytest.mark.xfail(strict=True, reason="AUDIT-2026-09-24 RT-7: the up-front --batch-bytes check "
                   "reserves 9 bytes for a header that is 14+ bytes, so an ACCEPTED value "
                   "produces requests the pipe refuses")
def test_rt7_an_accepted_batch_bytes_never_produces_an_oversized_request(tmp_path, monkeypatch):
    monkeypatch.setenv("X4_LIVE_ALLOW_FFI", "1")

    def answer(verb, args, seq):
        size = len(_livepipe.encode_command(seq, verb, tuple(args)).encode("utf-8"))
        if size > _livepipe.MAX_REQUEST_BYTES:       # the transport's own refusal
            raise _livepipe.LiveRequestTooLarge(f"{size}-byte request")
        return _livepipe.Reply(seq, "OK", TAB.join(["hdr"] + [f"{n}|exported|" for n in args]))

    def run(names, bb):
        text = "ffi.cdef[[\n" + "".join(f"int {n}(void);\n" for n in names) + "]]\n"
        monkeypatch.setattr(_ffinames, "census",
                            lambda cfg: _ffinames.census_from_texts({"ui/a.lua": text}))
        _stub_live(monkeypatch, _FakeLive(answer))
        dest = tmp_path / f"c{bb}.tsv"
        rc = _livecli.cmd_ffi_census(None, 1.0, str(dest), out=io.StringIO(), batch_bytes=bb)
        return rc, dest

    # The LARGEST --batch-bytes the command accepts (probed, not re-derived from its code).
    bb = _livepipe.MAX_REQUEST_BYTES
    while run(["Probe"], bb)[0] == 2:
        bb -= 1
    rc, dest = run(_names_filling(bb), bb)
    tsv = dest.read_text(encoding="utf-8")
    assert "TOO LARGE" not in tsv and rc == 0, (
        f"--batch-bytes {bb} passed the up-front check, then every batch was refused:\n{tsv}")


# --------------------------------------------------------------------------- RT-8

@pytest.mark.xfail(strict=True, reason="AUDIT-2026-09-24 RT-8: _dps_channels multiplies amount x "
                   "barrelamount; the 348-macro capture (KB 2026-09-20) measured max(amount, barrel)")
def test_rt8_shot_multiplier_is_max_not_product(monkeypatch):
    store = {}
    monkeypatch.setattr(_livecli, "_store_props", lambda con, name: store.get(name))
    base = {"reload.rate": "1", "damage.value": "10", "bullet.attach": "0"}

    def dps(extra, tag):
        store["w" + tag] = {"bullet.class": "b" + tag}
        store["b" + tag] = {**base, **extra}
        return _livecli._dps_channels(None, store["w" + tag])["hullshielddps"]

    one = dps({}, "1")
    # The shotgun shape that DISCRIMINATES (amount=8, barrel=2: product 16, max 8). The
    # pinned fixture in test_dps_derivation uses amount=1, barrel=9, where they coincide.
    shotgun = dps({"bullet.amount": "8", "bullet.barrelamount": "2"}, "8")
    assert shotgun == pytest.approx(one * 8)


# --------------------------------------------------------------------------- RT-9

@pytest.mark.xfail(strict=True, reason="AUDIT-2026-09-24 RT-9: `groundtruth --with-ramp` help says "
                   "the lua client does not reconnect; the module's own MEASURED note says it does")
def test_rt9_with_ramp_help_does_not_repeat_the_withdrawn_reconnect_claim(capsys):
    with pytest.raises(SystemExit):
        _livecli.main(["groundtruth", "--help"])
    helptext = " ".join(capsys.readouterr().out.split())
    assert "does not reconnect" not in helptext


def test_rt9_save_info_prints_no_machine_specific_counts(tmp_path):
    save = _write_save(tmp_path / "s.xml.gz", '<patch extension="ws_1" version="1" name="A"/>')
    buf = io.StringIO()
    _savecli.cmd_info(save, out=buf)
    assert not re.search(r"\b121\b|\b129\b", buf.getvalue()), buf.getvalue()


# --------------------------------------------------------------------------- RG-1

@pytest.mark.parametrize("failure", ["urlerror", "timeout", "not_json"])
@pytest.mark.xfail(strict=True, reason="AUDIT-2026-09-24 RG-1: _nexus catches only HTTPError, and "
                   "refresh saves once at the end, so one network drop loses the whole run")
def test_rg1_a_network_failure_mid_refresh_keeps_what_was_fetched(tmp_path, monkeypatch, failure):
    monkeypatch.setenv("X4_NEXUS_KEY", "test-key-not-real")
    regp = tmp_path / "r.yaml"
    reg = _registry._new_registry()
    reg["mods"].append(_pinned_row("a_first", 1))
    reg["mods"].append(_pinned_row("b_second", 2))
    _registry.save_registry(reg, regp)

    def fake_urlopen(req, timeout=None):
        if "/1.json" in req.full_url:
            return _Resp(_meta_json())
        if failure == "urlerror":
            raise urllib.error.URLError("network is unreachable")
        if failure == "timeout":
            raise TimeoutError("timed out")
        return _Resp(b"<html>Cloudflare</html>")
    monkeypatch.setattr(_nexus.urllib.request, "urlopen", fake_urlopen)

    try:
        _modlist.cmd_refresh(_refresh_args(regp))
    except Exception as exc:                          # noqa: BLE001 - the finding itself
        pytest.fail(f"refresh crashed on a transport failure: {type(exc).__name__}: {exc}")
    rows = {m["id"]: m["auto"] for m in _registry.load_registry(regp)["mods"]}
    assert rows["a_first"].get("checked_at"), "the row fetched before the failure was lost"


# --------------------------------------------------------------------------- RG-2

@pytest.mark.xfail(strict=True, reason="AUDIT-2026-09-24 RG-2: an auth failure (401) is recorded "
                   "per row as 'error', overwriting every lane, and the run keeps calling")
def test_rg2_an_invalid_key_stops_the_run_and_keeps_every_lane(tmp_path, monkeypatch):
    monkeypatch.setenv("X4_NEXUS_KEY", "revoked-key-not-real")
    regp = tmp_path / "r.yaml"
    reg = _registry._new_registry()
    for i, mid in enumerate(("a", "b", "c"), 1):
        reg["mods"].append(_pinned_row(mid, i, classification="ready", settled="stable"))
    _registry.save_registry(reg, regp)
    calls = []

    def fake_urlopen(req, timeout=None):
        calls.append(req.full_url)
        raise urllib.error.HTTPError(req.full_url, 401, "Unauthorized", {}, None)
    monkeypatch.setattr(_nexus.urllib.request, "urlopen", fake_urlopen)

    rc = _modlist.cmd_refresh(_refresh_args(regp))
    lanes = [m["auto"]["classification"] for m in _registry.load_registry(regp)["mods"]]
    assert len(calls) == 1, f"kept calling after a 401: {len(calls)} calls"
    assert lanes == ["ready"] * 3, lanes
    assert rc != 0


# --------------------------------------------------------------------------- RG-4

@pytest.mark.xfail(strict=True, reason="AUDIT-2026-09-24 RG-4: refresh --registry <typo> writes a "
                   "NEW empty registry there and reports success")
def test_rg4_refresh_refuses_a_registry_path_that_does_not_exist(tmp_path, monkeypatch):
    monkeypatch.setattr(_nexus.urllib.request, "urlopen",
                        lambda *a, **k: pytest.fail("no network call expected"))
    typo = tmp_path / "modlsit.yaml"
    try:
        rc = _modlist.cmd_refresh(_refresh_args(typo))
    except SystemExit as exc:
        rc = exc.code
    assert not typo.exists(), "a typo'd --registry created a fresh empty registry"
    assert rc not in (0, None)


@pytest.mark.xfail(strict=True, reason="AUDIT-2026-09-24 RG-4: a malformed profile content.xml "
                   "crashes ingest (XMLSyntaxError is not OSError)")
def test_rg4_ingest_reports_a_malformed_profile_instead_of_crashing(tmp_path):
    bad = tmp_path / "content.xml"
    bad.write_text("<content><extension id='a' enabled='true'></content", encoding="utf-8")
    ext = tmp_path / "ext"
    ext.mkdir()
    args = types.SimpleNamespace(registry=str(tmp_path / "r.yaml"), installed_only=False,
                                 content=str(bad), dirs=str(ext), all=False, build=None)
    try:
        rc = _modlist.cmd_ingest(args)
    except Exception as exc:                          # noqa: BLE001 - the finding itself
        pytest.fail(f"ingest crashed: {type(exc).__name__}: {exc}")
    assert rc == 2


@pytest.mark.xfail(strict=True, reason="AUDIT-2026-09-24 RG-4: `verify --rescore` promotes a guess "
                   "to exact, but a same-day refresh skips it (TTL) so the lane stays capped")
def test_rg4_rescore_then_same_day_refresh_uncaps_the_lane(tmp_path, monkeypatch):
    monkeypatch.setenv("X4_NEXUS_KEY", "test-key-not-real")
    monkeypatch.setattr(_nexus.urllib.request, "urlopen",
                        lambda req, timeout=None: _Resp(_meta_json("Cool Mod")))
    today = datetime.now(timezone.utc).date().isoformat()
    regp = tmp_path / "r.yaml"
    reg = _registry._new_registry()
    e = _registry._new_entry("cool_mod", True)
    e["auto"].update(installed=True, nexus_id=7, id_state="guess", installed_name="Cool Mod",
                     name="Cool Mod", version="2.0", updated="2026-06-01", status="published",
                     checked_at=today, classification=_registry.UNCONFIRMED_LANE)
    reg["mods"].append(e)
    _registry.save_registry(reg, regp)
    _modlist.cmd_verify(types.SimpleNamespace(registry=str(regp), rescore=True))
    _modlist.cmd_refresh(_refresh_args(regp, force=False))
    a = _registry.load_registry(regp)["mods"][0]["auto"]
    assert a["id_state"] == "exact"
    assert a["classification"] != _registry.UNCONFIRMED_LANE, a["classification"]


# --------------------------------------------------------------------------- RG-5

@pytest.mark.xfail(strict=True, reason="AUDIT-2026-09-24 RG-5: _unquote cuts a QUOTED value at the "
                   "first ' #', leaving a dangling quote in the path")
def test_rg5_a_quoted_value_containing_space_hash_is_kept_whole(tmp_path):
    env = tmp_path / "x4-paths.env"
    env.write_text('X4_MODS="C:/My Mods #2/x4"\n', encoding="utf-8")
    assert _paths.parse_env_file(env)["X4_MODS"] == "C:/My Mods #2/x4"
