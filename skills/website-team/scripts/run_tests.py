#!/usr/bin/env python3
"""Generic website test runner (Playwright + Chromium). No AI involved.

Usage:
  python3 run_tests.py SITE_DIR [--out results.json] [--shots DIR] [--quiet: counts + non-pass lines only]

Optional config: SITE_DIR/site-tests.json
  {
    "backend": {"POST /api/contact": 200},   # declared backend contract, served by a mock
    "pages": ["index.html", "menu.html"],     # default: every *.html file (max 20)
    "skip": ["contrast:"],                    # check-id prefixes to skip (reported as not_run)
    "scenarios": [ ... ],                     # custom behaviour checks, see references/scenarios.md
    "form_setup": {"#order-form": [{"click": ".add"}]},  # preconditions before the generic form check
                                                         # (may 'visit' other pages; the form page is reopened)
    "form_values": {"#order-form": {"address": "..."}}   # realistic values for fields with strict validation
  }

Reliability rules:
  * Site served from SITE_DIR on 127.0.0.1 (ephemeral port). Requests to any other host are
    blocked, so results never depend on the internet.
  * Every check opens its own fresh page.
  * A check that cannot execute -> needs_review (never crashes, never a fake pass).
  * The runner knows nothing about expected bugs; it reports what it observes.
Statuses: pass | fail | needs_review | not_run
"""
import argparse
import hashlib
import json
import sys
import threading
from contextlib import contextmanager
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urljoin, urlparse

try:
    from playwright.sync_api import sync_playwright
except ImportError:  # pragma: no cover
    print("ERROR: playwright is not installed. Run scripts/check_env.py for setup steps.", file=sys.stderr)
    sys.exit(3)

TIMEOUT = 3000
DESKTOP = {"width": 1280, "height": 800}
MOBILE = {"width": 375, "height": 667}
MAX_PAGES = 20
MAX_BUTTONS_PER_PAGE = 25


# ------------------------------------------------------------------ server
def make_handler(site_dir, backend):
    class H(SimpleHTTPRequestHandler):
        def __init__(self, *a, **kw):
            super().__init__(*a, directory=site_dir, **kw)

        def _backend(self, method):
            key = f"{method} {self.path.split('?')[0]}"
            n = int(self.headers.get("Content-Length") or 0)
            if n:
                self.rfile.read(n)
            if key in backend:
                code = int(backend[key])
                body = b'{"ok": true}' if code < 400 else b'{"ok": false}'
                self.send_response(code)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)
                return True
            return False

        def do_GET(self):
            if not self._backend("GET"):
                super().do_GET()

        def do_POST(self):
            if not self._backend("POST"):
                self.send_error(404, "Not Found (endpoint not in declared backend)")

        do_PUT = do_POST

        def end_headers(self):
            self.send_header("Cache-Control", "no-store")
            super().end_headers()

        def log_message(self, *a):
            pass

    return H


class QuietServer(ThreadingHTTPServer):
    """The browser often closes connections mid-transfer (navigation, page close). Those disconnects are
    normal and must not print tracebacks that look like failures; any other server error is still shown."""
    daemon_threads = True

    def handle_error(self, request, client_address):
        exc = sys.exc_info()[1]
        if isinstance(exc, (BrokenPipeError, ConnectionResetError, ConnectionAbortedError)):
            return
        super().handle_error(request, client_address)


# ------------------------------------------------------------------ helpers
def row(cid, name, status, detail, evidence=None):
    return {"id": cid, "name": name, "status": status, "detail": detail, "evidence": evidence}


class Ctx:
    def __init__(self, browser, origin):
        self.browser = browser
        self.origin = origin

    @contextmanager
    def page(self, viewport=DESKTOP, offline=()):
        ctx = self.browser.new_context(viewport=viewport)

        def router(route):
            u = route.request.url
            if u.startswith("data:"):
                return route.continue_()
            if not u.startswith(self.origin):
                return route.abort()  # isolation: only our local server
            if urlparse(u).path in offline:
                return route.abort("internetdisconnected")  # simulated network failure
            return route.continue_()
        ctx.route("**/*", router)
        page = ctx.new_page()
        page.set_default_timeout(TIMEOUT)
        try:
            yield page
        finally:
            ctx.close()


SNAPSHOT_JS = """() => {
  const h = document.body ? document.body.outerHTML : '';
  return [location.href, document.body ? document.body.innerText : '', h.length, h, window.scrollY];
}"""

CANDIDATES_JS = """(maxN) => {
  const vis = e => { const r = e.getBoundingClientRect(); const s = getComputedStyle(e);
                     return r.width > 0 && r.height > 0 && s.visibility !== 'hidden' && s.display !== 'none'; };
  const all = [...document.querySelectorAll('button, input[type=button], [onclick], [role=button]')]
    .filter(e => !e.closest('form') || e.type === 'button' && e.tagName === 'BUTTON' && e.getAttribute('type') === 'button');
  const seen = {}; const out = [];
  all.forEach((e, i) => {
    const label = (e.id ? '#' + e.id : (e.innerText || e.value || e.getAttribute('aria-label') || e.tagName).trim().slice(0, 30));
    seen[label] = (seen[label] || 0) + 1;
    const key = seen[label] > 1 ? label + '[' + seen[label] + ']' : label;
    out.push({i, key, visible: vis(e), tag: e.tagName.toLowerCase()});
  });
  return out.slice(0, maxN);
}"""

