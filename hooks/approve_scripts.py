#!/usr/bin/env python3
"""PreToolUse hook: auto-approve ONLY plain invocations of website-team's own scripts.

Approved (prints an "allow" decision):
    python3 "<plugin>/skills/website-team/scripts/<known>.py" ARG...
where every ARG is a plain word or a quoted string, and every path-like ARG stays inside the
current project folder. One command, nothing else: no cd, no variables, no pipes, no redirection,
no ;, &&, $(...), backticks, globs or heredocs.

Anything else prints nothing, so Claude Code's normal permission flow (and the user's own
allow/deny rules) applies unchanged. Any internal error also prints nothing (fail closed to
"ask"). This hook never denies and never approves other tools.
"""
import json
import os
import posixpath
import re
import sys

SCRIPTS = {"check_env", "selftest", "selftest_loop", "run_tests", "verify_fix", "report",
           "validate_committee", "audit_project"}
INTERPRETER = re.compile(r"^(python3?(\.\d+)?|py)(\.exe)?$", re.I)
# characters allowed in an unquoted word (no shell meaning anywhere in it; '#' only mid-word)
SAFE_WORD = re.compile(r"^[A-Za-z0-9_./:=,@%+\-#\u0080-\uffff]+$")


def split_words(cmd):
    """Split into words, accepting only plain words, '...' and "..." without expansions.
    Returns list of (text, quoted) or None if anything shell-active is present."""
    words, i, n = [], 0, len(cmd)
    while i < n:
        c = cmd[i]
        if c in " \t":
            i += 1
            continue
        buf, quoted = "", False
        while i < n and cmd[i] not in " \t":
            c = cmd[i]
            if c == "'":
                j = cmd.find("'", i + 1)
                if j < 0:
                    return None
                buf += cmd[i + 1:j]
                quoted, i = True, j + 1
            elif c == '"':
                j = i + 1
                while j < n and cmd[j] != '"':
                    if cmd[j] in "$`" or (cmd[j] == "\\" and j + 1 < n and cmd[j + 1] in '$`"\\\n'):
                        return None
                    j += 1
                if j >= n:
                    return None
                buf += cmd[i + 1:j]
                quoted, i = True, j + 1
            else:
                j = i
                while j < n and cmd[j] not in " \t'\"":
                    j += 1
                part = cmd[i:j]
                if not SAFE_WORD.match(part) or (not buf and part.startswith("#")):
                    return None
                buf += part
                i = j
        if "\n" in buf or "\r" in buf or "\x00" in buf:
            return None
        words.append((buf, quoted))
    return words


def norm(p):
    """Comparable absolute path for POSIX, Windows (C:\\x, C:/x) and Git-Bash (/c/x) forms."""
    p = p.replace("\\", "/")
    m = re.match(r"^/([a-zA-Z])(/|$)", p)
    if m and os.name == "nt":
        p = m.group(1) + ":/" + p[3:]
    win = bool(re.match(r"^[a-zA-Z]:/", p))
    p = posixpath.normpath(p)
    return (p.lower() if win else p), win


def is_abs(p):
    return p.startswith(("/", "\\", "~")) or bool(re.match(r"^[a-zA-Z]:[\\/]", p))


def inside(child, parent):
    c, _ = norm(child)
    p, _ = norm(parent)
    return c == p or c.startswith(p.rstrip("/") + "/")


def looks_like_path(w):
    return ("/" in w or "\\" in w or w.startswith((".", "~")) or bool(re.match(r"^[a-zA-Z]:", w)))


def decide(cmd, cwd, plugin_root):
    """Return the approved script name, or None."""
    if not cmd or not cwd or not plugin_root or "\n" in cmd.strip():
        return None
    words = split_words(cmd.strip())
    if not words or len(words) < 2:
        return None
    interp, _ = words[0]
    if not INTERPRETER.match(interp):
        return None
    script = words[1][0]
    scripts_dir = posixpath.join(plugin_root.replace("\\", "/"), "skills/website-team/scripts")
    name = posixpath.basename(script.replace("\\", "/"))
    if not name.endswith(".py") or name[:-3] not in SCRIPTS:
        return None
    if norm(script)[0] != norm(posixpath.join(scripts_dir, name))[0]:
        return None
    for text, quoted in words[2:]:
        vals = [text]
        if text.startswith("-") and "=" in text:
            vals = [text.split("=", 1)[1]]
        for v in vals:
            if quoted and re.search(r"\s", v):
                # free text (e.g. a retire reason), passed as one argument; it must not
                # double as an escaping path ("a b/../../x") or an outside absolute path
                if ".." in v or (is_abs(v) and not inside(v, cwd)):
                    return None
                continue
            if not looks_like_path(v):
                continue
            if v.startswith("~"):
                return None
            target = v if is_abs(v) else posixpath.join(cwd.replace("\\", "/"), v)
            if not inside(target, cwd):
                return None
    return name[:-3]


def main():
    try:
        data = json.load(sys.stdin)
        if data.get("tool_name") != "Bash":
            return
        cmd = (data.get("tool_input") or {}).get("command", "")
        root = os.environ.get("CLAUDE_PLUGIN_ROOT") or os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        name = decide(cmd, data.get("cwd", ""), root)
        if name:
            print(json.dumps({"hookSpecificOutput": {
                "hookEventName": "PreToolUse",
                "permissionDecision": "allow",
                "permissionDecisionReason": f"website-team: its own {name}.py script with project-local arguments"}}))
    except Exception:
        pass  # never block, never approve on error


if __name__ == "__main__":
    main()
