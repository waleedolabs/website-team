---
name: website-team
description: >-
  Runs a full website team on a site - understands the project, proposes three genuinely
  different design directions, builds the chosen one, then a four-member review committee
  (advocate, critic, technical inspector, chair) reviews it, and every fix is verified by real
  browser tests with automatic rollback, ending in an honest report. Use when the user asks to
  design, build, review, test or improve a website or landing page with "the website team",
  "the committee", "فريق الموقع", "فريق التصميم", "اللجنة", or asks for a site that is reviewed,
  tested and fixed rather than just generated.
---

# Website Team

Act as the coordinator of a website team. The value of this workflow is **verified honesty**: nothing is called "working" unless a real test passed, no fix is kept unless tests prove it helped without breaking anything, and the final report shows what is still open or untested.

`${CLAUDE_SKILL_DIR}` below is this skill's base directory (the folder containing this SKILL.md). If you see it literally instead of a path, write the absolute base directory yourself; never use a shell variable. Scripts: `${CLAUDE_SKILL_DIR}/scripts/`. Reference files: `${CLAUDE_SKILL_DIR}/references/`. Committee role definitions: the plugin agents; if they are missing, `${CLAUDE_SKILL_DIR}/roles/`.

## Using tools without interrupting the user

Every shell command can make the user approve it, so tool choice decides how often they are interrupted:
- **Read** files with Read, Glob and Grep. Never with `cat`, `sed`, `head`, `tail`, `grep`, `ls` or `find`.
- **Create or change** files (brief, STATUS.md, prototypes, the site before `init`, checks, proposals, REPORT.md) with Write and Edit. Never with heredocs, `echo >`, or `python - <<EOF`. Write creates missing folders.
- **The shell is only for this plugin's scripts**, one per command, exactly in this form, run from your working directory:
  `python3 "${CLAUDE_SKILL_DIR}/scripts/<name>.py" <arguments>`
  No `cd`, variables, `&&`, `;`, pipes, `2>&1`, `| tail` or redirection. Arguments are paths inside the project folder, plain words, or quoted text. The plugin approves exactly this form automatically, and any other command asks the user. The scripts already print short output and create their output folders. Use `python` instead of `python3` if that is what works on the machine.
- Long scripts (selftest, `try`, `add-check`) run in the foreground with the shell tool's longest timeout (e.g. 600000 ms). Never run them in the background and never poll logs: polling creates a stream of "not finished yet" messages and an approval for each poll.
- Subagents follow the same rules; say so in their prompts.

## Non-negotiable rules

1. Never state that something works without a `pass` result from the test runner. Use the four statuses exactly: pass / fail / needs_review / not_run.
2. After `verify_fix.py init`, change `site/` **only** through `verify_fix.py try`, and the test contract only through `verify_fix.py add-check` / `retire-check`. Never edit site files, test scripts or `site-tests.json` directly.
3. Separate three levels of claims everywhere: **proven by a test**, **suspected** (code reading, needs a check), **opinion** (design taste).
4. Content changes, removing features/pages, publishing, or anything touching real data need the user's explicit approval (`needs_user_approval: true`, then `--approved` only after the user agreed).
5. Never hide a problem. Rejected fixes, open failures, retired checks, untested areas and assumptions (e.g. a simulated backend) all go in the report.
6. Respect the caps (enforced by the script): 3 attempts per check, 25 attempts in total, at most 2 committee rounds.
7. Never retype or summarise a committee member's report. Members write their own files; you validate them.

## Working with the user (checkpoints)

Assume the user is **present** unless they said they will not be available, or the run is scheduled/unattended. When present, there are two checkpoints where you **stop and end your turn**:

- **Checkpoint 1, questions (after Step 1):** if answers would change the design, ask them (AskUserQuestion if available, otherwise a short numbered list in plain text) and end your turn. Build nothing and run nothing before the answers. Add one line telling the user that, when asked to allow file edits, choosing to allow edits for this session avoids a prompt per file.
- **Checkpoint 2, direction (after Step 2):** show the three directions (screenshots + 2–3 line pitch each) and end your turn until the user picks, merges or asks for another.