TAG_JS = """(i) => {
  const all = [...document.querySelectorAll('button, input[type=button], [onclick], [role=button]')]
    .filter(e => !e.closest('form') || e.type === 'button' && e.tagName === 'BUTTON' && e.getAttribute('type') === 'button');
  all[i].setAttribute('data-wt-target', '1');
}"""

CONTRAST_JS = """() => {
  // Effective colours are computed by alpha-compositing every background layer from the root down
  // to the element (semi-transparent colours are blended, not treated as solid). Gradients are
  // judged against each colour stop (worst case). Text over url() images cannot be judged.
  const parse = c => { const m = c && c.match(/rgba?\\(([^)]+)\\)/); if (!m) return null;
    const p = m[1].split(/[\\s,\\/]+/).filter(Boolean).map(Number);
    return [p[0], p[1], p[2], p.length > 3 ? p[3] : 1]; };
  const blend = (top, base) => [0,1,2].map(i => top[i]*top[3] + base[i]*(1-top[3]));
  const lum = ([r,g,b]) => { const f = v => { v/=255; return v<=0.03928 ? v/12.92 : Math.pow((v+0.055)/1.055, 2.4); };
                             return 0.2126*f(r)+0.7152*f(g)+0.0722*f(b); };
  const ratio = (a, b) => { const l1 = lum(a), l2 = lum(b); return (Math.max(l1,l2)+0.05)/(Math.min(l1,l2)+0.05); };
  const bases = el => {           // possible effective background colours behind el, or null = unknown
    const chain = []; for (let n = el; n && n.nodeType === 1; n = n.parentElement) chain.unshift(n);
    let set = [[255,255,255]];
    for (const n of chain) {
      const cs = getComputedStyle(n);
      const bc = parse(cs.backgroundColor);
      if (bc && bc[3] > 0) set = set.map(b => blend(bc, b));
      const bi = cs.backgroundImage;
      if (bi && bi !== 'none') {
        if (bi.includes('url(')) return null;
        const stops = (bi.match(/rgba?\\([^)]+\\)/g) || []).map(parse).filter(Boolean);
        if (!stops.length) return null;
        const next = []; for (const b of set) for (const st of stops) next.push(blend(st, b));
        set = next;
      }
    }
    return set;
  };
  const out = [];
  document.querySelectorAll('body *').forEach(el => {
    if (['SCRIPT','STYLE','NOSCRIPT','svg'].includes(el.tagName)) return;
    const cs = getComputedStyle(el);
    if (cs.visibility === 'hidden' || cs.display === 'none') return;
    const hasText = [...el.childNodes].some(n => n.nodeType === 3 && n.textContent.trim());
    if (!hasText) return;
    const selector = el.tagName.toLowerCase() + (el.className && typeof el.className === 'string' ? '.' + el.className.trim().split(/\\s+/).join('.') : '');
    const text = el.textContent.trim().slice(0, 40);
    const fg = parse(cs.color), bs = bases(el);
    if (!fg || !bs) { out.push({selector, text, judged: false}); return; }
    let worst = Infinity;
    for (const b of bs) worst = Math.min(worst, ratio(blend(fg, b), b));
    const size = parseFloat(cs.fontSize), bold = parseInt(cs.fontWeight) >= 700;
    const need = (size >= 24 || (size >= 18.66 && bold)) ? 3 : 4.5;
    out.push({selector, text, judged: true, ratio: Math.round(worst*100)/100, need, ok: worst >= need});
  });
  return out;
}"""

LABELS_JS = """() => {
  const fields = [...document.querySelectorAll('input, select, textarea')]
    .filter(e => !['hidden','submit','button','reset','image'].includes((e.type||'').toLowerCase()));
  return fields.filter(e => {
    if (e.getAttribute('aria-label') && e.getAttribute('aria-label').trim()) return false;
    if (e.getAttribute('aria-labelledby')) return false;
    if (e.closest('label')) return false;
    if (e.id && document.querySelector('label[for="' + CSS.escape(e.id) + '"]')) return false;
    if (e.getAttribute('title') && e.getAttribute('title').trim()) return false;
    return true;
  }).map(e => e.tagName.toLowerCase() + (e.name ? '[name=' + e.name + ']' : '') + (e.id ? '#' + e.id : ''));
}"""

