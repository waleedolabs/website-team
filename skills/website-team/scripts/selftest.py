#!/usr/bin/env python3
"""Self-test of the test suite on the bundled fixture. Run before trusting the tests in a new environment.

  T1 control     : known-good page -> zero fail / needs_review (no false alarms)
  T2 mutation    : known-good page + ONE bug -> exactly the expected checks fail (detection + specificity)
  T3 determinism : identical statuses over repeated runs
Exit 0 = the suite is trustworthy here.

Options:
  --quick          fewer repetitions (about 3 minutes)
  --log FILE       also append the output to FILE (no shell redirection needed; earlier runs are kept)
  --if-needed      skip if this exact plugin code already PASSED on this machine
                   (cache: ~/.cache/website-team/, keyed by a hash of scripts + fixtures + Python version)
"""
import datetime
import hashlib
import json
import platform
import shutil
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from wt_common import apply_ops, reverse_ops, run_once, run_suite  # noqa: E402

for _stream in (sys.stdout, sys.stderr):  # Arabic output must not crash on a Windows (cp125x) console/pipe
    try:
        _stream.reconfigure(encoding="utf-8", errors="replace")
    except (AttributeError, ValueError):
        pass

FIX = Path(__file__).parent.parent / "fixtures"
# fixtures whose expected.json lists exact statuses for specific checks (regression guards)
LISTED_FIXTURES = ["contrast-cases", "form-cases"]


CACHE = Path.home() / ".cache" / "website-team"


class Tee:
    def __init__(self, *streams):
        self.streams = streams

    def write(self, x):
        for s in self.streams:
            s.write(x)
            s.flush()

    def flush(self):
        for s in self.streams:
            s.flush()


def code_key(quick):
    """Hash of everything the self-test result depends on."""
    h = hashlib.sha256()
    base = Path(__file__).parent.parent
    files = sorted(list((base / "scripts").glob("*.py")) + [p for p in (base / "fixtures").rglob("*") if p.is_file()])
    for f in files:
        if "__pycache__" in f.parts:
            continue
        h.update(str(f.relative_to(base)).encode())
        h.update(f.read_bytes())
    h.update(f"{platform.python_version()}|{'quick' if quick else 'full'}".encode())
    return h.hexdigest()[:16]


def bad(res):
    return sorted(i for i, r in res["results"].items() if r["status"] in ("fail", "needs_review"))


