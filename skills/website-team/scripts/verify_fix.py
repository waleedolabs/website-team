#!/usr/bin/env python3
"""Fix-verification loop. The only way changes reach the site during the fix phase.

  verify_fix.py init   --site SITE --work WORK
      Run the suite (3x) on the site, store it as the baseline and current state.
  verify_fix.py try    --site SITE --work WORK --proposal P.json [--approved]
      Apply the proposal to an isolated copy, run the suite 3x, compare with the current state.
      ACCEPT -> the site is updated and a version snapshot is saved.
      REJECT -> nothing in the site changes.
  verify_fix.py add-check --site SITE --work WORK --scenario S.json [MORE.json ...]
      Add a custom behaviour check (scenario) to site-tests.json. Must give a stable pass/fail and
      must not change any other result. FAIL = a suspicion is now proven; PASS = refuted, kept as guard.
  verify_fix.py retire-check --site SITE --work WORK --id scenario:X --reason "..." [--replaced-by scenario:Y | --approved]
      Withdraw a scenario that was written wrongly (kept on record, never deleted).
  verify_fix.py status --work WORK
      Show the current failing/needs_review checks and attempt counts.

Proposal JSON:
  {"title": "...", "rationale": "...", "source": "plan item 3 / critic",
   "kind": "fix" | "design",          # fix: must make >=1 target pass; design: must not regress anything
   "targets": ["btn:index.html:#order-btn"],   # required for kind=fix
   "needs_user_approval": false,       # true for content/sensitive changes; requires --approved
   "removes": [],                      # check ids whose element/page is deliberately removed (needs approval)
   "ops": [ ...edit operations, see wt_common.py... ]}

Acceptance rules:
  * patch must apply cleanly (exact-once replacements, no paths outside the site)
  * no flaky check after the change
  * no regression: pass -> not pass; fail -> needs_review (masking, e.g. hiding a broken form);
    needs_review -> fail; a new failing element/page; a removed element/page not listed in 'removes'
  * kind=fix: at least one TARGET must go from fail/needs_review to pass
  * kind=design: no test improvement is required; benefit is logged as UNVERIFIED
Caps: max 3 attempts per target, max 25 attempts in total.
"""
import argparse
import json
import shutil
import sys
from datetime import datetime, timezone
from pathlib import Path

from wt_common import apply_ops, compare, counts, run_suite, run_suite_incremental, run_targeted

MAX_PER_TARGET = 3
MAX_TOTAL = 25


def now():
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def tree_hash(site):
    from run_tests import tree_hash as th
    return th(Path(site))


def load(p):
    return json.loads(Path(p).read_text(encoding="utf-8"))


def save(p, data):
    Path(p).write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


def check_layout(site, work):
    site, work = Path(site).resolve(), Path(work).resolve()
    if work == site or site in work.parents:
        sys.exit("ERROR: --work must be OUTSIDE the site directory (it would be served and tested)")
    return site, work


def snapshot(site, dest):
    if dest.exists():
        shutil.rmtree(dest)
    shutil.copytree(site, dest)


def cmd_init(a):
    site, work = check_layout(a.site, a.work)
    existing = (work / "state.json").exists()
    if existing and not a.force:
        sys.exit("ERROR: work dir already initialised (use --force to re-baseline after changes made outside the loop)")
    work.mkdir(parents=True, exist_ok=True)
    suite = run_suite(site)
    suite["at"] = now()
    if not existing:
        save(work / "baseline.json", suite)  # the original starting point is never overwritten
        (work / "decisions.jsonl").write_text("", encoding="utf-8")
        version = 0
    else:
        # history and caps survive a re-baseline; the outside change is recorded as unverified
        prev = load(work / "state.json")
        version = prev["version"] + 1
        log_decision(work, {"attempt": len(read_log(work)) + 1, "at": now(), "kind": "rebaseline",
                            "title": "re-baseline after changes made outside the loop",
                            "decision": "rebaseline", "targets": [], "ops": [],
                            "reason": "site changed outside verify_fix; these changes were NOT verified by the loop",
                            "counts_before": counts(prev["results"]), "counts_after": counts(suite["results"]),
                            "version_before": prev["version"], "version_after": version})
    save(work / "state.json", {"version": version, **suite})
    snapshot(site, work / "versions" / f"v{version}")
    c = counts(suite["results"])
    print(f"{'RE-BASELINE' if existing else 'BASELINE'} v{version}: {json.dumps(c)}")
    for i, r in suite["results"].items():
        if r["status"] in ("fail", "needs_review"):
            print(f"  {r['status']:12} {i} | {r['detail']}")