FILL_JS = """(formIndex) => {
  const f = document.querySelectorAll('form')[formIndex];
  const radios = {};
  // dates are relative to the day the test runs (a fixed date silently becomes "in the past"),
  // then clamped to the field's own min/max
  const pad = n => String(n).padStart(2, '0');
  const fut = new Date(Date.now() + 30 * 864e5);
  const isoDay = fut.getFullYear() + '-' + pad(fut.getMonth() + 1) + '-' + pad(fut.getDate());
  const isoWeek = (() => { const d = new Date(Date.UTC(fut.getFullYear(), fut.getMonth(), fut.getDate()));
    const day = d.getUTCDay() || 7; d.setUTCDate(d.getUTCDate() + 4 - day);
    const y0 = new Date(Date.UTC(d.getUTCFullYear(), 0, 1));
    return d.getUTCFullYear() + '-W' + pad(Math.ceil(((d - y0) / 864e5 + 1) / 7)); })();
  const clamp = (e, v) => { if (e.min && v < e.min) v = e.min; if (e.max && v > e.max) v = e.max; return v; };
  [...f.elements].forEach(e => {
    const t = (e.type || '').toLowerCase();
    if (e.disabled || ['hidden','submit','button','reset','image','file'].includes(t)) return;
    if (e.tagName === 'SELECT') { const o = [...e.options].find(o => o.value && !o.disabled); if (o) e.value = o.value; return; }
    if (t === 'checkbox') { e.checked = true; return; }
    if (t === 'radio') { if (!radios[e.name]) { e.checked = true; radios[e.name] = 1; } return; }
    const v = {email: 'test@example.com', tel: '0500000000', number: (e.min || '1'), url: 'https://example.com',
               date: clamp(e, isoDay), time: clamp(e, '10:00'), 'datetime-local': clamp(e, isoDay + 'T10:00'),
               password: 'Test1234!', month: clamp(e, isoDay.slice(0, 7)), week: clamp(e, isoWeek),
               color: '#336699', range: (e.min || '1')}[t];
    e.value = v !== undefined ? v : (e.tagName === 'TEXTAREA' ? 'Test message' : 'Test');
    e.dispatchEvent(new Event('input', {bubbles: true})); e.dispatchEvent(new Event('change', {bubbles: true}));
  });
  const invalid = [...f.elements].filter(e => e.willValidate && !e.checkValidity()).map(e => e.name || e.id || e.tagName);
  const sub = f.querySelector('button[type=submit], input[type=submit], button:not([type])');
  if (sub) sub.setAttribute('data-wt-submit', '1');
  return {invalid, hasSubmit: !!sub, action: f.getAttribute('action'), method: (f.getAttribute('method') || 'get').toLowerCase(),
          id: f.id || null};
}"""


SET_VALUES_JS = """([formIndex, values]) => {
  const f = document.querySelectorAll('form')[formIndex]; const missing = [];
  for (const [name, v] of Object.entries(values)) {
    const els = [...f.elements].filter(e => e.name === name);
    if (!els.length) { missing.push(name); continue; }
    for (const e of els) {
      const t = (e.type || '').toLowerCase();
      if (t === 'checkbox') e.checked = !!v;
      else if (t === 'radio') e.checked = (e.value === String(v));
      else e.value = String(v);
      e.dispatchEvent(new Event('input', {bubbles: true})); e.dispatchEvent(new Event('change', {bubbles: true}));
    }
  }
  return missing;
}"""

INVALID_JS = """(formIndex) => [...document.querySelectorAll('form')[formIndex].elements]
  .filter(e => e.willValidate && !e.checkValidity()).map(e => e.name || e.id || e.tagName)"""


