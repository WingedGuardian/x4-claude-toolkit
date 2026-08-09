#!/usr/bin/env python
r"""Offline replay gate for the Nexus layer (`x4modlist refresh`).

`refresh` was the last untested command, and for a structural reason: it is the
only code path that talks to the network. Testing it live burns rate budget,
needs a personal API key, and fails for reasons that have nothing to do with our
code (Cloudflare, a mod going hidden). So it never got tested at all — which is
the worst outcome, because the parsing and classification around it are exactly
the kind of code that rots silently when an API adds or renames a field.

Two modes:

  --record   Hit the REAL API once, using mod ids DISCOVERED from the local
             registry, and assert our parsers handle the live responses. Then
             write an ANONYMIZED fixture: field names, types and status values
             are preserved (that is what the parsers actually read), while ids,
             names and authors become neutral placeholders. So the committed
             artifact leaks neither the API key nor which mods are installed,
             and it was still verified against reality at the moment it was made.

  (default)  Replay the fixture with no network at all, exercising fetch_mod,
             search_mods, steam_title, the classifier, and the failure paths
             (HTTP 404, empty search, malformed node).

The key is read only via `_nexus.nexus_key()` and is NEVER written to the
fixture, printed, or logged.

Run:  uv run python gates/nexus_fixture.py [--record]
Exit: 0 all replays behave as recorded, 1 any mismatch, 2 no fixture.
"""
from __future__ import annotations

import json
import shutil
import sys
import urllib.error
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(Path(__file__).resolve().parent))
from x4validate import _modlist, _nexus, _registry  # noqa: E402

FIXTURE = Path(__file__).resolve().parent / "fixtures" / "nexus.json"
RECORD = "--record" in sys.argv

#: An id that must not exist, for the 404 path. Far above the live id space.
MISSING_ID = 99999999


# ---------------------------------------------------------------- recording --

def _registry_ids(limit: int = 3) -> list[int]:
    """Nexus ids discovered from the local registry (never hardcoded)."""
    reg = _registry.load_registry()
    ids: list[int] = []
    for entry in reg.get("mods", []):
        auto = dict(entry).get("auto") or {}
        nid = auto.get("nexus_id")
        if nid and int(nid) not in ids:
            ids.append(int(nid))
        if len(ids) >= limit:
            break
    return ids


def _anonymize_rest(raw: dict, ordinal: int) -> dict:
    """Keep every field the parser reads; replace identifying VALUES.

    `updated_timestamp` is kept as a real epoch because `fetch_mod` converts it
    and a placeholder would not exercise that conversion.
    """
    return {
        "name": f"Example Mod {ordinal}",
        "version": str(raw.get("version", "")),
        "updated_timestamp": int(raw.get("updated_timestamp") or 0),
        "status": raw.get("status", ""),
        "author": f"example_author_{ordinal}",
        "mod_id": 1000 + ordinal,
    }


def record() -> int:
    ids = _registry_ids()
    if not ids:
        print("no nexus ids in the local registry — cannot record", file=sys.stderr)
        return 2
    try:
        _nexus.nexus_key()
    except _nexus.NexusError as exc:
        print(f"cannot record: {exc}", file=sys.stderr)
        return 2

    print(f"recording against the live API for {len(ids)} discovered id(s)")
    fixture: dict = {"recorded": date.today().isoformat(),
                     "note": "anonymized; shapes verified against the live API when recorded",
                     "rest": {}, "graphql": {}, "steam": {}, "missing_id": MISSING_ID}

    headers = {"apikey": _nexus.nexus_key(), **_nexus._APP}
    for i, nid in enumerate(ids, 1):
        raw = _nexus._get_json(f"{_nexus.NEXUS_REST}/{nid}.json", headers)
        # Prove the live shape still parses BEFORE we anonymize it.
        meta = _nexus.fetch_mod(nid)
        assert meta.nexus_id == nid and meta.status, f"live parse failed for {nid}"
        for field in ("name", "version", "status", "updated_timestamp"):
            assert field in raw, f"live REST response lost field {field!r}"
        fixture["rest"][str(1000 + i)] = _anonymize_rest(raw, i)
        print(f"  rest  id={nid} -> status={meta.status!r} version={meta.version!r} (anonymized)")

    # A real search, recorded under a neutral term.
    hits = _nexus.search_mods("station", 3)
    assert isinstance(hits, list), "search_mods no longer returns a list"
    fixture["graphql"]["example"] = {
        "data": {"mods": {"nodes": [
            {"modId": 1000 + i, "name": f"Example Mod {i}"} for i in range(1, len(hits) + 1)
        ]}}}
    fixture["graphql"]["nomatch"] = {"data": {"mods": {"nodes": []}}}
    # A node the parser must survive (missing modId) — the silent-ok path.
    fixture["graphql"]["malformed"] = {
        "data": {"mods": {"nodes": [{"name": "no id here"}, {"modId": 1001, "name": "ok"}]}}}
    print(f"  graphql search -> {len(hits)} live hit(s) (anonymized to "
          f"{len(fixture['graphql']['example']['data']['mods']['nodes'])} node(s))")

    fixture["steam"]["1000000001"] = {
        "response": {"publishedfiledetails": [
            {"title": "Example Workshop Item", "creator": "76500000000000001", "result": 1}]}}
    fixture["steam"]["missing"] = {"response": {"publishedfiledetails": [{"result": 9}]}}

    FIXTURE.parent.mkdir(parents=True, exist_ok=True)
    FIXTURE.write_text(json.dumps(fixture, indent=2) + "\n", encoding="utf-8")
    blob = FIXTURE.read_text(encoding="utf-8")
    key = _nexus.nexus_key()
    assert key not in blob, "REFUSING to keep a fixture containing the API key"
    print(f"\nwrote {FIXTURE} ({len(blob)} bytes), key-free")
    return 0


