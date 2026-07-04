"""x4modlist — mod-registry CLI: ingest the modlist, refresh upstream data, triage.

API-FIRST: all Nexus access is via the API (never scrape). See _nexus.py.
"""

from __future__ import annotations

import argparse
import re
import sys
from datetime import date, datetime, timezone
from pathlib import Path

from . import _nexus, _registry

NINE_ZERO = date(2026, 6, 10)  # X4 9.00 release
CHURN_DAYS = 14


def _now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%MZ")


def _dash_path(reg_path) -> Path:
    """WORKLIST.md sits next to whichever registry we're using."""
    base = reg_path if reg_path else _registry.DEFAULT_REGISTRY
    return Path(base).parent / "WORKLIST.md"


def _classify(meta: "_nexus.ModMeta", today: date, is_custom: bool = False) -> tuple[str, str]:
    """(classification, settled) from API truth only. 9.0-readiness is NOT in the
    API, so post-9.0-update is a *proxy*; pre-9.0 mods are 'predates-9.0/review'.

    removed/hidden means "unavailable to DOWNLOAD from Nexus" — for a mod the user
    is NOT custom-editing that's a real drop (abandoned/pulled). But if the mod is
    marked custom_edited (a locally-maintained fork, e.g. an author who hid their
    page mid-update while we keep porting our own copy), "drop" is actively wrong
    guidance — surface it as its own lane instead."""
    if meta.status in ("removed", "hidden"):
        if is_custom:
            return "custom-local", "n/a — upstream unavailable, local fork maintained"
        return "drop", "unavailable"
    try:
        upd = date.fromisoformat(meta.updated)
    except (ValueError, TypeError):
        return "untriaged", "unknown"
    if upd >= NINE_ZERO:
        if (today - upd).days <= CHURN_DAYS:
            return "churning", "churning"
        return "ready", "stable"
    return "predates-9.0", "unknown"


def _humanize(content_id: str) -> str:
    """Turn a folder-id into a searchable name: split camelCase + underscores.
    e.g. kuerteeSocialStandingsAndCitizenships -> 'kuertee Social Standings And Citizenships'."""
    s = content_id.replace("_", " ")
    s = re.sub(r"(?<=[a-z0-9])(?=[A-Z])", " ", s)  # camelCase boundary
    return re.sub(r"\s+", " ", s).strip()


def _strip_author_label(name: str) -> str:
    """Manifest names often prefix the real title with an author/category label,
    e.g. 'kuertee: Ship scanner' or 'kuertee UI: Boarding operation notifications'
    -> 'Ship scanner' / 'Boarding operation notifications' (the label usually
    isn't in the Nexus mod title)."""
    if ":" in name:
        prefix, rest = name.split(":", 1)
        if len(prefix.split()) <= 3 and rest.strip():
            return rest.strip()
    return name.strip()


def _manifest_name_variants(name: str) -> list[str]:
    """Progressive fallback variants for a manifest title, most-specific first:
    full name -> drop a ' - <suffix>' qualifier (e.g. 'Vibrant Engine Plumes -
    Divinity Edition' -> 'Vibrant Engine Plumes') -> drop a trailing ALL-CAPS
    qualifier word (e.g. 'Terran Beam Weapons VRO' -> 'Terran Beam Weapons')."""
    variants = [name]
    if " - " in name:
        variants.append(name.split(" - ", 1)[0].strip())
    words = name.split()
    if len(words) > 1 and words[-1].isupper() and 2 <= len(words[-1]) <= 5:
        variants.append(" ".join(words[:-1]))
    return variants


def _search_with_fallback(name_hint: str) -> list[tuple[int, str]]:
    """Search; if empty and multi-word, retry dropping the leading token (often
    an author prefix not present in the Nexus title)."""
    hits = _nexus.search_mods(name_hint, 5)
    if not hits and " " in name_hint:
        hits = _nexus.search_mods(name_hint.split(" ", 1)[1], 5)
    return hits


def _resolve_identity(content_id: str, auto) -> int | None:
    """A3 cascade (API-first): ws_ -> Steam title -> Nexus search; named -> prefer
    the mod's OWN manifest name (`installed_name`, read straight from its
    content.xml — far more reliable than guessing from the folder/content id) ->
    else a humanized-id guess -> Nexus search, with an author-prefix-drop retry.
    Auto-match (top hit); flagged for spot-check. Never scrapes Nexus."""
    if content_id.startswith("ws_"):
        name_hint = content_id
        t = _nexus.steam_title(content_id)
        if t:
            name_hint = t[0]
            auto["steam_title"] = t[0]
        candidates = [name_hint]
    else:
        installed_name = auto.get("installed_name")
        candidates = (_manifest_name_variants(_strip_author_label(installed_name))
                     if installed_name else []) + [_humanize(content_id)]

    hits, used_hint = [], None
    try:
        for hint in candidates:
            hits = _search_with_fallback(hint)
            if hits:
                used_hint = hint
                break
    except _nexus.NexusError:
        return None
    if hits:
        auto["resolve"] = "auto (spot-check)"
        auto["resolve_hint"] = used_hint
        # Keep top candidates so the user can spot-check / correct cheaply.
        auto["candidates"] = [f"{mid}:{nm}" for mid, nm in hits[:3]]
        return hits[0][0]
    return None