# ------------------------------------------------------------------ page-level checks
def check_page(cx, base, page_name, results, skip, form_setup=None, form_values=None, groups=None):
    url = urljoin(base, page_name)
    P = page_name

    def add(r):
        if any(r["id"].startswith(s) for s in skip):
            r = row(r["id"], r["name"], "not_run", "skipped by site-tests.json")
        results.append(r)

    def safe(cid, name, fn):
        group = GROUP_OF_KIND.get(cid.split(":", 1)[0])
        if groups is not None and group not in groups:
            return
        if any(cid.startswith(s) for s in skip):
            results.append(row(cid, name, "not_run", "skipped by site-tests.json"))
            return
        try:
            fn()
        except Exception as e:
            first = (str(e).strip().splitlines() or [""])[0][:160]
            results.append(row(cid, name, "needs_review", f"check could not run: {type(e).__name__}: {first}"))

    # load + console + failed resources
    def load():
        errs, bad, ext = [], [], []
        with cx.page() as page:
            page.on("console", lambda m: errs.append(m.text) if m.type == "error" else None)
            page.on("pageerror", lambda e: errs.append("JS error: " + str(e)))
            page.on("response", lambda r: bad.append(f"{r.status} {urlparse(r.url).path}") if r.status >= 400 else None)
            page.on("request", lambda r: ext.append((r.resource_type, r.url))
                    if not r.url.startswith(cx.origin) and not r.url.startswith("data:") else None)
            resp = page.goto(url)
            page.wait_for_timeout(300)
        if ext:
            heavy = sorted({u for t, u in ext if t in ("script", "stylesheet")})
            light = sorted({u for t, u in ext if t not in ("script", "stylesheet")})
            if heavy:
                add(row(f"external:{P}", f"{P}: depends on external scripts/styles", "needs_review",
                        f"{len(heavy)} external scripts/stylesheets were blocked by the isolated test; "
                        "the page was tested WITHOUT them, so layout/behaviour results may not match the live site",
                        heavy[:8]))
            else:
                add(row(f"external:{P}", f"{P}: external fonts/images", "not_run",
                        f"{len(light)} external resources (fonts/images) not loaded in the isolated test", light[:8]))
        status = resp.status if resp else 0
        add(row(f"load:{P}", f"{P} loads", "pass" if 0 < status < 400 else "fail", f"HTTP {status}"))
        problems = sorted(set(bad)) + [e for e in errs if not e.startswith("Failed to load resource")]
        add(row(f"console:{P}", f"{P}: no errors or failed resources on load",
                "fail" if problems else "pass", f"{len(problems)} problems", problems[:8] or None))
    safe(f"load:{P}", f"{P} loads", load)

    # static DOM checks (one page load)
    def static():
        with cx.page() as page:
            page.goto(url)
            page.wait_for_timeout(200)
            info = page.evaluate("""() => ({
                vp: (document.querySelector('meta[name=viewport]') || {}).content || null,
                lang: document.documentElement.getAttribute('lang'),
                title: document.title,
                imgs: [...document.images].map(i => ({src: i.getAttribute('src'), alt: i.getAttribute('alt'),
                         broken: i.complete && i.naturalWidth === 0}))})""")
            contrast = page.evaluate(CONTRAST_JS)
            unlabeled = page.evaluate(LABELS_JS)
        vp = info["vp"]
        add(row(f"viewport:{P}", f"{P}: viewport meta for mobile", "pass" if vp and "width=device-width" in vp else "fail",
                f"viewport meta: {vp!r}"))
        add(row(f"lang:{P}", f"{P}: <html lang> set", "pass" if (info["lang"] or "").strip() else "fail",
                f"lang={info['lang']!r}"))
        add(row(f"title:{P}", f"{P}: page has a title", "pass" if (info["title"] or "").strip() else "fail",
                f"title={info['title']!r}"))
        imgs = info["imgs"]
        if imgs:
            noalt = [i["src"] for i in imgs if i["alt"] is None]
            add(row(f"alt:{P}", f"{P}: images have alt attribute", "fail" if noalt else "pass",
                    f"{len(noalt)} of {len(imgs)} images missing alt", noalt or None))
            is_ext = lambda src: (src or "").lower().startswith(("http://", "https://", "//"))
            broken = [i["src"] for i in imgs if i["broken"] and not is_ext(i["src"])]
            local = [i for i in imgs if not is_ext(i["src"])]
            if local:
                add(row(f"img:{P}", f"{P}: local images load", "fail" if broken else "pass",
                        f"{len(broken)} of {len(local)} local images failed to load", broken or None))
        judged = [c for c in contrast if c["judged"]]
        unjudged = [c for c in contrast if not c["judged"]]
        bad = [c for c in judged if not c["ok"]]
        note = f"; {len(unjudged)} over images not judged" if unjudged else ""
        add(row(f"contrast:{P}", f"{P}: text contrast meets WCAG AA", "fail" if bad else "pass",
                f"{len(bad)} of {len(judged)} text elements below threshold{note}", bad[:8] or None))
        add(row(f"labels:{P}", f"{P}: form fields have labels", "fail" if unlabeled else "pass",
                f"{len(unlabeled)} fields without an accessible label", unlabeled or None))
    safe(f"static:{P}", f"{P}: static checks", static)

    # mobile overflow
    def mobile():
        with cx.page(MOBILE) as page:
            page.goto(url)
            page.wait_for_timeout(200)
            d = page.evaluate("() => ({sw: document.documentElement.scrollWidth, iw: window.innerWidth})")
            wide = page.evaluate("""() => [...document.querySelectorAll('body *')].filter(e => {
                const r = e.getBoundingClientRect(); return r.right > window.innerWidth + 1 || r.left < -1; })
                .map(e => e.tagName.toLowerCase() + (e.className && typeof e.className === 'string' ? '.' + e.className.split(' ').join('.') : ''))""")
        over = d["sw"] > d["iw"]
        add(row(f"overflow:{P}", f"{P}: no horizontal scroll on mobile (375px)", "fail" if over else "pass",
                f"scrollWidth={d['sw']} vs viewport={d['iw']}", wide[:6] if over else None))
    safe(f"overflow:{P}", f"{P}: mobile overflow", mobile)

    # links
    def links():
        with cx.page() as page:
            page.goto(url)
            hrefs = page.eval_on_selector_all("a[href]", "els => els.map(e => e.getAttribute('href'))")
            ids = set(page.eval_on_selector_all("[id], a[name]", "els => els.map(e => e.id || e.getAttribute('name'))"))
            seen = set()
            for href in hrefs:
                if href in seen:
                    continue
                seen.add(href)
                cid, name = f"link:{P}:{href}", f"{P}: link {href} works"
                h = href.strip()
                if h in ("#", ""):
                    add(row(cid, name, "needs_review", "placeholder link: goes nowhere"))
                elif h.startswith("#"):
                    ok = h[1:] in ids
                    add(row(cid, name, "pass" if ok else "fail", "anchor target found" if ok else "no element with this id"))
                elif h.lower().startswith("javascript:"):
                    add(row(cid, name, "needs_review", "javascript: link, behaviour not verified"))
                elif h.lower().startswith(("mailto:", "tel:", "http://", "https://", "//", "whatsapp:", "sms:")):
                    add(row(cid, name, "not_run", "external/app link not checked (isolated environment)"))
                else:
                    r = page.request.get(urljoin(url, h))
                    add(row(cid, name, "pass" if r.status < 400 else "fail", f"HTTP {r.status}", f"GET {h} -> {r.status}"))
    safe(f"link:{P}", f"{P}: links", links)

    # buttons (each in a fresh page)
    def buttons():
        with cx.page() as page:
            page.goto(url)
            cands = page.evaluate(CANDIDATES_JS, MAX_BUTTONS_PER_PAGE)
        hidden = [c["key"] for c in cands if not c["visible"]]
        if hidden:
            add(row(f"btn-hidden:{P}", f"{P}: hidden buttons", "not_run",
                    f"{len(hidden)} buttons hidden at load were not clicked", hidden))
        for c in cands:
            if not c["visible"]:
                continue
            cid, name = f"btn:{P}:{c['key']}", f"{P}: button '{c['key']}' works"
            try:
                with cx.page() as page:
                    errs, popups = [], []
                    page.on("pageerror", lambda e: errs.append(str(e)))
                    page.on("popup", lambda p: popups.append(p.url))
                    page.goto(url)
                    page.wait_for_timeout(150)
                    page.evaluate(TAG_JS, c["i"])
                    active = page.evaluate("""() => { const e = document.querySelector('[data-wt-target]');
                        return ['aria-pressed', 'aria-selected', 'aria-checked'].some(a => e.getAttribute(a) === 'true')
                               || (e.getAttribute('aria-current') || 'false') !== 'false'; }""")
                    before = page.evaluate(SNAPSHOT_JS)
                    page.click("[data-wt-target]")
                    page.wait_for_timeout(400)
                    after = page.evaluate(SNAPSHOT_JS)
                    nav_status = None
                    if after[0].split("#")[0] != before[0].split("#")[0]:
                        nav_status = page.request.get(after[0]).status
                if errs:
                    add(row(cid, name, "fail", "click threw a JS error", errs[0][:200]))
                elif nav_status is not None and nav_status >= 400:
                    add(row(cid, name, "fail", f"click navigated to a broken page (HTTP {nav_status})", after[0]))
                elif before != after or popups:
                    add(row(cid, name, "pass", "click produced an observable change"))
                elif active:
                    add(row(cid, name, "pass", "already active (aria-pressed/selected/current) so no change is expected"))
                else:
                    add(row(cid, name, "needs_review", "no error, but the click changed nothing observable"))
            except Exception as e:
                first = (str(e).strip().splitlines() or [""])[0][:160]
                add(row(cid, name, "needs_review", f"check could not run: {type(e).__name__}: {first}"))
    safe(f"btn:{P}", f"{P}: buttons", buttons)

    # forms
    def forms():
        with cx.page() as page:
            page.goto(url)
            n = page.evaluate("() => document.querySelectorAll('form').length")
        for fi in range(n):
            cid = f"form:{P}:{fi}"
            try:
                with cx.page() as page:
                    errs, reqs = [], []
                    page.on("pageerror", lambda e: errs.append(str(e)))
                    page.on("request", lambda r: reqs.append(r) if r.resource_type in ("document", "xhr", "fetch") else None)
                    page.goto(url)
                    page.wait_for_timeout(150)
                    fid = page.evaluate("(i) => document.querySelectorAll('form')[i].id || null", fi)
                    setup = (form_setup or {}).get(f"#{fid}") if fid else None
                    if setup:
                        problem = do_simple_steps(page, setup)
                        if problem:
                            add(row(f"form:{P}:#{fid}", f"{P}: form #{fid} submits", "fail",
                                    "declared precondition could not run", problem))
                            continue
                        if page.url.split("#")[0] != url.split("#")[0]:
                            page.goto(url)  # setup visited other pages: come back to the form page
                            page.wait_for_timeout(150)
                        reqs.clear()
                    meta = page.evaluate(FILL_JS, fi)
                    values = (form_values or {}).get(f"#{fid}") if fid else None
                    if values:
                        missing = page.evaluate(SET_VALUES_JS, [fi, values])
                        if missing:
                            add(row(f"form:{P}:#{fid}", f"{P}: form #{fid} submits", "fail",
                                    "declared form value refers to a field that does not exist", missing))
                            continue
                        meta["invalid"] = page.evaluate(INVALID_JS, fi)
                    if meta["id"]:
                        cid = f"form:{P}:#{meta['id']}"
                    name = f"{P}: form {cid.split(':', 2)[2]} submits"
                    act = (meta["action"] or "").strip().lower()
                    if act.startswith("mailto:"):
                        add(row(cid, name, "not_run", "mailto: form, opens the user's mail app; not verifiable"))
                        continue
                    if meta["invalid"]:
                        add(row(cid, name, "needs_review", "could not fill the form validly", meta["invalid"]))
                        continue
                    before = page.evaluate(SNAPSHOT_JS)
                    reqs.clear()
                    if meta["hasSubmit"]:
                        page.click("[data-wt-submit]")
                    else:
                        page.evaluate("(i) => document.querySelectorAll('form')[i].requestSubmit()", fi)
                    page.wait_for_timeout(1200)
                    sent = [r for r in reqs if not r.url.startswith("data:")]
                    resp_info = []
                    for r in sent:
                        try:
                            resp = r.response()
                            resp_info.append((r.method, urlparse(r.url).path, urlparse(r.url).query,
                                              resp.status if resp else None))
                        except Exception:
                            resp_info.append((r.method, urlparse(r.url).path, "", None))
                    try:
                        after = page.evaluate(SNAPSHOT_JS)
                    except Exception:
                        after = None
                if errs:
                    add(row(cid, name, "fail", "submitting threw a JS error", errs[0][:200]))
                elif resp_info:
                    m, path, q, st = resp_info[0]
                    page_path = urlparse(url).path
                    if st is None:
                        add(row(cid, name, "needs_review", f"{m} {path}: no response received"))
                    elif st >= 400:
                        add(row(cid, name, "fail", f"{m} {path} -> HTTP {st}",
                                "endpoint is not in the declared backend (site-tests.json)" if st == 404 else None))
                    elif m == "GET" and path == page_path:
                        add(row(cid, name, "needs_review", "form reloads its own page; no backend receives the data"))
                    else:
                        add(row(cid, name, "pass", f"{m} {path} -> HTTP {st}"))
                elif after is not None and after != before:
                    add(row(cid, name, "needs_review",
                            "page changed (e.g. a thank-you message) but NO data was sent anywhere"))
                else:
                    add(row(cid, name, "fail", "submitting did nothing: no request, no visible change"))
            except Exception as e:
                first = (str(e).strip().splitlines() or [""])[0][:160]
                add(row(cid, f"{P}: form {fi} submits", "needs_review", f"check could not run: {type(e).__name__}: {first}"))
    safe(f"form:{P}", f"{P}: forms", forms)


