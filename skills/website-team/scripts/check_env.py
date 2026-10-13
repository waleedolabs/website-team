#!/usr/bin/env python3
"""Check that the test environment works. Exit 0 = ready. Prints exact setup steps otherwise."""
import json
import sys
from pathlib import Path

try:
    VERSION = json.loads((Path(__file__).resolve().parents[3] / ".claude-plugin" / "plugin.json").read_text(encoding="utf-8"))["version"]
except (OSError, ValueError, KeyError, IndexError):
    VERSION = "unknown"

steps = []
try:
    from playwright.sync_api import sync_playwright
except ImportError:
    print("NOT READY: Python package 'playwright' is missing.")
    print("Setup:  pip install playwright   (add --break-system-packages if pip refuses)")
    print("Then:   python3 -m playwright install chromium")
    sys.exit(1)

try:
    with sync_playwright() as p:
        b = p.chromium.launch()
        pg = b.new_page()
        pg.set_content("<p id=x>ok</p>")
        assert pg.inner_text("#x") == "ok"
        b.close()
except Exception as e:
    print(f"NOT READY: Chromium could not start: {type(e).__name__}: {str(e).splitlines()[0][:200]}")
    print("Setup:  python3 -m playwright install chromium")
    print("Linux may also need:  python3 -m playwright install-deps chromium")
    sys.exit(1)

print(f"READY: website-team {VERSION}; Python {sys.version.split()[0]} + Playwright + Chromium work.")
