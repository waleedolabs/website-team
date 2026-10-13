#!/usr/bin/env python3
"""Copy the user's site into the team folder, and later copy the verified result back.

  sync_site.py prepare --from SITE_DIR --project TEAM_DIR
      Copies SITE_DIR into TEAM_DIR/site (skips TEAM_DIR itself, hidden folders, node_modules)
      and records a fingerprint of the original in TEAM_DIR/work-origin.json.
  sync_site.py apply --project TEAM_DIR
      Copies back only the files that accepted fixes changed (TEAM_DIR/site vs TEAM_DIR/work/versions/v0),
      never site-tests.json. Refuses if the original folder changed since `prepare`.
"""
import argparse
import hashlib
import json
import shutil
import sys
from pathlib import Path

for _stream in (sys.stdout, sys.stderr):
    try:
        _stream.reconfigure(encoding="utf-8", errors="replace")
    except (AttributeError, ValueError):
        pass

SKIP_DIRS = {"node_modules", "__pycache__"}
CONTRACT = "site-tests.json"


def files(root, exclude=None):
    out = {}
    root = Path(root)
    for p in sorted(root.rglob("*")):
        rel = p.relative_to(root)
        if exclude and (p == exclude or exclude in p.parents):
            continue
        if any(part.startswith(".") or part in SKIP_DIRS for part in rel.parts):
            continue
        if p.is_file():
            out[rel.as_posix()] = hashlib.sha256(p.read_bytes()).hexdigest()
    return out


def prepare(a):
    src, proj = Path(a.src).resolve(), Path(a.project).resolve()
    if not src.is_dir():
        sys.exit(f"not a folder: {src}")
    if (proj / "site").exists():
        sys.exit(f"{proj / 'site'} already exists; the team already prepared this project")
    fs = files(src, exclude=proj)
    if not any(k.endswith((".html", ".htm")) for k in fs):
        sys.exit(f"no HTML files in {src}")
    for rel in fs:
        d = proj / "site" / rel
        d.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(src / rel, d)
    proj.mkdir(parents=True, exist_ok=True)
    (proj / "work-origin.json").write_text(json.dumps({"origin": str(src), "files": fs}, indent=1), encoding="utf-8")
    print(f"copied {len(fs)} files from {src} to {proj / 'site'}")


def apply(a):
    proj = Path(a.project).resolve()
    meta = json.loads((proj / "work-origin.json").read_text(encoding="utf-8"))
    src = Path(meta["origin"])
    now = files(src, exclude=proj)
    if now != meta["files"]:
        changed = sorted(set(now.items()) ^ set(meta["files"].items()))
        sys.exit(f"NOT APPLIED: the original folder changed since the team copied it ({len(changed)} differences); "
                 f"the verified version stays in {proj / 'site'}")
    v0 = files(proj / "work" / "versions" / "v0")
    final = files(proj / "site")
    changed = [r for r in final if r != CONTRACT and final[r] != v0.get(r)]
    removed = [r for r in v0 if r != CONTRACT and r not in final]
    for rel in changed:
        d = src / rel
        d.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(proj / "site" / rel, d)
    for rel in removed:
        (src / rel).unlink(missing_ok=True)
    print(f"APPLIED to {src}: changed {changed or 'nothing'}; removed {removed or 'nothing'}")


def main():
    ap = argparse.ArgumentParser()
    sub = ap.add_subparsers(dest="cmd", required=True)
    p = sub.add_parser("prepare")
    p.add_argument("--from", dest="src", required=True)
    p.add_argument("--project", required=True)
    p = sub.add_parser("apply")
    p.add_argument("--project", required=True)
    a = ap.parse_args()
    {"prepare": prepare, "apply": apply}[a.cmd](a)


if __name__ == "__main__":
    main()