# ------------------------------------------------------------------ custom scenarios
STEP_KEYS = {"click", "fill", "select", "submit", "double_submit", "wait", "check", "visit"}
EXPECT_KEYS = {"request", "no_request", "text", "count_visible", "body", "no_js_error", "visible", "hidden"}


def validate_scenario(sc):
    """Return a list of problems (empty = valid)."""
    errs = []
    if not isinstance(sc, dict):
        return ["scenario must be an object"]
    sid = sc.get("id", "")
    if not sid or not all(ch.isalnum() or ch in "-_" for ch in sid):
        errs.append("id must be non-empty and use only letters, digits, - or _")
    if not sc.get("page"):
        errs.append("page is required")
    if not isinstance(sc.get("steps", []), list):
        errs.append("steps must be a list")
    exp = sc.get("expect")
    if not isinstance(exp, list) or not exp:
        errs.append("expect must be a non-empty list")
    for st in sc.get("steps", []) or []:
        k = [x for x in st if x in STEP_KEYS]
        if len(k) != 1:
            errs.append(f"step needs exactly one of {sorted(STEP_KEYS)}: {st}")
    for e in exp or []:
        k = [x for x in e if x in EXPECT_KEYS]
        if len(k) != 1:
            errs.append(f"expectation needs exactly one of {sorted(EXPECT_KEYS)}: {e}")
    if sc.get("viewport", "desktop") not in ("desktop", "mobile"):
        errs.append("viewport must be desktop or mobile")
    return errs


