"""Small shared helpers for capped, resumable verification runners."""
import hashlib
import json
import os
from pathlib import Path
import subprocess
import time


def external_output(path, root):
    """Reports must not mutate the source being fingerprinted or protected data."""
    path, root = Path(path).resolve(), Path(root).resolve()
    if path == root or root in path.parents:
        raise ValueError("output must be outside the toolkit source tree")
    # The reports are write artifacts; reject known game/reference/profile roots.
    for name in ("X4_GAME", "X4_REFERENCE", "X4_PROFILE"):
        value = os.environ.get(name)
        if value:
            protected = Path(value).resolve()
            if path == protected or protected in path.parents:
                raise ValueError("output overlaps a protected X4 root")
    return path


def evidence_digest(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def evidence_intact(out, row):
    return bool(row.get("evidence")) and all(
        (out / name).is_file() and evidence_digest(out / name) == digest
        for name, digest in row["evidence"].items())


def gate_environment():
    """Keep child `bash` lookups on Git Bash, never the Windows WSL stub."""
    env=dict(os.environ,PYTHONDONTWRITEBYTECODE="1",PYTHONUTF8="1")
    if os.name=="nt":
        from gitbash import find_bash
        bash=find_bash()
        if not bash:raise RuntimeError("Git Bash is required for these gates")
        bindir=Path(bash).parent
        env["PATH"]=os.pathsep.join([str(bindir),str(bindir.parent/"usr"/"bin"),env.get("PATH","")])
    return env


def dispatch_ready():
    p = os.environ.get("RB_PRESSURE_FILE")
    if not p:
        return True
    state = json.loads(Path(p).read_text(encoding="utf-8"))
    if time.time()-state["updated"] > 30:
        raise RuntimeError("resource monitor heartbeat is stale")
    return not state["blocked"]


def wait_dispatch():
    while not dispatch_ready():
        time.sleep(1)


def save(path, data):
    path = Path(path)
    payload = (json.dumps(data, indent=2, sort_keys=True)+"\n").encode("utf-8")
    temp = path.with_suffix(path.suffix+".partial")
    temp.write_bytes(payload)
    temp.replace(path)


def source_fingerprint(root):
    """Hash actual tracked/untracked source bytes; never read ignored path configs."""
    p = subprocess.run(["git","-C",str(root),"ls-files","-z","--cached","--others","--exclude-standard"],
                       capture_output=True,check=True)
    h=hashlib.sha256()
    for name in sorted(set(p.stdout.decode("utf-8").split("\0")) - {""}):
        path=Path(root)/name
        h.update(name.encode("utf-8"))
        h.update(path.read_bytes() if path.is_file() else b"<absent>")
    return h.hexdigest()
