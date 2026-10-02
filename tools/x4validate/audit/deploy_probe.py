"""Exercise legacy deploy guards only after rebinding every root to scratch."""
import importlib.util
from pathlib import Path
import subprocess
import sys
import time
import driver as D

mode = sys.argv[1]
root = D.inside(D.OUT / ("deploy-probe-" + mode + ("-optimized" if sys.flags.optimize else "-normal") + "-" + str(time.time_ns())))
if root.exists():
    raise SystemExit("Refuse to reuse an existing scratch fixture")
root.mkdir()
helper_root = Path(D.LOCAL['reviewed_dev']) if 'reviewed_dev' in D.LOCAL else D.MODDING / 'dev'
spec = importlib.util.spec_from_file_location("legacy_deploy", helper_root / "_tools/deploy.py")
m = importlib.util.module_from_spec(spec)
spec.loader.exec_module(m)
m.DEV = root / "dev"
m.EXT = root / "extensions"
name = "audit_unowned" if mode == "optimized" else sorted(m.OWNED - set(m.RETIRED))[0]
src, dst = m.DEV / name, m.EXT / name
D.write(src / "content.xml", '<content id="audit_source"/>')
D.write(dst / "content.xml", '<content id="audit_victim"/>' if mode == "optimized" else '<content id="audit_source"/>')
if mode == "junction":
    victim = root / "outside-extension"
    D.write(victim / "payload.txt", "ORIGINAL")
    D.write(src / "linked/payload.txt", "REPLACED")
    p = subprocess.run(["cmd", "/c", "mklink", "/J", str(dst / "linked"), str(victim)], capture_output=True, text=True)
    print(p.stdout, p.stderr)
    if p.returncode:
        raise SystemExit(3)
try:
    result = m.deploy(name, True)
except (AssertionError, ValueError, OSError) as exc:
    print("REFUSED:", exc)
    raise SystemExit(2)
print("RESULT", result)
if mode == "junction":
    print("OUTSIDE_EXTENSION_PAYLOAD:", (victim / "payload.txt").read_text())
else:
    print("DESTINATION_MANIFEST:", (dst / "content.xml").read_text())
