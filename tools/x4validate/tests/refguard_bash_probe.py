"""Run the three native Git Bash ACL probes without backup/restore bypass rights.

Copied from the scratch diagnostic measured in hosted run 37844985751. Only a
disposable Python child loses these two privileges; the pytest token is untouched.
This is not full unelevation. All other token attributes remain unchanged.
"""
from __future__ import annotations

import ctypes
from ctypes import wintypes as w
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile

NAMES = ("SeBackupPrivilege", "SeRestorePrivilege")
COMMANDS = {
    "bash_redirect": 'echo x > "$T/libraries/wares.xml"',
    "rm_f": 'rm -f "$T/libraries/wares.xml"',
    "rm_rf_tree": 'rm -rf "$T/libraries"',
}


def run_probe(root, env, name):
    result = subprocess.run([sys.executable, str(Path(__file__).resolve()), str(root), name],
                            env=env, capture_output=True, text=True)
    assert result.returncode == 0, "isolated Git Bash probe did not run (rc %d)" % result.returncode
    data = json.loads(result.stdout)
    assert set(data["token_after"]) == set(NAMES)
    assert not any(v["present"] for v in data["token_after"].values())
    return data


def child(root, name):
    assert os.name == "nt"
    root = Path(root).resolve()
    temp = Path(tempfile.gettempdir()).resolve()
    sandbox = Path(os.environ["X4_REFGUARD_SANDBOX"]).resolve()
    assert sandbox != temp and sandbox.is_relative_to(temp)
    assert root != sandbox and root.is_relative_to(sandbox)
    assert Path(os.environ["T"]).resolve() == root
    assert name in COMMANDS
    k = ctypes.WinDLL("kernel32", use_last_error=True)
    a = ctypes.WinDLL("advapi32", use_last_error=True)
    k.GetCurrentProcess.restype = w.HANDLE
    k.CloseHandle.argtypes = [w.HANDLE]
    a.OpenProcessToken.argtypes = [w.HANDLE, w.DWORD, ctypes.POINTER(w.HANDLE)]
    a.GetTokenInformation.argtypes = [w.HANDLE, ctypes.c_int, ctypes.c_void_p, w.DWORD, ctypes.POINTER(w.DWORD)]

    class LUID(ctypes.Structure):
        _fields_ = [("low", w.DWORD), ("high", w.LONG)]

    class ENTRY(ctypes.Structure):
        _fields_ = [("luid", LUID), ("attributes", w.DWORD)]

    class PRIVS(ctypes.Structure):
        _fields_ = [("count", w.DWORD), ("entries", ENTRY * 1)]

    a.LookupPrivilegeValueW.argtypes = [w.LPCWSTR, w.LPCWSTR, ctypes.POINTER(LUID)]
    a.AdjustTokenPrivileges.argtypes = [w.HANDLE, w.BOOL, ctypes.POINTER(PRIVS), w.DWORD, ctypes.c_void_p, ctypes.c_void_p]
    token = w.HANDLE()
    assert a.OpenProcessToken(k.GetCurrentProcess(), 0x20 | 0x08, ctypes.byref(token)), ctypes.get_last_error()
    luids = {}
    for privilege in NAMES:
        value = LUID()
        assert a.LookupPrivilegeValueW(None, privilege, ctypes.byref(value))
        luids[privilege] = value

    def snapshot():
        size = w.DWORD()
        a.GetTokenInformation(token, 3, None, 0, ctypes.byref(size))
        assert size.value
        buf = ctypes.create_string_buffer(size.value)
        assert a.GetTokenInformation(token, 3, buf, size, ctypes.byref(size))
        count = w.DWORD.from_buffer(buf).value
        entries = (ENTRY * count).from_buffer(buf, PRIVS.entries.offset)
        found = {(e.luid.low, e.luid.high): e.attributes for e in entries}
        return {n: {"present": (v.low, v.high) in found,
                    "enabled": bool(found.get((v.low, v.high), 0) & 2)}
                for n, v in luids.items()}

    try:
        before = snapshot()
        for n, v in luids.items():
            if before[n]["present"]:
                request = PRIVS(1, (ENTRY(v, 4),))
                ctypes.set_last_error(0)
                assert a.AdjustTokenPrivileges(token, False, ctypes.byref(request), 0, None, None)
                assert ctypes.get_last_error() == 0
        after = snapshot()
        assert not any(v["present"] for v in after.values()), after
    finally:
        k.CloseHandle(token)
    repo = Path(__file__).resolve().parents[3]
    sys.path.insert(0, str(repo / "scripts"))
    import gitbash
    bash = gitbash.find_bash()
    assert bash, "Git Bash required; no silent non-answer"
    result = subprocess.run([bash, "-c", COMMANDS[name]],
                            env={**os.environ, "T": str(root)}, capture_output=True)
    print(json.dumps({"token_before": before, "token_after": after,
                      "primitive_rc": result.returncode}))


if __name__ == "__main__":
    child(sys.argv[1], sys.argv[2])
