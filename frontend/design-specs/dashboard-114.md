# Design Spec: Unified Dashboard (default landing route)

- **Issue:** [#114 — Add a unified Dashboard as the default landing route](https://github.com/ssandy33/regress/issues/114)
- **Date:** 2026-05-05
- **Author:** Designer agent
- **Status:** Draft — for user review before implementation
- **Scope:** Frontend visual + structural spec only. No code, no PR, no issue comment yet.

---

## 1. Overview

A new `/dashboard` route becomes the default landing page after auth and answers the question: **"What should I pay attention to today?"** It surfaces the user's current portfolio context, expiration pressure, data-source health, and recent activity in a single screen, replacing the current behavior where the app dumps users into the Analysis research view with no portfolio framing.

The design follows the teardown's principle of **decision density with progressive disclosure**: each card surfaces the *next decision* (a strike to manage, a stale connection to fix, a position to roll) as a one-line summary, with click-throughs into the existing detail tools (Journal, Options scanner, Settings, Analysis) for evidence. The dashboard is read-mostly — actions live on the destination pages.

Design language matches the existing dark-mode slate palette already established in `Header`, `JournalPage`, `SettingsPage`, and `OptionScannerPage`. No new visual vocabulary is introduced.

---

## 2. Information hierarchy (1440×900 desktop, above the fold)

Above the fold (top ~720px of content area, below the 56px Header):

1. **Status strip** — single row of four pill-style health indicators (Schwab, FRED, cache freshness, journal). High signal, low height (~48px). Lets the user dismiss or act on infrastructure problems before reading numbers that might be stale.
2. **Portfolio summary KPI row** — four StatCard tiles (Open positions, Notional value, Open option legs, Unrealized P/L). Anchors the page in "what do I own."
3. **Decision row** — two cards side-by-side at equal width:
   - **Upcoming expirations** (left, primary) — sorted by DTE, with a visual emphasis band on items ≤ 7 DTE. This is the highest-action surface in v0; it is *the* reason a user opens the dashboard.
   - **Open option legs** (right) — flat list of open puts/calls. Lower-action than expirations but provides the wider context.

Below the fold:

4. **Positions table** — open stock + option positions from the journal. Larger surface, supports horizontal scan.
5. **Recent activity** — last 5–10 events (saved sessions, scanner runs, journal trade entries) in a compact timeline-style list.
6. **Data-source readiness panel (detail)** — only renders if the status strip surfaced any non-green item; otherwise hidden to save vertical space.

This ordering places the two questions a wheel-strategy operator asks first ("am I about to be assigned?" and "what do I own right now?") above the fold. The Recent activity card is intentionally pushed below — it's diary-style, not decisional.

---

## 3. Visual mock — populated state (1440×900)

```
┌──────────────────────────────────────────────────────────────────────────────────────────────┐
│  Regression Analysis Tool                              Options  Journal  ⚙  ?  ☾             │  ← existing Header (h-14)
├──────────────────────────────────────────────────────────────────────────────────────────────┤
│  Dashboard                                                                  Last sync 09:42  │  ← page title row
├──────────────────────────────────────────────────────────────────────────────────────────────┤
│  ● Schwab Connected   ● FRED Connected   ● Cache Fresh (3 stale)   ● Journal 4 positions     │  ← status strip
├──────────────────────────────────────────────────────────────────────────────────────────────┤
│  ┌──── Open Positions ────┐ ┌──── Notional ────┐ ┌──── Open Legs ────┐ ┌──── Unrealized ────┐│
│  │                        │ │                  │ │                   │ │                    ││
│  │       4                │ │     $48,210      │ │        7          │ │      +$612         ││
│  │  3 stock · 1 cash      │ │  +2.1% from cost │ │  4 puts · 3 calls │ │   +1.3% on basis   ││
│  └────────────────────────┘ └──────────────────┘ └───────────────────┘ └────────────────────┘│
├──────────────────────────────────────────────────────────────────────────────────────────────┤
│  ┌── Upcoming expirations (next 14d) ──────┐  ┌── Open option legs ────────────────────────┐│
│  │                                          │  │                                            ││
│  │  ⚠  AAPL 175 P    Fri 05/08    3 DTE    │  │  AAPL  175 P   05/08   3d   ITM by $0.42  ││
│  │     ITM by $0.42  ·  Roll or assign      │  │  TSLA  240 C   05/15   10d  OTM by 4.1%   ││
│  │  ─────────────────────────────────────   │  │  NVDA  920 P   05/22   17d  OTM by 1.8%   ││
│  │  ⚠  TSLA 240 C    Fri 05/15    10 DTE   │  │  AMD   165 C   06/05   31d  OTM by 6.2%   ││
│  │     OTM 4.1%  ·  Watch                   │  │  …                                        ││
│  │  ─────────────────────────────────────   │  │                                            ││
│  │     NVDA 920 P    Fri 05/22    17 DTE   │  │  Showing 7 of 7 open legs                  ││
│  │     OTM 1.8%  ·  Hold                    │  │  → View all in Options                    ││
│  │                                          │  │                                            ││
│  │  → Manage in Journal                     │  │                                            ││
│  └──────────────────────────────────────────┘  └────────────────────────────────────────────┘│
├──────────────────────────────────────────────────────────────────────────────────────────────┤
│  ┌── Positions ────────────────────────────────────────────────────────────────────────────┐│
│  │  Ticker   Shares   Adj. Basis    Current      Notional      P/L         Open Legs       ││
│  │  AAPL     100      $172.40       $175.42      $17,542       +$302       1                ││
│  │  TSLA     50       $235.10       $238.80      $11,940       +$185       1                ││
│  │  NVDA     —        cash-secured  —            $9,200        —           1 put            ││
│  │  AMD      75       $158.20       $162.35      $12,176       +$311       1                ││
│  │                                                                                          ││
│  │  → Open Journal                                                                          ││
│  └──────────────────────────────────────────────────────────────────────────────────────────┘│
├──────────────────────────────────────────────────────────────────────────────────────────────┤
│  ┌── Recent activity ──────────────────────────────────────────────────────────────────────┐│
│  │  09:42  Schwab import completed — 3 trades added                                         ││
│  │  09:18  Scanned AAPL — 12 strikes, top return 2.4%                                       ││
│  │  yest   Saved regression session "AAPL vs DGS10 5y"                                      ││
│  │  yest   Closed trade: AAPL 170P @ $0.32 (50% target hit)                                 ││
│  │  2d     New position: NVDA cash-secured put cycle                                        ││
│  └──────────────────────────────────────────────────────────────────────────────────────────┘│
└──────────────────────────────────────────────────────────────────────────────────────────────┘
```

**Column widths (12-col grid, page max-width `max-w-7xl mx-auto px-6`):**

| Section | Cols | Notes |
|---|---|---|
| Status strip | 12 | One row, four equal-width pills |
| KPI row | 12 (4 × 3) | Each KPI is 3 cols, `grid-cols-4 gap-4` |
| Decision row | 12 (7 + 5) | Expirations 7 cols, Open legs 5 cols. Asymmetric to give the higher-stakes card more room. Or 6 + 6 — see open question Q3. |
| Positions | 12 | Full-width table |
| Recent activity | 12 | Full-width list |

---

## 4. Visual mock — empty state (no Schwab, no journal, no FRED key)

```
┌──────────────────────────────────────────────────────────────────────────────────────────────┐
│  Regression Analysis Tool                              Options  Journal  ⚙  ?  ☾             │
├──────────────────────────────────────────────────────────────────────────────────────────────┤
│  Dashboard                                                                                    │
├──────────────────────────────────────────────────────────────────────────────────────────────┤
│  ● Schwab Not connected   ● FRED Not configured   ● Cache Empty   ● Journal 0 positions      │
├──────────────────────────────────────────────────────────────────────────────────────────────┤
│  ┌────────────────────────────────────────────────────────────────────────────────────────┐ │
│  │                                                                                          │ │
│  │                     Welcome to Regress                                                   │ │
│  │                     Set up the basics so the dashboard can show your portfolio.          │ │
│  │                                                                                          │ │
│  │   ┌─────────────────────────┐  ┌─────────────────────────┐  ┌──────────────────────┐    │ │
│  │   │  1. Connect Schwab      │  │  2. Add a FRED API key  │  │  3. Import positions │    │ │
│  │   │  Live prices, option    │  │  Macro context for      │  │  Or add a position   │    │ │
│  │   │  chains, trade import.  │  │  regression analysis.   │  │  manually.           │    │ │
│  │   │                         │  │                         │  │                      │    │ │
│  │   │  → Open Settings        │  │  → Open Settings        │  │  → Open Journal      │    │ │
│  │   └─────────────────────────┘  └─────────────────────────┘  └──────────────────────┘    │ │
│  │                                                                                          │ │
│  └────────────────────────────────────────────────────────────────────────────────────────┘ │
├──────────────────────────────────────────────────────────────────────────────────────────────┤
│  ┌── Recent activity ──────────────────────────────────────────────────────────────────────┐│
│  │  No activity yet — saved sessions, imports, and trades will appear here.                 ││
│  └──────────────────────────────────────────────────────────────────────────────────────────┘│
└──────────────────────────────────────────────────────────────────────────────────────────────┘
```

When **partially configured** (e.g. Schwab connected but no positions imported), the per-card empty states render inline rather than collapsing to one onboarding panel. The all-empty consolidated panel only renders if Schwab is unconnected AND no positions exist AND no FRED key is set, on the assumption that this is a brand-new install and the three setup CTAs are the only sensible action.

---

## 5. Per-card specs

Each card is a `bg-white dark:bg-slate-800 border border-slate-200 dark:border-slate-700 rounded-xl` (matches existing convention from `PositionsTable`, `TradeHistory`, `StrikeTable`). Padding `p-4` to `p-6` depending on density. Card header: `text-lg font-semibold text-slate-900 dark:text-white` with optional small descriptor in `text-xs text-slate-500 dark:text-slate-400`.

### 5.1 Positions card

**Purpose:** "What do I own right now?" — open stock and cash-secured-put cycles from the journal.

**Data shape (per row):**
```ts
{
  id: string,
  ticker: string,
  shares: number | null,           // null for pure CSP cycles
  strategy: 'wheel' | 'cc' | 'csp' | 'stock',
  adjusted_cost_basis: number | null,
  current_price: number | null,    // from Schwab; null if disconnected
  notional: number,                // shares × current_price OR strike × 100 for CSP collateral
  unrealized_pl: number | null,    // (current_price - adjusted_basis) × shares; null if no current_price
  open_legs_count: number,
}
```

**Sort order:** Notional value descending. The user wants their largest exposure first. Tiebreaker: ticker A→Z.

**Row layout:** Reuses the `PositionsTable` column pattern from `frontend/components/journal/PositionsTable.jsx` but with a different column set tailored to the dashboard:

| Ticker | Shares | Adj. Basis | Current | Notional | Unrealized P/L | Open Legs |

- Ticker: bold, `text-slate-900 dark:text-white`
- Numeric columns: right-aligned, `text-slate-700 dark:text-slate-300`
- P/L: green if ≥ 0 (`text-green-600 dark:text-green-400`), red if < 0 (`text-red-600 dark:text-red-400`) — matches the convention in `CompareStats` and `RiskRewardPanel`
- For CSP-only positions (no shares), render `—` in Shares and `cash-secured` in Adj. Basis
- Row click navigates to `/journal?position=<id>` (selecting that position in the existing Journal page)

**Empty state:** "No positions yet. Import from Schwab or add one manually." Two link buttons: `Import from Schwab` → `/journal` with import modal opened, `Add manually` → `/journal` with new-position form opened.

**Loading state:** 3 shimmer rows using the same `animate-pulse` skeleton pattern from `PositionsTable` (already established).

**Stale state:** If `current_price` is null because Schwab is disconnected, the Current and Notional columns show `—` and a yellow `?` icon-tooltip on the column header reads "Live prices unavailable — Schwab disconnected." No banner inside the card; the global status strip already covers the connection issue.

**Actions:** Row click → Journal. Card footer link "→ Open Journal" → `/journal`.

### 5.2 Open option legs card

**Purpose:** Flat list of every open put/call across all positions. Differs from "Upcoming expirations" in that it shows *all* open legs regardless of DTE — a fuller inventory view.

**Data shape (per row):**
```ts
{
  id: string,
  ticker: string,
  type: 'put' | 'call',
  strike: number,
  expiration: string,        // ISO date
  dte: number,
  moneyness: {
    state: 'ITM' | 'OTM' | 'ATM',
    distance_pct: number,    // signed, ITM negative for puts, etc.
    distance_dollars: number,
  } | null,                  // null if current_price unavailable
  position_id: string,
}
```

**Sort order:** DTE ascending (soonest expiring first). Within the same DTE, ticker A→Z.

**Row layout:** Compact single-line rows, monospace-feel for alignment but using normal font:
```
TICKER   STRIKE TYPE   EXP        DTE   MONEYNESS
AAPL     175 P         05/08      3d    ITM by $0.42
```

- Ticker: bold
- Type: `P` shown in `text-orange-600` style pill, `C` in `text-blue-600` style — or just plain text with letter (open question Q4)
- DTE: small badge: `≤ 7d` red bg, `≤ 14d` yellow bg, `> 14d` neutral (matches the freshness color pattern in `SettingsPage`)
- Moneyness: text-only summary, color-coded (red for ITM puts/calls about to be assigned, neutral for OTM)

**Empty state:** "No open option legs." If positions exist but no options: "Your stock-only positions don't have open options. Use the Options scanner to find candidate strikes." with a `→ Open Options` link.

**Loading state:** 4 shimmer rows.

**Actions:** Row click → `/journal?position=<position_id>` (jumps to that position's trade history). Card footer link "→ View all in Options" → `/options`.

**Note:** This card overlaps with the Upcoming expirations card on items ≤ 14 DTE. That's intentional — the Expirations card is filtered/sorted for *action*, this card is the full inventory.

### 5.3 Upcoming expirations card

**Purpose:** Items in the next 14 days that may need a management decision. The single highest-action surface on the dashboard.

**Data shape:** Subset of "Open option legs" filtered to `dte <= 14`, with an additional decision tag:
```ts
{
  // ... same fields as open option legs
  decision_tag: 'roll-or-assign' | 'watch' | 'hold' | 'manage',
  decision_reason: string,    // human-readable, e.g. "ITM by $0.42"
}
```

**Decision tag heuristic (v0, simple):**
- `dte <= 7` AND ITM → **roll-or-assign** (red emphasis)
- `dte <= 7` AND OTM → **manage** (yellow emphasis)
- `dte <= 14` AND ITM → **watch** (yellow emphasis)
- otherwise → **hold** (neutral)

(See open question Q5 — this heuristic should be confirmed by the user. AC just says "highlighting items that need a management decision (≤ 7 DTE)" without specifying the criterion beyond DTE.)

**Sort order:** DTE ascending; within same DTE, ITM before OTM.

**Row layout:** Larger row than the Open legs card, two-line per item:
```
⚠  AAPL 175 P    Fri 05/08    3 DTE
   ITM by $0.42  ·  Roll or assign
─────────────────────────────────
```

- Leading icon: `⚠` for `roll-or-assign` (red), `●` for `watch` (yellow), no icon for `hold`
- Line 1: ticker + strike + type + day-of-week + date + DTE badge
- Line 2: smaller, the decision reason in muted text + the decision tag in a colored pill

**Empty state:** "Nothing expiring in the next 14 days." Shown only when the user has open legs but none in the window. If no open legs at all, hide this card entirely below the fold (decision row collapses to single column with Open Legs taking 12 cols).

**Loading state:** 3 two-line shimmer rows.

**Actions:** Row click → `/journal?position=<position_id>`. Card footer link "→ Manage in Journal" → `/journal`.

### 5.4 Data-source readiness card

**Purpose:** Schwab + FRED + cache freshness in one place, sourced from existing endpoints. **Not duplicated business logic** — it composes the same data already used by `SettingsPage`.

**Two surfaces:**
1. **Status strip** at the top of the page — always visible, single row, four pills.
2. **Detail card** below the fold — only renders if any item is non-green.

**Data shape:** Composed from existing API endpoints:
```ts
{
  schwab: { configured: boolean, valid: boolean, expires_at: string | null },     // from checkSchwabHealth
  fred: { configured: boolean, valid: boolean },                                   // from checkFredHealth
  sources: { yfinance: {...}, fred: {...}, zillow: {...} },                        // from checkSourceHealth
  cache: { fresh: number, stale: number, very_stale: number, total: number },     // from getCacheFreshness, aggregated
  journal: { positions_count: number },                                            // from listPositions
}
```

**Status strip pill format (reusing `OptionScanner` banner pattern):**
- Green dot + "Schwab Connected" or red dot + "Schwab Not connected"
- Green dot + "FRED Connected" or yellow + "Key set, validation failed" or red + "Not configured"
- Green dot + "Cache Fresh" or yellow + "Cache stale (N items)" or red + "Cache very stale (N items)"
- Neutral + "Journal N positions" (info-only, never a problem state)

Each pill click navigates to the relevant Settings section (`/settings` deep-linked via hash, e.g. `/settings#schwab`).

**Detail card:** Only renders when at least one of Schwab/FRED/cache is non-green. Shows the same row treatment as the existing `SettingsPage` "Data Source Status" section (bullet + label + status text), plus a "Refresh stale data" button that calls `refreshStaleCache` from the existing client. This is identical to what's already in Settings — the dashboard surfaces it inline so the user doesn't have to navigate.

**Empty state (all healthy):** Detail card is hidden entirely. Status strip shows all-green.

**Loading state:** Status strip pills render as gray skeletons. Detail card not shown until data resolves.

**Actions:** Pill click → Settings deep-link. "Refresh stale" button in detail card → calls existing `refreshStaleCache`, shows toast on completion (matches `SettingsPage` pattern).

### 5.5 Recent activity card

**Purpose:** Diary-style log of the last few things that happened. Low-priority context, lives below the fold. AC says "whichever data is cheapest to surface in v0" — leaning into that.

**Data shape:** Union list of three event types:
```ts
type Activity =
  | { kind: 'session_saved', timestamp: string, session_name: string, session_id: string }
  | { kind: 'scanner_run',   timestamp: string, ticker: string, strikes_count: number }
  | { kind: 'trade_added',   timestamp: string, ticker: string, trade_type: string, position_id: string }
  | { kind: 'import',        timestamp: string, count: number };
```

**v0 source:** Saved sessions are already persisted (`/api/sessions`), trades are persisted (`/api/journal/trades`). Scanner runs are *not* currently persisted. For v0, recommend showing only saved sessions + recent trades, deferring scanner-run logging to a follow-up (see open question Q6 and the out-of-scope recap).

**Sort order:** Timestamp descending. Show the last 5–10 events.

**Row layout:** Single-line, time-prefixed:
```
09:42  Schwab import completed — 3 trades added
09:18  Saved regression session "AAPL vs DGS10 5y"
yest   Closed trade: AAPL 170P @ $0.32 (50% target hit)
```

- Time column: fixed width, monospace-feel (`font-mono` or `tabular-nums`), muted
- Description: `text-slate-700 dark:text-slate-300`, with the noun highlighted (`font-medium`)

Time formatting: same-day → `HH:MM`, yesterday → `yest`, older → `Md Mdd` (e.g. `May 03`). Reuse `formatDate` from `frontend/utils/formatters` if it covers this; otherwise add a `formatRelativeTime` helper.

**Empty state:** "No activity yet — saved sessions, imports, and trades will appear here." (See empty-state mock above.)

**Loading state:** 5 shimmer rows.

**Actions:** Row click navigates contextually:
- session_saved → `/` with session loaded (`?session=<id>`)
- scanner_run → `/options?ticker=<ticker>` (only if we add scanner persistence)
- trade_added → `/journal?position=<position_id>`
- import → `/journal`

Card footer link: none in v0 (there's no full activity page).

---

## 6. Component inventory — reuse vs. new

### Reuse (already exist; no changes needed)

| Component | Path | Used for |
|---|---|---|
| Header (top nav) | `frontend/components/layout/Header.jsx` | Top of page; needs a new `Dashboard` link added (see implementation note) |
| OfflineBanner | `frontend/components/layout/OfflineBanner.jsx` | Stays at top of page when all sources are unreachable |
| LoadingSkeleton (concept) | `frontend/components/layout/LoadingSkeleton.jsx` | Cards extend its `animate-pulse` shimmer-row pattern; the existing skeleton is page-level, so we'll use the *pattern* not the component itself |
| StatCard pattern | inlined in `frontend/components/results/StatsPanel.jsx` (`StatCard` function) | The KPI row reuses this exact card shape (rounded-lg, label + value, optional tooltip) |
| Status banner pattern | inlined in `frontend/components/options/OptionScanner.jsx` (Schwab status banner) | Status strip pills and the detail card reuse the colored-border + dot + text vocabulary |
| StatusBadge pattern | inlined in `frontend/components/journal/PositionsTable.jsx` | Pills inside cards (e.g., decision_tag pills, ITM/OTM badges) reuse this `inline-block px-2 py-0.5 text-xs rounded-full` recipe |
| Freshness color helper | `freshnessColor(...)` in `frontend/components/settings/SettingsPage.jsx` | Cache pill in the status strip |
| `formatDate`, `formatNumber` | `frontend/utils/formatters.js` | Used throughout |
| API client functions | `frontend/api/client.js` (`listPositions`, `checkSchwabHealth`, `checkFredHealth`, `getCacheFreshness`, `listSessions`) | Composed into the `/api/dashboard` backend response per the AC |

### Hoist into shared (used inline today; promote to `components/common/` so dashboard + existing pages share)

These are duplicated patterns rather than imported components. The dashboard is the right time to extract them:

| Pattern | Today | Extract to |
|---|---|---|
| Card shell | `bg-white dark:bg-slate-800 border border-slate-200 dark:border-slate-700 rounded-xl` repeated in 8+ places | `components/common/Card.jsx` — `<Card title="" description="" footer={...}>{children}</Card>` |
| StatCard | inline in `StatsPanel.jsx` | `components/common/StatCard.jsx` |
| Status pill (dot + label) | inline in `OptionScanner.jsx`, `SettingsPage.jsx` | `components/common/StatusPill.jsx` |
| Empty state block | inline in `page.jsx` (Analysis), `OptionScanner.jsx`, `PositionsTable.jsx` | `components/common/EmptyState.jsx` — `<EmptyState icon={...} title="" description="" cta={...} />` |

If extraction is too much scope for this issue, the alternative is to **inline the patterns inside the new dashboard components** (matching the existing convention of inlining), and file a follow-up issue to consolidate. The user should choose — see open question Q1.

### Net-new components (under `frontend/components/dashboard/`)

| Component | Purpose | Props (sketch) |
|---|---|---|
| `DashboardPage.jsx` | Top-level page; orchestrates the data fetch and lays out the cards | none — uses `useDashboard()` hook |
| `StatusStrip.jsx` | The four-pill status row at the top | `{ schwab, fred, cache, journal }` |
| `KpiRow.jsx` | The four-tile portfolio summary row | `{ openPositions, notional, openLegs, unrealizedPl }` |
| `UpcomingExpirationsCard.jsx` | Decision-row left card | `{ items, loading }` |
| `OpenLegsCard.jsx` | Decision-row right card | `{ legs, loading }` |
| `DashboardPositionsCard.jsx` | Below-fold positions table (lighter than the full Journal table) | `{ positions, loading }` |
| `RecentActivityCard.jsx` | Below-fold activity list | `{ events, loading }` |
| `DataReadinessDetail.jsx` | Conditional below-fold detail panel | `{ schwab, fred, cache }` — only renders if non-green |
| `OnboardingPanel.jsx` | Empty-state full-bleed onboarding shown when nothing is configured | none — three hard-coded CTAs |

### New hook

`frontend/hooks/useDashboard.js` — single hook that calls `GET /api/dashboard`, returns `{ data, loading, error, refetch }`. Per the AC, this is one round-trip; the backend composes from existing services.

### New route file

`frontend/app/dashboard/page.jsx` — thin shell that renders `<DashboardPage />`.

### Default-route redirect

`frontend/middleware.js` already exists. The redirect logic for authenticated `/` → `/dashboard` belongs there. Unauthenticated users continue to hit the auth flow (no change). The current `/` (Analysis) page is *not* deleted — it stays at `/analysis` (this rename is a small but real change; flag it as a decision in Q2).

---

## 7. Header / navigation update

The current Header (`frontend/components/layout/Header.jsx`) has three explicit links: Options, Journal, Settings (gear), Help (?). The Dashboard route needs a nav entry.

Recommendation: add `Dashboard` as the **first** link in the right cluster, and rename the `Regression Analysis Tool` brand link from pointing to `/` (which now redirects to `/dashboard`) to pointing to `/dashboard` explicitly. The brand link semantics stay the same — clicking the brand goes home — and home is now the dashboard.

The Analysis page becomes accessible via:
- A new `Analysis` link in the Header (replaces the implicit "click brand to go home" behavior)
- Or kept as the implicit landing for power users who type `/analysis` directly
(See open question Q2.)

---

## 8. Responsive behavior

Issue says desktop-first for v0. Out-of-scope: mobile-optimized layout.

Sensible breakpoints:

- **≥ 1280px (desktop, primary target):** Layout as drawn — 4-col KPI row, asymmetric 7+5 (or 6+6) decision row, full-width tables.
- **1024–1279px (small desktop / large tablet):** 4-col KPI row stays. Decision row stacks vertically (Expirations on top, Open legs below). Positions table scrolls horizontally if needed.
- **< 1024px:** Not optimized for v0. Minimum supported width: **1024px**. Below that, content becomes single-column and tables horizontal-scroll, but no claim of polish.

Tailwind breakpoint usage: `md:grid-cols-4` for KPI row, `lg:grid-cols-12` for the decision row's 7+5 split. Below `lg`, fall back to `grid-cols-1` for the decision row.

The status strip pills wrap with `flex-wrap` if they don't fit on one line.

---

## 9. Backend contract (informs the frontend, but spec'd in the issue's backend AC)

The frontend expects one round-trip to `GET /api/dashboard` returning:

```ts
{
  generated_at: string,                       // ISO timestamp; drives "Last sync 09:42"
  status: {
    schwab:  { configured: boolean, valid: boolean, expires_at: string | null },
    fred:    { configured: boolean, valid: boolean },
    cache:   { fresh: number, stale: number, very_stale: number, total: number },
    journal: { positions_count: number },
  },
  kpis: {
    open_positions: number,
    open_positions_breakdown: { stock: number, csp: number, cc: number, wheel: number },
    notional_value: number,
    notional_change_pct: number | null,       // vs cost basis
    open_legs: number,
    open_legs_breakdown: { puts: number, calls: number },
    unrealized_pl: number | null,
    unrealized_pl_pct: number | null,
  },
  positions: Array<{ /* see 5.1 */ }>,
  open_legs: Array<{ /* see 5.2 */ }>,
  upcoming_expirations: Array<{ /* see 5.3 */ }>,
  recent_activity: Array<{ /* see 5.5 */ }>,
  data_meta: {                                // standard freshness wrapper, like result.data_meta in Analysis
    is_stale: boolean,
    fetched_at: string,
    sources_unavailable: string[],            // e.g. ['schwab'] when prices missing
  },
}
```

Frontend renders the `is_stale` flag using the same yellow `StaleBanner` pattern from `app/page.jsx`.

---

## 10. Implementation order (for the Developer agent, when the user approves)

1. Backend `/api/dashboard` endpoint composing from existing services. Tests first (empty, populated, Schwab disconnected, stale cache).
2. `useDashboard` hook + `getDashboard` in `api/client.js`.
3. `app/dashboard/page.jsx` shell.
4. Status strip + KPI row (highest visual return for least effort; lets us validate the page wiring early).
5. Cards in this order: Positions → Open legs → Upcoming expirations → Recent activity → Data readiness detail.
6. Empty state / Onboarding panel.
7. Header nav update + middleware redirect from `/` to `/dashboard`.
8. Playwright e2e: default-route redirect, populated state, empty state, disconnected Schwab indicator (per AC).

Suggested commit boundaries: backend endpoint + tests = PR 1, frontend cards + e2e = PR 2. Or all-in-one if the reviewer prefers a single landed feature. (PR boundary is a developer-side call — not a design decision.)

---

## 11. Open questions (resolve before implementation)

| # | Question | Default if unresolved |
|---|---|---|
| Q1 | Extract shared `Card`, `StatCard`, `StatusPill`, `EmptyState` into `components/common/` as part of this issue, or inline patterns and file a follow-up cleanup? | Inline now, follow-up later. Keeps PR scope tight; matches existing convention. |
| Q2 | Does the current Analysis page move to `/analysis` and get its own header link, or stay reachable only by typing `/`? | Move to `/analysis` and add a header link. Discoverability matters more than a clean URL. |
| Q3 | Decision row column split: asymmetric 7+5 (emphasizes Expirations) or symmetric 6+6? | 7+5. Expirations is the primary action surface; emphasis is intentional. |
| Q4 | Put/call indicator: colored letter pill (`P` orange, `C` blue) or plain text? | Plain text in the Open legs card; colored leading icon (⚠/●) only on the Expirations card to avoid visual noise. |
| Q5 | Decision tag heuristic for the Expirations card. The AC only says "≤ 7 DTE highlighted." Does my proposed `roll-or-assign` / `manage` / `watch` / `hold` mapping match intent, or just one binary "needs attention" badge? | Use my four-tag heuristic. Wheel-strategy operators care about ITM/OTM-at-expiry; binary is too coarse. |
| Q6 | Recent activity in v0: include scanner runs (which aren't currently persisted, requires a new logging hook) or only sessions + trades (already persisted)? | Sessions + trades + Schwab imports only. Defer scanner-run logging to a follow-up issue. |
| Q7 | Positions card: include unrealized P/L column, or notional only? AC says "current notional and unrealized P/L if available." If Schwab is disconnected, P/L is null — show the column with `—` or hide it conditionally? | Show the column always; render `—` when null. Consistency over conditional layout. |
| Q8 | "Last sync HH:MM" timestamp in the page title row — does it show `data_meta.fetched_at`, or `now()` when the page rendered? | `data_meta.fetched_at` — the user wants to know data age, not page age. |

---

## 12. Out-of-scope recap (per issue #114)

To keep this design aligned with the issue scope and prevent feature creep:

- ❌ Live price tickers / websocket updates (StatCards and Notional column are static-on-load)
- ❌ Wheel-cycle summary cards (waiting on the cycle-state-machine issue)
- ❌ Alerts integration (separate roadmap item)
- ❌ Watchlist card (separate roadmap item)
- ❌ Mobile-optimized layout (desktop-first; min 1024px is the floor)
- ❌ Configurable card order or drag-to-rearrange
- ❌ A dedicated "Activity" full-page log (Recent activity card is a snippet, no "View all" target in v0)
- ❌ Scanner-run persistence (deferred per Q6 unless the user reverses)

If the user requests any of these inline, they should be filed as new issues that depend on #114, not folded into this one.
