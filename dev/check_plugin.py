#!/usr/bin/env python3
"""Strict structural check of the website-team plugin (developer/release tool; not shipped).

Usage: python3 dev/check_plugin.py [PLUGIN_ROOT]
Checks:
  * plugin.json valid JSON, kebab-case name, semver version
  * every SKILL.md and agent file has frontmatter that a STRICT YAML parser accepts,
    with the required fields; agent name == file name; tools are known names
  * every scripts/... and references/... path mentioned in SKILL.md exists
  * skills/website-team/roles/*.md are byte-identical to agents/*.md (fallback copies)
  * all Python scripts compile; fixtures referenced by the self-tests exist
  * no stray caches or dev files inside the shipped tree
Exit 0 = OK.
"""
import json
import re
import sys
from pathlib import Path

try:
    import yaml
except ImportError:
    sys.exit("check_plugin needs PyYAML (pip install pyyaml)")

ROOT = Path(sys.argv[1] if len(sys.argv) > 1 else Path(__file__).resolve().parent.parent)
SKILL = ROOT / "skills" / "website-team"
problems = []


def check(cond, msg):
    if not cond:
        problems.append(msg)
    return cond


def frontmatter(path):
    text = path.read_text(encoding="utf-8")
    if not text.startswith("---\n"):
        return None, "no frontmatter"
    parts = text.split("---\n", 2)
    if len(parts) < 3:
        return None, "unterminated frontmatter"
    try:
        return yaml.safe_load(parts[1]), None
    except yaml.YAMLError as e:
        return None, "strict YAML error: " + str(e).splitlines()[0]


pj = ROOT / ".claude-plugin" / "plugin.json"
if check(pj.exists(), "missing .claude-plugin/plugin.json"):
    d = json.loads(pj.read_text(encoding="utf-8"))
    check(re.fullmatch(r"[a-z0-9]+(-[a-z0-9]+)*", d.get("name", "")) is not None, "plugin name not kebab-case")
    check(re.fullmatch(r"\d+\.\d+\.\d+", d.get("version", "")) is not None, "version not semver")
    print(f"plugin.json: {d.get('name')} {d.get('version')}")

fm, err = frontmatter(SKILL / "SKILL.md")
if check(fm is not None, f"SKILL.md: {err}"):
    check(fm.get("name") == "website-team", "SKILL.md name must be website-team")
    check(isinstance(fm.get("description"), str) and len(fm["description"]) > 50, "SKILL.md description missing/short")
    print(f"SKILL.md frontmatter OK ({len(fm['description'])} chars description)")

KNOWN_TOOLS = {"Read", "Write", "Edit", "Glob", "Grep", "Bash"}
agents = sorted((ROOT / "agents").glob("*.md"))
check(len(agents) == 4, f"expected 4 agents, found {len(agents)}")
for a in agents:
    fm, err = frontmatter(a)
    if not check(fm is not None, f"{a.name}: {err}"):
        continue
    for k in ("name", "description", "model", "color"):
        check(k in fm, f"{a.name}: missing {k}")
    check(fm.get("name") == a.stem, f"{a.name}: name {fm.get('name')!r} != file name")
    check(set(fm.get("tools", [])) <= KNOWN_TOOLS, f"{a.name}: unknown tools {set(fm.get('tools', [])) - KNOWN_TOOLS}")
    role = SKILL / "roles" / a.name
    check(role.exists() and role.read_bytes() == a.read_bytes(), f"roles/{a.name} differs from agents/{a.name}")
    print(f"agent {a.stem}: OK tools={fm.get('tools')}")

skill_text = (SKILL / "SKILL.md").read_text(encoding="utf-8")
for ref in sorted(set(re.findall(r"(?:scripts|references)/[\w.\-]+\.(?:py|md)", skill_text))):
    check((SKILL / ref).exists(), f"SKILL.md references missing file {ref}")

# every shell command the skill tells the coordinator to run must be in the auto-approved form
for cmd in re.findall(r"`(python3? [^`]*scripts/[^`]*)`", skill_text):
    check(cmd.startswith('python3 "${CLAUDE_SKILL_DIR}/scripts/'), f"SKILL.md command not in the canonical form: {cmd[:80]}")
    bare = re.sub(r"<\w+>", "x", cmd).replace("${CLAUDE_SKILL_DIR}", "D")
    check(not re.search(r"[;|&<>`$]", bare), f"SKILL.md command has shell operators: {cmd[:80]}")

hj = ROOT / "hooks" / "hooks.json"
if check(hj.exists(), "missing hooks/hooks.json"):
    try:
        h = json.loads(hj.read_text(encoding="utf-8"))
        cmds = [x["command"] for e in h["hooks"]["PreToolUse"] for x in e["hooks"]]
        check(all("${CLAUDE_PLUGIN_ROOT}/hooks/approve_scripts.py" in c for c in cmds), "hooks.json command path")
        check((ROOT / "hooks" / "approve_scripts.py").exists(), "missing hooks/approve_scripts.py")
        print("hooks: OK", [e["matcher"] for e in h["hooks"]["PreToolUse"]])
    except (ValueError, KeyError) as e:
        check(False, f"hooks.json invalid: {e}")

for py in sorted((SKILL / "scripts").glob("*.py")):
    try:
        compile(py.read_text(encoding="utf-8"), str(py), "exec")  # in memory: writes no .pyc
    except SyntaxError as e:
        problems.append(f"{py.name} does not compile: {e}")

for fx in ("coffee-buggy/index.html", "fixes.json", "edge-cases/expected.json", "scenario-shop/expected.json"):
    check((SKILL / "fixtures" / fx).exists(), f"missing fixture {fx}")

stray = [str(p.relative_to(ROOT)) for p in ROOT.rglob("*")
         if p.name in ("__pycache__", ".DS_Store") or p.suffix == ".pyc"]
check(not stray, f"stray files in tree: {stray[:5]}")

print("\nCHECK_PLUGIN:", "OK" if not problems else "PROBLEMS")
for p in problems:
    print("  -", p)
sys.exit(1 if problems else 0)