def main():
    quick = "--quick" in sys.argv
    if "--log" in sys.argv:
        i = sys.argv.index("--log")
        log = Path(sys.argv[i + 1])
        log.parent.mkdir(parents=True, exist_ok=True)
        # append, so an earlier failed run stays on record when the test is repeated
        fh = open(log, "a", encoding="utf-8")
        fh.write(f"\n===== selftest run {datetime.datetime.now():%Y-%m-%d %H:%M:%S} =====\n")
        sys.stdout = Tee(sys.__stdout__, fh)
    key = code_key(quick)
    marker = CACHE / f"selftest-{key}.ok"
    if "--if-needed" in sys.argv and marker.exists():
        print(f"SELFTEST: PASSED (cached: this exact plugin code passed on this machine on {marker.read_text(encoding="utf-8").strip()}; key {key})")
        return 0
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

    # T6: regression fixtures with listed expectations (each guards a bug found during verification)
    for name in LISTED_FIXTURES:
        d = FIX / name
        spec = json.loads((d / "expected.json").read_text(encoding="utf-8"))
        res = run_suite(d, n=1 if quick else 2)["results"]
        diffs = []
        for k, v in spec["expected"].items():
            got = res.get(k)
            if got is None or got["status"] != v:
                diffs.append(f"{name} {k}: got {got['status'] if got else 'missing'} expected {v}")
            elif spec.get("detail_contains", {}).get(k, "") not in got["detail"]:
                diffs.append(f"{name} {k}: detail {got['detail']!r} lacks {spec['detail_contains'][k]!r}")
        for var in spec.get("variants", []):   # same fixture with parts of the test contract removed
            vd = work / f"{name}-variant"
            if vd.exists():
                shutil.rmtree(vd)
            shutil.copytree(d, vd)
            cfg = json.loads((vd / "site-tests.json").read_text(encoding="utf-8"))
            for k in var["remove"]:
                cfg.pop(k, None)
            (vd / "site-tests.json").write_text(json.dumps(cfg), encoding="utf-8")
            vres = run_suite(vd, n=1)["results"]
            for k, v in var["expected"].items():
                got = vres.get(k, {}).get("status", "missing")
                if got != v:
                    diffs.append(f"{name} without {var['remove']}: {k} got {got} expected {v} ({var['why']})")
        n_total = len(spec["expected"]) + sum(len(v["expected"]) for v in spec.get("variants", []))
        print(f"T6 {name}: {n_total - len(diffs)}/{n_total} as expected")
        problems += [f"T6 {d_}" for d_ in diffs]

    # T7: committee validator (no browser): a valid committee passes; each violation is caught
    import subprocess
    vc = [sys.executable, str(Path(__file__).parent / "validate_committee.py")]
    good = FIX / "committee-cases" / "good"

    def mutated(name, fn):
        d = work / f"committee-{name}"
        if d.exists():
            shutil.rmtree(d)
        shutil.copytree(good, d)
        fn(d)
        return d

    def edit(path, old, new):
        path.write_text(path.read_text(encoding="utf-8").replace(old, new), encoding="utf-8")

    def plan_edit(d, f):
        pj = d / "committee" / "plan.json"
        plan = json.loads(pj.read_text(encoding="utf-8"))
        f(plan)
        pj.write_text(json.dumps(plan), encoding="utf-8")

    cases = [
        ("valid committee", lambda d: None, 0),
        ("report saved as a condensed copy", lambda d: edit(d / "committee" / "critic.md", "## Findings", "(نسخة مختصرة من تقرير الناقد — ليست حرفية)\\n## Findings"), 1),
        ("report not written by the member (no signature)", lambda d: edit(d / "committee" / "advocate.md", "<!-- website-team:site-advocate -->", ""), 1),
        ("'proven' item on a passing check", lambda d: plan_edit(d, lambda p: p["items"][0].update(check_ids=["lang:index.html"])), 1),
        ("fix item without check ids", lambda d: plan_edit(d, lambda p: p["items"][0].update(check_ids=[])), 1),
        ("unknown check id in plan", lambda d: plan_edit(d, lambda p: p["items"][1].update(check_ids=["scenario:nope"])), 1),
        ("committee member modified the site", lambda d: edit(d / "site" / "index.html", "</body>", "<!-- x --></body>"), 1),
    ]
    ok_n = 0
    for name, fn, want in cases:
        d = mutated(name.replace(" ", "-").replace("'", ""), fn)
        rc = subprocess.run(vc + ["--project", str(d), "--quiet"], capture_output=True).returncode
        ok = rc == want
        ok_n += ok
        if not ok:
            problems.append(f"T7 {name}: exit {rc}, expected {want}")
    d = mutated("manifest", lambda d: None)
    subprocess.run(vc + ["--project", str(d), "--quiet"], capture_output=True)
    edit(d / "committee" / "inspector.md", "INS-1", "INS-1 (edited later)")
    rc = subprocess.run(vc + ["--project", str(d), "--verify-manifest"], capture_output=True).returncode
    ok_n += rc == 1
    if rc != 1:
        problems.append("T7 later edit of a report not detected by --verify-manifest")
    print(f"T7 committee validator: {ok_n}/{len(cases) + 1} as expected")

    shutil.rmtree(work, ignore_errors=True)
    if not problems:
        try:
            CACHE.mkdir(parents=True, exist_ok=True)
            marker.write_text(datetime.datetime.now().strftime("%Y-%m-%d %H:%M"), encoding="utf-8")
        except OSError:
            pass  # cache is only a convenience
    print("\nSELFTEST:", "PASSED" if not problems else "FAILED")
    for p in problems:
        print("  -", p)
    return 0 if not problems else 1


if __name__ == "__main__":
    sys.exit(main())
