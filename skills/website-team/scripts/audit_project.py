"""Independent, deterministic audit of a website-team project folder. Trusts nothing the session wrote
except raw artifacts (site/, work/versions/, work/decisions.jsonl, committee/manifest.json).
Usage: python3 audit_project.py PROJECT_DIR
Checks:
  A. re-run the test runner on site/ and compare every status with work/state.json
  B. version chain: for each v(n)->v(n+1), the logged decision must explain the difference exactly:
     accepted -> applying its ops to v(n) reproduces v(n+1) byte for byte;
     check-added / contract-amended / check-retired -> only site-tests.json differs;
     rebaseline -> flagged (change made outside the loop)
  C. final site/ == last version snapshot
  D. no scenario in v(n) site-tests.json was later removed or edited (tests never weakened)
  E. decisions summary; rejected attempts listed
  F. committee reports still match the fingerprints taken when they were validated (if a manifest exists)
Exit 0 = CLEAN.
"""
import filecmp
import json
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

SCRIPTS = Path(__file__).resolve().parent
sys.path.insert(0, str(SCRIPTS))
from wt_common import apply_ops  # noqa: E402

P = Path(sys.argv[1])
work, site = P / "work", P / "site"
problems = []


def tree(d):
    return {str(p.relative_to(d)): p.read_bytes() for p in d.rglob("*") if p.is_file()}


def diff_files(a, b):
    ta, tb = tree(a), tree(b)
    return sorted(k for k in set(ta) | set(tb) if ta.get(k) != tb.get(k))


# A. reproducibility
out = Path(tempfile.mkstemp(suffix=".json")[1])
subprocess.run([sys.executable, str(SCRIPTS / "run_tests.py"), str(site), "--out", str(out), "--quiet"], check=True)
mine = {r["id"]: r["status"] for r in json.loads(out.read_text())["results"]}
state = json.loads((work / "state.json").read_text())
rec = {i: r["status"] for i, r in state["results"].items()}
dif = {i: (rec.get(i), mine.get(i)) for i in set(mine) | set(rec) if mine.get(i) != rec.get(i)}
print(f"A. re-run vs recorded state: {len(mine)} checks, differences: {dif or 'none'}")
if dif:
    problems.append(f"A: re-run differs from recorded state: {dif}")
cnt = {}
for s in mine.values():
    cnt[s] = cnt.get(s, 0) + 1
print(f"   my run counts: {cnt}")

# B. version chain
log = [json.loads(l) for l in (work / "decisions.jsonl").read_text().splitlines() if l.strip()]
by_after = {}
for e in log:
    if e.get("version_after") is not None:
        by_after.setdefault(e["version_after"], []).append(e)
versions = sorted(int(p.name[1:]) for p in (work / "versions").iterdir() if p.name.startswith("v"))
print(f"B. versions v{versions[0]}..v{versions[-1]} ({len(versions)} snapshots); decisions logged: {len(log)}")
for v in versions[1:]:
    es = by_after.get(v, [])
    prev, cur = work / "versions" / f"v{v-1}", work / "versions" / f"v{v}"
    kinds = {e["decision"] for e in es}
    if not es:
        problems.append(f"B: v{v} has no decision explaining it")
        print(f"   v{v}: NO DECISION"); continue
    if kinds <= {"check-added", "contract-amended", "check-retired"}:
        d = diff_files(prev, cur)
        ok = d == ["site-tests.json"]
        print(f"   v{v}: {sorted(kinds)} -> changed {d} {'OK' if ok else 'UNEXPECTED'}")
        if not ok:
            problems.append(f"B: v{v} {kinds} changed {d}")
    elif kinds == {"accepted"}:
        tmp = Path(tempfile.mkdtemp())
        shutil.copytree(prev, tmp / "s")
        ok_apply, msg = apply_ops(tmp / "s", es[0]["ops"])
        d = diff_files(tmp / "s", cur)
        ok = ok_apply and not d
        print(f"   v{v}: accepted #{es[0]['attempt']} '{es[0]['title'][:50]}' kind={es[0]['kind']} -> replay {'MATCHES' if ok else 'MISMATCH ' + str(d) + ' ' + msg}")
        if not ok:
            problems.append(f"B: replay of v{v} mismatched: {d} {msg}")
        shutil.rmtree(tmp)
    else:
        print(f"   v{v}: {sorted(kinds)} (FLAG: change outside the loop or unknown)")
        problems.append(f"B: v{v} decision kinds {kinds}")

