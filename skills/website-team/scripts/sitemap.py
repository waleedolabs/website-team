#!/usr/bin/env python3
"""Site map: a compact "nerve map" of a static site, built by code (no AI tokens).

  sitemap.py SITE [--cache FILE]

Shows pages and sections, which element triggers which function (file:line), what each function
touches, forms and where they send, links between pages, and risk flags that tell a reviewer which
functions are worth reading (calculations, sorting, filtering, dates, phone/WhatsApp links...).
Per-file results are cached by content hash, so a second run only re-parses changed files.
"""
import argparse
import hashlib
import json
import re
import sys
from html.parser import HTMLParser
from pathlib import Path

for _s in (sys.stdout, sys.stderr):
    try:
        _s.reconfigure(encoding="utf-8", errors="replace")
    except (AttributeError, ValueError):
        pass

SKIP_DIRS = {"node_modules", "__pycache__", "website-team", "vendor", "dist-libs"}
MAX_JS = 400_000
VERSION = 1

FLAG_RULES = [
    ("calc", r"[*/]\s*\d|\d\s*[*/]|\+=\s*\d|toFixed|Math\.(round|floor|ceil)|parseFloat|parseInt|Number\("),
    ("sort", r"\.sort\("),
    ("filter", r"\.filter\(|dataset\.\w+\s*[!=]==?|classList\.(toggle|add|remove)\(['\"](hidden|active|show|open)"),
    ("date", r"new Date|getDay\(|getHours\(|getMonth\(|getDate\(|Date\.now"),
    ("contact-link", r"wa\.me|whatsapp|tel:|mailto:"),
    ("storage", r"localStorage|sessionStorage"),
    ("network", r"fetch\(|XMLHttpRequest|axios"),
    ("timer", r"setTimeout|setInterval"),
    ("validation", r"checkValidity|\.test\(|\.match\(|required|\.length\s*[<>=]"),
    ("fake-success", r"(شكرا|تم (ال)?(استلام|إرسال|ارسال)|thank you|sent successfully|received)"),
]


def sha(b):
    return hashlib.sha256(b).hexdigest()[:16]


def line_of(text, pos):
    return text.count("\n", 0, pos) + 1