def log_decision(work, entry):
    entry["attempt"] = len(read_log(work)) + 1  # sequential, even within a batch
    with open(work / "decisions.jsonl", "a", encoding="utf-8") as f:
        f.write(json.dumps(entry, ensure_ascii=False) + "\n")


def read_log(work):
    p = work / "decisions.jsonl"
    if not p.exists():
        return []
    return [json.loads(l) for l in p.read_text(encoding="utf-8").splitlines() if l.strip()]


def cmd_try(a):
    site, work = check_layout(a.site, a.work)
    if not (work / "state.json").exists():
        sys.exit("ERROR: run 'init' first")
    state = load(work / "state.json")
    prop = load(a.proposal)
    log = read_log(work)
    kind = prop.get("kind", "fix")
    targets = prop.get("targets") or []
    entry = {"attempt": len(log) + 1, "at": now(), "title": prop.get("title", "(untitled)"),
             "rationale": prop.get("rationale", ""), "source": prop.get("source", ""), "kind": kind,
             "targets": targets, "ops": prop.get("ops", []), "version_before": state["version"], "counted": False}

    def reject(reason, **extra):
        entry.update(decision="rejected", reason=reason, **extra)
        log_decision(work, entry)
        print(f"REJECTED: {reason}")
        for k in ("improved", "regressed", "flaky"):
            if extra.get(k):
                print(f"  {k}: {extra[k]}")
        for i, d in (extra.get("details") or {}).items():
            print(f"    {i}: {d}")
        sys.exit(1)

    # guards
    removes = prop.get("removes") or []
    entry["removes"] = removes
    if kind not in ("fix", "design"):
        reject(f"unknown kind {kind!r}")
    if any(Path(str(op.get("file", ""))).name == "site-tests.json" for op in (prop.get("ops") or [])):
        reject("a fix may not change site-tests.json (the test contract). Change it only with the user's "
               "agreement, then run 'init --force' so the change is recorded as unverified")
    if removes and not prop.get("needs_user_approval"):
        reject("removing elements/pages ('removes') always needs the user's approval: set needs_user_approval")
    if sum(1 for e in log if e.get("counted")) >= MAX_TOTAL:
        reject(f"attempt cap reached ({MAX_TOTAL} attempts in total); stop and report")
    if kind == "fix" and not targets:
        reject("kind=fix requires 'targets' (the check ids it claims to fix)")
    unknown = [t for t in targets if t not in state["results"]]
    if unknown:
        reject(f"unknown target check ids: {unknown}")
    for t in targets:
        used = sum(1 for e in log if e.get("counted") and t in e.get("targets", []))
        if used >= MAX_PER_TARGET:
            reject(f"attempt cap reached for {t} ({MAX_PER_TARGET} attempts); leave it open in the report")
    if prop.get("needs_user_approval") and not a.approved:
        reject("needs the user's approval (re-run with --approved only after the user agreed)")
    if tree_hash(site) != state["tree_hash"]:
        reject("site was changed outside the loop since the last verified state; run 'init --force' to re-baseline")

    # isolated candidate (from here on the attempt counts toward the caps)
    entry["counted"] = True
    cand = work / "candidate"
    if cand.exists():
        shutil.rmtree(cand)
    shutil.copytree(site, cand)
    ok, msg = apply_ops(cand, prop.get("ops"))
    if not ok:
        shutil.rmtree(cand)
        reject(f"patch did not apply: {msg}")
    before = state["results"]
    after = run_suite_incremental(cand, before)
    improved, regressed, flaky = compare(before, after["results"], allowed_removals=removes)
    hit = [t for t in targets if t in improved]
    details = {i: after["results"][i]["detail"] for i in set(regressed + flaky + targets) if i in after["results"]}
    extra = dict(improved=improved, regressed=regressed, flaky=flaky, targets_fixed=hit, details=details,
                 counts_before=counts(before), counts_after=counts(after["results"]))
    if flaky:
        shutil.rmtree(cand)
        reject("unstable (flaky) results after the change: verdict cannot be trusted", **extra)
    if regressed:
        shutil.rmtree(cand)
        reject("regression (something got worse, was masked, or was removed): " + ", ".join(regressed), **extra)
    if kind == "fix" and not hit:
        shutil.rmtree(cand)
        reject("none of the targets was fixed: " + ", ".join(f"{t} -> {after['results'][t]['status']}"
                                                                 for t in targets if t in after["results"]), **extra)

    # accept: replace the site contents with the verified candidate
    for p in sorted(site.rglob("*"), reverse=True):
        if p.is_file() or p.is_symlink():
            p.unlink()
        elif p.is_dir():
            p.rmdir()
    for p in cand.rglob("*"):
        dest = site / p.relative_to(cand)
        if p.is_dir():
            dest.mkdir(parents=True, exist_ok=True)
        else:
            dest.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(p, dest)
    shutil.rmtree(cand)
    version = state["version"] + 1
    snapshot(site, work / "versions" / f"v{version}")
    new_hash = tree_hash(site)
    save(work / "state.json", {"version": version, "at": now(), **after, "tree_hash": new_hash})
    reason = ("fixed " + ", ".join(hit) if kind == "fix" else "no regression; design benefit UNVERIFIED by tests")
    if improved and kind == "design":
        reason += "; also improved " + ", ".join(improved)
    entry.update(decision="accepted", reason=reason, version_after=version, **extra)
    log_decision(work, entry)
    print(f"ACCEPTED -> v{version}: {reason}")
    print(f"  counts: {json.dumps(extra['counts_before'])} -> {json.dumps(extra['counts_after'])}")
    if improved:
        print(f"  improved: {improved}")



