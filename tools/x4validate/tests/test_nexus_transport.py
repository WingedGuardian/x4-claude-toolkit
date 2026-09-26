"""The Nexus transport maps every failure, and a run-wide one stops the run (RG-1, RG-2).

`test_audit0924_runtime.py` pins the two headline shapes (a network drop mid-refresh keeps
what was fetched; a 401 stops the run with every lane intact). These pin the parts it does
not reach: the rate-limit paths -- an HTTP 429, and a response whose `X-RL-*-Remaining`
header says the budget is spent, which must stop the NEXT call before it is sent -- and the
stub seam: a test or gate that replaces `_get_json` must get the same mapping as the real
transport. No network: `urlopen` is stubbed throughout.
"""
from __future__ import annotations

import io
import json
import urllib.error

import pytest

from x4validate import _nexus


class _Resp(io.BytesIO):
    def __init__(self, body: bytes, headers: dict | None = None):
        super().__init__(body)
        self.headers = headers or {}

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


_META = json.dumps({"name": "M", "version": "1", "updated_timestamp": 0,
                    "status": "published", "author": "a"}).encode()


@pytest.fixture(autouse=True)
def _key_and_clean_budget(monkeypatch):
    monkeypatch.setenv("X4_NEXUS_KEY", "test-key-not-real")
    _nexus.reset_rate_limit()
    yield
    _nexus.reset_rate_limit()


def test_http_429_is_a_run_wide_stop(monkeypatch):
    def urlopen(req, timeout=None):
        raise urllib.error.HTTPError(req.full_url, 429, "Too Many Requests", {}, None)
    monkeypatch.setattr(_nexus.urllib.request, "urlopen", urlopen)
    with pytest.raises(_nexus.NexusRateLimited):
        _nexus.fetch_mod(1)


def test_a_spent_budget_header_stops_the_NEXT_call_before_it_is_sent(monkeypatch):
    calls = []

    def urlopen(req, timeout=None):
        calls.append(req.full_url)
        return _Resp(_META, {"X-RL-Hourly-Remaining": "0", "X-RL-Daily-Remaining": "500"})
    monkeypatch.setattr(_nexus.urllib.request, "urlopen", urlopen)
    assert _nexus.fetch_mod(1).name == "M"          # the answer that reported 0 is still valid
    with pytest.raises(_nexus.NexusRateLimited, match="X-RL-Hourly-Remaining"):
        _nexus.fetch_mod(2)
    assert len(calls) == 1, "the call after a spent budget must not reach the network"


def test_a_budget_above_zero_does_not_stop_anything(monkeypatch):
    """The twin: without it the test above passes on a transport that refuses always."""
    monkeypatch.setattr(_nexus.urllib.request, "urlopen",
                        lambda req, timeout=None: _Resp(_META, {"X-RL-Hourly-Remaining": "7"}))
    assert _nexus.fetch_mod(1).name == "M"
    assert _nexus.fetch_mod(2).name == "M"


@pytest.mark.parametrize("exc, kind", [
    (urllib.error.HTTPError("u", 404, "Not Found", {}, None), _nexus.NexusError),
    (urllib.error.HTTPError("u", 401, "Unauthorized", {}, None), _nexus.NexusAuthError),
    (urllib.error.URLError("no route"), _nexus.NexusUnreachable),
    (TimeoutError("timed out"), _nexus.NexusUnreachable),
    (json.JSONDecodeError("x", "<html>", 0), _nexus.NexusError),
])
def test_a_stubbed_transport_gets_the_same_mapping(monkeypatch, exc, kind):
    """Gates and tests replace `_get_json` directly; its failures must still be mapped."""
    def boom(url, headers):
        raise exc
    monkeypatch.setattr(_nexus, "_get_json", boom)
    with pytest.raises(kind):
        _nexus.fetch_mod(1)


def test_only_run_wide_causes_are_fatal():
    assert issubclass(_nexus.NexusAuthError, _nexus.NexusFatal)
    assert issubclass(_nexus.NexusRateLimited, _nexus.NexusFatal)
    assert issubclass(_nexus.NexusUnreachable, _nexus.NexusFatal)
    assert not issubclass(_nexus.NexusFatal, _nexus.NexusAuthError)
    assert issubclass(_nexus.NexusFatal, _nexus.NexusError)   # old `except NexusError` still catches
