# Full review (light committee)

Used only when the user asks for the **full** team. Same rules, steps and summary as SKILL.md (scan, review, fix, recheck), plus four viewpoints. It should cost about 1.5-2x a normal review, not more: one subagent only, no extra files to exchange, no per-fix loop.

1. **Scan** exactly as SKILL.md step 1 (the output is also saved to `SITE/.website-team/scan.txt`). Then take screenshots:
   `python3 "${CLAUDE_SKILL_DIR}/scripts/run_tests.py" SITE --shots SITE/.website-team/shots --shots-only`

2. **In ONE message, do both at once:**
   - launch the critic: subagent `site-critic-lite` (or a general-purpose subagent given `${CLAUDE_SKILL_DIR}/../../agents/site-critic-lite.md` as its instructions), passing the absolute paths of `SITE/.website-team/scan.txt` and the main page's mobile and desktop screenshots in `SITE/.website-team/shots/`;
   - and start your own code review (SKILL.md step 2, guided by the MAP).

3. **Your three viewpoints** (think them through yourself; do not write separate reports):
   - *Advocate*: what works and must not be lost (add the critic's `keep:` line).
   - *Inspector*: what is proven (scanner `PROBLEM`, failing behaviour you can see in code) versus only suspected.
   - *Chair*: decide. Fix every scanner problem and real bug, and the critic's `problem` items when the fix is small and changes no content. `probable`/`taste` items and anything `(needs user decision)` become suggestions.

4. **Fix, then recheck** exactly as SKILL.md steps 3-4.

5. **One Write**: `SITE/.website-team/review.md` with the critic's lines unchanged, what you fixed, and the suggestions you did not apply (with why). Then the summary from SKILL.md step 5, adding at most two lines:
```
- رأي الناقد: <1-3 most useful suggestions, very short> (بالتفصيل بـ .website-team/review.md)
- نقاط قوة محمية: <1-2 short>
```

The old four-subagent procedure is kept in `full-committee-classic.md` for reference only; do not use it unless the user explicitly asks for the "classic" committee.