def cmd_add_check(a):
    """Add a custom scenario check to the test contract. The site itself is not changed.
    The new check must give a definite result (pass/fail) on 3 identical runs, and no other check may change."""
    from run_tests import validate_scenario
    site, work = check_layout(a.site, a.work)
    if not (work / "state.json").exists():
        sys.exit("ERROR: run 'init' first")
    state = load(work / "state.json")
    docs = [load(f) for f in a.scenario]
    if any("form_setup" in d or "form_values" in d for d in docs):
        if len(docs) != 1:
            sys.exit("CHECK REJECTED: add a form amendment (form_setup/form_values) on its own, not together with scenarios")
        return amend_form_setup(site, work, state, docs[0])
    scs = docs
    if tree_hash(site) != state["tree_hash"]:
        sys.exit("CHECK REJECTED: site was changed outside the loop since the last verified state; run 'init --force' first")

    def entry_for(sc):
        cid = f"scenario:{sc.get('id', '?')}"
        return cid, {"attempt": len(read_log(work)) + 1, "at": now(), "kind": "add-check", "title": f"add check {cid}",
                     "rationale": sc.get("desc", ""), "source": sc.get("source", ""), "targets": [cid], "ops": [],
                     "scenario": sc, "counted": False, "version_before": state["version"]}

    cfg_now = json.loads((site / "site-tests.json").read_text(encoding="utf-8")) if (site / "site-tests.json").exists() else {}
    retired_ids = {r["id"] for r in cfg_now.get("retired", [])}
    good, ids = [], set()
    for sc in scs:
        cid, entry = entry_for(sc)
        problems = validate_scenario(sc)
        reason = None
        if problems:
            reason = "invalid scenario: " + "; ".join(problems)
        elif cid in retired_ids:
            reason = f"{cid} was retired; ids are permanent, use a new id"
        elif cid in state["results"] or cid in ids:
            reason = f"{cid} already exists (scenario ids are permanent; use a new id)"
        if reason:
            entry.update(decision="rejected", reason=reason)
            log_decision(work, entry)
            print(f"CHECK REJECTED {cid}: {reason}")
        else:
            good.append(sc)
            ids.add(cid)
    if not good:
        sys.exit(1)

    cand = work / "candidate"
    if cand.exists():
        shutil.rmtree(cand)
    shutil.copytree(site, cand)
    cfg_p = cand / "site-tests.json"
    cfg = json.loads(cfg_p.read_text(encoding="utf-8")) if cfg_p.exists() else {}
    cfg.setdefault("scenarios", []).extend(good)
    cfg_p.write_text(json.dumps(cfg, ensure_ascii=False, indent=2), encoding="utf-8")
    # the site itself is unchanged, so only the new checks can produce new information: run them 3x
    new_results = run_targeted(cand, sorted(ids))
    after = {"results": {**state["results"], **new_results}}
    changed = []
    if changed:
        shutil.rmtree(cand)
        for sc in good:
            cid, entry = entry_for(sc)
            entry.update(decision="rejected", reason=f"other checks changed status while only checks were added (unstable): {changed}")
            log_decision(work, entry)
        sys.exit(f"CHECKS REJECTED: other checks changed status while only checks were added (unstable): {changed}")

    # keep only the usable ones (stable pass/fail); unusable ones are logged and dropped
    usable, results = [], dict(after["results"])
    for sc in good:
        cid, entry = entry_for(sc)
        new = after["results"].get(cid)
        if new is None or new["flaky"] or new["status"] not in ("pass", "fail"):
            entry.update(decision="rejected",
                         reason=f"the new check is not usable: {new['status'] if new else 'missing'}: {new['detail'] if new else ''}")
            log_decision(work, entry)
            print(f"CHECK REJECTED {cid}: {entry['reason']}")
            results.pop(cid, None)
        else:
            usable.append((sc, cid, entry, new))
    if not usable:
        shutil.rmtree(cand)
        sys.exit(1)
    cfg["scenarios"] = [x for x in cfg["scenarios"] if f"scenario:{x.get('id')}" not in ids or
                        any(x is u[0] for u in usable)]
    (site / "site-tests.json").write_text(json.dumps(cfg, ensure_ascii=False, indent=2), encoding="utf-8")
    shutil.rmtree(cand)
    version = state["version"] + 1
    snapshot(site, work / "versions" / f"v{version}")
    save(work / "state.json", {**state, "version": version, "at": now(), "results": results, "tree_hash": tree_hash(site)})
    for sc, cid, entry, new in usable:
        if new["status"] == "fail":
            outcome = "currently FAILS: the suspected problem is now PROVEN"
        else:
            outcome = "currently PASSES: the suspicion is refuted; kept as a regression guard"
        entry.update(decision="check-added", reason=outcome, initial_status=new["status"],
                     initial_detail=new["detail"], initial_evidence=new.get("evidence"), version_after=version)
        log_decision(work, entry)
        print(f"CHECK ADDED {cid}: {outcome}")
        if new.get("evidence"):
            print(f"  evidence: {new['evidence']}")
    print(f"-> v{version}")



