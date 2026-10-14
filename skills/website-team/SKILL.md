---
name: website-team
description: >-
  Checks a website that already exists: real browser tests plus a careful code review find the
  problems, then it tells the user what it found and what it plans to change, and changes NOTHING
  until the user agrees. After approval it fixes, re-tests to prove the fixes, and gives a very short
  summary. Use ONLY when the user explicitly asks for it by name - "website team", "the website team",
  "فريق الموقع", "خلي فريق الموقع يراجع", "/website-team". Do not use it for ordinary requests to
  build, design or edit a website; Claude handles those normally.
---

# Website Team (find, ask, then fix)

Two parts work together: **you review the site's code yourself** like a careful senior developer, and the scanner (real browser tests) catches what reading misses and proves the result. The order is always: **discover (read-only) → one message with a plan → wait for the user's answer → fix → recheck → short summary.**

`${CLAUDE_SKILL_DIR}` is this skill's folder (if it appears literally, write the absolute path). Run scripts as `python3 "${CLAUDE_SKILL_DIR}/scripts/scan.py" ...` (if `python3` fails, use `python` or the full path to Python). One command per call, no `cd`/pipes/`head`.

If the user explicitly asks for the **full** team ("الكامل", full committee), also follow `${CLAUDE_SKILL_DIR}/references/full-committee.md` (it adds an independent critic to the discovery and its suggestions to the plan).

## Rules

- **Before the user answers the plan, change nothing in the site** (no Edit/Write on site files, no fixes, no copies of the project). Discovery only reads, and the scan writes only inside `SITE/.website-team`.
- No chatter: no status updates and no text between tool calls. The only messages are the plan (step 3) and the final summary (step 5).
- Never change prices, names, contact details or other texts, and never delete content, links, buttons or sections. Anything like that is a **suggestion** the user decides.
- Never call a scanner problem fixed unless the recheck says so.
- Never commit, push or deploy.

## Steps

1. **Scan (read-only).** SITE = the site's folder from this conversation (or the one the user named); if there is none, say so in one line and stop.
   `python3 "${CLAUDE_SKILL_DIR}/scripts/scan.py" scan SITE --state SITE/.website-team`
   It prints numbered problems, each with `where` (file:line and the line) and `fix`, then a **MAP** of the site: which element triggers which function (file:lines), forms and where they send, functions worth reading, things shown only on hover. It also saves a backup of the original files. If the script fails because Python/Playwright is missing, say in one line what to install, then continue with step 2 only and say in the plan that nothing was browser-tested.

2. **Review the code yourself, guided by the MAP (read-only).** If the MAP says the sources are under 60 KB, read the HTML/CSS/JS files once in full. If larger, read only: the functions under FUNCTIONS WORTH READING, the handlers of the main buttons and forms, anything marked NO HANDLER FOUND or SHOWN ONLY ON :hover, and the lines of each scanner problem (Read with offset/limit). The scanner cannot see logic, so look for: wrong calculations or conditions, filters/tabs/sorting showing the wrong items, wrong phone/WhatsApp/email link formats, inputs that accept invalid data, features hidden or unusable on mobile, state that never resets, text that contradicts what the code does.

3. **The plan: one message, then stop and wait.** In the user's language, each item under about 12 words, the whole plan under about 18 lines (merge similar items; no explanations of how you found them). Group by how sure you are, and say what you will do about each:

```
فريق الموقع لقي:
مثبتة بالاختبار (<N>): <short list, one phrase each>
من قراءة الكود (<M>): <short list, one phrase each>
اقتراحات بدها موافقتك (ما بلمسها بدونها): <short list; for text changes give your proposed wording>

إذا وافقت بصلّح الأولين (<N+M>) على ملفاتك مباشرة (نسخة احتياطية بـ .website-team، بدون commit ولا رفع).
قول "اي" للكل، أو حدد شو تستثني أو تضيف من الاقتراحات.
```

   If there is nothing to fix, say so in the same format and stop. Do not edit anything and do not continue until the user answers. If your environment offers a question tool with options, you may use it for the final question, but the list above must still be visible to the user.

4. **After the user agrees: fix, then recheck.** Fix only what was approved (plus the approved suggestions), with small edits in the site's real files, following each problem's `fix` line; no redesign or restyle. Then:
   `python3 "${CLAUDE_SKILL_DIR}/scripts/scan.py" recheck SITE --state SITE/.website-team`
   - BROKEN BY THE EDIT: fix it, or put the file back with `scan.py restore SITE --state SITE/.website-team FILE`.
   - NEW or STILL OPEN problems: fix what was approved, then recheck **once more** (at most two rechecks in total).
   - "no longer tested": you may have deleted something; restore it.

5. **Summary**: the only message after the recheck, in the user's language, at most 6 lines, scanner numbers taken from the last RECHECK line, nothing else:

```
فريق الموقع خلص:
- صلّح: <proven fixed> مثبتة بالاختبار + <count> من مراجعة الكود (<2-4 words each>)
- باقي: <open> <2-4 words each, or "ولا شي">
- لسا بدها قرارك: <suggestions not approved yet, very short, or "ولا شي">
- التعديلات على ملفاتك مباشرة (ما انرفع ولا انعمل commit شي). قبل ما ترفع: احذف مجلد .website-team
```

If the user answers the plan with only some items, do those and list the rest as "لسا بدها قرارك".

## What the scan covers

Per page: loading, JS errors, buttons that do nothing or throw, forms (flags fake "thank you" forms that send nothing), broken links and anchors, image alt text, contrast (WCAG AA), field labels, `lang`, `dir="rtl"` for Arabic, `charset`, `title`, viewport, horizontal scrolling at 375px. Not covered: design taste, wording, performance, security, other browsers, real backends, external links.
