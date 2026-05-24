#!/usr/bin/env bash
# check-playwright-tags.sh — Quality v1 Wave 2 (#270)
#
# Enforces the @smoke / @e2e tagging convention from PRD #261 R6.
# Every test.describe(...) and test(...) call in frontend/e2e/*.spec.{js,jsx}
# (excluding *.prod.spec.* — those run under playwright.prod.config.js) must
# carry @smoke and/or @e2e in its title string. The title may live on the
# same line as the call opening or on the following line (multi-line form).
#
# Exit 0  — every test/describe in scope is tagged.
# Exit 1  — at least one untagged call; offending file:line pairs printed to
#           stderr.
#
# Run locally:
#   cd frontend && bash scripts/check-playwright-tags.sh
#
# Pure bash + grep + awk; no node deps. Mirrors the read-only-stdout, exit-code
# discipline of backend/scripts/check_tdd_red.py (#269).

set -euo pipefail

# Resolve the e2e directory relative to this script so the script works whether
# invoked from frontend/ or repo root.
script_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
e2e_dir="${script_dir}/../e2e"

if [[ ! -d "${e2e_dir}" ]]; then
  echo "check-playwright-tags: e2e directory not found at ${e2e_dir}" >&2
  exit 2
fi

shopt -s nullglob
specs=("${e2e_dir}"/*.spec.js "${e2e_dir}"/*.spec.jsx)
shopt -u nullglob

# Track total scanned / failed for a concise summary.
total_files=0
failed_files=0
declare -a offenses=()

for spec in "${specs[@]}"; do
  base="$(basename "${spec}")"
  # *.prod.spec.* files run under a separate config (playwright.prod.config.js)
  # and are exempt from the tag convention (PRD #261 R6 — Worker C contract).
  case "${base}" in
    *.prod.spec.js|*.prod.spec.jsx)
      continue
      ;;
  esac

  total_files=$((total_files + 1))

  # awk scans the file once and emits "<lineno>" for each TOP-LEVEL (unindented,
  # column-zero) test.describe(...) or test(...) call whose first string-literal
  # argument lacks @smoke and @e2e in the TITLE STRING only.
  #
  # Why top-level only:
  # - Playwright concatenates parent-describe + nested-describe + test titles
  #   when matching --grep, so tagging the top-level wrapper propagates to
  #   every nested test. Enforcing tags on the outermost calls is enough.
  # - Most e2e specs have ONE top-level `test.describe('…', …)` at column 0;
  #   some (scanner-education, settings-objectives, stats-grouped-display) have
  #   multiple — each must be tagged independently.
  # - Bare `test('…', …)` calls at column 0 (storybook.spec.js post-skip-wrap)
  #   also count.
  #
  # Title-only check (CodeRabbit triage on PR #300): we MUST NOT count a tag
  # that appears in a trailing comment or elsewhere outside the title string
  # literal. We isolate the first '...' or "..." string literal after the
  # opening `(`, looking on the opening line first and then the next line
  # (multi-line title form), and check ONLY that string for the tag.
  #
  # We match call openings at word boundaries to avoid stray substring hits.
  # `test.describe.skip(` / `test.only(` etc. count too.
  bad_lines=$(awk '
    function has_tag(s) {
      return (index(s, "@smoke") > 0 || index(s, "@e2e") > 0)
    }
    # Extract the first single- or double-quoted string literal in s and
    # return its inner content. Returns "" if none found.
    function extract_title(s,    m, rest, q, end) {
      # Find the first single or double quote.
      m = match(s, /[\x27"]/)
      if (m == 0) return ""
      q = substr(s, RSTART, 1)
      rest = substr(s, RSTART + 1)
      end = index(rest, q)
      if (end == 0) return ""
      return substr(rest, 1, end - 1)
    }
    {
      lines[NR] = $0
    }
    END {
      for (i = 1; i <= NR; i++) {
        line = lines[i]
        # Top-level only: line must start with "test" (no leading whitespace).
        if (line !~ /^test(\.describe)?(\.only|\.skip|\.fixme|\.serial|\.parallel)?[[:space:]]*\(/) continue
        # Skip the no-op test.describe.configure(...) — a config call, not a
        # test wrapper.
        if (line ~ /^test\.describe\.configure[[:space:]]*\(/) continue
        # Strip everything up to and including the first "(" so extract_title
        # ignores any quotes that might appear inside the callee path (none
        # exist today, but be defensive).
        paren = index(line, "(")
        after = (paren > 0) ? substr(line, paren + 1) : line
        title = extract_title(after)
        # Multi-line title form: title literal lives on the next line.
        if (title == "" && i < NR) {
          title = extract_title(lines[i + 1])
        }
        if (!has_tag(title)) {
          print i
        }
      }
    }
  ' "${spec}") || bad_lines=""

  if [[ -n "${bad_lines}" ]]; then
    failed_files=$((failed_files + 1))
    while IFS= read -r ln; do
      [[ -z "${ln}" ]] && continue
      offenses+=("${spec}:${ln}: test() or test.describe() title missing @smoke or @e2e tag")
    done <<< "${bad_lines}"
  fi
done

if (( failed_files > 0 )); then
  echo "check-playwright-tags: ${failed_files}/${total_files} spec file(s) have untagged test/describe calls." >&2
  echo "Required: each test() or test.describe() title must contain @smoke and/or @e2e (see CLAUDE.md ## Testing Requirements)." >&2
  for line in "${offenses[@]}"; do
    echo "${line}" >&2
  done
  exit 1
fi

echo "check-playwright-tags: OK — ${total_files} spec file(s) tagged."
exit 0