def amend_form_setup(site, work, state, doc):
    """Amend the test contract for the generic check of ONE form:
      form_setup  : steps to run first (e.g. put an item in the cart, possibly on another page via 'visit')
      form_values : realistic values for named fields that have strict validation
    Only adds; never replaces an existing declaration. Requires a reason. The affected check must give a
    stable pass/fail and no other check may change. Logged visibly as a test-contract amendment."""
    log = read_log(work)
    keys = set(doc.get("form_setup", {})) | set(doc.get("form_values", {}))
    title_key = next(iter(keys)) if keys else "?"
    affected = [i for i in state["results"] if i.startswith("form:") and i.endswith(":" + title_key)]
    parts = [k for k in ("form_setup", "form_values") if k in doc]
    entry = {"attempt": len(log) + 1, "at": now(), "kind": "add-check",
             "title": f"{' + '.join('precondition' if k == 'form_setup' else 'field values' for k in parts)} for form {title_key}",
             "rationale": doc.get("reason", ""), "source": doc.get("source", ""), "targets": affected, "ops": [],
             **{k: doc[k] for k in parts}, "counted": False, "version_before": state["version"]}

    def reject(reason):
        entry.update(decision="rejected", reason=reason)
        log_decision(work, entry)
        sys.exit(f"CHECK REJECTED: {reason}")

    if len(keys) != 1:
        reject("an amendment must target exactly one form (the same key in form_setup and form_values)")
    key = title_key
    if not doc.get("reason"):
        reject("an amendment needs a 'reason' (it is shown in the report)")
    steps = doc.get("form_setup", {}).get(key)
    if steps is not None and (not isinstance(steps, list) or not steps or any(
            len([k for k in st if k in ("click", "fill", "select", "check", "wait", "visit")]) != 1 for st in steps)):
        reject("form_setup steps must be a non-empty list of click/fill/select/check/wait/visit steps")
    values = doc.get("form_values", {}).get(key)
    if values is not None and (not isinstance(values, dict) or not values):
        reject("form_values must map field names to values")
    if not affected:
        reject(f"no generic form check matches {key}")
    if tree_hash(site) != state["tree_hash"]:
        reject("site was changed outside the loop since the last verified state; run 'init --force' first")
    cand = work / "candidate"
    if cand.exists():
        shutil.rmtree(cand)
    shutil.copytree(site, cand)
    cfg_p = cand / "site-tests.json"
    cfg = json.loads(cfg_p.read_text(encoding="utf-8")) if cfg_p.exists() else {}
    for part, val in (("form_setup", steps), ("form_values", values)):
        if val is None:
            continue
        if key in cfg.get(part, {}):
            shutil.rmtree(cand)
            reject(f"{key} already has {part} (declarations can only be added, never replaced)")
        cfg.setdefault(part, {})[key] = val
    cfg_p.write_text(json.dumps(cfg, ensure_ascii=False, indent=2), encoding="utf-8")
    # only the affected form check can change (site files are unchanged): run it 3x
    after = {"results": {**state["results"], **run_targeted(cand, affected)}}
    changed = []
    bad = [i for i in affected if after["results"].get(i, {}).get("status") not in ("pass", "fail")
           or after["results"][i]["flaky"]]
    if changed or bad:
        shutil.rmtree(cand)
        reject(f"unstable or unusable: other checks changed {changed}; unusable affected {bad}")
    shutil.copy2(cfg_p, site / "site-tests.json")
    shutil.rmtree(cand)
    version = state["version"] + 1
    snapshot(site, work / "versions" / f"v{version}")
    save(work / "state.json", {**state, "version": version, "at": now(), "results": after["results"],
                               "tree_hash": tree_hash(site)})
    moves = {i: f"{state['results'][i]['status']} -> {after['results'][i]['status']}" for i in affected}
    entry.update(decision="contract-amended", reason=f"{' + '.join(parts)} added; {moves}", version_after=version,
                 initial_status=after["results"][affected[0]]["status"],
                 others_unchanged=len([i for i in after["results"] if i not in affected]))
    log_decision(work, entry)
    print(f"CONTRACT AMENDED ({' + '.join(parts)}) for {key} -> v{version}: {moves}")



