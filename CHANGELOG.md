# Changelog

## 0.4.1
From the first real run of 0.4.0 on a medium project (12 findings, only 2 real; 10 "likely" were noise).
- **Gradient-clipped text** (`background-clip:text`, transparent colour) is no longer reported as a contrast failure: its CSS colour is only a mask, so the ratio cannot be judged (counted as "not judged").
- **Web-font stylesheets** (Google Fonts, Typekit, Bunny) are treated as fonts ("not run"), not as external scripts that change behaviour.
- **Buttons that could not be clicked** (hidden/covered until a state change, e.g. before a presentation starts) are shown in one "NOT TESTABLE" line instead of one numbered problem each, and are not counted as problems.
- **Edit in place, never copy.** SKILL.md now says explicitly: edit the real files (originals are backed up in `.website-team`; `git diff` shows the changes), never copy the project, never commit/push/deploy. In 0.4.0 the model on that project worked on a copy, which the skill does not ask for.
- 3 new scanner tests reproduce the three noise sources (before: 1 fail + 2 needs_review; after: 0 problems); scanner tests 14/14, loop 60/60, selftest pass.

## 0.4.0
Redesign for low usage. Measured on the same machine: the old committee flow used ~1.1M cache-read tokens in the main session alone (and never finished a run); plain Claude ~0.15M; this version ~0.2-0.3M, about 40-50 s.
- **Fast mode is the default.** New `scripts/scan.py` (scan / recheck / restore): real-browser findings with file:line and a fix direction; Claude reviews the code itself and fixes; the recheck proves fixed / still open / broken-by-the-edit and warns when something was removed. Backup in `<site>/.website-team`.
- **Full committee only on request** ("الفريق الكامل"): the old procedure moved to `references/full-committee.md`. Not re-measured in this version.
- `run_tests.py`: a JS error at page load is no longer blamed on every button/form (it is reported once by the console check), so a button that really does nothing and a form that shows success without sending are now reported as such. State folder is excluded from page discovery.
- New `scan_selftest.py` (11 checks). Existing tests still pass (loop 60/60, selftest).
- **Benchmarks (honest):** on a site with 10 defects unknown to the author, plain Claude fixed 10/10 and this version 10/10 (48 s vs 24 s). On an earlier blind site: 8/10 vs 9/10 after a first version scored 4/10 because it forbade fixing anything the scanner had not reported. The skill does not find more defects than plain Claude; it adds browser proof, rollback, no content removal and no false "sent" messages.
- Untested: Windows, large sites, framework-built sites, the full committee in this version.

