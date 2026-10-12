#!/usr/bin/env python3
"""Self-test of the test suite on the bundled fixture. Run before trusting the tests in a new environment.

  T1 control     : known-good page -> zero fail / needs_review (no false alarms)
  T2 mutation    : known-good page + ONE bug -> exactly the expected checks fail (detection + specificity)
  T3 determinism : identical statuses over repeated runs
Exit 0 = the suite is trustworthy here.
"""
import json
import shutil
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from wt_common import apply_ops, reverse_ops, run_once, run_suite  # noqa: E402

FIX = Path(__file__).parent.parent / "fixtures"


def bad(res):
    return sorted(i for i, r in res["results"].items() if r["status"] in ("fail", "needs_review"))


def main():
    quick = "--quick" in sys.argv
    work = Path(tempfile.mkdtemp(prefix="wt-selftest-"))
    fixes = json.loads((FIX / "fixes.json").read_text(encoding="utf-8"))["fixes"]
    problems = []
    golden = work / "golden"
    shutil.copytree(FIX / "coffee-buggy", golden)
    for f in fixes:
        ok, msg = apply_ops(golden, f["ops"])
        if not ok:
            print(f"SETUP ERROR {f['id']}: {msg}")
            return 2

    ctl = run_suite(golden, n=2 if quick else 3)
    b = bad(ctl)
    print(f"T1 control (known-good page): non-pass = {b or 'none'}")
    if b:
        problems.append(f"T1 false alarms: {b}")

    print("T2 mutation (one bug at a time):")
    for f in fixes:
        m = work / f"mutant_{f['id']}"
        shutil.copytree(golden, m)
        ok, msg = apply_ops(m, reverse_ops(f["ops"]))
        if not ok:
            problems.append(f"T2 {f['id']} setup: {msg}")
            continue
        res = run_suite(m, n=1 if quick else 2)
        got = bad(res)
        missing = [e for e in f["expect"] if e not in got]
        extra = [g for g in got if g not in f["expect"]]
        flag = "OK " if not missing and not extra else "BAD"
        print(f"  {flag} {f['id']}: expected {f['expect']} got {got}")
        if missing:
            problems.append(f"T2 {f['id']}: NOT detected {missing}")
        if extra:
            problems.append(f"T2 {f['id']}: unrelated failures {extra}")

    buggy = work / "buggy"
    shutil.copytree(FIX / "coffee-buggy", buggy)
    sigs = []
    for _ in range(2 if quick else 3):
        r = run_once(buggy)
        sigs.append(json.dumps({x["id"]: x["status"] for x in r["results"]}, sort_keys=True))
    same = len(set(sigs)) == 1
    print(f"T3 determinism: identical = {same}")
    if not same:
        problems.append("T3 results differ between runs")

    # T4: edge cases with exact expected statuses
    exp = json.loads((FIX / "edge-cases" / "expected.json").read_text(encoding="utf-8"))["expected"]
    res = run_suite(FIX / "edge-cases", n=1 if quick else 2)
    got = {i: r["status"] for i, r in res["results"].items() if not i.startswith("N:")}
    diffs = [f"{k}: got {got.get(k)} expected {exp.get(k)}" for k in sorted(set(got) | set(exp)) if got.get(k) != exp.get(k)]
    print(f"T4 edge cases (fake forms, placeholder links, no-op buttons, multi-page): {len(exp) - len(diffs)}/{len(exp)} as expected")
    problems += [f"T4 {d}" for d in diffs]

    # T5: custom scenario engine (behaviour checks) on a buggy and a fixed shop
    sx = json.loads((FIX / "scenario-shop" / "expected.json").read_text(encoding="utf-8"))
    fixed = work / "shop-fixed"
    shutil.copytree(FIX / "scenario-shop", fixed)
    ok, msg = apply_ops(fixed, sx["fix_ops"])
    if not ok:
        problems.append(f"T5 setup: {msg}")
    else:
        for label, d in (("buggy", FIX / "scenario-shop"), ("fixed", fixed)):
            res = run_suite(d, n=1 if quick else 2)
            got = {i: r["status"] for i, r in res["results"].items()}
            diffs = [f"{label} {k}: got {got.get(k)} expected {v}" for k, v in sx[label].items() if got.get(k) != v]
            print(f"T5 scenarios ({label} shop): {len(sx[label]) - len(diffs)}/{len(sx[label])} as expected")
            problems += [f"T5 {d_}" for d_ in diffs]

    shutil.rmtree(work, ignore_errors=True)
    print("\nSELFTEST:", "PASSED" if not problems else "FAILED")
    for p in problems:
        print("  -", p)
    return 0 if not problems else 1


if __name__ == "__main__":
    sys.exit(main())