SIMPLE_STEPS = ("click", "fill", "select", "check", "wait", "visit")


def do_simple_steps(page, steps):
    """Run click/fill/select/check/wait/visit steps. Returns None or a failure message (missing/unusable element).
    'visit' opens another page of the site in the same browser session (cookies/localStorage are kept)."""
    for n_step, st in enumerate(steps, 1):
        key = next((k for k in st if k in SIMPLE_STEPS), None)
        if key is None:
            raise ValueError(f"unsupported setup step: {st}")
        if key == "wait":
            page.wait_for_timeout(int(st["wait"]))
            continue
        if key == "visit":
            page.goto(urljoin(page.url, st["visit"]))
            page.wait_for_timeout(150)
            continue
        sel = st[key]
        if page.locator(sel).count() == 0:
            return f"setup step {n_step}: element not found: {sel}"
        if key == "click":
            for _ in range(int(st.get("times", 1))):
                page.click(sel)
                page.wait_for_timeout(50)
        elif key == "fill":
            page.fill(sel, str(st.get("value", "")))
        elif key == "select":
            page.select_option(sel, str(st.get("value", "")))
        elif key == "check":
            page.check(sel)
    return None


def _method_path(spec):
    parts = spec.split(None, 1)
    return (parts[0].upper(), parts[1]) if len(parts) == 2 else ("ANY", parts[0])


