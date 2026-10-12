#!/usr/bin/env bash
# Benchmark the loop on a real project. Usage: dev/bench.sh SCRIPTS_DIR SITE_DIR LABEL
# Measures: one full test run, init (baseline), add-check with 3 scenarios, one 'try' of a no-op design change.
set -u
S=$1; SRC=$2; L=$3
W=$(mktemp -d); cp -r "$SRC" "$W/site"
t() { local s=$(date +%s.%N); "$@" > "$W/last.out" 2>&1; local rc=$?; local e=$(date +%s.%N); printf "%-34s %6.1f s  (exit %s) %s\n" "$L $NAME" "$(echo "$e - $s" | bc)" "$rc" "$(head -1 "$W/last.out" | cut -c1-90)"; }
NAME="one full run";        t python3 "$S/run_tests.py" "$W/site" --quiet --out "$W/r.json"
NAME="init (baseline)";     t python3 "$S/verify_fix.py" init --site "$W/site" --work "$W/work"
for i in 1 2 3; do echo "{\"id\": \"bench-$i\", \"page\": \"index.html\", \"desc\": \"bench $i\", \"steps\": [], \"expect\": [{\"visible\": \"body\"}]}" > "$W/sc$i.json"; done
NAME="add-check 3 scenarios"; t python3 "$S/verify_fix.py" add-check --site "$W/site" --work "$W/work" --scenario "$W/sc1.json" "$W/sc2.json" "$W/sc3.json"
F=$(cd "$W/site" && ls *.css | head -1)
echo "{\"title\": \"bench no-op\", \"kind\": \"design\", \"ops\": [{\"op\": \"write\", \"file\": \"bench-note.txt\", \"text\": \"x\"}]}" > "$W/p.json"
NAME="try 1 design proposal"; t python3 "$S/verify_fix.py" try --site "$W/site" --work "$W/work" --proposal "$W/p.json"
rm -rf "$W"