def cmd_ingest(args) -> int:
    """Two passes: (1) the profile content.xml — SECONDARY, just backfills a
    registry row for any historically-tracked id so nothing is silently dropped;
    (2) the installed-folder scan — PRIMARY, authoritative for installed/enabled/
    version/name/author. Pass 2 always runs last so it wins."""
    reg_path = Path(args.registry) if args.registry else None
    reg = _registry.load_registry(reg_path)

    added = existing = 0
    if not args.installed_only:
        content = Path(args.content) if args.content else None
        ids = _registry.ingest_content_xml(content)
        added, existing = _registry.merge(reg, ids, enabled_only=not args.all)

    dirs = [Path(d) for d in args.dirs.split(",")] if args.dirs else None
    installed = _registry.scan_installed(dirs)
    new, matched, not_installed = _registry.merge_installed(reg, installed)

    reg["meta"]["game_build"] = args.build
    reg["meta"]["generated"] = _now()
    _registry.save_registry(reg, reg_path)
    dash = _registry.write_dashboard(reg, _dash_path(reg_path))
    print(f"profile content.xml (cross-check): +{added} new, {existing} existing")
    print(f"installed folders (PRIMARY, {len(installed)} found): "
          f"+{new} new to registry, {matched} matched prior research, "
          f"{not_installed} tracked-but-not-installed")
    print(f"registry:  {reg_path or _registry.DEFAULT_REGISTRY}")
    print(f"dashboard: {dash}")
    return 0


def cmd_refresh(args) -> int:
    reg_path = Path(args.registry) if args.registry else None
    reg = _registry.load_registry(reg_path)
    today = datetime.now(timezone.utc).date()
    want = set(args.ids.split(",")) if args.ids else None

    if want:
        # Explicit --ids targets a mod regardless of installed status (e.g. to
        # check an old-modlist mod's upstream status before re-acquiring it).
        mods = [m for m in reg["mods"] if m["id"] in want]
    else:
        mods = [m for m in reg["mods"] if m["auto"].get("installed")]
    if args.seeded:
        mods = [m for m in mods if m["auto"].get("nexus_id")]
    if args.limit:
        mods = mods[: args.limit]

    resolved = fetched = errors = 0
    for m in mods:
        a = m["auto"]
        if a.get("checked_at") == today.isoformat() and not args.force:
            continue  # already refreshed today (TTL)
        nid = a.get("nexus_id")
        if not nid and not args.no_resolve:
            nid = _resolve_identity(m["id"], a)
            if nid:
                a["nexus_id"] = nid
                resolved += 1
        if not nid:
            a["classification"] = "untriaged"
            continue
        try:
            meta = _nexus.fetch_mod(nid)
        except _nexus.NexusError as exc:
            a["classification"] = "error"
            a["error"] = str(exc)
            errors += 1
            continue
        a["name"], a["version"], a["updated"] = meta.name, meta.version, meta.updated
        a["status"], a["author"] = meta.status, meta.author
        a["checked_at"] = today.isoformat()
        a["classification"], a["settled"] = _classify(meta, today, m["human"].get("custom_edited", False))
        fetched += 1

    _registry.save_registry(reg, reg_path)
    dash = _registry.write_dashboard(reg, _dash_path(reg_path))
    print(f"refresh: {fetched} fetched, {resolved} newly id-resolved, {errors} errors "
          f"({len(mods)} processed)")
    print(f"dashboard: {dash}")
    return 0


def cmd_dashboard(args) -> int:
    reg_path = Path(args.registry) if args.registry else None
    reg = _registry.load_registry(reg_path)
    dash = _registry.write_dashboard(reg, _dash_path(reg_path))
    print(f"dashboard regenerated: {dash}")
    return 0


def _find(reg, content_id):
    for m in reg["mods"]:
        if m["id"] == content_id:
            return m
    return None


def cmd_needs_review(args) -> int:
    reg = _registry.load_registry(Path(args.registry) if args.registry else None)
    review = _registry.needs_review(reg)
    if not review:
        print("nothing needs spot-check")
        return 0
    print(f"{len(review)} need spot-check (resolve <id> <nexus_id> | ignore <id>):")
    for m in sorted(review, key=lambda x: x["id"]):
        a = m["auto"]
        cur = f"{a.get('nexus_id')}:{a.get('name')}" if a.get("nexus_id") else "unresolved"
        cands = " | ".join(a.get("candidates") or [])
        print(f"  {m['id']:42} -> {cur}" + (f"   candidates: {cands}" if cands else ""))
    return 0


