"""The live Codex e2e rows must not be satisfiable by the model ECHOING the prompt.

v4.0.0 review R4-8: the `validator-context` row passed when the transcript contained
"X4 VALIDATION" (case-folded) -- and its own prompt asked for "any message about X4
validation", which `codex exec` echoes into the very transcript the check reads. The row could
not go red. The check now looks only for strings the VALIDATOR emits, after removing the
prompt from the transcript, and the prompt no longer contains any of them.

No Codex runs here: the rows' check functions are pure over a transcript string.
"""
from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[3]
SCRIPT = REPO / "scripts" / "codex-e2e.py"


@pytest.fixture(scope="module")
def e2e():
    if not SCRIPT.is_file():
        pytest.skip("no scripts/codex-e2e.py")
    spec = importlib.util.spec_from_file_location("codex_e2e_rows", SCRIPT)
    mod = importlib.util.module_from_spec(spec)
    sys.modules["codex_e2e_rows"] = mod
    spec.loader.exec_module(mod)
    return mod


def _check(e2e, text):
    prompt, check, _blocks = e2e.ROWS["validator-context"]
    return check(None, text)


def test_the_ECHOED_prompt_alone_does_NOT_satisfy_the_validator_row(e2e):
    prompt = e2e.ROWS["validator-context"][0]
    transcript = "user\n" + prompt + "\ncodex\nI received no such message.\n"
    assert not _check(e2e, transcript)


@pytest.mark.parametrize("said", ["x4validate (advisory) flagged this edit:",
                                  "VALIDATION NOT COMPLETED: one or more requested checks could not run",
                                  "X4 VALIDATION DID NOT RUN for dev/mymod/libraries/wares.xml: x"])
def test_TWIN_a_message_the_VALIDATOR_emits_does(e2e, said):
    prompt = e2e.ROWS["validator-context"][0]
    assert _check(e2e, "user\n" + prompt + "\ncodex\nThe message was: " + said + "\n")


def test_the_prompt_names_none_of_the_markers(e2e):
    prompt = e2e.ROWS["validator-context"][0]
    for marker in e2e.VALIDATOR_MARKERS:
        assert marker.lower() not in prompt.lower(), marker
