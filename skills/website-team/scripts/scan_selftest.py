#!/usr/bin/env python3
"""Regression tests for scan.py (scan -> edit -> recheck -> restore). Usage: scan_selftest.py"""
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
SCAN = HERE / "scan.py"
PAGE = """<!doctype html>
<html>
<head><meta charset="utf-8"><style>.note{color:#bbb}.ok{color:#222}</style></head>
<body>
<nav><a href="#contactt">اتصل بنا</a><a href="#about">عن المحل</a></nav>
<section id="about"><h1>محل تجربة للاختبار والتحقق من الأدوات</h1><p class="ok">نص عربي طويل بما يكفي لاكتشاف الاتجاه من اليمين إلى اليسار</p>
<p class="note">ساعات العمل</p><button id="go" onclick="document.body.dataset.x=1">ابدأ</button></section>
<section id="contact"><h2>اتصل</h2></section>
</body></html>
"""
fails = []


def run(*args):
    p = subprocess.run([sys.executable, str(SCAN), *args], capture_output=True, text=True, encoding="utf-8")
    return p.stdout + p.stderr


def check(name, cond, out=""):
    print(("OK   " if cond else "FAIL ") + name)
    if not cond:
        fails.append(name)
        print(out[-1500:])


def main():
    tmp = Path(tempfile.mkdtemp())
    site = tmp / "site"
    site.mkdir()
    (site / "index.html").write_text(PAGE, encoding="utf-8")
    st = site / ".website-team"
    out = run("scan", str(site), "--state", str(st))
    check("scan finds broken anchor with its line", "link:index.html:#contactt" in out and "index.html:5:" in out, out)
    check("scan finds missing dir=rtl", "dir:index.html" in out, out)
    check("scan finds contrast with CSS line", "contrast:index.html" in out and ".note{color:#bbb}" in out, out)
    check("backup made", (st / "backup" / "index.html").is_file())
    check("state folder is not scanned as a page", ":.website-team/" not in out and ":website-team/" not in out, out)

    t = PAGE.replace("#contactt", "#contact").replace("<html>", '<html lang="ar" dir="rtl">')
    (site / "index.html").write_text(t, encoding="utf-8")
    out = run("recheck", str(site), "--state", str(st))
    check("corrected link counted as fixed (link kept)", "link kept, now points elsewhere" in out, out)
    check("lang and dir fixed", "fixed: lang:index.html" in out and "fixed: dir:index.html" in out, out)
    check("still-open contrast reported", "STILL OPEN" in out and "contrast:index.html" in out, out)

    t2 = t.replace('<a href="#contact">اتصل بنا</a>', "").replace('onclick="document.body.dataset.x=1"', 'onclick="nope()"')
    (site / "index.html").write_text(t2, encoding="utf-8")
    out = run("recheck", str(site), "--state", str(st))
    check("button broken by an edit is flagged", "BROKEN BY THE EDIT" in out and "btn:index.html:#go" in out
          and "of which 1 were passing before" in out, out)
    check("deleted link is not counted as fixed", "no longer tested" in out and "link:index.html:#contactt" in out, out)

    # noise sources seen on a real project: gradient headings, buttons hidden until a state change, web fonts
    n = tmp / "noise"
    n.mkdir()
    (n / "index.html").write_text("""<!doctype html><html lang="ar" dir="rtl"><head><meta charset="utf-8"><title>اختبار الضجيج</title>
<meta name="viewport" content="width=device-width, initial-scale=1">
<link rel="stylesheet" href="https://fonts.googleapis.com/css2?family=Cairo">
<style>h1{background:linear-gradient(90deg,#f0f,#0ff);-webkit-background-clip:text;background-clip:text;color:transparent;-webkit-text-fill-color:transparent}
#later{opacity:0;pointer-events:none}</style></head>
<body><h1>عنوان متدرج اللون طويل بما يكفي</h1><button id="later" onclick="this.dataset.x=1">لاحقاً</button>
<button id="go" onclick="document.body.dataset.x=1">ابدأ الآن</button></body></html>""", encoding="utf-8")
    out = run("scan", str(n), "--state", str(n / ".website-team"))
    check("gradient heading is not a contrast problem", "contrast:" not in out.split("NOT TESTABLE")[0], out)
    check("web fonts are not a problem", "external:" not in out, out)
    check("hidden-until-later button is grouped as not testable", "NOT TESTABLE (1)" in out and "btn:" not in out.split("NOT TESTABLE")[0], out)

    # site map
    m = tmp / "mapsite"
    m.mkdir()
    (m / "index.html").write_text("""<!doctype html><html lang="ar" dir="rtl"><head><title>خريطة</title>
<style>.bar .tools{display:none}.bar:hover .tools{display:flex}</style></head><body>
<div class="bar"><div class="tools"><button class="t">ثيم</button></div></div>
<button id="calc">احسب</button><button class="tab" data-k="a">أ</button><button class="tab" data-k="b">ب</button>
<form id="book"><input name="phone" required><button type="submit">احجز</button></form>
<script src="app.js"></script></body></html>""", encoding="utf-8")
    (m / "app.js").write_text("""function total(n){ return n * 0.5; }
document.getElementById('calc').addEventListener('click', function(){ document.getElementById('out').textContent = total(10); });
document.querySelectorAll('.tab').forEach(btn => btn.addEventListener('click', () => show(btn.dataset.k)));
function show(k){ document.querySelectorAll('.card').forEach(c => c.classList.toggle('hidden', c.dataset.k !== k)); }
document.getElementById('book').addEventListener('submit', e => { e.preventDefault(); alert('تم استلام طلبك'); });
""", encoding="utf-8")
    out = run("scan", str(m), "--state", str(m / ".website-team"))
    check("map links a button to its handler and flags calc", "#calc" in out and "total app.js:1" in out and "calc" in out, out)
    check("map links forEach-wired tabs to their handler", out.count("(inline app.js:3)") >= 2, out)
    check("map lists functions worth reading", "FUNCTIONS WORTH READING" in out and "show app.js:4" in out, out)
    check("map finds hover-only reveal", "SHOWN ONLY ON :hover" in out and ".bar:hover .tools" in out, out)
    check("map form handler flagged as fake success", "form #book" in out and "fake-success" in out, out)
    check("missing charset is reported", "charset:index.html" in out, out)
    check("scan output saved for a subagent", (m / ".website-team" / "scan.txt").is_file())
    out = run("scan", str(m), "--state", str(m / ".website-team"))
    check("second scan reuses the map cache", "2 unchanged, from cache" in out, out)

    out = run("restore", str(site), "--state", str(st), "index.html")
    check("restore puts the original back", (site / "index.html").read_text(encoding="utf-8") == PAGE, out)
    shutil.rmtree(tmp, ignore_errors=True)
    print(f"\nSCAN SELFTEST: {'PASSED' if not fails else 'FAILED'} ({22 - len(fails)}/22)")
    return 1 if fails else 0


if __name__ == "__main__":
    sys.exit(main())
