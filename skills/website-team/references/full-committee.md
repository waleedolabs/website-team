# Full review (light committee)

Used only when the user asks for the **full** team. Same rules and steps as SKILL.md (scan, review, plan, wait, fix, recheck, summary), plus four viewpoints. It should cost about 1.5-2x a normal review, not more: one subagent only, no extra files to exchange, no per-fix loop. Nothing is changed before the user answers the plan.

1. **Scan** exactly as SKILL.md step 1 (the output is also saved to `SITE/.website-team/scan.txt`). Then take screenshots:
   `python3 "${CLAUDE_SKILL_DIR}/scripts/run_tests.py" SITE --shots SITE/.website-team/shots --shots-only`

2. **In ONE message, do both at once:**
   - launch the critic: subagent `site-critic-lite` (or a general-purpose subagent given `${CLAUDE_SKILL_DIR}/../../agents/site-critic-lite.md` as its instructions), passing the absolute paths of `SITE/.website-team/scan.txt` and the main page's mobile and desktop screenshots in `SITE/.website-team/shots/`;
   - and start your own code review (SKILL.md step 2, guided by the MAP).

3. **Your three viewpoints** (think them through yourself; do not write separate reports):
   - *Advocate*: what works and must not be lost (add the critic's `keep:` line).
   - *Inspector*: what is proven (scanner `PROBLEM`, failing behaviour you can see in code) versus only suspected.
   - *Chair*: decide what goes in the plan. Check the critic's claims against the code and facts (for example a stated duration or count) and drop or correct what is wrong. The critic's `problem` items with a small fix that changes no content go into the plan as fixes. `probable`/`taste` items and anything `(needs user decision)` go into "اقتراحات بدها موافقتك".

4. **The plan message** is SKILL.md step 3, with two extra lines before the closing question:
```
رأي الناقد: <1-3 most useful points, very short>
نقاط قوة بحميها: <1-2 short>
```
   Stop and wait for the answer. Write nothing to the site yet.

5. **After approval:** fix, recheck and summary exactly as SKILL.md steps 4-5. Also write ONE file, `SITE/.website-team/review.md`, with the critic's lines unchanged, what you fixed, and the suggestions you did not apply (with why), and end the summary with `التفصيل: .website-team/review.md`.

The old four-subagent procedure is kept in `full-committee-classic.md` for reference only; do not use it unless the user explicitly asks for the "classic" committee.
