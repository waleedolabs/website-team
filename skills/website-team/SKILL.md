---
name: website-team
description: >-
  Quietly reviews and fixes a website that already exists - a four-member committee
  (advocate, critic, technical inspector, chair) reviews it, every fix is verified by real
  browser tests with automatic rollback, and the user gets a very short summary at the end.
  Use ONLY when the user explicitly asks for it by name - "website team", "the website team",
  "فريق الموقع", "خلي فريق الموقع يراجع", "/website-team". Do not use it for ordinary
  requests to build, design or edit a website; Claude handles those normally.
---

# Website Team (background review)

You run a review team **in the background** on a website that already exists (usually the one Claude just built for the user in the normal way). The user does not want the conversation taken over: **no questions, no design directions, no progress messages.** Work silently, then give one very short summary. Everything detailed goes into files.

`${CLAUDE_SKILL_DIR}` is this skill's base directory. If it appears literally instead of a path, write the absolute path yourself. Scripts: `${CLAUDE_SKILL_DIR}/scripts/`.

## Rules

1. Never call something working without a `pass` from the test runner. Statuses: pass / fail / needs_review / not_run.
2. Only the fix loop changes the site: `verify_fix.py try`. A fix is kept only if tests prove it helped and broke nothing.
3. Never change content (texts, prices, names, contact data), remove features, or touch real data on your own. Those become **suggestions** in the summary; the user decides later.
4. Never hide a problem: rejected fixes, open failures and untested areas go into `REPORT.md`.
5. Caps (enforced by the script): 3 attempts per check, 25 in total, one committee round.
6. Do not talk while working: no status updates, no SendUserMessage or similar tool, no text between tool calls, from the moment this skill starts until step 5 (the user explicitly does not want progress messages, even if your environment normally encourages them). Do not answer background or hook notifications with explanations. If another plugin's hook keeps waking you with the same error, say once, in one line, which plugin is broken; afterwards reply with one short line only.
7. Never retype a committee report. Members write their own files.

Tools: read with Read/Glob/Grep and write with Write/Edit. Use the shell only for the plugin scripts, one per command, in the form `python3 "${CLAUDE_SKILL_DIR}/scripts/<name>.py" <arguments>` (if `python3` fails, use `python` or the full path to the Python executable). No `cd`, pipes or redirection, and nothing in the background. Use the longest shell timeout (600000 ms) for `selftest`, `try` and `add-check`.

## Steps

**0. Find the site.** It is the site from this conversation, or the folder the user named. If there is no site, say so in one line and stop. Team folder: `website-team/` next to the site's files (in the same parent folder, or inside the site folder if that is the working directory). Every path below is inside the team folder: put that prefix on it in commands (for example `website-team/site`).

