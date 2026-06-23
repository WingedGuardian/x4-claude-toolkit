"""Nexus + Steam API clients. API-FIRST: all Nexus access is via the API, NEVER scraped.

- Nexus metadata by id : v1 REST   /v1/games/x4foundations/mods/{id}.json   (apikey header)
- Nexus name -> id     : v2 GraphQL /v2/graphql  (nameStemmed filter, gameId 2659)
- Steam ws_ title      : keyless ISteamRemoteStorage/GetPublishedFileDetails
"""

from __future__ import annotations

import json
import os
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass
from datetime import datetime, timezone

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
    k = os.environ.get("X4_NEXUS_KEY")
    if not k:
        raise NexusError("X4_NEXUS_KEY not set (Nexus personal API key)")
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
        return None
    details = (((d or {}).get("response") or {}).get("publishedfiledetails") or [])
    if details and details[0].get("title"):
        return details[0]["title"], str(details[0].get("creator", ""))
    return None
