"""Nexus + Steam API clients. API-FIRST: all Nexus access is via the API, NEVER scraped.

- Nexus metadata by id : v1 REST   /v1/games/x4foundations/mods/{id}.json   (apikey header)
- Nexus name -> id     : v2 GraphQL /v2/graphql  (nameStemmed filter, gameId 2659)
- Steam ws_ title      : keyless ISteamRemoteStorage/GetPublishedFileDetails
"""

from __future__ import annotations

import json
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass
from datetime import datetime, timezone

from x4validate import _paths

NEXUS_REST = "https://api.nexusmods.com/v1/games/x4foundations/mods"
NEXUS_GQL = "https://api.nexusmods.com/v2/graphql"
STEAM_GPFD = "https://api.steampowered.com/ISteamRemoteStorage/GetPublishedFileDetails/v1/"
X4_GAMEID = "2659"
# A real User-Agent matters: the GraphQL endpoint is behind Cloudflare and 403s
# urllib's default "Python-urllib/x.y" UA.
_APP = {"Application-Name": "x4modlist", "Application-Version": "0.1",
        "User-Agent": "x4modlist/0.1 (+X4 mod registry tool)"}


class NexusError(Exception):
    pass


def nexus_key() -> str:
    """The personal API key, from the environment OR `.claude/x4-paths.env`.

    Resolved through `_paths`, not `os.environ`: `setup.sh` tells users they may
    put `X4_NEXUS_KEY` in the config file, and reading only the environment made
    that documented placement silently ineffective. `value()` (not `path_value()`)
    because a key is not a path and must come back byte-for-byte.
    """
    k = _paths.value("X4_NEXUS_KEY")
    if not k:
        raise NexusError("X4_NEXUS_KEY not set (Nexus personal API key). Export it, "
                         "or add it to .claude/x4-paths.env.")
    return k


def _get_json(url: str, headers: dict) -> dict:
    req = urllib.request.Request(url, headers=headers)
    with urllib.request.urlopen(req, timeout=30) as r:
        return json.load(r)


def _post_json(url: str, body: dict, headers: dict) -> dict:
    data = json.dumps(body).encode()
    req = urllib.request.Request(url, data=data,
                                 headers={"Content-Type": "application/json", **headers}, method="POST")
    with urllib.request.urlopen(req, timeout=30) as r:
        return json.load(r)


#: ACCOUNT-WIDE: every mod the key's account tracks, across every game. Filtering
#: it to one game is a NARROWING STEP, which is why `fetch_tracked` returns the
#: denominator alongside the kept ids rather than a bare list.
NEXUS_TRACKED = "https://api.nexusmods.com/v1/user/tracked_mods.json"


@dataclass
class Tracked:
    """Tracked mods for ONE game, carrying the account-wide denominator.

    `ids` alone would read as the whole answer. MEASURED 2026-08-27 on a live
    key: 1,616 tracked rows across 9 domains, of which 413 are x4foundations —
    so a bare "413" hides three quarters of what the endpoint returned, and an
    empty `ids` would be indistinguishable from "you track nothing at all".
    """
    ids: list[int]            # deduped, sorted, for the requested domain
    kept: int                 # len(ids) — stated so the pair reads as a fraction
    total: int                # rows returned ACROSS ALL GAMES: the denominator
    domains: dict[str, int]   # per-domain counts, so the exclusion is nameable
    malformed: int            # rows dropped for having no usable mod_id


def fetch_tracked(domain: str = "x4foundations") -> Tracked:
    """Mods the account TRACKS on Nexus, filtered to *domain*.

    Tracking is a SUPERSET of installing and a different question from either
    "what is on disk" or "what is enabled": it is what the user asked Nexus to
    watch. That makes it the right source for two things `_registry` cannot
    answer — mods followed but never installed (candidates), and mods installed
    but NOT followed (updates nobody will hear about).

    Raises rather than returning an empty result when the payload is not a list.
    A shape change upstream must be a NON-ANSWER; rendering it as "you track 0"
    is the absence-versus-non-answer confusion this toolkit exists to refuse.
    """
    rows = _get_json(NEXUS_TRACKED, {"apikey": nexus_key(), **_APP})
    if not isinstance(rows, list):
        raise NexusError(
            f"unexpected payload from {NEXUS_TRACKED}: expected a list, got "
            f"{type(rows).__name__}. Refusing to report a count from a shape "
            "this function does not understand.")
    domains: dict[str, int] = {}
    ids: set[int] = set()
    malformed = 0
    for r in rows:
        d = r.get("domain_name") if isinstance(r, dict) else None
        if d:
            domains[d] = domains.get(d, 0) + 1
        if d != domain:
            continue
        raw = r.get("mod_id")
        # A missing key must be COUNTED, never silently skipped: `el.get(...)`
        # dropping rows quietly is a registered defect shape in this workspace.
        try:
            ids.add(int(raw))
        except (TypeError, ValueError):
            malformed += 1
    out = sorted(ids)
    return Tracked(ids=out, kept=len(out), total=len(rows),
                   domains=domains, malformed=malformed)


