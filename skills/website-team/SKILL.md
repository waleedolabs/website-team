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

All paths below are relative to this skill's base directory (the folder containing this SKILL.md). Scripts: `scripts/`. Committee role definitions: `../../agents/` (plugin root) — if that folder is missing, use `roles/` next to this file.

## Non-negotiable rules

1. Never state that something works without a `pass` result from the test runner. Use the four statuses exactly: pass / fail / needs_review / not_run.
2. After `verify_fix.py init`, change `site/` **only** through `verify_fix.py try`. Never edit site files directly, never edit test scripts or `site-tests.json` to make results look better.
3. Separate three levels of claims everywhere: **proven by a test**, **suspected** (code reading, needs a check), **opinion** (design taste).
4. Content changes, removing features/pages, publishing, or anything touching real data need the user's explicit approval (`needs_user_approval: true`, then `--approved` only after the user agreed).
5. Never hide a problem. Rejected fixes, open failures, untested areas, assumptions (e.g. a simulated backend) all go in the report.
6. Respect the caps (enforced by the script): 3 attempts per check, 25 attempts in total, at most 2 committee rounds.

## Project layout

Create one project folder (ask where if the user has a preference, else `./website-team-<short-name>/`):

```
brief.md                 project understanding + assumptions
directions/A|B|C/        three direction prototypes (+ shots/)
site/                    THE site being built, tested and fixed (only thing the loop changes)
site/site-tests.json     test contract: declared backend endpoints, pages, skips
work/                    verify_fix state, versions, decision log (must stay OUTSIDE site/)
committee/               advocate.md, critic.md, inspector.md, chair.md, plan.json, shots/
checks/<id>.json         custom behaviour checks (scenarios) added during the review
proposals/NN-name.json   every fix proposal sent to the loop
REPORT.md                final report
```

## Step 0 — Environment (once per environment)

Run `python3 scripts/check_env.py`. If NOT READY, run the printed setup commands, then re-check. If it still fails, tell the user plainly that real testing is unavailable here; continue only with design work and mark every technical check as not_run.

On first use in an environment, run `python3 scripts/selftest.py --quick` (about 2–3 minutes). It proves the tests have no false alarms, catch each known bug, handle tricky cases (fake forms, placeholder links, dead buttons), run custom scenarios correctly, and are stable. If it FAILS, tell the user the tests cannot be trusted here and do not present test results as verified. `python3 scripts/selftest_loop.py` (about 4–5 minutes) proves every accept/reject rule of the fix loop; run it when the user asks for full verification or after changing the scripts.

## Step 1 — Understand the project → `brief.md`

Extract from the request: business type, goal of the site (e.g. visits to a physical shop vs delivery orders vs online sales vs brand), audience, primary action, pages, required functions, tone, existing identity/examples, constraints. Ask **only** questions whose answers would change the design (max 5, use AskUserQuestion when available). Always settle: *where form submissions should go*. If there is no real backend yet, declare a simulated endpoint in `site/site-tests.json` and record it as an assumption that must be connected before launch.

If the user is not available, make the most reasonable assumptions, write them at the top of `brief.md`, and continue.

## Step 2 — Three directions

Create three directions that differ in **strategy**, not just colours — each a different way to reach the goal (for example: product-first, brand/story-first, fastest-path-to-action). Name each direction's bet and which audience/goal it serves best.

Build each as a lean, self-contained `directions/X/index.html` (inline CSS/JS, system fonts or local fonts, local or placeholder images, no CDN frameworks — tests run isolated from the internet and would otherwise test an unstyled page). Take screenshots:
`python3 scripts/run_tests.py directions/A --shots directions/A/shots --shots-only` (repeat for B, C).

Show the user the screenshots with a 2–3 line pitch each and let them pick, merge elements, or ask for another direction. When merging, keep one coherent visual system. If the user is unavailable, choose the best fit for the brief and say why.

## Step 3 — Build the site, then freeze the baseline

Build the chosen direction into `site/` with all required pages and functions, responsive, accessible, self-contained (same rules as above). Write `site/site-tests.json`, e.g.:

```json
{"backend": {"POST /api/contact": 200}}
```

Then: `python3 scripts/verify_fix.py init --site site --work work`. From now on, rule 2 applies.

## Step 4 — Committee review (one round by default)

1. Screenshots for reviewers: `python3 scripts/run_tests.py site --shots committee/shots --shots-only`.
2. Launch the **advocate**, **critic** and **inspector** in parallel as separate subagents, so each judges independently (plugin agents `site-advocate`, `design-critic`, `qa-inspector`; if they are not available, spawn a general-purpose subagent whose prompt starts with the full content of the role file). Give each the absolute paths of `brief.md`, `site/`, `committee/shots/`, `work/state.json`, and the scripts folder (inspector only). Do **not** give them each other's output. Save their replies verbatim to `committee/advocate.md`, `critic.md`, `inspector.md`.
3. Launch the **chair** (`committee-chair`) with the brief, the three reports and `work/state.json`. Save its reply to `committee/chair.md` and its JSON plan to `committee/plan.json`.

