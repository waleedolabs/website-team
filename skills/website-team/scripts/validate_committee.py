#!/usr/bin/env python3
"""Validate the committee's reports after Step 4 and fingerprint them.

Usage: python3 validate_committee.py --project PROJECT [--dir committee] [--quiet]

Each committee member writes its OWN full report to the file the coordinator names; nobody retypes or
summarises them. This script checks that, and that the chair's plan is consistent with the real test state:
  * advocate.md, critic.md, inspector.md, chair.md, plan.json exist and are substantial
  * the reports look like originals, not summaries (first line must not announce a summary/condensed copy)
  * advocate has ADV-n items, critic has CRIT-n items with a Class line, inspector cites real check ids
  * plan.json: valid shape; 'proven' items only on checks that currently fail/need review; 'fix' items name
    check ids that exist (or are scenarios listed in checks_to_add); evidence/kind values are valid
  * the site was not modified by any committee member (tree hash equals work/state.json)
Writes DIR/manifest.json with a SHA-256 of every report so later edits are detectable. Exit 0 = OK.
"""
import argparse
import hashlib
import json
import re
import sys
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

# explicit admissions that a file is a retyped/condensed copy (a heading such as "## ملخص الرئيس" is legitimate)
SUMMARY_MARKERS = ("condensed", "abridged", "summary of", "verbatim summary", "excerpt", "retyped",
                   "نسخة مختصرة", "ليست حرفية", "ملخص مختصر", "مقتطف", "مختصر من تقرير", "ملخص لتقرير")
SIGNATURES = {"advocate.md": "site-advocate", "critic.md": "design-critic", "inspector.md": "qa-inspector",
              "chair.md": "committee-chair"}
FILES = ("advocate.md", "critic.md", "inspector.md", "chair.md", "plan.json")
MIN_CHARS = 400


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--project", required=True)
    ap.add_argument("--dir", default="committee")
    ap.add_argument("--quiet", action="store_true")
    ap.add_argument("--verify-manifest", action="store_true",
                    help="later audits: only check that the reports still match the fingerprints taken at Step 4")
    a = ap.parse_args()
    P = Path(a.project)
    C = P / a.dir
    problems = []
    if a.verify_manifest:
        m = json.loads((C / "manifest.json").read_text(encoding="utf-8"))
        changed = [f for f, h in m["sha256"].items()
                   if not (C / f).exists() or hashlib.sha256((C / f).read_bytes()).hexdigest() != h]
        print(f"MANIFEST (taken at state v{m['state_version']}, valid={m['valid']}):",
              "reports unchanged" if not changed else f"CHANGED since validation: {changed}")
        return 0 if not changed and m["valid"] else 1

    def need(cond, msg):
        if not cond:
            problems.append(msg)
        return cond

    state = json.loads((P / "work" / "state.json").read_text(encoding="utf-8"))
    results = state["results"]
    for f in FILES:
        need((C / f).exists(), f"missing {a.dir}/{f}")
    texts = {f: (C / f).read_text(encoding="utf-8") for f in FILES if (C / f).exists()}

    for f in ("advocate.md", "critic.md", "inspector.md", "chair.md"):
        t = texts.get(f)
        if t is None:
            continue
        need(len(t.strip()) >= MIN_CHARS, f"{f} is only {len(t.strip())} characters: not a full report")
        head = " ".join(l for l in t.splitlines()[:3]).lower()
        need(not any(m in head for m in SUMMARY_MARKERS),
             f"{f} announces itself as a condensed copy ({head[:70]!r}): the member's original report is required")
        need(f"<!-- website-team:{SIGNATURES[f]} -->" in t,
             f"{f} lacks the member's closing signature <!-- website-team:{SIGNATURES[f]} --> "
             "(the member must write its own file)")

    if "advocate.md" in texts:
        need(re.search(r"\bADV-\d+", texts["advocate.md"]), "advocate.md has no ADV-n items")
    if "critic.md" in texts:
        crit = re.findall(r"\bCRIT-\d+", texts["critic.md"])
        need(crit, "critic.md has no CRIT-n items")
        need(len(re.findall(r"Class\s*:|التصنيف\s*:|الفئة\s*:", texts["critic.md"])) >= len(set(crit)) > 0,
             "critic.md: every CRIT item needs a Class line (problem / probable / taste)")
    if "inspector.md" in texts:
        cited = [i for i in results if i in texts["inspector.md"]]
        need(cited, "inspector.md cites no real check id from work/state.json")

    plan = None
    if "plan.json" in texts:
        try:
            plan = json.loads(texts["plan.json"])
        except json.JSONDecodeError as e:
            need(False, f"plan.json is not valid JSON: {e}")
    if plan is not None:
        for k in ("keep", "items", "checks_to_add", "deferred", "questions_for_user"):
            need(isinstance(plan.get(k), list), f"plan.json: '{k}' must be a list")
        planned = {f"scenario:{c.get('id')}" for c in plan.get("checks_to_add", []) if isinstance(c, dict)}
        for it in plan.get("items", []):
            iid = it.get("id", "?")
            ev, kind, cids = it.get("evidence"), it.get("kind"), it.get("check_ids", [])
            need(ev in ("proven", "suspected", "opinion"), f"plan {iid}: evidence must be proven/suspected/opinion")
            need(kind in ("fix", "design"), f"plan {iid}: kind must be fix/design")
            need(isinstance(it.get("needs_user_approval"), bool), f"plan {iid}: needs_user_approval must be true/false")
            need(isinstance(cids, list), f"plan {iid}: check_ids must be a list")
            unknown = [c for c in cids if c not in results and c not in planned]
            need(not unknown, f"plan {iid}: unknown check ids {unknown}")
            if kind == "fix":
                need(bool(cids), f"plan {iid}: kind=fix needs check_ids that should start passing")
            if ev == "proven":
                not_failing = [c for c in cids if results.get(c, {}).get("status") not in ("fail", "needs_review")]
                need(cids and not not_failing,
                     f"plan {iid}: marked 'proven' but these checks are not failing in the test state: {not_failing or 'none listed'}")

    from run_tests import tree_hash
    need(tree_hash(P / "site") == state["tree_hash"],
         "site/ changed since the last verified state: a committee member (or someone) modified the site")

    manifest = {"at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"), "state_version": state["version"],
                "sha256": {f: hashlib.sha256((C / f).read_bytes()).hexdigest() for f in FILES if (C / f).exists()},
                "valid": not problems, "problems": problems}
    (C / "manifest.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
    if not a.quiet:
        print("COMMITTEE:", "VALID" if not problems else "INVALID")
        for p in problems:
            print("  -", p)
        if plan is not None and not problems:
            print(f"  plan: {len(plan['items'])} items, {len(plan['checks_to_add'])} checks to add; fingerprints in {a.dir}/manifest.json")
    return 0 if not problems else 1


if __name__ == "__main__":
    sys.exit(main())
