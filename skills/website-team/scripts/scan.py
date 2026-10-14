#!/usr/bin/env python3
"""Website Team scanner: finds problems with real browser tests and tells Claude exactly where they are.
It never edits the site. Claude fixes; `recheck` proves the fixes and catches anything that broke.

  scan.py scan    SITE --state STATE_DIR   first scan: saves a backup + baseline, prints numbered findings
  scan.py recheck SITE --state STATE_DIR   compares with the baseline: fixed / still open / NEW problems
  scan.py restore SITE --state STATE_DIR FILE   puts one file back from the backup (undo a bad fix)

Output is short on purpose: each finding has WHERE (file:line and the line itself) and the FIX direction.
"""
import argparse
import json
import re
import shutil
import sys
from pathlib import Path

for _s in (sys.stdout, sys.stderr):
    try:
        _s.reconfigure(encoding="utf-8", errors="replace")
    except (AttributeError, ValueError):
        pass

sys.path.insert(0, str(Path(__file__).resolve().parent))
import run_tests  # noqa: E402

SRC_EXT = (".html", ".htm", ".css", ".js")
SKIP_DIRS = {"node_modules", "__pycache__", "website-team"}
RTL_CHARS = re.compile(r"[֐-ࣿ]")

# What correct looks like, per check kind. ASK = needs the user's decision; only suggest it.
HINTS = {
    "console": "Fix the cause of this JS error (define the missing function or remove the broken call if nothing uses it).",
    "viewport": 'Add <meta name="viewport" content="width=device-width, initial-scale=1"> in <head>.',
    "lang": 'Add the page language on <html>, e.g. lang="ar" (and dir="rtl" for Arabic).',
    "dir": 'Arabic/Hebrew text without dir="rtl": add dir="rtl" on <html>.',
    "title": "Add a meaningful <title> (site name + purpose) in <head>.",
    "alt": 'Add a short alt describing the image (alt="" only if purely decorative).',
    "contrast": "Darken the text colour (or change the background) until the ratio is at least 4.5:1. Keep the text.",
    "labels": "Give each field a visible <label for=...> or an aria-label. Keep the placeholder.",
    "overflow": "Stop this element overflowing on a 375px phone (max-width:100% / width:auto / wrap). Keep its content.",
    "link-anchor": "This #anchor points to no element. Point it to the existing section id (do not remove the link).",
    "link-page": "This page does not exist. Do NOT delete the link text: point it to the closest existing page/section and list it under ASK (create the page?).",
    "btn": "Button does nothing visible. Make it do its obvious job (e.g. go to the order/contact section). Do not remove it.",
    "btn-error": "Clicking throws a JS error. Fix the handler.",
    "form-fake": "Form shows success but sends nothing. You MUST fix this now (it is a false claim, not content): stop showing 'sent/thank you' unless something is really sent - e.g. open WhatsApp/mailto with the message, or show an honest 'not connected yet, contact us by phone/WhatsApp' note. Then put 'connect a real backend' under ASK.",
    "form": "Form submission fails. Fix it so it really sends, or tell the user honestly.",
    "load": "Page does not load. Fix the file/path.",
}


def kind_of(r):
    cid, det = r["id"], (r.get("detail") or "")
    k = cid.split(":", 1)[0]
    if k == "link":
        return "link-anchor" if "#" in cid.split(":", 2)[-1] and "no element" in det else "link-page"
    if k == "btn":
        return "btn-error" if "JS error" in det else "btn"
    if k == "form":
        return "form-fake" if "NO data was sent" in det else "form"
    return k


def site_files(site):
    out = []
    for p in sorted(Path(site).rglob("*")):
        rel = p.relative_to(site)
        if any(x.startswith(".") or x in SKIP_DIRS for x in rel.parts):
            continue
        if p.is_file() and p.suffix.lower() in SRC_EXT:
            out.append(p)
    return out