## 0.3.0
Redesign requested by the user: a team that works in the background only when asked, instead of taking over the conversation.
- **Only on request.** The skill is used only when asked by name ("فريق الموقع", "website team", /website-team); ordinary website requests are left to Claude.
- **Nothing always-on.** The approval hook from 0.2.3/0.2.4 is removed: it ran on every command in every session. `dev/check_plugin.py` now fails if a `hooks/` folder exists. (Trade-off: the plugin's scripts ask for approval again, as normal commands.)
- **Reviews an existing site.** No questions, no three directions, no checkpoints. New `scripts/sync_site.py`: copies the site into `website-team/site`, and at the end copies back only the verified changes (never `site-tests.json`), refusing if the user's files changed in the meantime. 2 new loop tests.
- **Content is never changed on its own** (texts, prices, contact data, removals): these become suggestions.
- **One very short final message** (at most 6 lines: checked, proven problems, fixed and applied, open, suggestions, report path). Details stay in `website-team/REPORT.md`. The independent auditor subagent was dropped to save usage; the deterministic audit (`audit_project.py`) still has to be CLEAN before anything is copied back.

## 0.2.4
From the first real run of 0.2.3 on Windows (flower shop).
- **Repeated "automatic notice" messages: caused by another plugin.** security-guidance on that machine is missing `security_reminder_hook.py`; its Stop hook (asyncRewake) fails after every reply and wakes the model again, so the chat filled with "this is an automatic notice, still waiting for your choice". Not fixable inside website-team; the user has to disable or reinstall that plugin. SKILL.md: say so once, then one-line replies only.
- **Audit reported PROBLEMS on Windows for versions with Arabic text.** `audit_project.py` read the decision log without `encoding="utf-8"`, so on Windows (cp125x) Arabic `old` text did not match and replays failed. All file reads and subprocess output now use UTF-8 explicitly and every script forces UTF-8 stdout. Test: running the scripts with default-encoding I/O made fatal (`PYTHONWARNINGS=error::EncodingWarning`) failed the audit before and passes now; selftest, loop selftest (58/58) and audit all pass that way.
- **Python not on PATH in PowerShell.** The approval hook now runs through `hooks/run-python.sh`, which finds a working Python (skips the Microsoft Store stub, tries python, py -3) and stays silent if none exists; the hook also accepts a full path to python.exe outside the project. SKILL.md says to use that path if needed.
- **Self-test failed once, then passed, and the failing output was overwritten.** `--log` now appends each run, and SKILL.md says to report such a run as unstable with its failing lines.
- Messages to the user in their language only (an English line slipped in).

## 0.2.3
Usability review of real use (too many approval prompts; repeated "not received yet" messages). Evidence: every tool call in three earlier full runs was classified: 23, 30 and 32 shell commands per run each needed an approval, and none of them could ever be covered by an "always allow" rule (all compound: variables, `cd`, pipes, heredocs).
- **Root cause 1: the coordinator used the shell for everything** (writing pages with heredocs, reading with `cat`/`sed`, editing with inline Python). SKILL.md now sets tool discipline: Read/Glob/Grep to read, Write/Edit to change files, shell only for the plugin's scripts in one fixed form.
- **Root cause 2: script commands had a different shape every time.** New plugin hook `hooks/approve_scripts.py` approves exactly `python3 "<plugin>/skills/website-team/scripts/<known>.py" <args>` with every path inside the project folder, plus reads of the plugin's own files. Everything else keeps the normal prompt; the hook never denies and never approves writes. `dev/test_hook.py`: 78/78 cases (incl. 29 bypass attempts), 0 of 85 commands from earlier runs approved, and every command written in SKILL.md approved. Confirmed inside Claude Code: canonical command ran without a prompt; the same command with `| tail` or an outside path still asked.
- **Root cause 3: the self-test ran in the background and its log was polled**, each poll being a new command, a new approval and a "not finished yet" message. It now runs in the foreground after the questions are answered, writes its own log (`--log`), and runs once per plugin code per machine (`--if-needed`, cache keyed by a hash of scripts + fixtures; 2 min 33 s first run, 0.05 s after; changed code re-runs).
- Inspector: no ad-hoc servers or probe scripts; suspicions become checks.
- `run_tests.py --quiet` now prints counts plus non-pass lines (it printed nothing, which led to an ad-hoc command to read the results).
- Fix proposals are validated before anything is applied, with usable messages (e.g. `write` with `content` instead of `text`, found in a real run). 4 new loop tests (58/58).
- Clearer direction presentation (bet, audience, first impression, health, how they differ); questions never repeat what the request or STATUS.md already says; one line advising "allow edits for this session".
- `check_env.py` and the report facts show the plugin version.
- Interactive run on the installed build (gym site, default permission mode, edits allowed for the session): 2 approval requests in the whole run, both traced to causes fixed in this version (the quiet output; plugin-file reads), versus 23–32 per run before.

## 0.2.2
- Found by the first real user run (Windows, Claude desktop app): the coordinator launched the committee as background tasks and answered every background/hook notification with a line of text ("still waiting for the inspector"), flooding the chat. Step 4 now launches the three reviewers together as foreground subagents and waits silently; one failed member is relaunched once. General rule: no progress chatter, talk only at checkpoints, decisions, failures and the end.

## 0.2.1
Found by the interactive verification of 0.2.0 (two installed-plugin runs: dental clinic, wedding photographer).
- **Generic form check used a fixed date (2026-01-15) that had become past**, so a site that correctly refuses past dates looked broken (it caused a rejected fix in the photographer run). Dates are now relative to the day the test runs (+30 days) and clamped to the field's min/max. Fixture `form-cases/booking.html`: 0.2.0 needs_review, 0.2.1 pass.
- **Direction prototypes were shown without being tested** (the clinic's direction B scrolled sideways on mobile, 470 px on a 375 px screen, unnoticed). Step 2 now tests every prototype, fixes obvious breakage before showing it, and discloses what remains.
- **The self-test log was kept outside the project** (a temporary folder), so a later turn could not find it. It now goes to `logs/selftest.log` and its result into `STATUS.md`.

## 0.2.0
Fixes for the six problems found when verifying 0.1.0 as an installed plugin. Each fix comes with a test that fails on 0.1.0 and passes now.

1. **Contrast check was wrong with semi-transparent colours** (false alarms *and* missed real problems). Backgrounds and text are now alpha-composited from the root down; gradients are judged by their worst colour stop; text over images is reported as "not judged". Regression fixture `contrast-cases`: 0.1.0 got 1/6 right, 0.2.0 6/6.
2. **Committee reports were retyped as summaries.** Members now write their own complete reports (closing signature line). New `scripts/validate_committee.py` rejects condensed copies, checks the chair's plan against the real test state, checks the site was not touched, and fingerprints the reports.
3. **Slow loop (a 10-minute command limit was hit).** Targeted runs (`run_tests.py --only`); `try` = 1 full run + 2 targeted re-runs of changed checks; `add-check` runs only the new checks. Shop benchmark: add-check 118.7 s → 14.1 s, try 118.5 s → 39.1 s. Unit tests guard the flaky/regression verdict logic.
4. **A wrongly written check stayed failing forever.** New `verify_fix.py retire-check` (reason required; active replacement or user approval; kept on record; ids never reusable).
5. **The generic form check could not represent real forms** (cart filled on another page, strict validation). `form_setup` can `visit` other pages; new add-only `form_values`. Fixture `form-cases`, including variants proving the declarations do not mask failures.
6. **SKILL.md frontmatter was not strict YAML.** Fixed; new `dev/check_plugin.py` parses all frontmatter strictly and checks the plugin's structure.

Other improvements:
- Interactive checkpoints: the skill stops and waits for answers (after the questions) and for the direction choice; `STATUS.md` lets a session resume.
- Toggle buttons that are already active (`aria-pressed`/`aria-selected`/`aria-current`) are no longer flagged as dead.
- `scripts/audit_project.py` ships with the plugin: re-runs the tests, replays every version from the decision log, checks tests were never weakened, checks committee fingerprints.
- `visit` step for cross-page scenarios.
- Trigger phrase "فريق الموقع".
- Report wording: counts failing checks, not causes; explains the confirmation method.

## 0.1.0
First release.