# C. final site == last version
d = diff_files(work / "versions" / f"v{versions[-1]}", site)
print(f"C. site/ vs v{versions[-1]}: {'identical' if not d else 'DIFFERS ' + str(d)}")
if d:
    problems.append(f"C: site differs from last version: {d}")

# D. tests never weakened
first_seen = {}
for v in versions:
    f = work / "versions" / f"v{v}" / "site-tests.json"
    cfg = json.loads(f.read_text()) if f.exists() else {}
    for sc in cfg.get("scenarios", []):
        first_seen.setdefault(sc["id"], json.dumps(sc, sort_keys=True))
final_cfg = json.loads((site / "site-tests.json").read_text()) if (site / "site-tests.json").exists() else {}
final_sc = {sc["id"]: json.dumps(sc, sort_keys=True) for sc in final_cfg.get("scenarios", [])}
weak = [i for i, s in first_seen.items() if final_sc.get(i) != s]
retired_final = {r["id"] for r in final_cfg.get("retired", [])}
retired_logged = {e["targets"][0] for e in json.loads("[" + ",".join(
    l for l in (work / "decisions.jsonl").read_text().splitlines() if l.strip()) + "]") if e["decision"] == "check-retired"}
if retired_final != retired_logged:
    problems.append(f"D: retired list in site-tests.json {sorted(retired_final)} != retirements in the log {sorted(retired_logged)}")
print(f"   retired checks: {sorted(retired_final) or 'none'}")
base_cfg_p = work / "versions" / "v0" / "site-tests.json"
base_backend = json.loads(base_cfg_p.read_text()).get("backend") if base_cfg_p.exists() else None
print(f"D. scenarios ever added: {len(first_seen)}; removed/edited later: {weak or 'none'}; "
      f"backend contract v0 {base_backend} -> final {final_cfg.get('backend')}; skips: {final_cfg.get('skip', [])}")
if weak:
    problems.append(f"D: scenarios weakened: {weak}")
if base_backend != final_cfg.get("backend"):
    problems.append("D: backend contract changed after v0")

# E. decisions summary
dec = {}
for e in log:
    dec[e["decision"]] = dec.get(e["decision"], 0) + 1
print(f"E. decisions: {dec}")
for e in log:
    if e["decision"] == "rejected":
        print(f"   rejected #{e['attempt']}: {e['title'][:60]} | {e['reason'][:120]}")
base = json.loads((work / "baseline.json").read_text())
bc = {}
for r in base["results"].values():
    bc[r["status"]] = bc.get(r["status"], 0) + 1
print(f"   baseline counts: {bc}")
# F. committee fingerprints
for man in sorted(P.glob("committee*/manifest.json")) + sorted(P.glob("committee/*/manifest.json")):
    m = json.loads(man.read_text(encoding="utf-8"))
    import hashlib
    changed = [f for f, h in m["sha256"].items()
               if not (man.parent / f).exists() or hashlib.sha256((man.parent / f).read_bytes()).hexdigest() != h]
    print(f"F. {man.parent.relative_to(P)}: validated={m['valid']} at state v{m['state_version']}; "
          f"{'reports unchanged since validation' if not changed else 'CHANGED: ' + str(changed)}")
    if changed or not m["valid"]:
        problems.append(f"F: {man.parent.relative_to(P)} invalid or changed after validation: {changed}")
if not any(P.glob("committee*/manifest.json")) and not any(P.glob("committee/*/manifest.json")):
    print("F. no committee manifest (reports were never validated)")
    if (P / "committee").exists():
        problems.append("F: committee reports exist but were never validated (scripts/validate_committee.py)")

print("\nAUDIT:", "CLEAN" if not problems else "PROBLEMS")
for p in problems:
    print("  -", p)
sys.exit(0 if not problems else 1)
