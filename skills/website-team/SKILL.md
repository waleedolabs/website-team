---
name: website-team
description: >-
  Quickly checks a website that already exists with real browser tests, points to the exact
  lines of every problem so they can be fixed, then re-tests to prove the fixes and catch anything
  that broke. Ends with a very short summary. Use ONLY when the user explicitly asks for it by name -
  "website team", "the website team", "فريق الموقع", "خلي فريق الموقع يراجع", "/website-team".
  Do not use it for ordinary requests to build, design or edit a website; Claude handles those normally.
---

# Website Team (fast check)

Two parts work together: **you review the site's code yourself** like a careful senior developer, and the scanner (real browser tests) catches what reading misses and proves the result. Work quietly: no progress messages, no questions, no plans. Aim for about six tool calls.

`${CLAUDE_SKILL_DIR}` is this skill's folder (if it appears literally, write the absolute path). Run scripts as `python3 "${CLAUDE_SKILL_DIR}/scripts/scan.py" ...` (if `python3` fails, use `python` or the full path to Python). One command per call, no `cd`/pipes.

If the user explicitly asks for the **full** team / committee, follow `${CLAUDE_SKILL_DIR}/references/full-committee.md` instead.

## Steps

1. **Scan.** SITE = the site's folder from this conversation (or the one the user named); if there is none, say so in one line and stop.
   `python3 "${CLAUDE_SKILL_DIR}/scripts/scan.py" scan SITE --state SITE/website-team`
   It prints numbered problems, each with `where` (file:line and the line) and `fix`. If the script fails because Python/Playwright is missing, say in one line what to install, then continue with step 2 only and say in the summary that nothing was browser-tested.

2. **Review the code yourself.** Read the site's HTML/CSS/JS files once (Read; skip images and libraries). The scanner cannot see logic, so look for: wrong calculations or conditions, filters/tabs/sorting showing the wrong items, wrong phone/WhatsApp/email link formats, inputs that accept invalid data, features hidden or unusable on mobile, state that never resets, text that contradicts what the code does.

3. **Fix** every scanner problem (following its `fix` line) and every real bug you found, with small edits:
   - Never change prices, names, contact details or texts, and never delete content, links, buttons or sections.
   - `[ASK USER]` items: still fix them now with the smallest honest change (replacing a false "sent" message is required, not a content change); keep the real decision for the summary.
   - Fix bugs, do not redesign or restyle.

4. **Recheck.** `python3 "${CLAUDE_SKILL_DIR}/scripts/scan.py" recheck SITE --state SITE/website-team`
   - BROKEN BY THE EDIT: fix it, or put the file back with `scan.py restore SITE --state SITE/website-team FILE`.
   - NEW or STILL OPEN problems: fix what you can, then recheck **once more** (at most two rechecks in total).
   - "no longer tested": you may have deleted something; restore it.

5. **Summary**: the only message, in the user's language, at most 6 lines, scanner numbers taken from the last RECHECK line, nothing else:

```
فريق الموقع خلص:
- فحص: <N> مشكلة
- صلّح: <proven fixed> (مثبتة بالاختبار)
- ومن مراجعة الكود: <count> <2-4 words each> (ما بيثبتها الفحص الآلي)
- باقي: <open> <2-4 words each, or "ولا شي">
- بدها قرارك: <the ASK USER decisions, very short, or "ولا شي">
```

Never call a scanner problem fixed unless the recheck says so; bugs found by reading are reported as code-review fixes, not as test-proven. The backup of the original files is in `SITE/website-team/backup`.

## What the scan covers

Per page: loading, JS errors, buttons that do nothing or throw, forms (flags fake "thank you" forms that send nothing), broken links and anchors, image alt text, contrast (WCAG AA), field labels, `lang`, `dir="rtl"` for Arabic, `title`, viewport, horizontal scrolling at 375px. Not covered: design taste, wording, performance, security, other browsers, real backends, external links.