If no subagent tool exists, play the roles yourself one at a time, writing each report to its file before starting the next, and state in the report that independence was reduced.

## Step 5 — Verified fix loop

**5a. Make the tests realistic, then turn suspicions into proof.** If a generic form check cannot represent real use (e.g. an order form that must have an item in the cart, so a correct fix would look like "the form does nothing"), add a declared precondition: a file `{"form_setup": {"#order-form": [{"click": ".add"}]}, "reason": "..."}` passed to `add-check`. It may only add steps, must not change any other result, and is listed in the report. Then:

 For each entry in the chair's `checks_to_add`, write a scenario file `checks/<id>.json` (format: `references/scenarios.md`) describing the *correct* behaviour, and run `python3 scripts/verify_fix.py add-check --site site --work work --scenario checks/<id>.json`. FAIL = the suspicion is now proven, and its plan item becomes a `kind: "fix"` targeting `scenario:<id>`. PASS = the suspicion was wrong: drop or downgrade the item and say so in the report. Never edit or delete a scenario to make it pass.

**5b. Fix.** Follow the chair's order. For each plan item:

- Skip items marked `needs_user_approval` until the user agrees (unattended: leave them open and list them).
- Write the smallest change as `proposals/NN-name.json`:

```json
{"title": "...", "rationale": "...", "source": "plan P3 (critic CRIT-2 + inspector)",
 "kind": "fix", "targets": ["btn:index.html:#order-btn"], "needs_user_approval": false,
 "ops": [{"op": "replace", "file": "index.html", "old": "exact unique text", "new": "replacement"}]}
```

  `kind: "fix"` must make at least one target check pass. `kind: "design"` (opinion-level improvements) only has to cause no regression; its benefit is logged as unverified. Ops: `replace` (old text must appear exactly once), `create`, `write` (whole file), `delete`. Deliberately removing an element/page requires `"removes": [check ids]` plus approval.
- Run `python3 scripts/verify_fix.py try --site site --work work --proposal proposals/NN-name.json`.
- ACCEPTED → next item. REJECTED → read the reason (regression, target not fixed, patch did not apply, flaky). Revise at most within the caps, with a genuinely different approach; otherwise leave the item open.

Check progress anytime with `python3 scripts/verify_fix.py status --work work`.

Optional second round (only if the user wants it or many items changed): re-run the inspector and critic on the new version, then the chair, then the loop. Never more than 2 rounds.

**5c. Look at the result.** Take final screenshots (`run_tests.py site --shots final_shots --shots-only`) and view them yourself, desktop and mobile. Tests do not see everything (e.g. text that became bold, overlapping elements, awkward spacing). Fix what you see through the loop as `kind: "design"` and say in the report that it came from visual review.

## Step 6 — Final report → `REPORT.md`, then an independent audit

Run `python3 scripts/report.py --work work --out work/facts.md`. Write `REPORT.md` with the structure in `references/report-template.md`. The facts section must be pasted **unchanged** from `work/facts.md`; the narrative must not contradict it. Every "fixed" claim in the narrative needs a check id that now passes; if a change has no covering check (e.g. a security hardening), list it under "not tested", not under "fixed".

Then launch one **independent auditor** subagent that has not seen the work: give it the project folder, and ask it to check every claim in the narrative against `work/state.json`, `work/baseline.json` and `work/decisions.jsonl`, re-run `run_tests.py` on `site/` and confirm the results match, confirm every difference between `work/versions/v0` and `site/` comes from an accepted proposal, and list overclaims. Correct the report for every valid finding (add a check where a claim was unproven, or downgrade the claim). Skip the audit only in light mode, and say so.

Deliver `REPORT.md`, the before/after screenshots, and the site folder to the user, with a 2–3 sentence summary: what improved (numbers from facts), what is still open, what was not tested.

## Cost control

Default is one committee round (4 subagent calls) plus one audit. For a quick pass the user can ask for "light mode": skip Step 2 (one direction) and run only the inspector + chair. Keep direction prototypes to one page each.

## What the tests cover (and do not)

Custom scenarios (Step 5a) cover site-specific behaviour: cart totals, empty-cart blocking, double submission, network-failure messages, request contents, mobile visibility.
Covered per page: page loads, console/JS errors and failed local resources, every visible button (JS errors, dead buttons, broken navigation), every form (submits to a declared endpoint; flags fake "thank you" forms that send nothing), internal links and anchors, image alt and local image loading, text contrast (WCAG AA), form labels, `lang`, `title`, viewport meta, horizontal scrolling at 375px. External resources are blocked and reported.
Not covered (always reported as not_run): performance/Lighthouse, full accessibility audit, security, other browsers, real backend, business results. Never imply otherwise.