def cmd_retire_check(a):
    """Withdraw a custom scenario check that was written wrongly. Never deletes it: the definition stays in
    site-tests.json and is listed under 'retired' with the reason, its status at retirement and any replacement.
    Rules: scenario checks only; reason required; either --replaced-by an existing active check, or --approved."""
    site, work = check_layout(a.site, a.work)
    state = load(work / "state.json")
    log = read_log(work)
    cid = a.id
    entry = {"attempt": len(log) + 1, "at": now(), "kind": "retire-check", "title": f"retire check {cid}",
             "rationale": a.reason or "", "source": "", "targets": [cid], "ops": [], "counted": False,
             "replaced_by": a.replaced_by, "version_before": state["version"]}

    def reject(reason):
        entry.update(decision="rejected", reason=reason)
        log_decision(work, entry)
        sys.exit(f"RETIRE REJECTED: {reason}")

    cfg_p = site / "site-tests.json"
    cfg = json.loads(cfg_p.read_text(encoding="utf-8")) if cfg_p.exists() else {}
    retired_ids = {r["id"] for r in cfg.get("retired", [])}
    if not cid.startswith("scenario:"):
        reject("only custom scenario checks can be retired (generic checks are part of the test suite)")
    if cid in retired_ids:
        reject(f"{cid} is already retired")
    if cid not in state["results"]:
        reject(f"{cid} is not an active check")
    if not a.reason or len(a.reason.strip()) < 15:
        reject("a clear --reason is required (at least 15 characters; it is shown in the report)")
    if a.replaced_by:
        if a.replaced_by == cid or a.replaced_by not in state["results"] or a.replaced_by in retired_ids:
            reject(f"--replaced-by must be another active check; {a.replaced_by!r} is not")
    elif not a.approved:
        reject("without --replaced-by, retiring a check needs the user's approval (--approved after they agreed)")
    if tree_hash(site) != state["tree_hash"]:
        reject("site was changed outside the loop since the last verified state; run 'init --force' first")
    status = state["results"][cid]["status"]
    cfg.setdefault("retired", []).append({"id": cid, "reason": a.reason.strip(), "replaced_by": a.replaced_by,
                                          "status_at_retirement": status, "at": now()})
    cfg_p.write_text(json.dumps(cfg, ensure_ascii=False, indent=2), encoding="utf-8")
    results = {i: r for i, r in state["results"].items() if i != cid}
    version = state["version"] + 1
    snapshot(site, work / "versions" / f"v{version}")
    save(work / "state.json", {**state, "version": version, "at": now(), "results": results, "tree_hash": tree_hash(site)})
    entry.update(decision="check-retired", reason=f"retired (was {status}): {a.reason.strip()}",
                 status_at_retirement=status, version_after=version, approved=bool(a.approved))
    log_decision(work, entry)
    print(f"CHECK RETIRED {cid} (was {status}) -> v{version}" + (f"; replaced by {a.replaced_by}" if a.replaced_by else "; user-approved"))


