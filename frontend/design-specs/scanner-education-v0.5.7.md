# Design Spec: Options Scanner — learning surface (Phase A)

- **Issue:** [#190 — Options Scanner: turn results table into a learning surface (Phase A)](https://github.com/ssandy33/regress/issues/190)
- **Milestone:** V0.5.7
- **Date:** 2026-05-13
- **Author:** Designer agent
- **Status:** Draft — for user review before implementation
- **Scope:** Frontend visual + structural spec for the four Phase A affordances (primer, header tooltips, per-row expansion, humanized rejected list) plus the backend `human_reasons` field shape. Phase B items (risk panel, earnings context, comparison-layer education, beginner toggle, scenario sparkline) are explicitly **out of scope** — they ship as separate follow-ups after Phase A.
- **Non-goals:** no AI narration (that is #181 on the Recovery surface), no new pricing math, no new option-chain endpoints.

---

## 0. Why now

The scanner is functionally complete for the primary operator. Phase A adds four deterministic education affordances that widen the audience (less-experienced wheel users, future-self after a break) without lowering the ceiling for the experienced operator — the dense table stays dense, education layers in via hover, click, and a single collapsible block.

The four affordances are deliberately **decorative**: each one can be ignored by an experienced user and the underlying table still does its job. The primer collapses; tooltips are hover-only; the row expansion already exists for Greeks/Metrics today (Phase A enriches it, doesn't introduce it); the rejected list is already collapsed-by-default behind a `<details>` element. None of these are gated dialogs or required reading.

---

## 1. Page anatomy after Phase A (desktop, ≥ lg)

```
┌──────────────────────────────────────────────────────────────────────────────────┐
│ App Header (existing)                                                             │
├─────────────┬────────────────────────────────────────────────────────────────────┤
│             │  Schwab API: Connected (existing banner)                            │
│  ChainFilt. │                                                                     │
│  (existing  │  ┌─[ NEW: Strategy primer card — collapsed by default ]─────────┐  │
│   sidebar)  │  │ ▸  What is a Covered Call?            Learn (3 paragraphs)   │  │
│             │  └─────────────────────────────────────────────────────────────┘  │
│             │                                                                     │
│             │  F — Covered Call Scan       Price $13.26          3 opportunities │
│             │  (existing market context card)                                     │
│             │                                                                     │
│             │  Capital Deployment (existing, unchanged)                           │
│             │                                                                     │
│             │  ┌─ Strike table (existing) ───────────────────────────────────┐   │
│             │  │ □  #  Strike  Exp   DTE ⓘ  Bid/Ask  Δ ⓘ  OI ⓘ  Prem ⓘ ... │   │
│             │  │ ▸  1  $14.00  6/20   38     0.30/.. 0.22 1,240  $0.30 ... │   │
│             │  │ ▾  2  $15.00  6/20   38     ...                            │   │
│             │  │      ┌─[ EXPANDED, NEW: Trade explanation block ]──────┐   │   │
│             │  │      │ Greeks   │ Metrics    │ Rule Compliance         │   │   │
│             │  │      │  (today) │  (today)   │  (today)                │   │   │
│             │  │      ├──────────┴────────────┴─────────────────────────┤   │   │
│             │  │      │ What this trade commits you to                  │   │   │
│             │  │      │   Obligation:  100 sh × $15.00 = $1,500         │   │   │
│             │  │      │   Premium:     $0.30 × 100      = $30 up front  │   │   │
│             │  │      │   Break-even:  $13.26 − $0.30   = $12.96        │   │   │
│             │  │      │                                                 │   │   │
│             │  │      │ Three ways this can end                         │   │   │
│             │  │      │   • Called away at $15 → keep $30 + $174 gain   │   │   │
│             │  │      │   • Expired worthless → keep $30, still hold sh │   │   │
│             │  │      │   • Closed early at 50% → keep ~$15, free shares│   │   │
│             │  │      └─────────────────────────────────────────────────┘   │   │
│             │  └─────────────────────────────────────────────────────────────┘   │
│             │                                                                     │
│             │  RiskRewardPanel (existing, unchanged)                              │
│             │                                                                     │
│             │  ▸ Rejected strikes (50) — UPDATED rendering                        │
│             │      $99.00 6/20 · Strike sits 645% above your $13.26 basis, but   │
│             │                    the 10% rule only allows up to 1% above.        │
│             │      $20.00 6/20 · Delta 0.42 is outside your 0.15–0.35 range —    │
│             │                    too close to the money, higher assignment risk. │
│             │      $13.50 6/20 · No buyers showing a bid right now (zero_bid).   │
│             │                                                                     │
└─────────────┴────────────────────────────────────────────────────────────────────┘
```

Nothing moves. Three blocks are added (primer, per-row "What this trade commits you to" sub-section, humanized rejection lines) and one is added inline (`ⓘ` icons on numeric headers). The order of the page is unchanged.

---

## 2. Affordance 1 — Strategy primer

### 2.1 Placement and behavior

| Aspect | Decision | Rationale |
|---|---|---|
| Position | **Top of main pane**, above the market-context header card | Education before context. Putting it above the header keeps the page's narrative linear (learn → see this scan → see strikes → see rejections). A side-rail would compete with `ChainFilters`. A modal-on-first-visit was rejected — modals interrupt; this is decoration the user can ignore. |
| Default state | **Collapsed**, with a one-line teaser visible (`What is a Covered Call?  Learn ▸`) | Experienced operator sees a single thin row; less-experienced user has an obvious entry point. |
| Persistence | `localStorage` key `scanner.primer.<strategy>.dismissed = boolean` | Per-strategy because the CC and CSP primers are different content; dismissing one doesn't dismiss the other. Persists across reloads, scoped to the browser. |
| Reset path | A "Show primers" link in the footer of `ChainFilters` (next to Reset) clears both keys | Reset of filters and reset of dismissed-state are conceptually adjacent; one place to undo "I learned this, hide it". |
| Reactivity to strategy toggle | **Yes — re-reads on strategy change** | When the user flips Covered Call → Cash-Secured Put in `ChainFilters`, the primer body swaps. If the user has dismissed CC but not CSP, the CSP primer expands on first view of that strategy and then can be dismissed independently. |

### 2.2 Content shape (collapsed)

```
┌────────────────────────────────────────────────────────────────────────────┐
│  ▸  What is a Covered Call?              Learn ▸          [ × hide ]       │
└────────────────────────────────────────────────────────────────────────────┘
```

### 2.3 Content shape (expanded)

Plain prose with a short bulleted "what can go wrong" block. No sub-sections, no images, no diagrams — this is decoration, not a course.

```
┌────────────────────────────────────────────────────────────────────────────┐
│  ▾  What is a Covered Call?                                  [ × hide ]    │
│                                                                            │
│   You own 100 shares of a stock and sell someone the right to buy them    │
│   from you at a higher strike price before a chosen expiration date.      │
│   You collect a premium up front in exchange for capping your upside.     │
│                                                                            │
│   The 10% rule: this scanner only shows strikes at least your             │
│   "Min Call Distance %" above your cost basis (default 10%). The idea     │
│   is that if you're called away, you still book a meaningful gain on the  │
│   stock on top of the premium. Strikes closer than that are filtered      │
│   into "Rejected Strikes" below the table.                                 │
│                                                                            │
│   What can go wrong:                                                       │
│     • If the stock rips through the strike, you miss the upside above it. │
│     • If the stock drops, the premium softens but doesn't cancel the loss. │
│     • If earnings land inside the trade window, IV crush + price gap can  │
│       move the position faster than usual.                                 │
└────────────────────────────────────────────────────────────────────────────┘
```

The CSP variant differs in body copy (sell-a-put obligation, collateral instead of shares, assignment risk if stock drops below strike). Implementer fills in the exact copy.

### 2.4 Component contract

```
<StrategyPrimer
  strategy="covered_call" | "cash_secured_put"
  dismissed={boolean}             // from localStorage
  onToggleDismissed={() => void}
  data-testid="strategy-primer"
/>
  └ inner toggle button: data-testid="strategy-primer-toggle"
  └ hide button:         data-testid="strategy-primer-hide"
  └ body region:         data-testid="strategy-primer-body" (only when expanded)
```

Content lives in a small constant inside the component file:

```js
const PRIMER_CONTENT = {
  covered_call: { title: "What is a Covered Call?", paragraphs: [...], risks: [...] },
  cash_secured_put: { title: "What is a Cash-Secured Put?", paragraphs: [...], risks: [...] },
};
```

No backend involvement. No props beyond strategy + dismissed.

### 2.5 Visual tokens

| Token | Value |
|---|---|
| Card shell | `bg-white dark:bg-slate-800 border border-slate-200 dark:border-slate-700 rounded-xl` |
| Header padding | `px-4 py-3` |
| Body padding | `px-4 pb-4` |
| Title | `text-sm font-medium text-slate-700 dark:text-slate-200` |
| Body prose | `text-sm text-slate-600 dark:text-slate-400 leading-relaxed` |
| Risk bullets | same as body, `list-disc pl-5 space-y-1` |
| Hide-button | `text-xs text-slate-400 hover:text-slate-600 dark:hover:text-slate-300` |

Same shell vocabulary as the existing market-context and capital-utilization cards — slots in without visual novelty.

### 2.6 Mobile (< sm, 640px)

`ChainFilters` is already a drawer on mobile. Primer card spans full width above the market context card, same internal structure. No layout change beyond that.

### 2.7 Empty / edge

- **No strategy selected** is not reachable — `ChainFilters` defaults to `covered_call`. If `strategy` is somehow `null`, render a generic "Pick a strategy in the sidebar to see what it does" one-liner; no expand control.
- **Pre-scan state** (no `result` yet): primer still renders. It does not depend on scan data. This is a feature: a new user can read the primer before scanning.

---

## 3. Affordance 2 — Column-header tooltips

### 3.1 Trigger pattern

| Surface | Behavior |
|---|---|
| Desktop hover | Reveals tooltip after ~150ms hover on the `ⓘ` icon OR anywhere on the header cell. |
| Keyboard | `ⓘ` is a `<button type="button">` inside the `<th>`, so it is naturally focusable. Tab to the icon → tooltip opens. `Escape` closes it. Tooltip is `role="tooltip"` and `aria-describedby` wires to the icon. |
| Touch | Tap on `ⓘ` opens; tap outside closes. (No long-press — discoverability is poor.) |

**Decision: small `ⓘ` icon next to the label, not hover-anywhere-on-the-header.** Reason: the header cell is already a sort affordance (`onClick` toggles sort). Conflating "click for sort" and "hover for tooltip" on the same target makes the click target ambiguous on touch (tap → does it sort or explain?). A dedicated icon button isolates the explain affordance and leaves sort untouched.

### 3.2 Visual treatment

```
  ┌─────────────────────────┐
  │  Delta  ⓘ    ↑          │      ← icon between label and sort indicator
  └─────────────────────────┘
              │
              ▼  on hover/focus
  ┌──────────────────────────────────────────────┐
  │ Delta                                        │
  │ Roughly the probability the option expires   │
  │ in the money — and how much the option price │
  │ moves per $1 of stock move.                  │
  │                                              │
  │ Good range for covered calls: 0.15 – 0.30.   │
  │ Higher = more premium but more assignment    │
  │ risk; lower = safer but thinner premium.     │
  └──────────────────────────────────────────────┘
```

Tokens:

| Token | Value |
|---|---|
| Icon | `w-3.5 h-3.5 text-slate-400 hover:text-slate-600 dark:text-slate-500 dark:hover:text-slate-300` |
| Tooltip surface | `bg-slate-900 dark:bg-slate-700 text-slate-100 text-xs leading-relaxed rounded-lg shadow-lg p-3 max-w-xs` |
| Tooltip arrow | optional; if hand-rolled, skip; if Radix Tooltip is available, use its arrow primitive |
| Open delay | 150ms (hover); 0ms (focus) |
| Close | leave + 100ms; Escape; tap-outside |

### 3.3 Content shape

Every numeric header tooltip is exactly three things:

1. **Definition** — one sentence, plain language.
2. **Good range** — what value you want for the current strategy.
3. **Why it matters** — one sentence on the trade-off.

Three reference examples (Delta, Open Interest, Annualized Return). Implementer fills in the rest using this shape.

**Delta**
> Roughly the probability the option expires in the money — and how much the option price moves per $1 of stock move.
>
> **Good range for covered calls:** 0.15 – 0.30. Higher = more premium but more assignment risk; lower = safer but thinner premium.

**OI (Open Interest)**
> The number of contracts currently open at this strike. A liquidity proxy — higher OI means tighter bid/ask spreads and easier exits.
>
> **Good range:** at least 50, ideally 500+. The scanner already filters out anything below 50.

**Ann. % (Annualized Return)**
> The premium-yield-on-capital extrapolated to a full year. Useful for comparing a 30-day trade against a 60-day trade on equal footing.
>
> **Good range:** depends on your target — most wheel traders aim for 15–30% annualized. Higher numbers usually mean more risk somewhere (closer-to-the-money strike, longer DTE, lower-quality underlying).

Columns to cover (verify against `StrikeTable.jsx` header list, current set is): `DTE`, `Bid/Ask`, `Delta`, `OI`, `Premium`, `Return%`, `Ann.%`, `Dist.%`, plus `Contracts` and `Max Income` when the capital-aware columns are showing. Strike, Exp, and # do not get tooltips — they are self-explanatory.

### 3.4 Component contract

```
<HeaderWithTooltip
  label="Delta"
  tooltipKey="delta"
  sortField="delta"
  sortField={sortField}
  sortDir={sortDir}
  onSort={handleSort}
  align="right"
/>
```

Effectively wraps the existing `SortHeader` and renders an extra `ⓘ` button. Tooltip content lives in a single module:

```js
// frontend/components/options/columnTooltips.js
export const COLUMN_TOOLTIPS = {
  dte: { title: "DTE — Days to Expiration", definition: "…", range: "…", why: "…" },
  delta: { … },
  // …
};
```

If a tooltip key is missing, render the header without the icon (graceful degradation).

`data-testid`:
- Icon button: `column-tooltip-trigger-{key}` (e.g. `column-tooltip-trigger-delta`)
- Tooltip body: `column-tooltip-body-{key}` (only present when open)

### 3.5 Mobile

The strike table already scrolls horizontally on small screens (`overflow-x-auto`). The `ⓘ` icon is small enough not to compete with the header label or sort indicator. Tap → tooltip pops as a popover near the icon (not full-screen). Implementer can lean on Radix Tooltip's mobile-aware behavior if available.

### 3.6 Edge

If the user has filtered out everything and the table is empty, the headers are not rendered (existing empty state replaces the table). Tooltips never appear in an empty-table state — not a concern.

---

## 4. Affordance 3 — Per-row trade explanation

### 4.1 Click affordance

The row is already clickable today — click anywhere on the row toggles the existing expanded panel (Greeks / Metrics / Rule Compliance). Phase A:

| Aspect | Decision |
|---|---|
| Trigger | **Keep the existing row click** to toggle expand. Add a visible chevron in the leftmost column (left of the checkbox) so the affordance is discoverable. |
| Multi-expand | **Single row at a time (accordion-style)**, which matches today's `useState(expandedRow)` behavior. Justification: keeps the table scannable; the user is in "compare three strikes via the table" mode or "drill into one strike" mode, not both. Multi-expand would balloon vertical space and bury the comparison flow further down. |
| Keyboard | Row is `tabIndex={0}` with `onKeyDown` for `Enter`/`Space`. Chevron rotates `→` to `▾` on expand. Existing `aria-expanded` should be added to the row. |

The existing expanded panel **keeps** its three columns (Greeks / Metrics / Rule Compliance). Phase A **adds a new sub-section below** them.

### 4.2 New sub-section layout

```
┌─ Expanded row (existing top row stays) ────────────────────────────────────┐
│  Greeks      │  Metrics            │  Rule Compliance                       │
│  (existing)  │  (existing)         │  (existing)                            │
├────────────────────────────────────────────────────────────────────────────┤
│  NEW: What this trade commits you to                                       │
│  ────────────────────────────────────────────────────────────────────────  │
│   Obligation     100 sh × $15.00       =  $1,500   (if called away)         │
│   Premium        $0.30 × 100           =  $30      collected up front       │
│   Break-even     $13.26 − $0.30        =  $12.96   stock price floor        │
│                                                                            │
│  Three ways this can end                                                   │
│   ●  Called away at $15.00                                                 │
│      You sell 100 sh at $15.00 → +$30 premium plus +$174 stock gain         │
│      = $204 net (assumes your $13.26 cost basis).                          │
│                                                                            │
│   ●  Expired worthless (stock stays below $15.00)                          │
│      Keep the $30 premium, keep the shares. You can sell another call.     │
│                                                                            │
│   ●  Closed early at 50% profit target                                     │
│      Buy back the call for ~$0.15, net ≈ $15 in premium, shares are free   │
│      to use for a new call sooner.                                         │
└────────────────────────────────────────────────────────────────────────────┘
```

### 4.3 Math sourcing (no new backend asks)

All numbers come from data the scanner already returns for the row, plus user inputs already on the page:

| Field | Source |
|---|---|
| `obligation_dollars` | `strike × 100` (covered call) or `strike × 100` collateral (CSP) |
| `premium_dollars` | `premium_per_contract` (already in `StrikeRecommendation`) |
| `break_even` | `breakeven` field on the row when present; otherwise compute `cost_basis − mid` on the client |
| Called-away P/L | `(strike − cost_basis) × shares + premium_dollars` |
| Expired-worthless P/L | `premium_dollars` |
| Close-early P/L | `premium_dollars × 0.5` (the existing 50% profit target convention; `fifty_pct_profit_target` is already on the row) |

If `cost_basis` is missing (user hasn't entered it), render the section with the formulas visible and a soft hint: *"Enter your cost basis in the sidebar to see dollar outcomes."* The structural block stays — it just shows the formula instead of the number. This matches the spec's empty-state requirement for "per-row expansion when the row would suggest a strike that fails the user's own rules": the row is still shown (per existing `rule_compliance` rendering), the "three ways this can end" math still renders, and the existing yellow flag styling on the strike cell carries the warning. No new error UI.

**No additional backend fields requested for Phase A.** If during implementation a missing field surfaces (e.g., the API doesn't return `premium_per_contract` for CSP rows in the way we need), file a backend-only follow-up; do not block Phase A on it.

### 4.4 Component contract

```
<TradeExplanation
  strike={StrikeRecommendation}     // existing row data
  strategy="covered_call" | "cash_secured_put"
  costBasis={number | null}          // from ChainFilters state
  sharesHeld={number | null}         // for CC outcome math
  capitalAvailable={number | null}   // for CSP outcome math
/>
```

`data-testid`:
- Section root: `trade-explanation-{strike}-{expiration}` (e.g. `trade-explanation-15.00-2026-06-20`)
- Obligation row: `trade-explanation-obligation`
- Premium row: `trade-explanation-premium`
- Break-even row: `trade-explanation-breakeven`
- Each outcome: `trade-explanation-outcome-{called_away | expired | closed_early}`

### 4.5 Mobile

Existing expanded panel currently renders 3 columns at `grid-cols-3`. On `< sm` it should stack to one column. The new sub-section is naturally vertical and needs no special mobile treatment. **No drawer/modal pattern** — in-place expand is consistent with today's behavior and matches the dense-table feel.

### 4.6 Visual tokens

| Token | Value |
|---|---|
| Section divider | `border-t border-slate-200 dark:border-slate-700 mt-4 pt-4` |
| Sub-section heading | `text-xs font-semibold uppercase tracking-wide text-slate-500 dark:text-slate-400 mb-2` |
| Math rows | `font-mono text-xs text-slate-700 dark:text-slate-200` with three columns: label / formula / annotation |
| Outcome bullet color | green dot for the favorable path, slate for neutral, no red — this is education, not warning |
| Outcome body | `text-xs text-slate-600 dark:text-slate-400 leading-relaxed` |

### 4.7 Tone

Plain English, no jargon-first. Avoid "you'll be assigned" → use "you sell the shares at the strike price". Avoid "premium decay" → use "the option's value drops as expiration approaches". Don't add disclaimers — the non-goals already cover "not advice".

---

## 5. Affordance 4 — Humanized rejected strikes

### 5.1 Backend change — new `human_reasons` field

`backend/app/models/schemas.py::RejectedStrike` gains a sibling field:

```python
class RejectedStrike(BaseModel):
    strike: float
    expiration: str
    rejection_reasons: list[str]      # existing — raw codes for debugging
    human_reasons: list[str]          # new — one human sentence per code
```

The raw `rejection_reasons` field **stays** so Playwright tests and any internal debug surface can still assert against the structured codes. The frontend renders `human_reasons` only.

### 5.2 Mapper location

A new module `backend/app/services/rejection_messages.py` exports:

```python
def humanize_reasons(raw_reasons: list[str], context: dict) -> list[str]:
    """Map each raw reason string to a one-sentence human explanation.

    context = {
        "cost_basis": float | None,
        "current_price": float | None,
        "min_call_distance_pct": float,
        "min_delta": float,
        "max_delta": float,
        "min_return_pct": float,
        "max_return_pct": float | None,
    }
    """
```

`OptionsScanner` calls this once per `RejectedStrike` before appending, populating `human_reasons` alongside `rejection_reasons`. Unit tests in `backend/tests/test_rejection_messages.py` cover one input/output pair per reason code (the AC requires "every reason code currently emitted").

### 5.3 Reason-code → sentence templates

Reason codes currently emitted by `options_scanner.py` (verified):

| Code | Raw format | Human sentence template |
|---|---|---|
| `fails_10pct_rule` | `fails_10pct_rule: strike {pct:.1f}% above basis, requires {min}%` | `Strike sits {pct:.1f}% above your ${cost_basis:.2f} basis, but the {min}% rule requires at least that much room.` |
| `itm_put` | `itm_put: strike ${strike:.2f} > price ${current_price:.2f}` | `Strike ${strike:.2f} is above the current price ${current_price:.2f} — that's in-the-money for a put, which the scanner skips.` |
| `delta_out_of_range` | `delta_out_of_range: |{delta:.2f}| not in [{min}, {max}]` | `Delta {delta:+.2f} is outside your {min}–{max} range — {too_high_or_too_low_explanation}.` See §5.3.1 for the conditional. |
| `low_open_interest` | `low_open_interest: {oi} < 50` | `Only {oi} contracts open — too thin to trade comfortably (the scanner requires at least 50).` |
| `zero_bid` | `zero_bid` | `No buyer is showing a bid right now, so there's no real market to sell into.` |
| `return_below_target` | `return_below_target: {pct:.2f}% < {min_return}%` | `Premium is only {pct:.2f}% of capital — below your {min_return}% target return.` |
| `return_above_cap` | `return_above_cap: {pct:.2f}% > {max_return}%` | `Premium is {pct:.2f}% of capital — above your {max_return}% cap. Usually means the strike is too close to the money for the risk.` |

#### 5.3.1 Delta sub-cases

`delta_out_of_range` carries two distinct meanings depending on which side it failed on:

- `|delta| > max_delta` → "too close to the money — higher chance of assignment than you've set as acceptable."
- `|delta| < min_delta` → "too far out of the money — premium is likely too thin to justify the trade."

The mapper picks the appropriate clause by comparing the parsed delta against the context's min/max.

#### 5.3.2 Parser robustness

Raw reason strings are constructed by f-strings in `options_scanner.py`. The mapper parses them with simple regex per code. **Hard rule: if a reason string fails to match any known code, the mapper falls back to the raw string unchanged.** Phase A does not crash on unknown codes; it degrades to today's behavior for that one line.

### 5.4 Frontend rendering

**Decision: bulleted list, one human sentence per rejection. Not flowing prose.** Reason: each strike has its own row already (`$99.00 6/20`); appending a one-sentence reason to that row keeps the existing structure. When a strike has multiple reasons (e.g. both delta and OI fail), the sentences become a small bulleted nested list inside that row.

```
┌────────────────────────────────────────────────────────────────────────────┐
│  ▾ Rejected strikes (50)                                                   │
│  ────────────────────────────────────────────────────────────────────────  │
│  $99.00  6/20    Strike sits 645.7% above your $13.26 basis, but the 1%   │
│                  rule requires at least that much room.                    │
│  ────────────────────────────────────────────────────────────────────────  │
│  $20.00  6/20    • Delta +0.42 is outside your 0.15–0.35 range — too      │
│                    close to the money, higher chance of assignment.        │
│                  • Only 12 contracts open — too thin to trade comfortably. │
│  ────────────────────────────────────────────────────────────────────────  │
│  $13.50  6/20    No buyer is showing a bid right now, so there's no real  │
│                  market to sell into.                                      │
│  …and 47 more                                                              │
└────────────────────────────────────────────────────────────────────────────┘
```

Existing render in `OptionScanner.jsx` currently joins reasons with `'; '`. Replace with:
- 1 reason → render as a single sentence (no bullet).
- 2+ reasons → render as a `<ul>` with `list-disc` and the sentences as items.

### 5.5 Component contract

Inline change to the rejected-strikes block already in `OptionScanner.jsx`. No new component file required — the existing `<details>` element stays. The map happens at render time:

```jsx
{result.rejected.slice(0, 20).map((r, i) => (
  <RejectedStrikeRow
    key={i}
    strike={r.strike}
    expiration={r.expiration}
    reasons={r.human_reasons}    // not r.rejection_reasons
    data-testid={`rejected-strike-${r.strike}-${r.expiration}`}
  />
))}
```

`RejectedStrikeRow` is a tiny internal component (file-local, no separate file) that handles the 1-vs-many rendering.

### 5.6 Tokens

| Token | Value |
|---|---|
| Strike label | `font-medium text-slate-700 dark:text-slate-200 text-xs` |
| Reason sentence | `text-xs text-slate-600 dark:text-slate-400 leading-relaxed` (NOT red — red was used because it was a debug string; humanized prose is informational, not an error) |
| Bullet list | `list-disc pl-5 mt-1 space-y-0.5` |
| Row spacing | `py-2 border-b border-slate-100 dark:border-slate-700` |

**Color change**: today the joined raw reasons render in `text-red-500`. After Phase A, the humanized sentence is the same slate-600/400 as other secondary text. The red was signaling "error string"; once it's a human sentence, no error signal is needed — the fact that it's inside the "Rejected Strikes" disclosure already carries that meaning.

---

## 6. Mobile (< sm, 640px) — composite view

```
┌──────────────────────────────────────┐
│  App header                          │
├──────────────────────────────────────┤
│  [☰ Filters drawer trigger]          │
│                                      │
│  ▸ What is a Covered Call?  Learn ▸ │
│                                      │
│  F — Covered Call Scan               │
│  Price $13.26 · 3 opportunities      │
│                                      │
│  Capital Deployment (existing)       │
│                                      │
│  ┌──────────────────────────────┐   │
│  │  Strike table                │   │
│  │  (horizontal scroll)         │   │
│  │  Tap row to expand           │   │
│  └──────────────────────────────┘   │
│                                      │
│  ▾ Strike $15.00  6/20  ($30 prem)  │
│    ┌──────────────────────────────┐ │
│    │ Greeks                       │ │
│    │ Metrics                      │ │
│    │ Rule Compliance              │ │
│    │ ─────────────────────────── │ │
│    │ What this trade commits you  │ │
│    │ to (stacked, full-width)    │ │
│    │ Three ways this can end      │ │
│    └──────────────────────────────┘ │
│                                      │
│  ▸ Rejected strikes (50)            │
└──────────────────────────────────────┘
```

No bottom-sheet, no full-screen drawer for the row expand. The existing in-place expand pattern stays — it's already mobile-friendly because the page is single-column on small screens and the expanded panel becomes a vertical stack.

---

## 7. Test IDs — full inventory

| Element | data-testid |
|---|---|
| Primer card root | `strategy-primer` |
| Primer toggle | `strategy-primer-toggle` |
| Primer hide | `strategy-primer-hide` |
| Primer body | `strategy-primer-body` |
| Column tooltip icon | `column-tooltip-trigger-{key}` |
| Column tooltip body | `column-tooltip-body-{key}` |
| Trade explanation section | `trade-explanation-{strike}-{expiration}` |
| Obligation row | `trade-explanation-obligation` |
| Premium row | `trade-explanation-premium` |
| Break-even row | `trade-explanation-breakeven` |
| Outcome — called away | `trade-explanation-outcome-called_away` |
| Outcome — expired | `trade-explanation-outcome-expired` |
| Outcome — closed early | `trade-explanation-outcome-closed_early` |
| Rejected strike row | `rejected-strike-{strike}-{expiration}` |

Existing test IDs (`strike-table`, `schwab-status-banner`, `capital-utilization-card`, `budget-alert-banner`) are preserved.

---

## 8. Acceptance criteria mapping

The issue's six ACs map to this spec as follows:

1. *Collapsible primer with 10% rule, dismissal persists* → §2.
2. *Numeric column headers expose keyboard-reachable tooltips* → §3.
3. *Row expand reveals dollar obligation / premium / break-even / three scenarios* → §4.
4. *Rejected strikes show human-readable reasons* → §5.
5. *Backend mapper has unit coverage for every emitted reason code* → §5.3 (table covers all seven current codes; `backend/tests/test_rejection_messages.py` is the test home).
6. *Frontend e2e: primer present, row expansion shows correct math, Delta tooltip shows on hover* → existing `frontend/e2e/` with a new spec file (`options-scanner-education.spec.ts` or similar — follow the project's existing naming).

---

## 9. Open forks (user sign-off needed before implementer picks up)

The spec defaults each of these; flagging here so they can be overridden:

1. **Primer placement** → **defaulted to top-of-page, collapsed-by-default with localStorage persistence**. Alternative: side-rail in `ChainFilters` (rejected because it competes with filters); modal-on-first-visit (rejected as interruptive).
2. **Row expansion** → **single-row accordion (matches today)**. Alternative: multi-row expand (rejected; balloons vertical space).
3. **Rejected list rendering** → **bulleted sentences, one per failed rule, color shifted from red to neutral**. Alternative: flowing prose paragraph per strike (rejected; harder to scan, breaks the per-rule structure).
4. **Tooltip trigger** → **dedicated `ⓘ` icon, not hover-anywhere on header**. Alternative: hover-anywhere (rejected because it conflicts with the click-to-sort affordance on touch).

---

## 10. Implementation notes (for the planner)

- The primer, the column-tooltip module, and the trade-explanation component are all isolated additions. They can be implemented and tested in any order.
- The rejected-strikes change spans backend + frontend in one PR (since the frontend depends on the new `human_reasons` field). Suggest sequencing: backend mapper + schema + unit tests first, then frontend swap to consume `human_reasons`.
- Suggested implementation order: (1) backend `human_reasons` + tests, (2) frontend rejected-list swap, (3) primer, (4) column tooltips, (5) per-row trade explanation, (6) e2e spec covering all four.
- Don't touch `RiskRewardPanel`, `ChainFilters`, or `useOptionScanner` beyond what is required to thread `costBasis` / `sharesHeld` / `capitalAvailable` into `<TradeExplanation>` (already in scope props for the page).
- The existing 50% profit target convention (`fifty_pct_profit_target` on each row) is the source for the close-early outcome math. Don't re-derive it.
