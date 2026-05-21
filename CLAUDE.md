# CLAUDE.md — Project Instructions

## Testing Requirements

- Every issue must have automated test coverage for all its acceptance criteria before the PR is merged.
- Tests must be written as part of the implementation, not as a separate follow-up step.
- If an AC is a manual/infrastructure step (e.g., "create an OAuth app"), document it in the test file as a skipped test or comment explaining why it's not automatable.
- Backend tests: `backend/tests/` using pytest (in-memory SQLite via conftest fixtures).
- Frontend tests: `frontend/e2e/` using Playwright for integration/e2e flows.
- Run backend tests: `cd backend && python -m pytest`
- Run frontend tests: `cd frontend && npx playwright test`
- CI runs both backend tests and frontend lint/build on every PR.

## Code Quality

- Never return raw exception messages (`str(e)`) in API responses — use generic error messages.
- Sanitize user input at system boundaries; trust internal code.
- No unused imports, variables, or dead code.
- Keep PRs focused — one issue per PR (or, for parallel-execution releases, one PR per integration branch — see Release Model).

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
