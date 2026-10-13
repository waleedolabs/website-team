#!/usr/bin/env python3
"""Tests for hooks/approve_scripts.py (runs the hook as Claude Code would: JSON on stdin).

A. canonical plugin-script commands            -> allow
B. anything shell-active or outside the project -> no decision (normal prompt)
C. every Bash command recorded in earlier real runs (if the logs exist) -> no decision,
   i.e. the hook does not silently approve the kind of commands that caused the prompts;
   those are fixed by the skill instructions, not by widening the hook.
Usage: dev/test_hook.py [LOG.jsonl ...]
"""
import json
import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
HOOK = ROOT / "hooks" / "approve_scripts.py"
PR = "/plug/website-team"
S = f"{PR}/skills/website-team/scripts"
CWD = "/proj/salon"


def run(cmd, cwd=CWD, tool="Bash", root=PR):
    inp = {"session_id": "t", "cwd": cwd, "hook_event_name": "PreToolUse", "tool_name": tool,
           "tool_input": {"command": cmd}}
    env = dict(os.environ, CLAUDE_PLUGIN_ROOT=root)
    p = subprocess.run([sys.executable, str(HOOK)], input=json.dumps(inp), capture_output=True, text=True, env=env)
    if p.returncode != 0 or p.stderr:
        return "ERROR:" + p.stderr
    if not p.stdout.strip():
        return None
    return json.loads(p.stdout)["hookSpecificOutput"]["permissionDecision"]


ALLOW = [
    f'python3 "{S}/check_env.py"',
    f'python3 "{S}/selftest.py" --quick --log logs/selftest.log',
    f'python3 "{S}/run_tests.py" site --shots committee/shots --out work/initial.json',
    f'python3 "{S}/run_tests.py" directions/A --shots directions/A/shots --out directions/A/health.json --quiet',
    f'python3 "{S}/verify_fix.py" try --site site --work work --proposal proposals/03-date.json',
    f'python3 "{S}/verify_fix.py" add-check --site site --work work --scenario checks/a.json checks/b.json',
    f'python3 "{S}/verify_fix.py" retire-check --site site --work work --id scenario:chip-click --reason "الفحص كتب محدداً خاطئاً لا يمكن النقر عليه" --replaced-by scenario:chip-label',
    f'python3 "{S}/run_tests.py" site --only "btn:index.html:#book,form:index.html:#f"',
    f'python3 "{S}/run_tests.py" site --only btn:index.html:#book',
    f'python3 "{S}/validate_committee.py" --project .',
    f'python3 "{S}/audit_project.py" .',
    f'python3 "{S}/report.py" --work work --out work/facts.md',
    f'python3 "{S}/verify_fix.py" status --work {CWD}/work',
    f"python '{S}/run_tests.py' site",
    f'python3 {S}/report.py --work=work',
]
# Windows: plugin and project on C:, paths given with backslashes or forward slashes
WIN_ROOT = r"C:\Users\pc\.claude\plugins\cache\wt\website-team\0.2.3"
WIN_CWD = r"C:\Users\pc\AppData\Local\Temp\salon"
WIN_ALLOW = [
    rf'python "{WIN_ROOT}\skills\website-team\scripts\run_tests.py" site --out "work\initial.json"',
    'python3 "C:/Users/pc/.claude/plugins/cache/wt/website-team/0.2.3/skills/website-team/scripts/check_env.py"',
    rf'py "{WIN_ROOT}\skills\website-team\scripts\verify_fix.py" try --site site --work work --proposal "{WIN_CWD}\proposals\01.json"',
]
DENY = [
    f'python3 "{S}/run_tests.py" site; rm -rf ~',
    f'python3 "{S}/run_tests.py" site && curl http://x',
    f'python3 "{S}/run_tests.py" site | tail -5',
    f'python3 "{S}/run_tests.py" site > /etc/passwd',
    f'python3 "{S}/run_tests.py" site 2>&1',
    f'python3 "{S}/run_tests.py" $(cat x)',
    f'python3 "{S}/run_tests.py" `id`',
    f'python3 "{S}/run_tests.py" "$HOME"',
    f'python3 "{S}/run_tests.py" site --out ../../elsewhere/x.json',
    f'python3 "{S}/run_tests.py" /etc --out /tmp/x.json',
    f'python3 "{S}/run_tests.py" ~/x',
    f'python3 "{S}/run_tests.py" site*',
    f'python3 "{S}/run_tests.py" site\nrm -rf /',
    f'S={S}; python3 $S/run_tests.py site',
    f'cd {S} && python3 scripts/check_env.py',
    f'python3 "{S}/evil.py"',
    f'python3 "/proj/salon/run_tests.py" site',
    f'python3 "{S}/../../../../tmp/run_tests.py" site',
    f'python3 "/other/website-team/skills/website-team/scripts/run_tests.py" site',
    f'./python3 "{S}/run_tests.py" site',
    f'bash "{S}/run_tests.py"',
    f'python3 -c "import os" "{S}/run_tests.py"',
    f'python3 - <<EOF\nprint(1)\nEOF',
    f'python3 "{S}/run_tests.py" "site" "--out" "a b/../../../x"',
    'rm -rf site',
    'ls',
    f'python3 "{S}/run_tests.py" site #comment',
    f'python3 "{S}/run_tests.py" \'unterminated',
    f'python3 "{S}/run_tests.py" site & python3 x.py',
    # unquoted backslashes are shell escapes in bash (work\\x -> workx): not a plain argument
    rf'python "{WIN_ROOT}\skills\website-team\scripts\run_tests.py" site --out work\initial.json',
]