Ask again later only for items that need approval (rule 4). When the user is not available, make reasonable assumptions, write them at the top of `brief.md`, choose the direction yourself and say why, and continue.

Talk to the user only at the checkpoints, when something needs their decision, when something fails, and at the end: no progress chatter while commands or subagents run, and never answer a background or hook notification with text. Before a step that takes minutes (the first selftest, building, the committee, the fix loop), say once what is starting and roughly how long it takes, then stay silent until it is done. Keep `STATUS.md` in the project folder updated (with Write/Edit) at every step: current step, decisions so far (direction chosen, user answers, approvals), and what you are waiting for. On a new turn or a new session, read it first and continue from there; do not ask again what it already records.

## Project layout

If your working directory is empty or a temporary folder, it is the project folder. Otherwise create `website-team-<short-name>/` inside it and put that prefix on every project path below (e.g. `website-team-salon/site`). Do not ask where, unless the user mentioned a location.

```
STATUS.md                current step / waiting for / selftest result
logs/                    selftest and long-running command logs
brief.md                 project understanding + assumptions + user answers
directions/A|B|C/        three direction prototypes (+ shots/)
site/                    THE site being built, tested and fixed (only thing the loop changes)
site/site-tests.json     test contract (backend, scenarios, form_setup, form_values, retired)
work/                    verify_fix state, versions, decision log (must stay OUTSIDE site/)
committee/               advocate.md, critic.md, inspector.md, chair.md, plan.json, manifest.json, shots/
checks/<id>.json         custom behaviour checks and form declarations sent to add-check
proposals/NN-name.json   every fix proposal sent to the loop
REPORT.md                final report
```

## Step 0: Environment (after Checkpoint 1, before Step 2)

Run `python3 "${CLAUDE_SKILL_DIR}/scripts/check_env.py"` (it also prints the plugin version; record it in `STATUS.md`; `report.py` puts it in the facts). If NOT READY, show the user the printed setup commands (they need approval) and re-check. If it still fails, tell the user plainly that real testing is unavailable here; continue only with design work and mark every technical check as not_run.

Then run `python3 "${CLAUDE_SKILL_DIR}/scripts/selftest.py" --quick --if-needed --log logs/selftest.log` in the foreground. The first time on a machine, it takes about 3 minutes. After that it returns at once, because a pass for this exact plugin code is cached. Record its result line in `STATUS.md`. It proves the tests have no false alarms, catch known bugs one by one, handle tricky and regression cases, run scenarios correctly, and that the committee validator works. If it FAILS, tell the user the tests cannot be trusted here, and do not present test results as verified. `selftest_loop.py` (about 3 minutes) proves every accept/reject rule of the fix loop; run it only when the user asks for full verification.

## Step 1: Understand the project → `brief.md`

Extract from the request: business type, goal of the site (e.g. visits to a physical shop vs delivery orders vs online sales vs brand), audience, primary action, pages, required functions, tone, existing identity/examples, constraints. Ask **only** questions whose answers would change the design (max 5), and never ask what the request already says. Always settle *where form submissions should go*. If there is no real backend yet, declare a simulated endpoint in `site/site-tests.json` and record it as an assumption that must be connected before launch. → Checkpoint 1.

## Step 2: Three directions

Create three directions that differ in **strategy**, not just colours: each a different way to reach the goal (for example product-first, brand/story-first, fastest-path-to-action). Name each direction's bet and which audience/goal it serves best.

Build each as a lean, self-contained `directions/X/index.html` (inline CSS/JS, system or local fonts, local or placeholder images, no CDN frameworks: tests run isolated from the internet and would otherwise test an unstyled page). Give each direction the same `site-tests.json` backend you plan for the site, so forms are not reported as broken only because the prototype has no endpoint.

