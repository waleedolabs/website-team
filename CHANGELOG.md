# Changelog

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