def cmd_status(a):
    work = Path(a.work)
    state = load(work / "state.json")
    log = read_log(work)
    print(f"version v{state['version']}  counts {json.dumps(counts(state['results']))}  attempts {sum(1 for e in log if e.get('counted'))}/{MAX_TOTAL}")
    for i, r in state["results"].items():
        if r["status"] in ("fail", "needs_review"):
            used = sum(1 for e in log if e.get("counted") and i in e.get("targets", []))
            print(f"  {r['status']:12} {i}  (attempts {used}/{MAX_PER_TARGET}) | {r['detail']}")


def main():
    ap = argparse.ArgumentParser()
    sub = ap.add_subparsers(dest="cmd", required=True)
    p = sub.add_parser("init"); p.add_argument("--site", required=True); p.add_argument("--work", required=True)
    p.add_argument("--force", action="store_true")
    p = sub.add_parser("try"); p.add_argument("--site", required=True); p.add_argument("--work", required=True)
    p.add_argument("--proposal", required=True); p.add_argument("--approved", action="store_true")
    p = sub.add_parser("add-check"); p.add_argument("--site", required=True); p.add_argument("--work", required=True)
    p.add_argument("--scenario", required=True, nargs="+", help="one or more scenario JSON files")
    p = sub.add_parser("retire-check"); p.add_argument("--site", required=True); p.add_argument("--work", required=True)
    p.add_argument("--id", required=True); p.add_argument("--reason"); p.add_argument("--replaced-by")
    p.add_argument("--approved", action="store_true")
    p = sub.add_parser("status"); p.add_argument("--work", required=True)
    a = ap.parse_args()
    {"init": cmd_init, "try": cmd_try, "add-check": cmd_add_check, "retire-check": cmd_retire_check,
     "status": cmd_status}[a.cmd](a)


if __name__ == "__main__":
    sys.path.insert(0, str(Path(__file__).parent))
    main()