**Test each prototype before showing it:** `python3 "${CLAUDE_SKILL_DIR}/scripts/run_tests.py" directions/A --shots directions/A/shots --out directions/A/health.json --quiet` (repeat for B, C). Fix obvious breakage first (horizontal scroll on mobile, unreadable contrast, JS errors, broken links): a direction must not be judged on a bug. Anything you leave unfixed is named in that direction's pitch as a known issue. Then show the three directions: for each, its name, the bet in one line, who it serves best, what you would see first, and a one-line health note. Show the screenshots (send the image files if you can; otherwise give their paths), and end with one line on how they differ. Ask the user to pick one, merge, or ask for another. → Checkpoint 2. When merging or revising, test the new prototype the same way and stop again until the user approves. When merging, keep one coherent visual system.

## Step 3: Build the site, then freeze the baseline

Build the chosen direction into `site/` with all required pages and functions, responsive, accessible, self-contained. Write `site/site-tests.json`, e.g. `{"backend": {"POST /api/contact": 200}}`. Then `python3 "${CLAUDE_SKILL_DIR}/scripts/verify_fix.py" init --site site --work work`. From now on, rule 2 applies.

## Step 4: Committee review (one round by default)

1. Screenshots for reviewers: `python3 "${CLAUDE_SKILL_DIR}/scripts/run_tests.py" site --shots committee/shots --shots-only`.
2. Launch the **advocate**, **critic** and **inspector** together in **one message, as normal (foreground) subagents, not background tasks**, so you simply wait until all three return; never poll or post status lines while they work. If your environment still sends background or hook notifications while waiting, do not answer them with text: stay silent until all three reports exist, then continue. If one member fails or times out, relaunch only that member once and say so in one line. Run them as separate subagents (plugin agents `site-advocate`, `design-critic`, `qa-inspector`; if unavailable, a general-purpose subagent whose prompt starts with the full role file). Give each the absolute paths of `brief.md`, `site/`, `committee/shots/`, `work/state.json`, the project folder and scripts folder (inspector only) and its **output path** (`committee/advocate.md`, `committee/critic.md`, `committee/inspector.md`). Do **not** give them each other's output. They write their own complete reports.
3. Launch the **chair** (`committee-chair`) with the brief, the three report paths, `work/state.json`, and its output paths `committee/chair.md` and `committee/plan.json`.
4. Run `python3 "${CLAUDE_SKILL_DIR}/scripts/validate_committee.py" --project .`. If INVALID, send the specific problem back to that member and ask it to rewrite its own file; never fix or shorten reports yourself. Proceed only when VALID (it also fingerprints the reports).

If no subagent tool exists, play the roles yourself one at a time, each writing its own file with its signature line before the next starts, and state in the report that independence was reduced.

## Step 5: Verified fix loop

**5a. Make the tests realistic, then turn suspicions into proof.** Details and formats: `${CLAUDE_SKILL_DIR}/references/scenarios.md`.
- If a generic form check cannot represent real use (the cart must hold an item first, possibly added on another page; fields have strict validation), declare it in `checks/form-<name>.json`, e.g. `{"form_setup": {"#order-form": [{"visit": "index.html"}, {"click": ".add"}]}, "form_values": {"#order-form": {"address": "12 King Fahd Rd, Riyadh"}}, "reason": "..."}`, and add it with `add-check`. Declarations are add-only and listed in the report.
- For every entry in the chair's `checks_to_add`, write `checks/<id>.json` describing the *correct* behaviour, then add **all of them in one command**: `python3 "${CLAUDE_SKILL_DIR}/scripts/verify_fix.py" add-check --site site --work work --scenario checks/a.json checks/b.json ...`. FAIL = the suspicion is now proven (its plan item becomes `kind: "fix"` targeting `scenario:<id>`). PASS = the suspicion was wrong: say so in the report.
- If a check turns out to be **written wrongly** (not a site problem), add a corrected check with a new id, then `python3 "${CLAUDE_SKILL_DIR}/scripts/verify_fix.py" retire-check --site site --work work --id scenario:old --reason "..." --replaced-by scenario:new`. Never edit or delete a scenario.

