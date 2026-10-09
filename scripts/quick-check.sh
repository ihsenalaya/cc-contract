#!/usr/bin/env bash
set -euo pipefail
task_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$task_root"
export PYTHONPATH="$task_root/src"
python3 -m compileall -q src scripts tests
python3 -m unittest discover -s tests/unit
python3 -m cc_contract.cli selftest >/dev/null
python3 scripts/release-guard.py
for script in scripts/*.sh; do bash -n "$script"; done
for file in experiments/*.json results/manifests/*.json kubernetes/local/*.json; do
  [ ! -f "$file" ] || python3 -m json.tool "$file" >/dev/null
done