**1. Prepare** (silently):
- `python3 "${CLAUDE_SKILL_DIR}/scripts/check_env.py"`. If NOT READY, tell the user in one line that real testing is unavailable and what to install, then stop.
- `python3 "${CLAUDE_SKILL_DIR}/scripts/selftest.py" --quick --if-needed --log website-team/logs/selftest.log`. The first run on a machine takes about 3 minutes; later runs are cached. If it fails, rerun once. If the rerun passes, note "unstable" in the report; if it fails again, stop and say the tests cannot be trusted here.
- `python3 "${CLAUDE_SKILL_DIR}/scripts/sync_site.py" prepare --from SITE_FOLDER --project website-team` (SITE_FOLDER = the site's folder) copies the site into `website-team/site`.
- Write `website-team/brief.md` from the conversation: what the site is for, its main action, required functions, and your assumptions. Do not ask the user.
- Write `website-team/site/site-tests.json` declaring where forms submit (simulated if there is no real backend, e.g. `{"backend": {"POST /api/contact": 200}}`).
- `python3 "${CLAUDE_SKILL_DIR}/scripts/verify_fix.py" init --site website-team/site --work website-team/work`
- `python3 "${CLAUDE_SKILL_DIR}/scripts/run_tests.py" website-team/site --shots website-team/committee/shots --shots-only`

**2. Committee.** Launch the advocate, critic and inspector together in one message as normal (foreground) subagents (plugin agents `site-advocate`, `design-critic`, `qa-inspector`; otherwise general-purpose subagents given the role file from `${CLAUDE_SKILL_DIR}/roles/`). Give each the absolute paths of `brief.md`, `site/`, `committee/shots/` and `work/state.json`; give the inspector also the team folder and the scripts folder. Give each its output path (`committee/advocate.md`, `critic.md`, `inspector.md`), and never another member's report. Then launch the chair (`committee-chair`) with the three report paths, the brief and the state; it writes `committee/chair.md` and `committee/plan.json`. Then run `python3 "${CLAUDE_SKILL_DIR}/scripts/validate_committee.py" --project website-team`; if it says INVALID, the named member rewrites its own file.

**3. Prove, then fix.** Formats: `${CLAUDE_SKILL_DIR}/references/scenarios.md`.
- Write each of the chair's `checks_to_add` as `website-team/checks/<id>.json` (the *correct* behaviour), then add them all in one command: `python3 "${CLAUDE_SKILL_DIR}/scripts/verify_fix.py" add-check --site website-team/site --work website-team/work --scenario website-team/checks/a.json website-team/checks/b.json`. FAIL means the problem is proven; PASS means the suspicion was wrong. If a form check cannot represent real use, declare `form_setup`/`form_values` the same way. If a check was written wrongly, add a corrected one and `retire-check` the old one with a reason.
- For each plan item in order (skip items needing approval, rule 3), write the smallest change as `website-team/proposals/NN-name.json`, e.g. `{"title": "...", "rationale": "...", "kind": "fix", "targets": ["scenario:x"], "needs_user_approval": false, "ops": [{"op": "replace", "file": "index.html", "old": "exact unique text", "new": "replacement"}]}` (ops: `replace`, `create`/`write` with `text`, `delete`; `kind: "design"` only has to break nothing). Then run `python3 "${CLAUDE_SKILL_DIR}/scripts/verify_fix.py" try --site website-team/site --work website-team/work --proposal website-team/proposals/NN-name.json`. If rejected, try once more with a different approach or leave the item open.

**4. Finish.**
- `python3 "${CLAUDE_SKILL_DIR}/scripts/report.py" --work website-team/work --out website-team/work/facts.md`. Write `website-team/REPORT.md` following `${CLAUDE_SKILL_DIR}/references/report-template.md`, with the facts pasted unchanged.
- `python3 "${CLAUDE_SKILL_DIR}/scripts/audit_project.py" website-team`. It must say CLEAN; otherwise put the problem in the report and do not apply.
- If the audit is CLEAN and at least one fix was accepted: `python3 "${CLAUDE_SKILL_DIR}/scripts/sync_site.py" apply --project website-team`. This copies only the verified changes back into the user's site. It refuses if the user's files changed in the meantime.

**5. The only message to the user:** at most 6 lines in the user's language, each under 15 words, with numbers taken from the facts. No explanations, no caveats, no lists of what was not tested (those are in the report):

```
فريق الموقع خلص:
- فحص: <N> فحص، و<M> مشكلة مثبتة
- صلّح: <K> (طُبّقت على موقعك) / <list in 2–4 words each>
- باقي: <open count> <very short>
- اقتراحات بتحتاج موافقتك: <count> (بالتقرير)
التفاصيل: website-team/REPORT.md
```

If the changes were not applied (audit not clean, or files changed), say so in that same message, in one line.

## What the tests cover

Per page: loading, JS errors, buttons, forms (submits to the declared endpoint; flags fake "thank you" forms), links and anchors, images and alt text, contrast (WCAG AA), labels, `lang`, `title`, viewport, horizontal scrolling at 375px. Custom scenarios cover site-specific behaviour (cart totals, validation, double submission, network failure, cross-page flows). Not covered, always reported as not_run: performance, full accessibility audit, security, other browsers, real backend, external links (for example WhatsApp).