def cmd_resolve(args) -> int:
    reg_path = Path(args.registry) if args.registry else None
    reg = _registry.load_registry(reg_path)
    m = _find(reg, args.id)
    if m is None:
        print(f"not in registry: {args.id}", file=sys.stderr)
        return 2
    a = m["auto"]
    a["nexus_id"] = args.nexus_id
    a["resolve"] = "manual"
    a.pop("candidates", None)
    try:
        meta = _nexus.fetch_mod(args.nexus_id)
    except _nexus.NexusError as exc:
        _registry.save_registry(reg, reg_path)
        print(f"set nexus_id but fetch failed: {exc}", file=sys.stderr)
        return 1
    today = datetime.now(timezone.utc).date()
    a["name"], a["version"], a["updated"] = meta.name, meta.version, meta.updated
    a["status"], a["author"] = meta.status, meta.author
    a["checked_at"] = today.isoformat()
    a["classification"], a["settled"] = _classify(meta, today, m["human"].get("custom_edited", False))
    _registry.save_registry(reg, reg_path)
    _registry.write_dashboard(reg, _dash_path(reg_path))
    print(f"resolved {args.id} -> {args.nexus_id} {meta.name!r} [{a['classification']}]")
    return 0


def cmd_ignore(args) -> int:
    reg_path = Path(args.registry) if args.registry else None
    reg = _registry.load_registry(reg_path)
    m = _find(reg, args.id)
    if m is None:
        print(f"not in registry: {args.id}", file=sys.stderr)
        return 2
    m["human"]["ignored"] = True
    if args.reason:
        m["human"]["notes"] = args.reason
    _registry.save_registry(reg, reg_path)
    _registry.write_dashboard(reg, _dash_path(reg_path))
    print(f"ignored {args.id}")
    return 0


def cmd_mark(args) -> int:
    reg_path = Path(args.registry) if args.registry else None
    reg = _registry.load_registry(reg_path)
    m = _find(reg, args.id)
    if m is None:
        print(f"not in registry: {args.id}", file=sys.stderr)
        return 2
    m["human"]["custom_edited"] = True
    if args.notes:
        m["human"]["notes"] = args.notes
    _registry.save_registry(reg, reg_path)
    print(f"marked {args.id} custom_edited=True")
    return 0


def main(argv: list[str] | None = None) -> int:
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except (AttributeError, ValueError):
        pass
    p = argparse.ArgumentParser(prog="x4modlist", description="X4 mod-registry triage tool (API-first).")
    p.add_argument("--registry", help="path to modlist.yaml (default: dev\\_registry\\modlist.yaml)")
    sub = p.add_subparsers(dest="cmd", required=True)

    pi = sub.add_parser("ingest", help="scan installed extension folders (PRIMARY) into the "
                        "registry, cross-checked against the profile content.xml")
    pi.add_argument("--content", help="path to profile content.xml (secondary cross-check)")
    pi.add_argument("--dirs", help="comma-separated extension dirs to scan "
                    "(default: game-root extensions\\, profile extensions\\, Steam Workshop)")
    pi.add_argument("--installed-only", action="store_true", dest="installed_only",
                    help="skip the profile content.xml cross-check pass entirely")
    pi.add_argument("--build", default="23660954", help="current game build id")
    pi.add_argument("--all", action="store_true",
                    help="content.xml cross-check: include disabled extensions too")
    pi.set_defaults(func=cmd_ingest)

    pr = sub.add_parser("refresh", help="refresh upstream metadata via Nexus/Steam API")
    pr.add_argument("--ids", help="comma-separated content ids to refresh (default: all enabled)")
    pr.add_argument("--seeded", action="store_true", help="only mods that already have a nexus_id")
    pr.add_argument("--limit", type=int, help="cap how many mods to process (API-call safety)")
    pr.add_argument("--force", action="store_true", help="ignore the once-per-day TTL")
    pr.add_argument("--no-resolve", action="store_true", help="skip A3 identity resolution")
    pr.set_defaults(func=cmd_refresh)

    pd = sub.add_parser("dashboard", help="regenerate WORKLIST.md from the registry")
    pd.set_defaults(func=cmd_dashboard)

    pn = sub.add_parser("needs-review", help="list entries needing a spot-check decision")
    pn.set_defaults(func=cmd_needs_review)

    prs = sub.add_parser("resolve", help="manually set/confirm a mod's Nexus id (+fetch)")
    prs.add_argument("id", help="content.xml extension id")
    prs.add_argument("nexus_id", type=int, help="the correct Nexus mod id")
    prs.set_defaults(func=cmd_resolve)

    pig = sub.add_parser("ignore", help="mark a junk/personal mod out of the active worklist")
    pig.add_argument("id", help="content.xml extension id")
    pig.add_argument("--reason", help="note why")
    pig.set_defaults(func=cmd_ignore)

    pm = sub.add_parser("mark", help="mark a mod as custom-edited (for /x4-update-mod)")
    pm.add_argument("id", help="content.xml extension id")
    pm.add_argument("--custom", action="store_true", help="(implied) set custom_edited")
    pm.add_argument("--notes", help="what you edited")
    pm.set_defaults(func=cmd_mark)

    args = p.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