@dataclass
class ModMeta:
    nexus_id: int
    name: str
    version: str
    updated: str  # YYYY-MM-DD
    status: str   # published | removed | ...
    author: str


def fetch_mod(nexus_id: int) -> ModMeta:
    """v1 REST metadata-by-id. Raises NexusError on HTTP failure."""
    h = {"apikey": nexus_key(), **_APP}
    try:
        m = _get_json(f"{NEXUS_REST}/{int(nexus_id)}.json", h)
    except urllib.error.HTTPError as exc:
        raise NexusError(f"fetch_mod({nexus_id}) HTTP {exc.code}") from exc
    ts = int(m.get("updated_timestamp") or 0)
    upd = datetime.fromtimestamp(ts, timezone.utc).strftime("%Y-%m-%d") if ts else ""
    return ModMeta(int(nexus_id), m.get("name", ""), str(m.get("version", "")),
                   upd, m.get("status", ""), m.get("author", ""))


@dataclass
class FileMeta:
    """One FILE on a mod page.

    Exists because a mod is not always a page. Plenty of add-ons ship as a file on
    someone else's mod page, and for those the page's own `version` is not the
    add-on's version — it tracks whatever the page owner last uploaded. Comparing
    an installed add-on against the page version silently answers a different
    question than the one asked.
    """
    file_id: int
    mod_id: int
    name: str
    version: str
    uploaded: str  # YYYY-MM-DD
    category: str  # MAIN | OPTIONAL | OLD_VERSION | ARCHIVED | ...


def fetch_files(nexus_id: int) -> list[FileMeta]:
    """Every file on a mod page, newest-uploaded last (API order preserved)."""
    h = {"apikey": nexus_key(), **_APP}
    try:
        d = _get_json(f"{NEXUS_REST}/{int(nexus_id)}/files.json", h)
    except urllib.error.HTTPError as exc:
        raise NexusError(f"fetch_files({nexus_id}) HTTP {exc.code}") from exc
    out = []
    for f in (d or {}).get("files") or []:
        try:
            out.append(FileMeta(int(f["file_id"]), int(nexus_id), f.get("name", ""),
                                str(f.get("version", "")),
                                str(f.get("uploaded_time", ""))[:10],
                                f.get("category_name") or ""))
        except (KeyError, TypeError, ValueError):
            # silent-ok: one malformed entry in a file listing. Callers that need a
            # SPECIFIC file use fetch_file(), which raises when its id is absent —
            # so a dropped row here can never render as "that file is gone".
            continue
    return out


def fetch_file(nexus_id: int, file_id: int) -> FileMeta:
    """One file by id.

    Raises NexusError when the id is not on the page — which is real information,
    not a lookup failure: an add-on file that has been superseded and archived off
    the page is exactly the "you are running something upstream no longer offers"
    signal the registry should surface, so it must never be swallowed.
    """
    for f in fetch_files(nexus_id):
        if f.file_id == int(file_id):
            return f
    raise NexusError(f"file {file_id} is not listed on mod {nexus_id} "
                     f"(superseded, archived, or the wrong page)")


def search_mods(name: str, count: int = 5) -> list[tuple[int, str]]:
    """v2 GraphQL name search (nameStemmed, X4). Returns [(mod_id, name), ...] best-first."""
    safe = json.dumps(name)  # JSON-quoted+escaped GraphQL string literal
    query = ('query { mods(filter: {gameId: [{value: "%s"}], nameStemmed: [{value: %s}]}, '
             'count: %d) { nodes { modId name } } }' % (X4_GAMEID, safe, count))
    try:
        res = _post_json(NEXUS_GQL, {"query": query}, {"apikey": nexus_key(), **_APP})
    except urllib.error.HTTPError as exc:
        raise NexusError(f"search_mods({name!r}) HTTP {exc.code}") from exc
    nodes = (((res or {}).get("data") or {}).get("mods") or {}).get("nodes") or []
    out = []
    for n in nodes:
        try:
            out.append((int(n["modId"]), n.get("name", "")))
        except (KeyError, TypeError, ValueError):
            # silent-ok: one malformed node in a GraphQL search result. The result
            # is a ranked suggestion list, not a denominator — a dropped candidate
            # cannot turn into a false negative about the local modlist.
            continue
    return out


def steam_title(ws_number: str) -> tuple[str, str] | None:
    """Keyless Steam Workshop title lookup. Returns (title, creator_steamid) or None."""
    ws_number = str(ws_number).removeprefix("ws_")
    form = urllib.parse.urlencode({"itemcount": "1", "publishedfileids[0]": ws_number}).encode()
    req = urllib.request.Request(STEAM_GPFD, data=form, method="POST")
    try:
        with urllib.request.urlopen(req, timeout=30) as r:
            d = json.load(r)
    except urllib.error.HTTPError:
        # silent-ok: None is the documented "no answer from Steam" sentinel and the
        # caller distinguishes it from a title of "". Network absence is not data.
        return None
    details = (((d or {}).get("response") or {}).get("publishedfiledetails") or [])
    if details and details[0].get("title"):
        return details[0]["title"], str(details[0].get("creator", ""))
    return None
