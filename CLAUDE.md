# CLAUDE.md — Project Instructions

## Testing Requirements

Test methodology and pyramid are governed by [PRD #261 — Quality v1: TDD Adoption + Test Pyramid](https://github.com/ssandy33/regress/discussions/261). PRD #261 is the historical *why*; this section is the operational *what*.

- Every issue must have automated test coverage for all its acceptance criteria before the PR is merged.
- Tests must be written as part of the implementation, not as a separate follow-up step.
- If an AC is a manual/infrastructure step (e.g., "create an OAuth app"), document it in the test file as a skipped test or comment explaining why it's not automatable.

### Test pyramid (R1)

| Layer | Runner | Definition | Speed budget |
|---|---|---|---|
| **Unit** | pytest + `@pytest.mark.unit` | A single function or class in isolation. No FastAPI app, no `TestClient`, no DB session, no network. | < 1s/test; suite < 30s |
| **Integration** | pytest + `@pytest.mark.integration` | Full backend stack: FastAPI `TestClient` + in-memory SQLite (`conftest.py` fixture) + routers + services + ORM. | < 2s/test; suite < 2min |
| **E2E** | Playwright (`frontend/e2e/*.spec.js`) | Real browser + a running app. Frontend is the system under test. | < 30s/test; suite < 10min |

Frontend has no unit / integration tier in v1 — Playwright is the only frontend test runner.

### Per-AC test spread (R2)

Every AC defaults to:

- **0–1 E2E** test (one if the AC is a rendered user flow; zero if backend-only).
- **1–3 integration** tests (always ≥1 — proves wiring).
- **3–10 unit** tests (branches, edge cases, error paths).

Deviations are explicit and justified in the plan file's Test List, not silent.

### File-naming + marker convention (R3)

**Backend** — marker is the source of truth; filename is a hint:

| Layer | Filename hint | Marker |
|---|---|---|
| Unit | `test_<module>.py` | `@pytest.mark.unit` |
| Integration | `test_<router>_router.py` or `test_<feature>_integration.py` | `@pytest.mark.integration` |
| In-flight Red | any | `@pytest.mark.tdd_red` |

Markers are registered in `backend/pytest.ini` with `--strict-markers`. A test missing a classifier marker fails `backend/scripts/classify_tests.py --check` (CI step in `backend-unit`).

**Frontend** — specs live in `frontend/e2e/<feature>.spec.js`; tagging via `@smoke` and/or `@e2e` in `test.describe()` / `test()` titles (see *Playwright tagging* below).

### Pragmatic TDD rhythm (R4)

Adopt the up-front-Test-List flavor, NOT strict one-cycle-per-assertion Beck-style TDD:

1. **Test List** — enumerate test cases in the plan file before any implementation.
2. **Write the tests** in their target layer (Red — they fail because impl doesn't exist).
3. **Implement** the smallest change that turns the tests Green.
4. **Refactor** without changing behavior; tests stay Green.

### tdd_red marker discipline (R4/R5)

In-flight Red tests carry `@pytest.mark.tdd_red`. The default pytest invocation (`pytest`, `pytest -m unit`, etc.) excludes them — `addopts` in `pytest.ini` sets `-m "not tdd_red"`. Run `pytest -m tdd_red` to exercise them explicitly during development.

**The PR merge gate (`tdd_red_gate` step in CI `backend-unit` job) fails if any `@pytest.mark.tdd_red` decorator or `pytestmark = pytest.mark.tdd_red` line survives in a PR's changed `.py` files.** A Red test must either be deleted or converted to passing before merge. Local check: `python -m scripts.check_tdd_red --diff-base origin/main`.

### Playwright tagging — @smoke / @e2e (R6)

Every `frontend/e2e/*.spec.js` carries `@smoke` and/or `@e2e` in its top-level `test.describe()` title (or each `test()` title for spec files without a top-level describe).

- **`@smoke`** — critical-path subset; runs first in CI; failure short-circuits the e2e run.
- **`@e2e`** — broader E2E set; runs after smoke passes.
- A test may carry both (e.g., `'Dashboard renders @smoke @e2e'`).

CI step `playwright_tag_check` (in `frontend-playwright` job) fails if any spec has neither tag. Run locally: `cd frontend && bash scripts/check-playwright-tags.sh`. Two npm scripts: `npm run test:smoke` and `npm run test:e2e:tags`.

`.prod.spec.js` files (run under `playwright.prod.config.js`) are exempt — they're excluded by the default Playwright config.

### Test List section requirement (R7)

Every plan file (`<spec>-plan.md`) includes a `## Test List` section enumerating each test by name + layer + AC. The planner-architect or CTO rejects plans without it.

### Where these rules apply

These rules govern **new tests on new issues**. The Quality v1 Wave 1 tagging pass (#266) classified the existing 63 backend test files; it did NOT rewrite them. Existing tests are correctly classified; they were not refactored to fit the new layer definitions retroactively.

- Backend tests live in `backend/tests/` (pytest, in-memory SQLite via conftest).
- Frontend tests live in `frontend/e2e/` (Playwright; `npx playwright test`).
- Run backend tests: `cd backend && python -m pytest`.
- Run frontend tests: `cd frontend && npm run test:e2e` (all), `npm run test:smoke` (smoke only).
- CI runs the three-job matrix on every PR: `backend-unit` (with classifier + tdd_red gate), `backend-integration`, `frontend-playwright` (with tag check + smoke-then-e2e).

### Lessons learned from the Wave 3 pilot (#271 / #160)

Quality v1's pragmatic-TDD methodology was piloted on #160 (per-trade entry-rule compliance tagging) during Wave 3. This subsection captures the lessons. PRD #261's R4 (pragmatic TDD) and R7 (Test List requirement) remain canonical; this is empirical refinement, not replacement.

**What worked**

- **Locking the Test List in the plan file before implementation surfaced the #157 OKR-engine dependency on day one.** The KR-5 integration AC ("OKR engine queries `trade_entry_compliance`...") was structurally deferrable to #157 because the OKR engine does not exist yet. Recording it in the Test List as "deferred to #157" instead of trying to stub it kept the pilot focused on the producer side — and is exactly the dependency-mismatch surfacing R7 promises.
- **Locking the failed_rules vocabulary in the plan file before writing tests OR code paid off immediately.** The eight string literals (`dte_too_low`, `delta_too_high`, `delta_unknown`, etc.) appear in the test file, the evaluator, and the snapshot — having one canonical list in the plan meant the tests were not driven by the implementation's choices, and a typo would have been caught at test-write time rather than at refactor time.
- **The Red phase was visible in the git log without ceremonial overhead.** Two Red commits (one for the unit Test List, one for the integration Test List) followed by their respective Green commits gave a 4-commit + 1-refactor + 1-docs cadence that reads as TDD without forcing one-test-per-commit micro-stepping.
- **The integration-test failure on the rolling-window endpoint caught a real date-arithmetic bug in the TEST, not the impl.** The original test pinned `opened_at = "2026-01-15"`, which by today's date (2026-05-23) was outside the rolling 30-day window. The endpoint correctly filtered it out and the test failed with `total == 0`. Without the integration test exercising the real date filter, the impl would have shipped fine — but the test would have been silently wrong. The Red phase paid for itself there.

**What was awkward**

- **The Red→Green cycle for the schema layer was so tight (model doesn't exist → add it → schema test passes) that splitting the test commit from the impl commit felt slightly ceremonial.** The methodology proof is the Test List existing in the plan + the lessons-learned retrospective, not the commit count — the plan's "acceptable shortcut" (R4 pragmatic TDD: combine schema Red+Green when the cycle is tight) is the right call. I kept them separate this time because the pilot's deliverable was the visible Red→Green rhythm, but for normal issues I'd collapse the schema pair.
- **The "snapshot non-retroactivity" AC has a stronger DB-layer enforcement (PK on `trade_id`) than the evaluator-layer behavior the unit test exercised.** The unit test verified that re-running the pure evaluator with different rules produces a different snapshot — which is true, but it doesn't actually exercise the protection against overwriting an existing row. That guarantee lives at the SQLAlchemy PK level (a second insert on the same `trade_id` raises `IntegrityError`). The test list flagged this as covered by `test_trade_entry_compliance_unique_per_trade`; in retrospect a more explicit "record then re-record must raise" integration test would have been a better choice. Not blocking; calling it out for the next pilot.
- **Lazy import inside `create_trade` to break a circular dependency between `services/journal.py` and `services/entry_compliance.py` (which itself imports `models/schemas.py` for the response type).** Acceptable workaround; the cleaner fix would be to move the response model the evaluator returns OUT of `schemas.py` (since it's not actually a route response) but that's a larger refactor that wasn't worth the methodology-noise. Noted as known tech debt.

**Concrete refinements for the next implementer**

- **When a Test List entry depends on an unbuilt sibling (like #157 here), record it as "deferred to <issue>" in the Test List itself — do not satisfy it with a stub.** A stub OKR engine would have been ~80 LOC of throwaway code, would have grown its own tests, and would have shipped the wrong API surface. The deferral is honest and the PR retrospective surfaces it; the consumer issue will close the loop.
- **For config-driven evaluators, the failed_rules vocabulary (or equivalent string-literal enum) is the place where the AC and the code converge. Lock the vocabulary in the plan file before writing tests OR code — both reference the same strings, drift dies, and the snapshot-vs-reference invariant (the AC that the snapshot is non-retroactive) becomes obvious because the snapshot literally embeds the vocabulary.**
- **When an integration test depends on "now()" semantics (rolling windows, expirations, freshness), parameterize the timestamp from `datetime.now(timezone.utc)` rather than pinning ISO literals.** Cuts the "test passed in May, mysteriously failed in August" class of bugs entirely. The same lesson applied to the seeded `opened_at` in the rolling-window test; the fix was a one-line `(datetime.now(timezone.utc) - timedelta(days=2)).isoformat()` substitution.
- **Save the "pragmatic-TDD acceptable shortcut" (Red+Green in one commit) for the cases where the Red phase is structurally a one-liner (e.g. importing a class that does not yet exist). For evaluator/router pairs where the implementation has real branching, keep them separate — the Red commit lets future readers reconstruct what the test was asserting before the impl colored their reading.**

**Cross-references**

- Pilot issue: #271
- Pilot feature: #160
- Anchor PRD: #261
- Deferred sibling: #157 (OKR engine — the KR-5 consumer)
- Failed-rules vocabulary lock: `backend/app/services/entry_compliance.py` (search for `dte_too_low` to find the canonical list)

## Code Quality

- Never return raw exception messages (`str(e)`) in API responses — use generic error messages.
- Sanitize user input at system boundaries; trust internal code.
- No unused imports, variables, or dead code.
- Keep PRs focused — one issue per PR (or, for parallel-execution releases, one PR per integration branch — see Release Model).

## Observability

All new logging code MUST follow the conventions in [ADR Discussion #292](https://github.com/ssandy33/regress/discussions/292):

- **Event names** — `<noun>.<lifecycle_phase>` (e.g., `refresh_job.complete`) or single `<noun>` (e.g., `provider_call`). snake_case, dot-separated, 1–3 segments.
- **Structured fields via `extra={}`** — canonical vocabulary: `event`, `request_id`, `outcome`, `duration_ms`, `error_class`, `ticker`, `position_id`, `data_class`, `provider`, `endpoint`, `status_code`, `latency_ms`, `cache_hit`. Use these field names exactly — don't invent local variants.
- **Lifecycle events** always carry `outcome` (`success` / `failed` / `throttled` / `no_data` / `degraded`); `.complete` and `.failed` always carry `duration_ms`.
- **Sanitization** (hard): never log raw upstream API response bodies, Schwab/Axiom tokens, encryption keys, user secrets, or full request bodies for authenticated endpoints. See #292 for the full NEVER / OK lists.
- **Phase 5 reviewers** check observability conformance during code review, alongside the no-raw-exception-messages and test-coverage checks.

## API Contract

The full API-contract architecture is specified in [**PRD #262 — Contract v1: OpenAPI as Source of Truth**](https://github.com/ssandy33/regress/discussions/262) — committed `openapi.json` snapshot artifact, CI drift detection, Schemathesis contract tests, and `openapi-typescript` frontend type generation. Contract v1 lands as a Platform-lane milestone (#28); first-wave issues are filed just-in-time when the milestone activates.

While Contract v1 is in draft, the following interim disciplines apply to all new endpoints:

- **`response_model` is required on every route** — `@router.get("/path", response_model=SomeSchema)`. This is the minimum-viable contract discipline; PRD #262 builds on this with Schemathesis + drift detection when it activates.
- **Pydantic model location** — define new response shapes in `backend/app/models/schemas.py` under the appropriate `# --- <domain> ---` section divider. No inline orphan models on routes.
- **Stability tiers** — every endpoint is **Internal** (UI-only, ships in lockstep, no deprecation cycle) unless explicitly promoted to **Public**. All endpoints are Internal today; reserve `/api/v1/...` for future Public per PRD #262's authoring direction.
- **Phase 5 reviewers** check API-contract conformance during code review (every new endpoint has `response_model` + every new response shape is in `schemas.py`).

## Issue Management

- When creating an issue, determine its priority (critical, high, medium, low) and add a comment explaining the rationale for the chosen priority level.
- Issues are filed just-in-time, derived from PRDs at planning time. Don't pre-file speculative issues.
- A milestone is a release anchored to a PRD or a coherent theme, not the PRD itself.

## SDLC Pipeline

Work flows through a phased pipeline. Each phase has an owner agent and a deliverable.

| Phase | Owner agent | Deliverable | When mandatory |
|---|---|---|---|
| **1 — Issue** | `feature-writer` | GitHub issue with priority + rationale comment | Always (per Issue Management above) |
| **1.5 — Design** | `designer` | Spec + HTML mock at `frontend/design-specs/issue-{N}-*.{md,mock.html}` | Always for rendered-UI work; skip only for pure-backend or trivial display-bug hotfixes |
| **2 — Plan** | `planner-architect` (or `cto` for architecture/refinement passes) | Implementation plan at `<spec-name>-plan.md` co-located with the design spec | For non-trivial work; trivial issues may go straight to implementation |
| **3 — Implement** | `implementer` (multi-language) or `senior-python-dev` (Python-focused) | Code + tests in a single PR | Always |
| **5 — Code review** | `finapp-code-reviewer` | Read-only review comments | Recommended for high-risk or large changes |
| **5.5 — CodeRabbit triage** | `finapp-code-reviewer` or the orchestrator | Fetch CodeRabbit PR comments after CI-green; filter aggressively (fix / defer / reject each) | Always between CI-green and merge |
| **6 — Release** | `release-manager` | Tag, GitHub release, milestone close, wiki Roadmap + Changelog sync | On release-worthy merges |

## Artifacts & Source Control

- **Design specs** (`frontend/design-specs/issue-{N}-*.md` + `-mock.html`) — local working artifacts, NOT committed to git. They reference each other and the plan file but live untracked in the working tree.
- **Implementation plans** (`<spec>-plan.md`, co-located with the spec) — also untracked.
- **PRDs / ADRs** — live ONLY as GitHub Discussions. Never as local files. Migrate any existing local requirement file into a Discussion and delete the file.
- **Wiki** (Roadmap + Changelog) — `release-manager` owns updates on release. No other agent edits the wiki.

## Release Model

- **Per-release integration branch:** `feat/v1.X.Y` off `main`. All worker sub-branches merge back into the integration branch; **no per-worker PRs to main**.
- **Single PR per release:** the integration branch is the only PR to `main`. Body cites every closed issue + the multi-worker DAG (if parallel).
- **Squash-merge with multi-issue close:** GitHub's `closes #N #M` keyword in a multi-issue squash commit auto-closes only ONE issue. Close the stragglers manually with an audit-trail comment of the form: `Closed by PR #X, shipped in vY.Z.W: <release URL>`.
- **Post-merge:** `release-manager` tags the version, publishes the GitHub release, closes the milestone, updates wiki Roadmap + Changelog. Release notes lead with user-visible changes; surface any `[CHAIN-UNVERIFIED]` or post-tag gates prominently.
- **Worktree cleanup:** run `git worktree remove -f -f <path>` after each worker's sub-branch merges. Locked worktrees pin branches and block interactive `git checkout`.

## Versioning

Versioning model — including the MAJOR/MINOR/PATCH bump table, why Platform-lane methodology shifts don't burn major bumps, and the post-`v2.0.0` migration plan — is the [Roadmap wiki's Versioning section](https://github.com/ssandy33/regress/wiki/Roadmap#versioning). That page is the source of truth; this file points at it so the version model stays in one place.

## Parallel Execution (for multi-issue releases with disjoint surfaces)

When a release has 3+ issues that touch disjoint files (or disjoint line ranges in shared files), fan out workers in parallel for ~50-90 min wall-clock vs ~3-4h serial.

1. **Designer wave** — all `needs-design` issues' designers run in parallel (independent design specs).
2. **V1 contract freeze** — single source of truth in the plan file, pins everything workers will reference by name:
   - Test IDs (frozen strings — `data-testid` and `data-*` attributes)
   - Schema field names + Literal values
   - Color/token recipes for new visual states
   - Endpoint URLs + request/response shapes
   - Sort field names, localStorage keys, route paths
3. **Worker DAG** — each worker gets a branch off the integration branch in a separate worktree. File ownership disjoint by design (or by line range when sharing a file, with append-only rules below).
4. **Conventions:**
   - **Append-only test edits** when multiple workers touch shared test files — append new tests at EOF; do not modify existing tests. If an existing test must change to accommodate the new behavior, a single "bridge edit" is acceptable and must be called out explicitly in the worker report.
   - **Schema + producer in one commit** — don't expose a new Literal value (e.g. `coverage="partial"`) in the API surface without the backend code that emits it in the same commit.
   - **No new dependencies without justification** — roll-your-own when a small component (popover, collapse, etc.) is the lighter pattern.
5. **Merge order** matches the DAG. Smoke-test the integration branch after each wave merges.
6. **Pre-flight verifications** (when applicable) — e.g. live API capture to verify an unverified field shape. Gates the worker fan-out. If pre-flight fails, ship with an explicit `[CHAIN-UNVERIFIED]` tag in the PR body and a post-tag verification step in the release notes.

## Memory Conventions

- Agent memory lives in `<repo>/.claude/agent-memory/<agent-name>/` (project-scope) and `~/.claude/agent-memory/<agent-name>/` (user-scope). Release-manager and other phase agents auto-load project-scope memory; user-scope is for personal preferences that shouldn't be committed.
- Each memory file is one fact with frontmatter (`name`, `description`, `metadata.type`). The agent's `MEMORY.md` index has one-line pointers; the index is what's loaded into context each session.
- Memories that become project policy belong in this file (CLAUDE.md), not in agent-memory.