**5b. Fix.** Follow the chair's order. For each plan item:
- Skip items marked `needs_user_approval` until the user agrees (unattended: leave them open and list them).
- Write the smallest change as `proposals/NN-name.json`:

```json
{"title": "...", "rationale": "...", "source": "plan P3 (critic CRIT-2 + inspector)",
 "kind": "fix", "targets": ["btn:index.html:#order-btn"], "needs_user_approval": false,
 "ops": [{"op": "replace", "file": "index.html", "old": "exact unique text", "new": "replacement"}]}
```

  `kind: "fix"` must make at least one target check pass. `kind: "design"` only has to cause no regression; its benefit is logged as unverified. Ops: `replace` (old text must appear exactly once), `create`, `write` (whole file), `delete`. Deliberately removing an element/page requires `"removes": [check ids]` plus approval.
- Run `python3 "${CLAUDE_SKILL_DIR}/scripts/verify_fix.py" try --site site --work work --proposal proposals/NN-name.json`.
- ACCEPTED → next item. REJECTED → read the reason (regression, target not fixed, patch did not apply, flaky). Revise within the caps with a genuinely different approach; otherwise leave the item open.

Progress: `python3 "${CLAUDE_SKILL_DIR}/scripts/verify_fix.py" status --work work`. Optional second round (only if the user wants it): re-run inspector and critic into `committee/round2/`, then the chair, validate with `--dir committee/round2`, then the loop.

**5c. Look at the result.** Take final screenshots (`python3 "${CLAUDE_SKILL_DIR}/scripts/run_tests.py" site --shots final_shots --shots-only`) and view them yourself, desktop and mobile. Tests do not see everything (text that became bold, overlapping elements, awkward spacing). Fix what you see through the loop as `kind: "design"` and say it came from visual review.

## Step 6: Final report → `REPORT.md`, then an independent audit

Run `python3 "${CLAUDE_SKILL_DIR}/scripts/report.py" --work work --out work/facts.md`. Write `REPORT.md` with the structure in `${CLAUDE_SKILL_DIR}/references/report-template.md`. Paste the facts section **unchanged**; the narrative must not contradict it. Every "fixed" claim needs a check id that now passes; a change with no covering check goes under "not tested".

Then run `python3 "${CLAUDE_SKILL_DIR}/scripts/audit_project.py" .` (deterministic: re-runs the tests and compares, replays every version from the decision log, checks no test was weakened, checks committee fingerprints). It must say CLEAN; if not, fix the cause or report it. Then launch one **independent auditor** subagent that has not seen the work: give it the project folder and the audit output, tell it to read files only with Read/Glob/Grep (no shell), and ask it to check every claim in the narrative against `work/state.json`, `work/baseline.json` and `work/decisions.jsonl` and list overclaims. Correct the report for every valid finding. Skip the subagent audit only in light mode, and say so.

Deliver `REPORT.md`, before/after screenshots and the site folder, with a 2–3 sentence summary: what improved (numbers from facts), what is still open, what was not tested.

## Cost control

Default: one committee round (4 subagent calls) plus one audit subagent. "Light mode" on request: skip Step 2 (one direction) and run only the inspector + chair. Keep direction prototypes to one page each.

## What the tests cover (and do not)

Per page: page loads, console/JS errors and failed local resources, every visible button (JS errors, dead buttons, broken navigation; already-active toggles are not flagged), every form (submits to a declared endpoint; flags fake "thank you" forms that send nothing), internal links and anchors, image alt and local image loading, text contrast (WCAG AA, with semi-transparent colours and gradients composited; text over images reported as not judged), form labels, `lang`, `title`, viewport meta, horizontal scrolling at 375px. External resources are blocked and reported.
Custom scenarios cover site-specific behaviour: cart totals, empty-cart blocking, double submission, network-failure messages, request contents, cross-page flows, mobile visibility.
Not covered (always reported as not_run): performance/Lighthouse, full accessibility audit, security, other browsers, real backend, business results. Never imply otherwise.
