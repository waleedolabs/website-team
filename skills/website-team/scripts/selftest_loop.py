#!/usr/bin/env python3
"""Self-test of the fix-verification loop (verify_fix.py): every accept/reject rule, on the bundled fixture.
Runs in a temp folder; takes about 4-6 minutes. Exit 0 = the loop behaves as documented."""
import json
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

HERE = Path(__file__).parent
FIX = HERE.parent / "fixtures"
V = [sys.executable, str(HERE / "verify_fix.py")]


def unit_tests():
    """Deterministic unit tests of the verdict logic with scripted run results (no browser)."""
    import wt_common as wc
    ok_all = []

    def res(**st):
        return {"tree_hash": "x", "pages": ["index.html"],
                "results": [{"id": k.replace("__", ":"), "name": k, "status": v, "detail": v, "evidence": None}
                            for k, v in st.items()]}

    def scripted(seq):
        it = iter(seq)
        return lambda site, only=None: next(it)

    before = {"a__1".replace("__", ":"): {"status": "pass"}, "b:1": {"status": "fail"}, "c:1": {"status": "pass"}}
    cases = [
        ("unchanged -> no reruns, not flaky", [res(a__1="pass", b__1="fail", c__1="pass")],
         lambda r: r["results"]["b:1"]["status"] == "fail" and not r["results"]["b:1"]["flaky"] and "no change" in r["runs"]),
        ("consistent change confirmed by reruns", [res(a__1="pass", b__1="pass", c__1="pass"), res(b__1="pass"), res(b__1="pass")],
         lambda r: r["results"]["b:1"]["status"] == "pass" and not r["results"]["b:1"]["flaky"]),
        ("change that flips on rerun -> flaky", [res(a__1="pass", b__1="pass", c__1="pass"), res(b__1="fail"), res(b__1="pass")],
         lambda r: r["results"]["b:1"]["flaky"] and r["results"]["b:1"]["status"] == "needs_review"),
        ("check gone in all runs -> missing (a removal)", [res(a__1="pass", b__1="fail"), res(), res()],
         lambda r: "c:1" not in r["results"]),
        ("check gone then back -> flaky", [res(a__1="pass", b__1="fail"), res(c__1="pass"), res()],
         lambda r: r["results"].get("c:1", {}).get("flaky") is True),
    ]
    saved = wc.run_once
    try:
        for name, seq, cond in cases:
            wc.run_once = scripted(seq)
            r = wc.run_suite_incremental("unused", before)
            ok = bool(cond(r))
            ok_all.append(ok)
            print(f"{'OK  ' if ok else 'FAIL'} unit: {name}")
    finally:
        wc.run_once = saved
    # compare(): regression rules
    B = {"p": {"status": "pass", "flaky": False}, "f": {"status": "fail", "flaky": False}, "n": {"status": "needs_review", "flaky": False}}
    A = lambda **st: {k: {"status": v, "flaky": False} for k, v in st.items()}
    rules = [
        ("pass -> fail is a regression", A(p="fail", f="fail", n="needs_review"), ["p"]),
        ("fail -> needs_review is a regression (masking)", A(p="pass", f="needs_review", n="needs_review"), ["f"]),
        ("needs_review -> fail is a regression", A(p="pass", f="fail", n="fail"), ["n"]),
        ("removed check is a regression", A(p="pass", n="needs_review"), ["f"]),
        ("new failing check is a regression", A(p="pass", f="fail", n="needs_review", x="fail"), ["x"]),
        ("fail -> pass is an improvement, not a regression", A(p="pass", f="pass", n="needs_review"), []),
    ]
    for name, after, want in rules:
        _, reg, _ = wc.compare(B, after)
        ok = reg == sorted(want)
        ok_all.append(ok)
        print(f"{'OK  ' if ok else 'FAIL'} unit: {name} (got {reg})")
    return ok_all


