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
def run_once(site_dir, only=None):
    fd, out = tempfile.mkstemp(suffix=".json")
    os.close(fd)
    cmd = [sys.executable, str(HERE / "run_tests.py"), str(site_dir), "--out", out, "--quiet"]
    if only:
        cmd += ["--only", ",".join(sorted(only))]
    try:
        p = subprocess.run(cmd, capture_output=True, text=True, timeout=600)
        if p.returncode != 0:
            raise RuntimeError("test runner failed: " + (p.stderr or p.stdout)[-500:])
        return json.loads(Path(out).read_text(encoding="utf-8"))
    finally:
        Path(out).unlink(missing_ok=True)


def _merge(runs, ids_filter=None):
    maps = [{r["id"]: r for r in x["results"]} for x in runs]
    ids = []
    for m in maps:
        for i in m:
            if i not in ids and (ids_filter is None or i in ids_filter):
                ids.append(i)
    merged = {}
    for i in ids:
        sts = [m[i]["status"] if i in m else "missing" for m in maps]
        first = next(m[i] for m in maps if i in m)
        flaky = len(set(sts)) > 1
        merged[i] = {**first, "status": "needs_review" if flaky else sts[0], "flaky": flaky}
        if flaky:
            merged[i]["detail"] = f"FLAKY: status differs between runs {sts}"
    return merged


def run_targeted(site_dir, ids, n=SUITE_RUNS):
    """Run only the checks in `ids` (their groups), n times. Returns id -> merged result for those ids."""
    runs = [run_once(site_dir, only=ids) for _ in range(n)]
    merged = _merge(runs, ids_filter=set(ids))
    for i in ids:  # an id that never appeared is reported, not silently dropped
        merged.setdefault(i, {"id": i, "name": i, "status": "missing", "detail": "check not produced", "evidence": None, "flaky": False})
    return merged


def run_suite_incremental(site_dir, before, n=SUITE_RUNS):
    """One full run; every check whose status differs from `before` (or is new / missing) is re-run n-1 more
    times in targeted mode, and flagged flaky if its status is not identical across all n runs.
    Unchanged checks agree with a state that was itself verified, so they need no extra runs."""
    full = run_once(site_dir)
    now_ = {r["id"]: r for r in full["results"]}
    changed = sorted(i for i in set(now_) | set(before)
                     if not i.startswith("N:") and (now_.get(i, {}).get("status") != before.get(i, {}).get("status")))
    reruns = [run_once(site_dir, only=changed) for _ in range(n - 1)] if changed else []
    merged = _merge([full] + reruns) if not changed else _merge([full])
    if changed:
        rmaps = [{r["id"]: r for r in x["results"]} for x in reruns]
        for i in changed:
            sts = [now_[i]["status"] if i in now_ else "missing"] + [m[i]["status"] if i in m else "missing" for m in rmaps]
            if i in merged:
                flaky = len(set(sts)) > 1
                merged[i]["flaky"] = flaky
                merged[i]["status"] = "needs_review" if flaky else sts[0]
                if flaky:
                    merged[i]["detail"] = f"FLAKY: status differs between runs {sts}"
            elif len(set(sts)) > 1:  # disappeared in the full run but reappeared in a rerun
                merged[i] = {"id": i, "name": i, "status": "needs_review", "flaky": True, "evidence": None,
                             "detail": f"FLAKY: status differs between runs {sts}"}
    return {"tree_hash": full["tree_hash"], "pages": full["pages"], "results": merged,
            "runs": f"1 full + {n - 1} targeted reruns of {len(changed)} changed checks" if changed else "1 full (no change vs verified state)"}


def run_suite(site_dir, n=SUITE_RUNS):
    """Run the full suite n times. A check whose status differs between runs is marked flaky/needs_review."""
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