def run_scenario(cx, base, sc):
    cid = f"scenario:{sc.get('id', '?')}"
    name = sc.get("desc") or cid
    problems = validate_scenario(sc)
    if problems:
        return row(cid, name, "needs_review", "invalid scenario: " + "; ".join(problems))
    vp = MOBILE if sc.get("viewport") == "mobile" else DESKTOP
    reqs, errs = [], []
    try:
        with cx.page(vp, offline=tuple(sc.get("offline", []))) as page:
            page.on("pageerror", lambda e: errs.append(str(e)))
            page.on("request", lambda r: reqs.append(r) if r.resource_type in ("xhr", "fetch", "document") else None)
            page.goto(urljoin(base, sc["page"]))
            page.wait_for_timeout(150)
            reqs.clear()
            for n_step, st in enumerate(sc.get("steps", []), 1):
                key = next(k for k in st if k in STEP_KEYS)
                sel = st[key] if key in ("click", "fill", "select", "check", "submit", "double_submit") else None
                if sel is not None and page.locator(sel).count() == 0:
                    # the control the correct behaviour needs does not exist: a definite failure
                    return row(cid, name, "fail", f"step {n_step}: required element not found: {sel}",
                               [f"step {n_step} ({key}) found no element matching {sel!r}"])
                try:
                    if key == "click":
                        for _ in range(int(st.get("times", 1))):
                            page.click(sel)
                            page.wait_for_timeout(50)
                    elif key == "fill":
                        page.fill(sel, str(st.get("value", "")))
                    elif key == "select":
                        page.select_option(sel, str(st.get("value", "")))
                    elif key == "check":
                        page.check(sel)
                except Exception as ex:
                    if "Timeout" in type(ex).__name__ or "Timeout" in str(ex)[:80]:
                        return row(cid, name, "fail", f"step {n_step}: element exists but could not be used "
                                   f"(hidden, covered or disabled): {sel}", [str(ex).splitlines()[0][:160]])
                    raise
                if key in ("click", "fill", "select", "check"):
                    continue
                if key == "visit":
                    page.goto(urljoin(page.url, st["visit"]))
                    page.wait_for_timeout(150)
                    continue
                if "wait" in st:
                    page.wait_for_timeout(int(st["wait"]))
                elif "submit" in st or "double_submit" in st:
                    sel = st.get("submit") or st.get("double_submit")
                    n = 2 if "double_submit" in st else 1
                    # JS-level click: a disabled submit button correctly does nothing
                    page.evaluate("""([sel, n]) => { const f = document.querySelector(sel);
                        if (!f) throw new Error('form not found: ' + sel);
                        const b = f.querySelector('button[type=submit], input[type=submit], button:not([type])');
                        for (let i = 0; i < n; i++) { if (b) b.click(); else f.requestSubmit(); } }""", [sel, n])
            page.wait_for_timeout(int(sc.get("settle_ms", 900)))
            sent = []
            for r in reqs:
                try:
                    body = r.post_data or ""
                except Exception:
                    body = ""
                sent.append((r.method, urlparse(r.url).path, body))
            failed = []
            for e in sc["expect"]:
                if "request" in e or "no_request" in e:
                    m, path = _method_path(e.get("request") or e.get("no_request"))
                    n = sum(1 for (mm, pp, _) in sent if pp == path and (m == "ANY" or mm == m))
                    if "no_request" in e:
                        if n:
                            failed.append(f"expected NO {m} {path}, saw {n}")
                    else:
                        want = e.get("count")
                        if (want is None and n < 1) or (want is not None and n != int(want)):
                            failed.append(f"expected {m} {path} x{want if want is not None else '>=1'}, saw {n}")
                elif "body" in e:
                    m, path = _method_path(e["body"])
                    bodies = [b for (mm, pp, b) in sent if pp == path and (m == "ANY" or mm == m)]
                    if not any(e.get("contains", "") in b for b in bodies):
                        failed.append(f"no {m} {path} body contains {e.get('contains')!r}")
                elif "text" in e:
                    loc = page.locator(e["text"])
                    t = loc.first.inner_text().strip() if loc.count() else None
                    if t is None:
                        failed.append(f"element not found: {e['text']}")
                    elif "contains" in e and e["contains"] not in t:
                        failed.append(f"{e['text']} text {t[:60]!r} lacks {e['contains']!r}")
                    elif "equals" in e and t != str(e["equals"]):
                        failed.append(f"{e['text']} text {t[:60]!r} != {e['equals']!r}")
                    elif e.get("not_empty") and not t:
                        failed.append(f"{e['text']} is empty")
                elif "count_visible" in e:
                    n = page.evaluate("""(sel) => [...document.querySelectorAll(sel)].filter(x => {
                        const r = x.getBoundingClientRect(); return r.width > 0 && r.height > 0; }).length""", e["count_visible"])
                    if n != int(e.get("equals", -1)):
                        failed.append(f"visible {e['count_visible']} = {n}, expected {e.get('equals')}")
                elif "visible" in e or "hidden" in e:
                    sel = e.get("visible") or e.get("hidden")
                    vis = page.evaluate("""(sel) => { const x = document.querySelector(sel); if (!x) return null;
                        const r = x.getBoundingClientRect(); const s = getComputedStyle(x);
                        return r.width > 0 && r.height > 0 && s.visibility !== 'hidden'; }""", sel)
                    if vis is None:
                        failed.append(f"element not found: {sel}")
                    elif "visible" in e and not vis:
                        failed.append(f"{sel} is not visible")
                    elif "hidden" in e and vis:
                        failed.append(f"{sel} is visible")
                elif "no_js_error" in e:
                    if errs:
                        failed.append(f"JS error: {errs[0][:150]}")
    except Exception as ex:
        first = (str(ex).strip().splitlines() or [""])[0][:160]
        return row(cid, name, "needs_review", f"scenario could not run: {type(ex).__name__}: {first}")
    if failed:
        return row(cid, name, "fail", f"{len(failed)} expectation(s) not met", failed)
    return row(cid, name, "pass", f"all {len(sc['expect'])} expectations met")


# ------------------------------------------------------------------ targeted runs
GROUP_OF_KIND = {"load": "load", "console": "load", "external": "load",
                 "viewport": "static", "lang": "static", "title": "static", "alt": "static", "img": "static",
                 "contrast": "static", "labels": "static", "static": "static",
                 "overflow": "overflow", "link": "link", "btn": "btn", "btn-hidden": "btn", "form": "form"}


def groups_for(ids):
    """Map check ids to what must run: {(page, group)} for page checks and {scenario_id} for scenarios.
    Unknown ids return None (= run everything)."""
    page_groups, scen = set(), set()
    for cid in ids:
        kind, _, rest = cid.partition(":")
        if kind == "N":
            continue
        if kind == "scenario":
            scen.add(rest)
            continue
        if kind not in GROUP_OF_KIND or not rest:
            return None
        page = rest.split(":", 1)[0]
        page_groups.add((page, GROUP_OF_KIND[kind]))
    return page_groups, scen