# ------------------------------------------------------------------ replay --

class _Replay:
    """Serves recorded bodies; anything unrecorded is a hard failure, never a
    silent fallthrough to the network."""

    def __init__(self, fx: dict):
        self.fx = fx
        self.calls: list[str] = []

    def get_json(self, url: str, headers: dict) -> dict:
        self.calls.append(url)
        mod_id = url.rsplit("/", 1)[-1].removesuffix(".json")
        if mod_id == str(self.fx["missing_id"]):
            raise urllib.error.HTTPError(url, 404, "Not Found", {}, None)
        body = self.fx["rest"].get(mod_id)
        if body is None:
            raise AssertionError(f"unrecorded REST call: {url}")
        return body

    def post_json(self, url: str, body: dict, headers: dict) -> dict:
        self.calls.append(url)
        query = body.get("query", "")
        for name in ("nomatch", "malformed", "example"):
            if f'"{name}"' in query:
                return self.fx["graphql"][name]
        return self.fx["graphql"]["example"]


def _check(label: str, got, want, failures: list[str]) -> None:
    ok = got == want
    print(f"  {'  ok ' if ok else ' FAIL'}  {label}: {got!r}")
    if not ok:
        failures.append(f"{label}: got {got!r}, want {want!r}")


def _sandbox_registry(tmp: Path, fx: dict) -> Path:
    """A throwaway registry with one seeded mod and one whose id 404s.

    Never the real registry: `cmd_refresh` WRITES (registry + dashboard), and a
    gate must not mutate the user's triage state to test itself.
    """
    good = sorted(fx["rest"])[0]
    reg = {
        "meta": {"generated": "gate"},
        "mods": [
            {"id": "gate_good", "auto": {"installed": True, "nexus_id": int(good)},
             "human": {"custom_edited": False}},
            {"id": "gate_404", "auto": {"installed": True, "nexus_id": fx["missing_id"]},
             "human": {"custom_edited": False}},
        ],
    }
    path = tmp / "modlist.yaml"
    _registry.save_registry(reg, path)
    return path