def main():
    sys.path.insert(0, str(HERE))
    unit_results = unit_tests()
    T = Path(tempfile.mkdtemp(prefix="wt-looptest-"))
    site, work, props = T / "site", T / "work", T / "p"
    shutil.copytree(FIX / "coffee-buggy", site)
    props.mkdir()
    results = []

    def run(name, want, args, reason=None):
        p = subprocess.run(V + args, capture_output=True, text=True, timeout=600)
        out = (p.stdout + p.stderr).strip().splitlines()
        ok = p.returncode == want and (reason is None or reason in (p.stdout + p.stderr))
        results.append(ok)
        print(f"{'OK  ' if ok else 'FAIL'} {name} -> {out[0][:130] if out else ''}")
        if not ok:
            print("     " + "\n     ".join(out[:6]))

    def prop(name, d):
        f = props / f"{name}.json"
        f.write_text(json.dumps(d, ensure_ascii=False), encoding="utf-8")
        return str(f)

    S, W = ["--site", str(site)], ["--work", str(work)]
    R = lambda o, n: {"op": "replace", "file": "index.html", "old": o, "new": n}
    tr = lambda name, d, *extra: ["try", *S, *W, "--proposal", prop(name, d), *extra]

    run("work dir inside site refused", 1, ["init", *S, "--work", str(site / ".work")])
    run("init baseline", 0, ["init", *S, *W])
    run("good fix accepted", 0, tr("good", {"title": "define startOrder", "kind": "fix", "targets": ["btn:index.html:#order-btn"],
        "ops": [R("</body>", '<p id="st"></p><script>function startOrder(){document.getElementById("st").textContent="ok"}</script></body>')]}))
    run("fix that does not fix its target -> rejected", 1, tr("weak", {"title": "weak contrast", "kind": "fix",
        "targets": ["contrast:index.html"], "ops": [R("color: #e8dccb;", "color: #d9cdb9;")]}), reason='none of the targets was fixed')
    run("fix that masks another problem (hides broken form) -> rejected", 1, tr("hide", {"title": "hide box", "kind": "fix",
        "targets": ["overflow:index.html"], "ops": [R(".contact-box { width: 900px;", ".contact-box { display:none;")]}), reason='regression')
    run("improves something else but not its target -> rejected", 1, tr("wrong", {"title": "alt but claims overflow", "kind": "fix",
        "targets": ["overflow:index.html"], "ops": [R('<img src="latte.jpg" width', '<img src="latte.jpg" alt="x" width')]}))
    run("patch that does not apply -> rejected", 1, tr("noapply", {"title": "missing text", "kind": "fix",
        "targets": ["overflow:index.html"], "ops": [R("NOT IN FILE", "x")]}))
    run("path outside the site -> rejected", 1, tr("escape", {"title": "escape", "kind": "fix", "targets": ["alt:index.html"],
        "ops": [{"op": "write", "file": "../evil.txt", "text": "x"}]}))
    results.append(not (T / "evil.txt").exists())
    print(f"{'OK  ' if results[-1] else 'FAIL'} nothing written outside the site")
    run("fix editing the test contract -> rejected", 1, tr("cheat", {"title": "declare endpoint", "kind": "fix",
        "targets": ["form:index.html:#contact-form"],
        "ops": [{"op": "write", "file": "site-tests.json", "text": '{"backend": {"POST /api/contact-missing": 200}}'}]}))
    run("unknown target id -> rejected", 1, tr("unknown", {"title": "bad", "kind": "fix", "targets": ["nope:x"], "ops": [R("</body>", "</body>")]}))
    head = {"title": "rewrite headline", "kind": "design", "needs_user_approval": True,
            "ops": [R("<h1>قهوة الصباح</h1>", "<h1>قهوة الصباح المختصة</h1>")]}
    run("content change without approval -> rejected", 1, tr("head", head))
    run("same change with --approved -> accepted as design", 0, tr("head2", head, "--approved"))
    run("design change that breaks a link -> rejected", 1, tr("dbreak", {"title": "break link", "kind": "design",
        "ops": [R('<a href="#menu">القائمة</a>', '<a href="#nowhere">القائمة</a>')]}))
    form_del = [R('<form id="contact-form" action="/api/contact-missing" method="post">', "<div>"), R("</form>", "</div>")]
    run("silently deleting a broken feature -> rejected", 1, tr("del", {"title": "delete form", "kind": "design", "ops": form_del}),
        reason="regression")
    run("declared removal without approval -> rejected", 1, tr("del2", {"title": "delete form", "kind": "design",
        "removes": ["form:index.html:#contact-form"], "ops": form_del}), reason="always needs the user's approval")
    run("design change that breaks a link -> rejected (reason)", 1, tr("dbreak2", {"title": "break link again", "kind": "design",
        "ops": [R('<a href="#menu">القائمة</a>', '<a href="#nowhere">القائمة</a>')]}), reason="link:index.html:#menu")
    # custom checks
    sc = {"id": "order-shows-status", "page": "index.html", "desc": "clicking order shows a status text",
          "steps": [{"click": "#order-btn"}], "expect": [{"text": "#st", "not_empty": True}]}
    run("add a custom check (passes -> kept as guard)", 0, ["add-check", *S, *W, "--scenario", prop("sc1", sc)])
    run("same check id again -> rejected", 1, ["add-check", *S, *W, "--scenario", prop("sc1b", sc)])
    sc2 = {"id": "alt-latte", "page": "index.html", "desc": "latte image has alt", "steps": [],
           "expect": [{"visible": "img[src='latte.jpg'][alt]"}]}
    run("add a custom check (fails -> suspicion proven)", 0, ["add-check", *S, *W, "--scenario", prop("sc2", sc2)])
    run("fix targeting the custom check -> accepted", 0, tr("altfix", {"title": "alt", "kind": "fix", "targets": ["scenario:alt-latte"],
        "ops": [R('<img src="latte.jpg" width', '<img src="latte.jpg" alt="لاتيه" width')]}), reason="fixed scenario:alt-latte")
    # outside edits and caps
    with open(site / "index.html", "a", encoding="utf-8") as f:
        f.write("<!-- manual edit -->")
    run("site edited outside the loop -> rejected", 1, tr("after_edit", {"title": "x", "kind": "fix", "targets": ["labels:index.html"],
        "ops": [R('name="name" placeholder', 'name="name" aria-label="name" placeholder')]}), reason="changed outside the loop")
    run("re-baseline is recorded (history kept)", 0, ["init", *S, *W, "--force"])
    for n in (1, 2):
        run(f"weak contrast attempt {n + 1} -> rejected", 1, tr(f"weak{n}", {"title": f"weak {n}", "kind": "fix",
            "targets": ["contrast:index.html"], "ops": [R("color: #e8dccb;", f"color: #d{n}cdb9;")]}))
    run("4th attempt on the same target -> refused by cap", 1, tr("real", {"title": "real contrast fix", "kind": "fix",
        "targets": ["contrast:index.html"], "ops": [R("color: #e8dccb;", "color: #5c4a3a;")]}), reason='attempt cap reached for contrast')
    text = (site / "index.html").read_text(encoding="utf-8")
    leaked = any(x in text for x in ("display:none", "#d9cdb9", "#nowhere", "#d1cdb9", "#d2cdb9"))
    results.append(not leaked)
    print(f"{'OK  ' if not leaked else 'FAIL'} no rejected change leaked into the site")
    log = [json.loads(l) for l in (work / "decisions.jsonl").read_text(encoding="utf-8").splitlines() if l.strip()]
    guards_ok = all(not e.get("counted") for e in log if e["decision"] == "rejected" and
                    e["reason"].startswith(("needs the user", "site was changed", "unknown target", "a fix may not", "removing elements")))
    results.append(guards_ok)
    print(f"{'OK  ' if guards_ok else 'FAIL'} guard rejections do not consume attempt caps")
    p = subprocess.run([sys.executable, str(HERE / "report.py"), "--work", str(work)], capture_output=True, text=True)
    results.append(p.returncode == 0 and "سجل محاولات الإصلاح" in p.stdout)
    print(f"{'OK  ' if results[-1] else 'FAIL'} report generated")
    shutil.rmtree(T, ignore_errors=True)
    results += unit_results
    passed = sum(results)
    print(f"\nLOOP SELFTEST: {'PASSED' if passed == len(results) else 'FAILED'} ({passed}/{len(results)})")
    return 0 if passed == len(results) else 1


if __name__ == "__main__":
    sys.exit(main())