def needles(r):
    """Text fragments that locate the finding in the source."""
    cid, ev, det = r["id"], r.get("evidence"), r.get("detail") or ""
    k = kind_of(r)
    parts = cid.split(":", 2)
    out = []
    if k in ("viewport", "title"):
        out = ["<head", "<title"]
    elif k in ("lang", "dir"):
        out = ["<html"]
    elif k == "console":
        for e in ev or []:
            m = re.search(r"(\w+) is not defined|(\w+) is not a function|reading '(\w+)'", e)
            if m:
                out.append(next(g for g in m.groups() if g) + "(")
    elif k == "alt":
        out = [f'src="{s}"' for s in (ev or [])] + [f"src='{s}'" for s in (ev or [])]
    elif k == "contrast":
        for c in ev or []:
            if isinstance(c, dict) and not c.get("ok", True):
                sel = c.get("selector", "")
                out += [f".{x}" for x in re.findall(r"\.([\w-]+)", sel)] + [f'id="{x}"' for x in re.findall(r"#([\w-]+)", sel)]
    elif k == "labels":
        for s in ev or []:
            m = re.search(r"name=([\w-]+)", s) or re.search(r"#([\w-]+)", s)
            if m:
                out += [f'name="{m.group(1)}"', f'id="{m.group(1)}"']
    elif k == "overflow":
        for s in ev or []:
            out += [f".{x}" for x in re.findall(r"\.([\w-]+)", s)] + [f'id="{x}"' for x in re.findall(r"#([\w-]+)", s)]
    elif k.startswith("link"):
        out = [f'href="{parts[-1]}"', f"href='{parts[-1]}'"]
    elif k.startswith("btn") or k.startswith("form"):
        key = parts[-1]
        if key.startswith("#"):
            out = [f'id="{key[1:]}"', f"id='{key[1:]}'"]
        else:
            out = [key[:30]]
    return [n for n in out if n]


def locate(site, r, files, limit=2):
    hits = []
    for n in needles(r):
        for f in files:
            try:
                lines = f.read_text(encoding="utf-8", errors="replace").splitlines()
            except OSError:
                continue
            for i, line in enumerate(lines, 1):
                if n in line:
                    s = line.strip()
                    if len(s) > 140:
                        j = max(0, s.find(n) - 50)
                        s = ("…" if j else "") + s[j:j + 130] + "…"
                    hits.append(f"{f.relative_to(site).as_posix()}:{i}: {s}")
                    break
            if len(hits) >= limit:
                return hits
    return hits


def rtl_findings(site, pages):
    out = []
    for pg in pages:
        p = Path(site) / pg
        try:
            t = p.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        m = re.search(r"<html[^>]*>", t, re.I)
        tag = m.group(0) if m else ""
        body = re.sub(r"<[^>]+>", " ", t)
        if len(RTL_CHARS.findall(body)) > 20:
            ok = bool(re.search(r'dir\s*=\s*["\']?rtl', tag, re.I))
            out.append({"id": f"dir:{pg}", "name": f"{pg}: right-to-left", "status": "pass" if ok else "fail",
                        "detail": 'dir="rtl" set' if ok else 'Arabic/Hebrew page without dir="rtl" on <html>',
                        "evidence": None})
    return out


def collect(site):
    data = run_tests.run(str(site))
    res = [r for r in data["results"] if not r["id"].startswith("N:")]
    res += rtl_findings(site, data["pages"])
    return data, res


def untested(r):
    """needs_review rows where the check itself could not run (e.g. a button hidden until a presentation starts)."""
    return r["status"] == "needs_review" and "could not run" in (r.get("detail") or "")


def problems(res):
    return [r for r in res if r["status"] in ("fail", "needs_review") and not untested(r)]


def untested_line(res):
    ids = [r["id"].split(":", 2)[-1] for r in res if untested(r)]
    if ids:
        print(f"\nNOT TESTABLE ({len(ids)}): hidden/covered/disabled at load, so they could not be clicked: "
              f"{', '.join(ids[:8])}{' ...' if len(ids) > 8 else ''}. Not counted as problems; mention in one phrase only if relevant.")


def show(site, rs, files, start=1):
    for n, r in enumerate(rs, start):
        k = kind_of(r)
        tag = "PROBLEM" if r["status"] == "fail" else "LIKELY "
        ask = "  [ASK USER]" if k in ("link-page", "form-fake") else ""
        print(f"\n{n}. {tag} {r['id']}{ask}\n   what: {r['detail']}")
        ev = r.get("evidence")
        if ev and k not in ("alt", "labels", "overflow", "contrast"):
            print(f"   seen: {json.dumps(ev, ensure_ascii=False)[:160]}")
        if k == "contrast":
            bad = [c for c in ev or [] if isinstance(c, dict) and not c.get("ok", True)]
            for c in bad[:3]:
                print(f"   seen: {c.get('selector')} ratio {c.get('ratio')} (need {c.get('need')}): {str(c.get('text'))[:50]}")
        for h in locate(site, r, files):
            print(f"   where: {h}")
        print(f"   fix: {HINTS.get(k, 'Fix so this check passes, without removing content.')}")


