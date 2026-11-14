#!/usr/bin/env bash
# Preserve npm's report AND process status; only the explicit policy may accept findings.
set -euo pipefail
ROOT=$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)
if [[ $# -ne 1 ]]; then
  printf 'usage: audit-frontend.sh OUTPUT_DIRECTORY\n' >&2
  exit 2
fi
OUTPUT=${1:?usage: audit-frontend.sh OUTPUT_DIRECTORY}
mkdir -p "$OUTPUT"
OUTPUT=$(cd "$OUTPUT" && pwd)
cd "$ROOT/frontend"
# Inventory totals do not prove coverage: include wins over inherited omit settings.
# Pin the public advisory authority and exit threshold, not caller npm configuration.
if npm audit --package-lock-only --json --include=dev --include=optional --include=peer \
  --registry=https://registry.npmjs.org/ --audit-level=low \
  > "$OUTPUT/npm-audit.json" 2> "$OUTPUT/npm-audit.stderr"; then
  status=0
else
  status=$?
fi
printf '%s\n' "$status" > "$OUTPUT/npm-audit.exit"
printf 'Raw npm audit (exit %s), not suppressed:\n' "$status"
cat "$OUTPUT/npm-audit.json"
cat "$OUTPUT/npm-audit.stderr" >&2
cd "$ROOT"
python scripts/check_frontend_audit.py --report "$OUTPUT/npm-audit.json" --npm-exit "$status" \
  2>&1 | tee "$OUTPUT/policy-result.log"