# ------------------------------------------------------------------ HTML
class Page(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.title = ""
        self.sections = []      # (id, heading)
        self.controls = []      # dict(tag, id, cls, text, onclick, href, line)
        self.forms = []         # dict(id, action, method, fields, line)
        self.links = []         # href
        self.scripts = []       # src
        self.inline_js = []     # (line, code)
        self.hover = []
        self._stack = []
        self._in = None
        self._buf = ""
        self._cur_section = None
        self._form = None
        self._ctl = None

    def handle_starttag(self, tag, attrs):
        a = dict(attrs)
        line = self.getpos()[0]
        if tag == "title":
            self._in, self._buf = "title", ""
        elif tag in ("section", "main", "header", "footer", "nav", "aside") and a.get("id"):
            self._cur_section = [a["id"], ""]
            self.sections.append(self._cur_section)
        elif tag in ("h1", "h2", "h3"):
            self._in, self._buf = "h", ""
        elif tag == "script":
            if a.get("src"):
                self.scripts.append(a["src"])
            else:
                self._in, self._buf, self._script_line = "script", "", line
        elif tag == "form":
            self._form = {"id": a.get("id", ""), "action": a.get("action", ""), "method": (a.get("method") or "get").lower(),
                          "fields": [], "line": line}
            self.forms.append(self._form)
        elif tag in ("input", "textarea", "select") and self._form is not None:
            self._form["fields"].append((a.get("name") or a.get("id") or tag) + ("*" if "required" in a else "")
                                        + (f":{a['type']}" if a.get("type") not in (None, "text") else ""))
        if tag in ("button", "a") or a.get("onclick") or a.get("role") == "button":
            href = a.get("href")
            if tag == "a" and href and not href.startswith("#") and not a.get("onclick"):
                self.links.append(href)
            ctl = {"tag": tag, "id": a.get("id", ""), "cls": a.get("class", ""), "text": "", "line": line,
                   "onclick": a.get("onclick", ""), "href": href or "", "type": a.get("type", "")}
            self.controls.append(ctl)
            self._ctl = ctl

    def handle_endtag(self, tag):
        if tag == "title" and self._in == "title":
            self.title, self._in = self._buf.strip(), None
        elif tag in ("h1", "h2", "h3") and self._in == "h":
            if self._cur_section is not None and not self._cur_section[1]:
                self._cur_section[1] = self._buf.strip()[:40]
            self._in = None
        elif tag == "script" and self._in == "script":
            self.inline_js.append((self._script_line, self._buf))
            self._in = None
        elif tag == "form":
            self._form = None
        elif tag in ("button", "a"):
            self._ctl = None

    def handle_data(self, data):
        if self._in in ("title", "h", "script"):
            self._buf += data
        if self._ctl is not None and len(self._ctl["text"]) < 30:
            self._ctl["text"] = (self._ctl["text"] + " " + data.strip()).strip()[:30]


# ------------------------------------------------------------------ JS
FUNC_PATTERNS = [
    r"function\s+([A-Za-z_$][\w$]*)\s*\(",
    r"(?:const|let|var)\s+([A-Za-z_$][\w$]*)\s*=\s*(?:async\s*)?(?:function\b|\([^)]*\)\s*=>|[A-Za-z_$][\w$]*\s*=>)",
    r"([A-Za-z_$][\w$]*)\s*:\s*(?:async\s*)?function\s*\(",
]
SEL_RE = re.compile(r"(?:getElementById\(\s*['\"]([^'\"]+)['\"]\)|querySelector(?:All)?\(\s*['\"]([^'\"]+)['\"]\)|"
                    r"getElementsByClassName\(\s*['\"]([^'\"]+)['\"]\))")
LISTEN_RE = re.compile(r"([\w$.\[\]'\"()#-]+?)\s*\.\s*(?:addEventListener\(\s*['\"](\w+)['\"]\s*,\s*([\w$.]+)?|on(click|submit|change|input)\s*=\s*([\w$.]+)?)")


def body_end(text, start):
    """index after the block starting at the first '{' after start (simple brace matching)."""
    i = text.find("{", start)
    if i < 0 or i - start > 300:
        return min(len(text), start + 200)
    depth = 0
    for j in range(i, min(len(text), i + 20000)):
        c = text[j]
        if c == "{":
            depth += 1
        elif c == "}":
            depth -= 1
            if depth == 0:
                return j + 1
    return min(len(text), i + 2000)


def sel_of(m):
    g = m.groups()
    if g[0]:
        return "#" + g[0]
    if g[1]:
        return g[1]
    return "." + g[2]


def parse_js(text, fname, line_offset=0):
    funcs = {}
    for pat in FUNC_PATTERNS:
        for m in re.finditer(pat, text):
            name = m.group(1)
            if name in funcs or name in ("if", "for", "while", "switch", "catch"):
                continue
            end = body_end(text, m.end())
            body = text[m.start():end]
            funcs[name] = {"file": fname, "line": line_of(text, m.start()) + line_offset,
                           "end": line_of(text, end) + line_offset,
                           "touches": sorted({sel_of(s) for s in SEL_RE.finditer(body)})[:8],
                           "calls": [], "flags": [f for f, rx in FLAG_RULES if re.search(rx, body, re.I)]}
    names = set(funcs)
    for name, f in funcs.items():
        body = "\n".join(text.splitlines()[f["line"] - 1 - line_offset:f["end"] - line_offset])
        f["calls"] = sorted({c for c in re.findall(r"\b([A-Za-z_$][\w$]*)\s*\(", body) if c in names and c != name})[:8]
    # variables that hold elements: const btn = document.getElementById('x')
    var_sel = {}
    for m in re.finditer(r"(?:const|let|var)\s+([A-Za-z_$][\w$]*)\s*=\s*document\.\s*(getElementById|querySelector(?:All)?)\(\s*['\"]([^'\"]+)['\"]\)", text):
        var_sel[m.group(1)] = ("#" + m.group(3)) if m.group(2) == "getElementById" else m.group(3)
    # querySelectorAll('.x').forEach(btn => btn.addEventListener(...)) and for (const b of document.querySelectorAll('.x'))
    for m in re.finditer(r"querySelectorAll\(\s*['\"]([^'\"]+)['\"]\)\s*\.forEach\(\s*(?:function\s*)?\(?\s*([A-Za-z_$][\w$]*)", text):
        var_sel[m.group(2)] = m.group(1)
    for m in re.finditer(r"for\s*\(\s*(?:const|let|var)\s+([A-Za-z_$][\w$]*)\s+of\s+document\.querySelectorAll\(\s*['\"]([^'\"]+)['\"]\)", text):
        var_sel[m.group(1)] = m.group(2)
    for m in re.finditer(r"(?:const|let|var)\s+([A-Za-z_$][\w$]*)\s*=\s*document\.querySelectorAll\(\s*['\"]([^'\"]+)['\"]\)", text):
        var_sel[m.group(1)] = m.group(2)
    for m in re.finditer(r"([A-Za-z_$][\w$]*)\.forEach\(\s*(?:function\s*)?\(?\s*([A-Za-z_$][\w$]*)", text):
        if m.group(1) in var_sel:
            var_sel[m.group(2)] = var_sel[m.group(1)]
    listeners = []
    for m in LISTEN_RE.finditer(text):
        target, ev, handler = m.group(1), m.group(2) or m.group(4), m.group(3) or m.group(5)
        if handler in ("function", "async") or (handler and re.match(r"\s*=>", text[m.end():])):
            handler = None
        sm = SEL_RE.search(target)
        sel = sel_of(sm) if sm else var_sel.get(target.split(".")[0].split("[")[0], target[-30:])
        line = line_of(text, m.start()) + line_offset
        if not handler:  # inline function: describe it by its own flags and touches
            end = body_end(text, m.end())
            body = text[m.end():end]
            handler = f"(inline {fname}:{line})"
            funcs[handler] = {"file": fname, "line": line, "end": line_of(text, end) + line_offset,
                              "touches": sorted({sel_of(s) for s in SEL_RE.finditer(body)})[:8],
                              "calls": sorted({c for c in re.findall(r"\b([A-Za-z_$][\w$]*)\s*\(", body) if c in names})[:8],
                              "flags": [f for f, rx in FLAG_RULES if re.search(rx, body, re.I)]}
        listeners.append({"sel": sel, "event": ev, "handler": handler, "line": line, "file": fname})
    # top-level calls (run on load)
    return {"funcs": funcs, "listeners": listeners}


def hover_reveals(css, fname):
    """CSS rules that show something only on :hover (unusable on touch screens)."""
    out = []
    for m in re.finditer(r"([^{}]*:hover[^{}]*)\{([^}]*)\}", css):
        sel, decl = m.group(1).strip(), m.group(2)
        if re.search(r"display\s*:\s*(block|flex|grid|inline)|opacity\s*:\s*1|visibility\s*:\s*visible|max-height\s*:\s*(?!0)", decl):
            if sel.split(":hover", 1)[1].strip():  # something other than the hovered element itself is revealed
                out.append(f"{fname}:{line_of(css, m.start())}: {sel[:70]}")
    return out


# ------------------------------------------------------------------ build
def site_sources(site):
    for p in sorted(site.rglob("*")):
        rel = p.relative_to(site)
        if any(x.startswith(".") or x in SKIP_DIRS for x in rel.parts):
            continue
        if p.is_file() and p.suffix.lower() in (".html", ".htm", ".js", ".css") and not p.name.endswith(".min.js"):
            yield p, rel.as_posix()


def analyse(path, rel):
    raw = path.read_bytes()
    text = raw.decode("utf-8", errors="replace")
    ext = path.suffix.lower()
    if ext in (".html", ".htm"):
        pg = Page()
        try:
            pg.feed(text)
        except Exception:
            pass
        js = {"funcs": {}, "listeners": []}
        for line, code in pg.inline_js:
            part = parse_js(code, rel, line - 1)
            js["funcs"].update(part["funcs"])
            js["listeners"] += part["listeners"]
        css = "\n".join(re.findall(r"<style[^>]*>(.*?)</style>", text, re.S | re.I))
        return {"kind": "html", "title": pg.title, "sections": pg.sections, "controls": pg.controls, "forms": pg.forms,
                "links": pg.links, "scripts": pg.scripts, "js": js,
                "hover": hover_reveals(css, rel) if css else [], "size": len(raw)}
    if ext == ".js":
        return {"kind": "js", "js": parse_js(text[:MAX_JS], rel), "size": len(raw)}
    return {"kind": "css", "hover": hover_reveals(text, rel), "size": len(raw)}


def build(site, cache_file=None):
    site = Path(site).resolve()
    cache = {}
    if cache_file and Path(cache_file).is_file():
        try:
            c = json.loads(Path(cache_file).read_text(encoding="utf-8"))
            if c.get("v") == VERSION:
                cache = c.get("files", {})
        except ValueError:
            cache = {}
    files, reused = {}, 0
    for p, rel in site_sources(site):
        h = sha(p.read_bytes())
        if rel in cache and cache[rel]["hash"] == h:
            files[rel] = cache[rel]
            reused += 1
        else:
            files[rel] = {"hash": h, "data": analyse(p, rel)}
    if cache_file:
        Path(cache_file).parent.mkdir(parents=True, exist_ok=True)
        Path(cache_file).write_text(json.dumps({"v": VERSION, "files": files}, ensure_ascii=False), encoding="utf-8")
    return files, reused


def render(files, reused=0, max_lines=160):
    out = []
    total = sum(f["data"]["size"] for f in files.values())
    funcs, listeners, hover = {}, [], []
    for rel, f in files.items():
        d = f["data"]
        if "js" in d:
            funcs.update(d["js"]["funcs"])
            listeners += d["js"]["listeners"]
        hover += d.get("hover", [])
    out.append(f"MAP: {len(files)} source files, {total // 1024} KB"
               f"{f' ({reused} unchanged, from cache)' if reused else ''}")
    by_sel = {}
    for li in listeners:
        by_sel.setdefault(li["sel"], []).append(li)

    def describe(handler, depth=0):
        f = funcs.get(handler)
        if not f:
            return handler
        s = f"{handler} [{f['file']}:{f['line']}-{f['end']}]"
        if f["flags"]:
            s += " {" + ",".join(f["flags"]) + "}"
        if f["touches"]:
            s += " → " + " ".join(f["touches"][:5])
        if f["calls"] and depth < 1:
            s += " → calls " + ", ".join(describe(c, depth + 1) if funcs.get(c, {}).get("flags") else c for c in f["calls"][:4])
        return s

    for rel, f in files.items():
        d = f["data"]
        if d["kind"] != "html":
            continue
        out.append(f"\nPAGE {rel}  \"{d['title'][:50]}\"")
        if d["sections"]:
            out.append("  sections: " + " | ".join(f"#{i} {h}".strip() for i, h in d["sections"][:14]))
        for c in d["controls"]:
            key = f"#{c['id']}" if c["id"] else (c["text"] or c["cls"])[:24]
            hits = list(by_sel.get(f"#{c['id']}", [])) if c["id"] else []
            toks = [f".{cl}" for cl in (c["cls"] or "").split()]
            for sel, ls in by_sel.items():
                if sel == f"#{c['id']}":
                    continue
                parts = re.split(r"[\s>+~,]+", sel)
                last = parts[-1] if parts else ""
                if any(tk in re.findall(r"\.[\w-]+", last) for tk in toks) or \
                        (re.fullmatch(r"[a-z]+", last or "") and last == c["tag"] and len(parts) > 1):
                    hits += ls
            if c["onclick"]:
                m = re.match(r"\s*([\w$]+)\s*\(", c["onclick"])
                target = describe(m.group(1)) if m else f"inline: {c['onclick'][:40]}"
            elif hits:
                target = "; ".join(f"{h['event']}: {describe(h['handler'])}" for h in hits[:2])
            elif c["tag"] == "a":
                if not c["href"] or c["href"].startswith("#") and len(c["href"]) > 1:
                    continue  # plain in-page anchor: covered by the link checks
                target = f"link {c['href'][:50]}"
            elif c["type"] == "submit":
                target = "submits its form"
            else:
                target = "NO HANDLER FOUND"
            out.append(f"  {c['tag']} {key} \"{c['text'][:20]}\" (line {c['line']}) → {target}")
        for fm in d["forms"]:
            key = f"#{fm['id']}" if fm["id"] else f"form@{fm['line']}"
            hs = by_sel.get(key, [])
            sub = "; ".join(f"{h['event']}: {describe(h['handler'])}" for h in hs[:2]) or "no JS handler"
            dest = fm["action"] or "(no action)"
            out.append(f"  form {key} (line {fm['line']}) {fm['method'].upper()} {dest} fields[{', '.join(fm['fields'][:8])}] → {sub}")
        if d["links"]:
            out.append("  links: " + ", ".join(sorted(set(d["links"]))[:12]))
    shown = {h["handler"] for h in listeners}
    risky = [(n, f) for n, f in funcs.items() if f["flags"] and not n.startswith("(inline")]
    if risky:
        out.append("\nFUNCTIONS WORTH READING (logic the browser tests cannot judge):")
        for n, f in sorted(risky, key=lambda x: (x[1]["file"], x[1]["line"])):
            out.append(f"  {n} {f['file']}:{f['line']}-{f['end']} {{{','.join(f['flags'])}}}")
    rest = [n for n in funcs if n not in shown and not funcs[n]["flags"] and not n.startswith("(inline")]
    if rest:
        out.append("  other functions: " + ", ".join(f"{n}@{funcs[n]['file']}:{funcs[n]['line']}" for n in rest[:20]))
    if hover:
        out.append("\nSHOWN ONLY ON :hover (unreachable by tapping on phones):")
        out += [f"  {h}" for h in hover[:10]]
    if len(out) > max_lines:
        out = out[:max_lines] + [f"  ... map truncated ({len(out) - max_lines} more lines)"]
    return "\n".join(out)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("site")
    ap.add_argument("--cache")
    a = ap.parse_args()
    files, reused = build(a.site, a.cache)
    print(render(files, reused))


if __name__ == "__main__":
    main()