def cmd_scan(a):
    site, st = Path(a.site).resolve(), Path(a.state).resolve()
    data, res = collect(site)
    st.mkdir(parents=True, exist_ok=True)
    bk = st / "backup"
    if not bk.exists():
        for f in run_tests_files(site):
            d = bk / f.relative_to(site)
            d.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(f, d)
    link_text = {}
    src = "\n".join(f.read_text(encoding="utf-8", errors="replace") for f in site_files(site))
    for r in problems(res):
        if r["id"].startswith("link:"):
            href = r["id"].split(":", 2)[-1]
            m = re.search(r"<a\b[^>]*href=[\"']" + re.escape(href) + r"[\"'][^>]*>\s*([^<]+?)\s*</a>", src)
            if m:
                link_text[r["id"]] = m.group(1)
    (st / "baseline.json").write_text(json.dumps({"site": str(site), "results": res, "link_text": link_text},
                                                 ensure_ascii=False, indent=1), encoding="utf-8")
    ps = problems(res)
    passed = sum(r["status"] == "pass" for r in res)
    print(f"SCAN {site.name}: {len(res)} checks, {passed} pass, {len(ps)} problems "
          f"({sum(r['status'] == 'fail' for r in ps)} proven, {sum(r['status'] == 'needs_review' for r in ps)} likely). "
          f"Backup: {bk}")
    show(site, ps, site_files(site))
    untested_line(res)
    print("\nRULES: fix with small edits; never change prices/names/contact data or delete content; "
          "[ASK USER] items: do the honest minimal fix and list the decision for the user. Then run recheck.")


def run_tests_files(site):
    out = []
    for p in sorted(site.rglob("*")):
        rel = p.relative_to(site)
        if any(x.startswith(".") or x in SKIP_DIRS for x in rel.parts):
            continue
        if p.is_file():
            out.append(p)
    return out


def cmd_recheck(a):
    site, st = Path(a.site).resolve(), Path(a.state).resolve()
    base = json.loads((st / "baseline.json").read_text(encoding="utf-8"))
    before = {r["id"]: r for r in base["results"]}
    _, res = collect(site)
    now = {r["id"]: r for r in res}
    bad = lambda r: r is not None and r["status"] in ("fail", "needs_review") and not untested(r)  # noqa: E731
    fixed = [i for i, r in before.items() if bad(r) and not bad(now.get(i)) and i in now]
    gone = [i for i, r in before.items() if bad(r) and i not in now]
    texts = base.get("link_text", {})
    src_now = "\n".join(f.read_text(encoding="utf-8", errors="replace") for f in site_files(site))
    for i in list(gone):
        txt = texts.get(i)
        if i.startswith("link:") and txt and re.search(r"<a\b[^>]*>\s*" + re.escape(txt) + r"\s*</a>", src_now):
            gone.remove(i)
            fixed.append(i + " (link kept, now points elsewhere)")
    still = [now[i] for i, r in before.items() if bad(r) and bad(now.get(i))]
    new = [r for i, r in now.items() if bad(r) and not bad(before.get(i))]
    broke = [r for r in new if before.get(r["id"], {}).get("status") == "pass"]
    total_before = sum(bad(r) for r in before.values())
    print(f"RECHECK: fixed {len(fixed)} of {total_before}; still open {len(still)}; "
          f"new problems {len(new)} (of which {len(broke)} were passing before = BROKEN BY THE EDIT)")
    for i in fixed:
        print(f"  fixed: {i}")
    for i in gone:
        print(f"  no longer tested (element removed?): {i}  <- check you did not delete content")
    files = site_files(site)
    if new:
        print("\nNEW (fix these; anything BROKEN must be fixed or the file restored with `restore`):")
        show(site, new, files)
    if still:
        print("\nSTILL OPEN:")
        show(site, still, files, start=len(new) + 1)
    print(f"\nRESULT: {'CLEAN' if not still and not new else 'OPEN'}"
          f" | proven fixed: {len(fixed)} | open: {len(still) + len(new)} | broken by edits: {len(broke)}")
    (st / "last-recheck.json").write_text(json.dumps({"fixed": fixed, "gone": gone, "still": [r["id"] for r in still],
                                                       "new": [r["id"] for r in new], "broken": [r["id"] for r in broke]},
                                                      ensure_ascii=False, indent=1), encoding="utf-8")


def cmd_restore(a):
    site, st = Path(a.site).resolve(), Path(a.state).resolve()
    src = st / "backup" / a.file
    if not src.is_file():
        sys.exit(f"no backup of {a.file}")
    shutil.copy2(src, site / a.file)
    print(f"restored {a.file} from the backup taken at the first scan")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("cmd", choices=["scan", "recheck", "restore"])
    ap.add_argument("site")
    ap.add_argument("--state", required=True, help="folder for backup and baseline (outside the site)")
    ap.add_argument("file", nargs="?")
    a = ap.parse_args()
    if not Path(a.site).is_dir():
        sys.exit(f"not a folder: {a.site}")
    if a.cmd == "restore" and not a.file:
        sys.exit("restore needs FILE")
    {"scan": cmd_scan, "recheck": cmd_recheck, "restore": cmd_restore}[a.cmd](a)


if __name__ == "__main__":
    main()
