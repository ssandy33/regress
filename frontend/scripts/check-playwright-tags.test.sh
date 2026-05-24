#!/usr/bin/env bash
# check-playwright-tags.test.sh — smoke tests for the tag-check script (#270).
#
# Runs five fixtures in a temp dir and asserts the script's exit code matches
# expectation. Tests written as part of the implementation per CLAUDE.md
# "Testing Requirements" (Quality v1 R7).
#
#   1. smoke_only_pass    — describe tagged @smoke → exit 0
#   2. e2e_only_pass      — describe tagged @e2e → exit 0
#   3. both_pass          — describe tagged @smoke @e2e → exit 0
#   4. neither_fail       — describe missing both tags → exit 1
#   5. prod_spec_skipped  — *.prod.spec.js missing tags is OK → exit 0
#
# Run:
#   cd frontend && bash scripts/check-playwright-tags.test.sh

set -euo pipefail

script_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
script_under_test="${script_dir}/check-playwright-tags.sh"

if [[ ! -x "${script_under_test}" ]]; then
  echo "test: ${script_under_test} is not executable" >&2
  exit 2
fi

pass_count=0
fail_count=0

# run_case <name> <expected_exit> — sets up a tmp frontend/scripts + frontend/e2e
# layout, copies the script-under-test into ./scripts, writes the fixture(s)
# into ./e2e/<provided name(s)>, runs the script, asserts the exit code.
run_case() {
  local name="$1"
  local expected="$2"
  shift 2
  # Remaining args are pairs: fixture_filename, fixture_contents.
  local tmp
  tmp="$(mktemp -d)"
  mkdir -p "${tmp}/scripts" "${tmp}/e2e"
  cp "${script_under_test}" "${tmp}/scripts/check-playwright-tags.sh"
  chmod +x "${tmp}/scripts/check-playwright-tags.sh"

  while (($# >= 2)); do
    printf '%s' "$2" > "${tmp}/e2e/$1"
    shift 2
  done

  local actual=0
  bash "${tmp}/scripts/check-playwright-tags.sh" >/dev/null 2>&1 || actual=$?

  if [[ "${actual}" == "${expected}" ]]; then
    echo "  PASS: ${name} (exit ${actual})"
    pass_count=$((pass_count + 1))
  else
    echo "  FAIL: ${name} — expected exit ${expected}, got ${actual}" >&2
    fail_count=$((fail_count + 1))
  fi
  rm -rf "${tmp}"
}

echo "check-playwright-tags.test.sh — running fixtures..."

run_case "smoke_only_pass" 0 "demo.spec.js" "$(cat <<'EOF'
import { test, expect } from '@playwright/test';
test.describe('Demo flow @smoke', () => {
  test('renders', async ({ page }) => {});
});
EOF
)"

run_case "e2e_only_pass" 0 "demo.spec.js" "$(cat <<'EOF'
import { test, expect } from '@playwright/test';
test.describe('Demo flow @e2e', () => {
  test('renders', async ({ page }) => {});
});
EOF
)"

run_case "both_pass" 0 "demo.spec.js" "$(cat <<'EOF'
import { test, expect } from '@playwright/test';
test.describe('Demo flow @smoke @e2e', () => {
  test('renders', async ({ page }) => {});
});
EOF
)"

run_case "neither_fail" 1 "demo.spec.js" "$(cat <<'EOF'
import { test, expect } from '@playwright/test';
test.describe('Demo flow (no tags)', () => {
  test('renders', async ({ page }) => {});
});
EOF
)"

run_case "prod_spec_skipped" 0 "demo.prod.spec.js" "$(cat <<'EOF'
import { test, expect } from '@playwright/test';
test.describe('Prod-only flow with no tags is fine', () => {
  test('renders', async ({ page }) => {});
});
EOF
)"

# Multi-line describe call — title is on the next line; the tag still counts.
run_case "multiline_title_pass" 0 "demo.spec.js" "$(cat <<'EOF'
import { test, expect } from '@playwright/test';
test.describe(
  'Multi-line title @smoke @e2e',
  () => {
    test('renders', async ({ page }) => {});
  }
);
EOF
)"

# Bare test() (no describe) — must also be tagged.
run_case "bare_test_tagged_pass" 0 "demo.spec.js" "$(cat <<'EOF'
import { test, expect } from '@playwright/test';
test('bare test @e2e', async ({ page }) => {});
EOF
)"

run_case "bare_test_untagged_fail" 1 "demo.spec.js" "$(cat <<'EOF'
import { test, expect } from '@playwright/test';
test('bare test no tags', async ({ page }) => {});
EOF
)"

# Regression fixture for CodeRabbit triage on PR #300:
# A tag injected via a comment after the title must NOT count — only the
# title string literal counts.
run_case "comment_tag_should_not_count_fail" 1 "demo.spec.js" "$(cat <<'EOF'
import { test, expect } from '@playwright/test';
test.describe('Demo flow no tags', // @e2e
  () => {
    test('renders', async ({ page }) => {});
  }
);
EOF
)"

echo
echo "Results: ${pass_count} passed, ${fail_count} failed"

if (( fail_count > 0 )); then
  exit 1
fi
exit 0
