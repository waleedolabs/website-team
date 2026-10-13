#!/usr/bin/env bash
# Run a hook script with the first working Python 3, silently doing nothing if there is none
# (the hook then simply makes no decision and Claude Code asks as usual).
# - Windows: `python3` is often the Microsoft Store stub, which fails without output; it is
#   skipped by the probe, then `python` / `py -3` (python.org installs) are tried.
# - Git Bash passes /c/... paths; Windows python needs C:\... (cygpath -w).
# - PYTHONUTF8=1: Windows Python otherwise reads/writes text as cp125x.
export PYTHONUTF8=1
if command -v cygpath >/dev/null 2>&1; then
    conv=()
    for a in "$@"; do
        case "$a" in /*) conv+=("$(cygpath -w "$a")") ;; *) conv+=("$a") ;; esac
    done
    set -- "${conv[@]}"
fi
for cmd in "python3" "python" "py -3"; do
    # shellcheck disable=SC2086
    if $cmd -c "import sys; sys.exit(0 if sys.version_info[0] == 3 else 1)" >/dev/null 2>&1; then
        # shellcheck disable=SC2086
        exec $cmd "$@"
    fi
done
exit 0