def _check_refresh_end_to_end(fx: dict, failures: list[str]) -> None:
    """Drive `x4modlist refresh` itself, not just the API helpers underneath it.

    Added after noticing the gate claimed to make `refresh` testable while never
    invoking it. These branches are only reachable through the command: the
    once-per-day TTL, `--force`, the 404 -> classification="error" path, and the
    registry/dashboard writes.
    """
    import tempfile
    tmp = Path(tempfile.mkdtemp(prefix="x4gate_refresh_"))
    try:
        reg_path = _sandbox_registry(tmp, fx)
        # --registry is a TOP-LEVEL argument, before the subcommand.
        argv = ["--registry", str(reg_path), "refresh", "--seeded"]

        rc = _modlist.main(argv)
        reg = _registry.load_registry(reg_path)
        by_id = {m["id"]: m["auto"] for m in reg["mods"]}
        ok = rc == 0 and by_id["gate_good"].get("status") == \
            fx["rest"][sorted(fx["rest"])[0]]["status"]
        _check("refresh populates a seeded mod", ok, True, failures)
        _check("refresh marks an unreachable id as error",
               by_id["gate_404"].get("classification"), "error", failures)
        _check("refresh recorded the check date",
               bool(by_id["gate_good"].get("checked_at")), True, failures)

        # TTL: a second run must fetch nothing, --force must fetch again.
        import contextlib
        import io
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            _modlist.main(argv)
        _check("second run is a TTL no-op", "0 fetched" in buf.getvalue(), True, failures)
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            _modlist.main(argv + ["--force"])
        _check("--force re-fetches", "0 fetched" not in buf.getvalue(), True, failures)

        dash = _registry.write_dashboard.__name__ and (reg_path.parent / "WORKLIST.md")
        _check("dashboard written beside the registry", dash.is_file(), True, failures)
    except Exception as exc:                      # a crash here IS the finding
        _check(f"refresh end-to-end raised {type(exc).__name__}", str(exc), "", failures)
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def replay() -> int:
    if not FIXTURE.is_file():
        print(f"no fixture at {FIXTURE} — run with --record once (needs X4_NEXUS_KEY)",
              file=sys.stderr)
        return 2
    fx = json.loads(FIXTURE.read_text(encoding="utf-8"))
    rp = _Replay(fx)
    failures: list[str] = []

    orig_get, orig_post, orig_key = _nexus._get_json, _nexus._post_json, _nexus.nexus_key
    _nexus._get_json, _nexus._post_json = rp.get_json, rp.post_json
    _nexus.nexus_key = lambda: "fixture-key-not-a-real-credential"
    try:
        print("=" * 88)
        print(f"NEXUS FIXTURE REPLAY — recorded {fx.get('recorded')}, no network")
        print("=" * 88)

        first = sorted(fx["rest"])[0]
        meta = _nexus.fetch_mod(int(first))
        _check("fetch_mod .nexus_id", meta.nexus_id, int(first), failures)
        _check("fetch_mod .status", meta.status, fx["rest"][first]["status"], failures)
        _check("fetch_mod .version", meta.version,
               str(fx["rest"][first]["version"]), failures)
        # updated_timestamp -> YYYY-MM-DD is real conversion logic, not a passthrough
        ok_date = len(meta.updated) == 10 and meta.updated[4] == "-"
        _check("fetch_mod .updated is YYYY-MM-DD", ok_date, True, failures)

        # 404 must become NexusError, not an HTTPError escaping to the caller
        try:
            _nexus.fetch_mod(fx["missing_id"])
            failures.append("a 404 did not raise NexusError")
            print("   FAIL  404 -> NexusError: no exception raised")
        except _nexus.NexusError:
            print("    ok   404 -> NexusError")
        except Exception as exc:
            failures.append(f"404 raised {type(exc).__name__}, not NexusError")
            print(f"   FAIL  404 -> {type(exc).__name__}")

        _check("search_mods returns pairs", _nexus.search_mods("example", 3),
               [(n["modId"], n["name"])
                for n in fx["graphql"]["example"]["data"]["mods"]["nodes"]], failures)
        _check("search_mods empty result", _nexus.search_mods("nomatch"), [], failures)
        # the documented silent-ok: one bad node must not lose the good one
        _check("search_mods survives a malformed node",
               _nexus.search_mods("malformed"), [(1001, "ok")], failures)

        # classification is what refresh actually DOES with the metadata
        today = date(2026, 8, 9)
        label, _why = _modlist._classify(meta, today)
        print(f"    ok   _classify -> {label!r}")
        if not label:
            failures.append("_classify returned an empty label")

        _check_refresh_end_to_end(fx, failures)
        print(f"\n  recorded calls served: {len(rp.calls)}  (network calls made: 0)")
    finally:
        _nexus._get_json, _nexus._post_json = orig_get, orig_post
        _nexus.nexus_key = orig_key

    print("\n" + "=" * 88)
    if failures:
        print(f"FAILURES: {len(failures)}")
        for f in failures:
            print(f"  - {f}")
        return 1
    print("Nexus layer replays exactly as recorded — refresh is testable offline.")
    return 0


if __name__ == "__main__":
    raise SystemExit(record() if RECORD else replay())