# ------------------------------------------------------------------ main
def find_pages(site, cfg):
    if cfg.get("pages"):
        return cfg["pages"][:MAX_PAGES]
    pages = sorted(str(p.relative_to(site)) for p in site.rglob("*.html")
                   if not any(part.startswith(".") or part == "node_modules" for part in p.relative_to(site).parts))
    if "index.html" in pages:
        pages.remove("index.html")
        pages.insert(0, "index.html")
    return pages[:MAX_PAGES]


def tree_hash(site):
    h = hashlib.sha256()
    for p in sorted(site.rglob("*")):
        if p.is_file():
            h.update(str(p.relative_to(site)).encode())
            h.update(p.read_bytes())
    return h.hexdigest()[:16]


def run(site_dir, shots=None, shots_only=False, only=None):
    """only: optional list of check ids; run just the groups that produce them (results may include
    sibling checks of the same group)."""
    site = Path(site_dir).resolve()
    cfg_path = site / "site-tests.json"
    cfg = json.loads(cfg_path.read_text(encoding="utf-8")) if cfg_path.exists() else {}
    backend = cfg.get("backend", {})
    skip = cfg.get("skip", [])
    pages = find_pages(site, cfg)
    target = groups_for(only) if only else None
    server = QuietServer(("127.0.0.1", 0), make_handler(str(site), backend))
    threading.Thread(target=server.serve_forever, daemon=True).start()
    origin = f"http://127.0.0.1:{server.server_address[1]}"
    base = origin + "/"
    results = []
    with sync_playwright() as p:
        browser = p.chromium.launch()
        cx = Ctx(browser, origin)
        if not pages:
            results.append(row("site", "site has HTML pages", "fail", "no .html files found"))
        for pg in pages:
            if shots_only:
                continue
            if target is None:
                check_page(cx, base, pg, results, skip, cfg.get("form_setup", {}), cfg.get("form_values", {}))
            else:
                gs = {g for (p_, g) in target[0] if p_ == pg}
                if gs:
                    check_page(cx, base, pg, results, skip, cfg.get("form_setup", {}), cfg.get("form_values", {}), gs)
        if not shots_only:
            retired = {r["id"] for r in cfg.get("retired", [])}
            for sc in cfg.get("scenarios", []):
                if f"scenario:{sc.get('id')}" in retired:
                    continue
                if target is None or sc.get("id") in target[1]:
                    results.append(run_scenario(cx, base, sc))
        if shots:
            out = Path(shots)
            out.mkdir(parents=True, exist_ok=True)
            for pg in pages:
                for label, vp in (("desktop", DESKTOP), ("mobile", MOBILE)):
                    try:
                        with cx.page(vp) as page:
                            page.goto(urljoin(base, pg))
                            page.wait_for_timeout(300)
                            safe_name = pg.replace("/", "__").replace(".html", "")
                            page.screenshot(path=str(out / f"{safe_name}_{label}.png"), full_page=True)
                    except Exception:
                        pass
        browser.close()
    server.shutdown()
    if target is not None:
        return {"site": str(site), "tree_hash": tree_hash(site), "pages": pages,
                "backend_declared": backend, "results": results, "partial": True}
    results += [
        row("N:performance", "performance audit (Lighthouse)", "not_run", "not available in this runner"),
        row("N:a11y-full", "full accessibility audit (axe/Lighthouse)", "not_run",
            "only basic checks ran: alt, contrast, labels, lang, title, viewport"),
        row("N:security", "security checks", "not_run", "no security checks implemented"),
        row("N:browsers", "other browsers (Safari/Firefox)", "not_run", "only Chromium was used"),
    ]
    return {"site": str(site), "tree_hash": tree_hash(site), "pages": pages,
            "backend_declared": backend, "results": results}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("site_dir")
    ap.add_argument("--out")
    ap.add_argument("--shots", help="save desktop+mobile screenshots of every page into this folder")
    ap.add_argument("--shots-only", action="store_true", help="only take screenshots, run no checks")
    ap.add_argument("--only", help="comma-separated check ids: run only the groups that produce them")
    ap.add_argument("--quiet", action="store_true")
    a = ap.parse_args()
    if not Path(a.site_dir).is_dir():
        print(f"ERROR: not a directory: {a.site_dir}", file=sys.stderr)
        return 2
    if a.shots_only and not a.shots:
        print("ERROR: --shots-only needs --shots DIR", file=sys.stderr)
        return 2
    data = run(a.site_dir, a.shots, a.shots_only, a.only.split(",") if a.only else None)
    if a.shots_only:
        print(f"screenshots saved to {a.shots}")
        return 0
    if a.out:
        Path(a.out).parent.mkdir(parents=True, exist_ok=True)
        Path(a.out).write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    counts = {}
    for r in data["results"]:
        counts[r["status"]] = counts.get(r["status"], 0) + 1
    print(json.dumps(counts))
    for r in data["results"]:
        # --quiet: only what needs attention (everything except pass)
        if not a.quiet or r["status"] != "pass":
            print(f'{r["status"]:12} {r["id"][:45]:45} | {r["detail"]}')
    return 0


if __name__ == "__main__":
    sys.exit(main())