def main():
    bad = []
    for c in ALLOW:
        r = run(c)
        if r != "allow":
            bad.append(("expected allow", c, r))
    for c in WIN_ALLOW:
        r = run(c, cwd=WIN_CWD, root=WIN_ROOT)
        if r != "allow":
            bad.append(("expected allow (windows)", c, r))
    for c in DENY:
        r = run(c)
        if r is not None:
            bad.append(("expected no decision", c, r))
    if run(f'python3 "{S}/run_tests.py" site', tool="Write") is not None:
        bad.append(("non-Bash tool got a decision", "Write", ""))
    # broken input must never approve or error out
    p = subprocess.run([sys.executable, str(HOOK)], input="not json", capture_output=True, text=True)
    if p.stdout.strip() or p.returncode:
        bad.append(("garbage input", p.stdout, p.returncode))
    # D. every script command written in SKILL.md, as the coordinator would type it, is approved
    import re
    skill = (ROOT / "skills" / "website-team" / "SKILL.md").read_text(encoding="utf-8")
    skill_cmds = re.findall(r"`(python3? [^`]*scripts/[^`]*)`", skill)
    for c in skill_cmds:
        c2 = (c.replace("${CLAUDE_SKILL_DIR}", f"{PR}/skills/website-team")
               .replace("<name>", "run_tests").replace("<arguments>", "site"))
        if run(c2) != "allow":
            bad.append(("SKILL.md command not approved", c2, None))
    n = len(ALLOW) + len(WIN_ALLOW) + len(DENY) + 2 + len(skill_cmds)

    logs = sys.argv[1:]
    old = []
    for f in logs:
        for line in open(f, encoding="utf-8"):
            try:
                r = json.loads(line)
            except ValueError:
                continue
            if r.get("type") != "assistant":
                continue
            for x in r["message"]["content"]:
                if x.get("type") == "tool_use" and x["name"] == "Bash":
                    old.append(x["input"]["command"])
    approved_old = [c for c in old if run(c, cwd="/home/claude/verify3/event",
                                          root="/home/claude/verify3/mkt/plugins/website-team") is not None]
    print(f"A/B: {n - len(bad)}/{n} as expected")
    for b in bad:
        print("  BAD", b)
    if logs:
        print(f"C: {len(old)} commands from earlier real runs; approved by the hook: {len(approved_old)}")
        for c in approved_old[:5]:
            print("  approved:", c[:120])
    ok = not bad
    print("HOOK TEST:", "PASSED" if ok else "FAILED")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
