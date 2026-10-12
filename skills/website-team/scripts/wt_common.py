"""Shared helpers: edit operations, repeated test runs, before/after comparison."""
import base64
import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path

HERE = Path(__file__).parent
SUITE_RUNS = 3


# ------------------------------------------------------------------ edit operations
# {"op":"replace","file":f,"old":s,"new":s}  old must occur exactly once
# {"op":"create","file":f,"text":s} | {"op":"create","file":f,"base64":b}   file must not exist
# {"op":"write","file":f,"text":s}   overwrite/create a whole file (use for new or rewritten files)
# {"op":"delete","file":f}
def _safe_path(site_dir, rel):
    root = Path(site_dir).resolve()
    p = (root / rel).resolve()
    if root != p and root not in p.parents:
        raise ValueError(f"path escapes the site directory: {rel}")
    return p


def apply_ops(site_dir, ops):
    if not isinstance(ops, list) or not ops:
        return False, "proposal has no operations"
    for i, op in enumerate(ops, 1):
        try:
            f = _safe_path(site_dir, op["file"])
            kind = op["op"]
            if kind == "replace":
                if not f.exists():
                    return False, f"op {i}: file not found: {op['file']}"
                text = f.read_text(encoding="utf-8")
                n = text.count(op["old"])
                if n != 1:
                    return False, f"op {i}: 'old' text found {n} times in {op['file']} (must be exactly 1)"
                f.write_text(text.replace(op["old"], op["new"]), encoding="utf-8")
            elif kind in ("create", "write"):
                if kind == "create" and f.exists():
                    return False, f"op {i}: file already exists: {op['file']} (use 'write' to overwrite)"
                f.parent.mkdir(parents=True, exist_ok=True)
                if "base64" in op:
                    f.write_bytes(base64.b64decode(op["base64"]))
                else:
                    f.write_text(op["text"], encoding="utf-8")
            elif kind == "delete":
                if not f.exists():
                    return False, f"op {i}: file to delete not found: {op['file']}"
                f.unlink()
            else:
                return False, f"op {i}: unknown op {kind!r}"
        except (KeyError, ValueError) as e:
            return False, f"op {i}: invalid operation: {e}"
    return True, "applied"


def reverse_ops(ops):
    out = []
    for op in reversed(ops):
        if op["op"] == "replace":
            out.append({**op, "old": op["new"], "new": op["old"]})
        elif op["op"] == "create":
            out.append({"op": "delete", "file": op["file"]})
        else:
            raise ValueError("cannot reverse op: " + op["op"])
    return out


# ------------------------------------------------------------------ running the suite
def run_once(site_dir):
    fd, out = tempfile.mkstemp(suffix=".json")
    os.close(fd)
    try:
        p = subprocess.run([sys.executable, str(HERE / "run_tests.py"), str(site_dir), "--out", out, "--quiet"],
                           capture_output=True, text=True, timeout=600)
        if p.returncode != 0:
            raise RuntimeError("test runner failed: " + (p.stderr or p.stdout)[-500:])
        return json.loads(Path(out).read_text(encoding="utf-8"))
    finally:
        Path(out).unlink(missing_ok=True)


def run_suite(site_dir, n=SUITE_RUNS):
    """Run the suite n times. A check whose status differs between runs is marked flaky/needs_review."""
    runs = [run_once(site_dir) for _ in range(n)]
    maps = [{r["id"]: r for r in x["results"]} for x in runs]
    ids = []
    for m in maps:
        for i in m:
            if i not in ids:
                ids.append(i)
    merged = {}
    for i in ids:
        sts = [m[i]["status"] if i in m else "missing" for m in maps]
        first = next(m[i] for m in maps if i in m)
        flaky = len(set(sts)) > 1
        merged[i] = {**first, "status": "needs_review" if flaky else sts[0], "flaky": flaky}
        if flaky:
            merged[i]["detail"] = f"FLAKY: status differs between runs {sts}"
    return {"tree_hash": runs[0]["tree_hash"], "pages": runs[0]["pages"], "runs": n, "results": merged}


def counts(results):
    c = {"pass": 0, "fail": 0, "needs_review": 0, "not_run": 0}
    for r in results.values():
        c[r["status"]] = c.get(r["status"], 0) + 1
    return c


def compare(before, after, allowed_removals=()):
    """before/after: id -> result. Returns improved, regressed, flaky lists.

    Regression = any of:
      * pass -> anything else
      * fail -> needs_review  (a definite problem became uncertain: masking, e.g. hiding a broken form)
      * needs_review -> fail
      * a new check that fails (new broken element/page)
      * a check that disappeared (element/page removed), unless explicitly listed in allowed_removals
    """
    improved = [i for i, a in after.items()
                if a["status"] == "pass" and not a["flaky"] and i in before and before[i]["status"] in ("fail", "needs_review")]
    regressed = []
    for i, a in after.items():
        b = before.get(i)
        if b is None:
            if a["status"] == "fail":
                regressed.append(i)
            continue
        bs, as_ = b["status"], a["status"]
        if bs == "pass" and as_ != "pass":
            regressed.append(i)
        elif bs == "fail" and as_ == "needs_review":
            regressed.append(i)
        elif bs == "needs_review" and as_ == "fail":
            regressed.append(i)
    for i, b in before.items():
        if i not in after and b["status"] != "not_run" and i not in allowed_removals:
            regressed.append(i)
    flaky = [i for i, a in after.items() if a["flaky"]]
    return improved, sorted(set(regressed)), flaky
