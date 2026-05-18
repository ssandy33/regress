# Design Spec: Settings — Trading Rules section

- **Issue:** [#158 — V1.0: Settings page — Trading Rules section](https://github.com/ssandy33/regress/issues/158)
- **Milestone:** V1.0 — Trading Rules Layer + Ship-Ready Hardening (#6)
- **Date:** 2026-05-17
- **Author:** Designer agent
- **Status:** Draft — for user review before implementation
- **Scope:** Frontend visual + structural spec for the Trading Rules editing surface on the Settings page. No code, no PR yet. The backend endpoint shape (generic `{key,value}` vs typed `/api/settings/rules`) is deliberately left open — see §10; it is a data-flow detail, not a layout concern.

---

## 1. Overview

The V1.0 rules layer (#156 / ADR-002 #216) introduces a single persisted `rules_config` object that every engine reads from — universe, entry, position, risk, and management-trigger rules. #156 builds the model and persistence; **#158 builds the surface that lets the trader edit it without touching JSON.** A config the trader cannot edit is only half-shipped, so the edit surface lands in V1.0 alongside the model.

This spec adds a **"Trading Rules" section** to the Settings page. It is a long, grouped form: five field groups, ~24 fields, each with a label, a number input, a units suffix, helper text, and the catalog default rendered as a placeholder. Four fields are `Optional`/unset rules — they render blank-and-clearable and never invent a default. The section has a single Save and a single Reset to defaults control, inline per-field validation matching the backend Pydantic validators, and the standard loading / saving / success / failure states.

The section header states the mental model the PRD asks for: **"Configure your system. Set once."**

The design is built so a sibling **"Trading OKRs"** section (V1.1, edits `okr_config`, derived from PRD #215) can be added alongside it **without rework** — see §3 for the routing/layout decision that makes this true.

Design language matches the existing Settings page slate palette, dark-mode aware. No new visual vocabulary is introduced — the section reuses the established Settings-card shell, the `bg-blue-600` primary button, and the `react-hot-toast` toast plumbing already wired into `SettingsPage.jsx`.

### Naming decision

The issue suggests the nav label "Trading Rules". **Decision: use "Trading Rules"** as both the nav label and the section title. It matches the PRD's `rules_config` namespace and ADR-001's "Trading Rules" layer name, and it reads as a sibling to the future "Trading OKRs" — the two share the "Trading …" prefix so the V1.1 addition slots in as an obvious pair.

---

## 2. Stack context (detected)

Detected from the repo before authoring — do not assume conventions from other projects:

- **Framework:** Next.js 16.2.4, App Router (`frontend/app/`).
- **Language:** JavaScript / JSX. `jsconfig.json` only — **no TypeScript.** The "Data Shape" in §9 is documented as JSDoc-style notes, not a `.ts` interface; the implementing component is a `.jsx` file.
- **Styling:** Tailwind CSS v4 (`@tailwindcss/postcss`). **No `tailwind.config.js`** — the project uses Tailwind's default token scale. Dark mode is **class-based** (`.dark` on `<html>`), re-bound via `@custom-variant dark` in `app/globals.css`.
- **Toasts:** `react-hot-toast` — already imported and used throughout `SettingsPage.jsx` (`toast.success` / `toast.error`).
- **Path alias:** `@/*` → repo `frontend/` root.
- **No `docs/DESIGN_SYSTEM.md`** exists. Tokens in §11 were derived from the codebase (`app/globals.css` + the existing Settings sections + `components/common/*`). Recommendation: extract a `docs/DESIGN_SYSTEM.md` in a future one-shot so future designs share one canonical token reference; not a blocker for this issue.

---

## 3. Routing & layout — and the V1.1 forward-compatibility decision

### 3.1 The decision

The issue's hard constraint is: *"Built so a sibling 'Trading OKRs' section can be added alongside it in V1.1 without rework."* There are two ways to satisfy this; the choice determines the whole layout.

⚠️ **DECISION NEEDED — confirm before implementation. Recommended option in bold.**

- **Option A — One Settings page, Trading Rules is a long section in the existing single column.**
  The new section is appended to the `space-y-8` column in `SettingsPage.jsx`, exactly like Reconcile Journal (#139) was. "Trading OKRs" later becomes the next section below it. *Forward-compat is free — V1.1 just appends another section.* But: the Settings page is already 8 sections of infrastructure/data settings (FRED key, Schwab, cache, backups). Adding ~24 trading-rule fields makes a very long scroll, and mixes "set up the app's plumbing" with "configure my trading strategy" — two different mental modes on one page.

- **Option B — Promote Settings to a tabbed page; Trading Rules is its own tab. ✅ RECOMMENDED.**
  Introduce a horizontal tab bar at the top of the Settings page. Tab 1 **"General"** holds everything that is on the page today (Data Source Status, FRED, Schwab, Data Freshness, Cache, Backups, Preferences, Reconcile, Danger Zone — unchanged). Tab 2 **"Trading Rules"** holds the new section. V1.1 adds Tab 3 **"Trading OKRs"** — a pure addition, zero rework, which is exactly the issue's requirement. It also separates "app plumbing" from "my trading system," and keeps each tab a manageable scroll.

**Recommendation: Option B.** It is the cleanest literal satisfaction of "added alongside without rework" — V1.1 is a one-line tab registration. It also fits the project's own trajectory: this is the first tabbed page, and per the established convention the tab bar should be **page-scoped** (defined inside the Settings page, not lifted into a shared `components/common/Tabs.jsx` primitive) until a second tabbed page exists elsewhere in the app. If a second tabbed surface appears later, lift then.

If the user prefers Option A for V1.0 speed, the field-group design in §5–§8 is **identical either way** — only the page wrapper differs. The spec below is written for Option B; §3.3 notes the Option A delta.

### 3.2 Option B — page structure

```
/settings  (app/settings/page.jsx → components/settings/SettingsPage.jsx)

Settings                                            [Back to Analysis]
┌─────────────────────────────────────────────────────────────────────┐
│  [ General ]  [ Trading Rules ]      ← page-scoped tab bar (new)      │
└─────────────────────────────────────────────────────────────────────┘

  ── when "General" active ──
  (the entire current SettingsPage column, unchanged)

  ── when "Trading Rules" active ──
  Trading Rules                                                          
  Configure your system. Set once.                                       
                                                                         
  [Universe group card]                                                  
  [Entry group card]                                                     
  [Position group card]                                                  
  [Risk group card]                                                      
  [Management triggers group card]                                       
                                                                         
  [ Reset to defaults ]                       [ Save trading rules ]     
```

- The tab bar is the only structural change to the General experience — its sections are untouched and stay in their current `space-y-8` column.
- The Trading Rules tab is a **new component** `components/settings/TradingRulesSection.jsx`, rendered when its tab is active.
- Page width: keep the existing `max-w-2xl mx-auto px-6 py-8` constraint of `SettingsPage.jsx`. The form is single-column; `max-w-2xl` is comfortable for label + input + helper rows.

### 3.3 Option A delta (if chosen instead)

No tab bar. `TradingRulesSection` is appended to the existing `space-y-8` column, placed **after Preferences and before Reconcile Journal** (group it with "configure the app" sections, keep the data-management/destructive sections — Reconcile, Danger Zone — as the page terminator). Everything in §4–§12 is otherwise unchanged.

---

## 4. Section anatomy

The Trading Rules tab/section is a vertical stack of **five group cards** followed by a **sticky action footer**.

```
┌─ Trading Rules ─────────────────────────────────────────────────────┐
│  Trading Rules                                                       │
│  Configure your system. Set once.                                    │
└──────────────────────────────────────────────────────────────────────┘

┌─ Group card: Universe ──────────────────────────────────────────────┐
│  Universe                                                            │
│  May I trade this underlying at all? Checked before any option       │
│  chain is scanned.                                                    │
│  ─────────────────────────────────────────────────────────────────  │
│  ┌ field row ┐  ┌ field row ┐  ...                                   │
└──────────────────────────────────────────────────────────────────────┘
   (Entry, Position, Risk, Management triggers — same shape)

┌─ Action footer ─────────────────────────────────────────────────────┐
│  [ Reset to defaults ]                       [ Save trading rules ]  │
│  (last-saved timestamp / unsaved-changes hint sits here)             │
└──────────────────────────────────────────────────────────────────────┘
```

### 4.1 Group card

Each of the five groups is one card using the **Settings-card shell** — `bg-slate-50 dark:bg-slate-800 rounded-xl p-6 border border-slate-200 dark:border-slate-700` — the same shell every existing Settings section uses (`ReconcileJournal.jsx`, FRED, Schwab, …). Do **not** use the `components/common/Card.jsx` primitive here — that primitive is `bg-white` and is the dashboard card; the Settings page has its own `bg-slate-50` shell and the new section must match its siblings, not the dashboard.

Card header:
- `h2` title — group name (`text-lg font-semibold text-slate-900 dark:text-white`).
- One-line description (`text-sm text-slate-500 dark:text-slate-400`) — the "may I trade this?" / "what trade?" framing from PRD §R2–R6, so the trader understands when the group's rules fire.

Card body: a vertical list of **field rows**, `space-y-5`.

### 4.2 Field row

Each field is one row. Layout:

```
Label text                                              [help ⓘ hover]
┌──────────────────────────────────┐ ┌──────┐
│  25                              │ │  %   │   ← input + units suffix
└──────────────────────────────────┘ └──────┘
Helper text explaining what the rule controls.            (slate-400, xs)
```

- **Label** — `<label htmlFor>` bound to the input id. `text-sm text-slate-700 dark:text-slate-300 mb-1`.
- **Input** — a `<input type="number">` styled to match the existing Settings inputs: `px-3 py-2 text-sm border border-slate-300 dark:border-slate-600 rounded-lg bg-white dark:bg-slate-700 text-slate-900 dark:text-slate-100 outline-none focus:ring-2 focus:ring-blue-500`. Width: `w-full` within the row, but the row caps input width so the suffix can sit to its right (see §4.3).
- **Units suffix** — a small static affix to the right of the input showing `$`, `%`, `days`, `contracts`, or `×` (for max-consecutive-rolls). Rendered as a non-interactive trailing addon, `text-xs text-slate-500 dark:text-slate-400`, in a bordered box that visually joins the input (left border removed / `rounded-l-none`). `$` renders as a **leading** affix (before the input) because that is the natural reading order for currency; `%`, `days`, `contracts`, `×` render **trailing**.
- **Default-as-placeholder** — the input's `placeholder` is the catalog default value (e.g. `21`, `45`, `500`). When the field has a stored value, the value fills the input and the placeholder is hidden as usual. When the field is empty, the greyed default is visible — it shows the trader what the system uses if they leave it blank, without that default being a real entered value.
- **Helper text** — `text-xs text-slate-500 dark:text-slate-400 mt-1`, sourced verbatim (lightly trimmed) from the PRD #209 "Why" column. This is the per-field explanation the issue's AC requires.

### 4.3 Range fields (min/max pairs)

`dte_range`, `delta_range_csp`, `delta_range_cc` are `{min, max}` pairs. Render them as **one row with two inputs** joined by an en-dash:

```
DTE range                                                [help ⓘ]
┌────────────┐        ┌────────────┐
│  21        │   to   │  45        │  days
└────────────┘        └────────────┘
The wheel sweet spot — far enough for theta decay, near enough to
avoid locking capital for months.
```

- Two `<input type="number">`, each with its own id (`rules-field-dte_range_min` / `_max`), a shared visible group label, and a visually-hidden per-input label ("DTE minimum" / "DTE maximum") for screen readers.
- The units suffix (`days`, or none for delta) sits after the max input.
- `min < max` validation: see §10.2.

### 4.4 Boolean / enum field — `assignment_risk_review`

`assignment_risk_review` in PRD §R6 has default "High" — it is not a number. Model it as a small `<select>` (`Off` / `Low` / `Medium` / `High`) matching the existing Preferences `<select>` style in `SettingsPage.jsx`. Same field-row layout (label, control, helper), no units suffix.

⚠️ **DECISION NEEDED:** PRD §R6 lists `assignment_risk_review` with default "High" but does not enumerate its allowed values. The `Off/Low/Medium/High` set above is a designer-proposed default — confirm against the `RulesConfig` Pydantic model in #156 before wiring. If #156 models it as a boolean toggle instead, render a checkbox/switch; the field-row layout is otherwise unchanged.

---

## 5. Group 1 — Universe

Card description: *"May I trade this underlying at all? Checked before any option chain is scanned."*

| Field key | Label | Input | Suffix | Default (placeholder) | Optional? | Helper text |
|---|---|---|---|---|---|---|
| `min_open_interest` | Min option open interest | number | `contracts` | `500` | required | Below this, bid-ask spreads widen enough to erode the edge. The standard liquidity floor for retail premium sellers. |
| `max_bid_ask_spread_pct` | Max bid-ask spread | number | `%` | `10` | required | A wider spread means you give up too much on entry and exit. A cheap proxy for tradeable liquidity. |
| `min_iv_rank` | IV Rank floor | number | (none) | `30` | required | Below IV Rank 30, options are historically cheap and selling premium has no statistical edge. 30 is the minimum gate; 50+ is preferred. |
| `min_iv_percentile` | IV Percentile floor | number | (none) | — *(unset)* | **Optional** | Complementary to IV Rank — more stable against outlier spikes. Leave blank to skip this check. Proposed value if you set it: 30. |

`min_iv_percentile` is one of the four Optional fields — see §8 for its blank/clearable rendering.

---

## 6. Group 2 — Entry

Card description: *"What trade may I open? Checked when a new option trade is opened or previewed in the scanner."*

| Field key | Label | Input | Suffix | Default (placeholder) | Optional? | Helper text |
|---|---|---|---|---|---|---|
| `dte_range` | DTE range | number range `{min,max}` | `days` | `21` to `45` | required | The wheel sweet spot — far enough for meaningful theta decay, near enough to avoid locking capital for months. Below 21 days gamma risk dominates. |
| `delta_range_csp` | Delta range (cash-secured puts) | number range `{min,max}` | (none) | `0.20` to `0.30` | required | A probability-of-assignment proxy. 0.20–0.30 is roughly a 70–80% chance the put expires worthless — the mainstream CSP consensus. |
| `delta_range_cc` | Delta range (covered calls) | number range `{min,max}` | (none) | `0.20` to `0.35` | required | Slightly wider — a higher delta is fine when you want shares called away above cost basis. Tighten it when you want to keep the shares. |
| `min_monthly_return_pct` | Min monthly return | number | `%` | `2` | required | A premium-yield floor. A trade earning under 2%/month doesn't justify the capital lockup and assignment risk. |
| `earnings_buffer_days` | Earnings buffer | number | `days` | `7` | required | Don't open within this many days of earnings — earnings gaps blow straight through strikes. |
| `min_call_distance_pct` | Min call distance | number | `%` | `5` | required | The covered-call strike must sit at least this far above the trader's **adjusted cost basis** — the scanner measures this from cost basis, *not* from spot price. ⚠️ See the note below this table and §18 Q6. |
| `min_call_distance_from_cost_basis_pct` | Min call distance from cost basis | number | `%` | `0` | required | Never sell a covered call below your adjusted cost basis — that locks in a guaranteed loss if called away. 0 means "at or above cost basis." |

> ⚠️ **`min_call_distance_pct` vs `min_call_distance_from_cost_basis_pct` — Q6, unresolved.** Both fields are measured from the trader's adjusted **cost basis** — verified against `backend/app/services/options_scanner.py`, and consistent with the #217 reconciliation of PRD #209 (an earlier draft of this spec wrongly described `min_call_distance_pct` as a distance "from spot"). Their distinct roles — a percentage margin above basis vs a bare at-or-above-basis floor — are too close to label legibly until #156 fixes the precise semantics of each. The label and helper text for `min_call_distance_pct` above are provisional pending that decision.

---

## 7. Group 3 — Position · Group 4 — Risk · Group 5 — Management triggers

### 7.1 Position

Card description: *"How big, how many? Caps on the capital tied up in any one position."*

| Field key | Label | Input | Suffix | Default (placeholder) | Optional? | Helper text |
|---|---|---|---|---|---|---|
| `sizing_cap_dollars` | Per-position sizing cap | number | `$` *(leading)* | `5000` | required | An absolute-dollar ceiling on capital tied up in one position — caps worst-case single-name loss regardless of account size. |
| `max_ticker_concentration_pct` | Ticker concentration cap | number | `%` | `25` | required | No single ticker exceeds this share of total notional — survives a single-name blow-up. |
| `max_open_positions` | Max open positions | number | (none) | — *(unset)* | **Optional** | A breadth guardrail — beyond a manageable count, monitoring discipline degrades. Leave blank for no cap. Most wheel practitioners cite 8–10. |

### 7.2 Risk

Card description: *"When do I intervene? Thresholds that flag a position for a deliberate look."*

| Field key | Label | Input | Suffix | Default (placeholder) | Optional? | Helper text |
|---|---|---|---|---|---|---|
| `loss_review_threshold_pct` | Loss-review threshold | number | `%` | `-15` | required | A position down this much unrealized warrants a deliberate look — is the thesis still intact? Enter a negative number. |
| `hard_max_loss_pct` | Hard max-loss / stop | number | `%` | — *(unset)* | **Optional** | Past this loss, the position is a capital trap — decide via the recovery plan rather than hoping. Leave blank for no hard stop. Proposed: -25. |
| `max_consecutive_rolls` | Max consecutive rolls | number | `×` | — *(unset)* | **Optional** | Rolling more than 2–3 times on the same loser usually just delays an inevitable assignment. At the cap, the system forces a decision. Leave blank for no cap. |

### 7.3 Management triggers

Card description: *"When do I act on an open leg? Thresholds that fire Next Actions on positions you already hold."*

| Field key | Label | Input | Suffix | Default (placeholder) | Optional? | Helper text |
|---|---|---|---|---|---|---|
| `profit_review_pct` | Profit-take review | number | `%` | `50` | required | Buy back a short option at this share of max profit — locks gains, frees capital, sheds tail risk. Research across 200K+ trades supports 50%. |
| `dte_review_days` | DTE review | number | `days` | `21` | required | At this DTE, decide roll vs close vs hold. Inside it, gamma risk accelerates and a small adverse move can wipe out weeks of theta. |
| `expiration_warning_days` | Expiration warning | number | `days` | `7` | required | Inside this many days to expiry, assignment mechanics dominate and the position needs attention. |
| `assignment_risk_review` | Assignment-risk review | select | (none) | `High` | required | The sensitivity for flagging ITM-near-expiry positions that need an explicit decision. See §4.4 decision point. |

---

## 8. Optional / unset fields — blank & clearable rendering

Four fields are backed by an `Optional` rule in `RulesConfig` (PRD #209 Q1 / ADR-002 D-OQ1): **`min_iv_percentile`, `max_open_positions`, `hard_max_loss_pct`, `max_consecutive_rolls`.** For these, *blank is a valid, honest state* — the rule is simply not enforced. The UI must not invent a default value for them.

Rendering rules for an Optional field:

1. **Unset → input is empty.** No value, no fallback number. The placeholder shows a non-numeric hint — `"Not set — no limit"` — **not** a proposed number, so the empty input is unambiguous. (Contrast required fields, whose placeholder *is* the default number.)
2. **Optional badge.** A small `Optional` pill (`text-xs text-slate-500 bg-slate-100 dark:bg-slate-700 rounded-full px-2 py-0.5`) sits next to the label so the trader knows blank is allowed.
3. **Clear affordance.** When an Optional field *has* a value, show a small "Clear" text button (`text-xs text-slate-500 hover:text-slate-700`) at the row's right edge. Clicking it returns the field to the unset state. The helper text mentions "Leave blank for no cap / no hard stop."
4. **Save semantics.** An empty Optional field is saved as unset (`null` in `rules_config`), never as `0` and never as the proposed default. The implementing component must distinguish "" (unset) from "0" (a real entered zero) — `0` is a legitimate value for some required percent fields, so empty-string is the only unset signal.
5. **Validation.** An empty Optional field is always valid (it is allowed to be unset). Validation only runs on Optional fields when they contain a value.

Visual treatment of a set vs unset Optional field:

```
unset:
  Max open positions   [Optional]
  ┌──────────────────────────────────┐
  │  Not set — no limit              │   ← placeholder, greyed
  └──────────────────────────────────┘
  A breadth guardrail … Leave blank for no cap.

set:
  Max open positions   [Optional]                            [Clear]
  ┌──────────────────────────────────┐
  │  10                              │
  └──────────────────────────────────┘
  A breadth guardrail … Leave blank for no cap.
```

---

## 9. Data shape

JSDoc-style (the project is JSX, not TS). `rules_config` is the object the section reads and writes; shape per ADR-002 D1.

```js
/**
 * @typedef {Object} RulesConfig
 * @property {number}  schema_version          - 1 (ADR-002 RULES_CONFIG_SCHEMA_VERSION)
 * @property {Object}  universe
 * @property {number}  universe.min_open_interest
 * @property {number}  universe.max_bid_ask_spread_pct
 * @property {number}  universe.min_iv_rank
 * @property {?number} universe.min_iv_percentile          - Optional, null = unset
 * @property {Object}  entry
 * @property {{min:number,max:number}} entry.dte_range
 * @property {{min:number,max:number}} entry.delta_range_csp
 * @property {{min:number,max:number}} entry.delta_range_cc
 * @property {number}  entry.min_monthly_return_pct
 * @property {number}  entry.earnings_buffer_days
 * @property {number}  entry.min_call_distance_pct
 * @property {number}  entry.min_call_distance_from_cost_basis_pct
 * @property {Object}  position
 * @property {number}  position.sizing_cap_dollars
 * @property {number}  position.max_ticker_concentration_pct
 * @property {?number} position.max_open_positions          - Optional, null = unset
 * @property {Object}  risk
 * @property {number}  risk.loss_review_threshold_pct
 * @property {?number} risk.hard_max_loss_pct               - Optional, null = unset
 * @property {?number} risk.max_consecutive_rolls           - Optional, null = unset
 * @property {Object}  management
 * @property {number}  management.profit_review_pct
 * @property {number}  management.dte_review_days
 * @property {number}  management.expiration_warning_days
 * @property {string}  management.assignment_risk_review    - enum; confirm vs #156 model
 */
```

Percent convention: `rules_config` standardises on **whole-percent** (per #156 / issue #158). The form takes and shows whole-percent (`25`, `-15`, `2`) directly — `1`-to-`1` with the stored value, no human↔fraction conversion. **The issue's "percent fields convert human ↔ stored convention" AC and its component test still apply** as a guard: the component must confirm whole-percent against the `RulesConfig` model before wiring, and if #156 turns out to store fractions the conversion (`25` ⇄ `0.25`) lives in the form's load/save mapping. Design assumes whole-percent; flag if #156 disagrees.

---

## 10. Data flow & save lifecycle

### 10.1 Endpoint (left open by design)

Per the issue, the endpoint shape is undecided. The UI is built **independent** of it:

- The component calls a thin API helper in `frontend/api/client.js` — propose `getRulesConfig()` and `saveRulesConfig(config)`.
- Those helpers wrap **whichever endpoint #156 ships**: the generic `GET`/`PUT /api/settings` `{key:"rules_config", value:<json string>}` upsert (ADR-002 OQ3 — sufficient), or the typed `GET`/`PUT /api/settings/rules` if #156 adds it.
- The component does not care which — it consumes `RulesConfig`-shaped JSON and posts `RulesConfig`-shaped JSON. Confirm available endpoints against the backend before wiring; the layout in this spec does not change either way.
- On save success, invalidate any cached dashboard data so rule changes reflect on the next dashboard view (issue AC). Mechanism: whatever cache layer the dashboard uses — flag for the Developer agent.

### 10.2 Validation

Inline, per-field, mirroring the backend Pydantic validators (ADR-002 — `RulesConfig` validates ranges). Validation runs on blur and again on Save attempt.

| Rule | Check | Message (generic, no raw exception) |
|---|---|---|
| Range fields (`dte_range`, `delta_range_csp`, `delta_range_cc`) | `min < max` | "Minimum must be less than maximum." |
| Non-negative fields (`min_open_interest`, `dte_*`, `earnings_buffer_days`, `*_distance_pct`, `min_monthly_return_pct`, `sizing_cap_dollars`, `profit_review_pct`, etc.) | `>= 0` | "Enter a value of 0 or greater." |
| Delta fields | `0 ≤ delta ≤ 1` | "Delta must be between 0 and 1." |
| Percent caps (`max_bid_ask_spread_pct`, `max_ticker_concentration_pct`, `profit_review_pct`, IV floors) | `0 ≤ x ≤ 100` | "Enter a percentage between 0 and 100." |
| Loss fields (`loss_review_threshold_pct`, `hard_max_loss_pct`) | `≤ 0` (a loss threshold is negative) | "Enter a loss as a negative percentage." |
| Optional fields | empty is always valid; validate only when filled | — |

Error rendering on a field row:
- The input gets a red ring: `border-red-400 dark:border-red-500 focus:ring-red-500`, and `aria-invalid="true"`.
- An error message renders below the helper text in red (`text-xs text-red-600 dark:text-red-400`), with `id="rules-field-{key}-error"`.
- The input carries `aria-describedby="rules-field-{key}-help rules-field-{key}-error"` so a screen reader announces both the helper and the error. When valid, `aria-describedby` references only the help id.
- Save is blocked while any field is invalid — the Save button is disabled and a count ("Fix 2 fields before saving") sits in the action footer.

### 10.3 Save / Reset controls

**Action footer** — sits below the five group cards. On Option B it can be `sticky bottom-0` within the tab's scroll container so Save is always reachable on a long form; on Option A it is a normal in-flow footer.

- **Save trading rules** — primary button, `bg-blue-600 text-white` (matches every primary action in `SettingsPage.jsx`). Disabled when (a) no unsaved changes, or (b) any field invalid. On click → §10.4 saving state.
- **Reset to defaults** — secondary button, `border border-slate-300 dark:border-slate-600`. Resets *every* field in the section to its catalog default — and resets the four Optional fields back to **unset**, not to their "proposed" numbers. Because this discards edits, it opens a `ConfirmDialog` (the existing `components/common/ConfirmDialog.jsx`) first — non-destructive of persisted data but destructive of in-progress edits, so confirm. Per the established project pattern, this confirm uses the **blue/primary** variant, not the red/danger variant (red is reserved for data-destroying actions like Danger Zone). Reset only changes the form's in-memory state; nothing persists until the trader then clicks Save.
- An **unsaved-changes hint** ("You have unsaved changes") and a **last-saved line** ("Saved just now" / "Last saved 3:14 PM") sit in the footer next to the buttons.

### 10.4 Save lifecycle states

- **Saving** — Save button shows a pending label ("Saving…") and a spinner; the button and every field in the section are disabled (`disabled` + `opacity-50`) so the form can't be edited mid-write. Matches the `ReconcileJournal` Apply pattern.
- **Save success** — `toast.success("Trading rules saved")` via `react-hot-toast`; a brief inline confirmation glyph (a checkmark, `text-green-600`) appears next to the Save button for ~2s; the footer's last-saved line updates; the unsaved-changes hint clears; fields re-enable.
- **Save failure** — `toast.error(...)` **plus** an inline error banner at the top of the section: `bg-red-50 dark:bg-red-900/30 border border-red-200 dark:border-red-800 text-red-700 dark:text-red-300 rounded-lg px-4 py-3`. The message is **generic** ("Couldn't save your trading rules. Please try again.") — per CLAUDE.md, never surface a raw `str(e)` / API exception. Fields re-enable so the trader can retry. The banner has a dismiss affordance and clears on the next save attempt.

---

## 11. States

The section has four required states plus the save-lifecycle states in §10.4.

### 11.1 Loading

While the initial `getRulesConfig()` resolves: render a **skeleton form**, not a bare spinner — the issue AC says "skeleton form while the config GET resolves." Five skeleton group cards, each with 3–4 shimmer rows (a short grey bar for the label, a full-width grey bar for the input). Reuse `components/layout/LoadingSkeleton.jsx` if its shape fits; otherwise a local skeleton row. The action footer renders disabled. `data-testid="settings-rules-loading"`.

### 11.2 Empty

There is no true "empty" state — `load_rules_config` (ADR-002) **always** returns a complete config (defaults merged over any partial stored object), so the form always has values to render. The closest thing is *"never edited — all defaults"*: required fields show their default values, Optional fields show as unset. This is the normal populated form; optionally show a one-line note at the top — *"You haven't changed any rules yet — these are the recommended defaults."* — that disappears once the trader has saved at least once. `data-testid="settings-rules-defaults-note"`.

### 11.3 Error (load failure)

If `getRulesConfig()` fails: render the section with an inline error block (`bg-red-50 …`, same treatment as §10.4 failure) and a **Retry** button. Copy: *"Couldn't load your trading rules."* — generic, no raw exception. Do **not** render the form with guessed values; render only the error + retry. `data-testid="settings-rules-load-error"`.

### 11.4 Populated

The normal state — the five group cards from §5–§8 with values, the action footer from §10.3. This is the layout the rest of the spec describes.

---

## 12. Component mapping

| UI element | Component | Status | Notes |
|---|---|---|---|
| Settings tab bar (Option B) | `SettingsPage.jsx` (inline, page-scoped) | Create (inline) | Horizontal tabs; page-scoped, not a shared primitive — first tabbed page in the app. |
| Trading Rules section | `components/settings/TradingRulesSection.jsx` | **Create** | Top-level section component; owns load/save/validation state. |
| Group card | inline in `TradingRulesSection` | Create (inline) | Settings-card shell `bg-slate-50 dark:bg-slate-800 rounded-xl p-6 border …`. |
| Field row | `components/settings/RuleField.jsx` | **Create** | One labeled number field + units suffix + helper + validation. Reused ~21×. |
| Range field row | `components/settings/RuleRangeField.jsx` | **Create** | Two-input `{min,max}` variant of `RuleField`. Reused 3×. Could be a `variant` prop on `RuleField` instead — implementer's call. |
| Optional-field badge + Clear | inside `RuleField` (`optional` prop) | Create (inline) | `optional` prop drives the badge, the "Not set" placeholder, the Clear button, and the unset-vs-0 save logic. |
| Confirm dialog (Reset) | `components/common/ConfirmDialog.jsx` | **Reuse** | Blue/primary variant — non-destructive of persisted data. |
| Toasts | `react-hot-toast` | **Reuse** | `toast.success` / `toast.error`, already wired in `SettingsPage.jsx`. |
| Primary / secondary buttons | inline Tailwind | Reuse pattern | `bg-blue-600` primary, `border-slate-300` secondary — exact classes already used across `SettingsPage.jsx`. |
| Skeleton (loading) | `components/layout/LoadingSkeleton.jsx` | Reuse if shape fits | Else a local skeleton row. |
| API helpers | `frontend/api/client.js` | **Create** | `getRulesConfig()`, `saveRulesConfig(config)` — wrap whichever endpoint #156 ships. |

**Do not** reuse `components/common/Card.jsx` (dashboard `bg-white` card) or `StatCard.jsx` here — the Settings page has its own `bg-slate-50` card shell and the new section must visually match its siblings.

---

## 13. Design tokens applied

No `docs/DESIGN_SYSTEM.md` exists — tokens below were **derived from the codebase** (`app/globals.css`, the existing Settings sections, `components/common/*`). Tailwind v4 default scale; no custom config.

| Token | Value | Usage |
|---|---|---|
| Page background | `bg-white` / `dark:bg-slate-900` | Settings page wrapper |
| Card shell | `bg-slate-50` / `dark:bg-slate-800` + `border-slate-200 dark:border-slate-700` + `rounded-xl p-6` | Each group card |
| Card title | `text-lg font-semibold text-slate-900 dark:text-white` | Group headers |
| Body/helper text | `text-sm` / `text-xs` `text-slate-500 dark:text-slate-400` | Descriptions, helper text |
| Input | `border-slate-300 dark:border-slate-600 rounded-lg bg-white dark:bg-slate-700 focus:ring-2 focus:ring-blue-500` | Number inputs |
| Primary button | `bg-blue-600 text-white hover:bg-blue-700 disabled:bg-blue-400` | Save |
| Secondary button | `border-slate-300 dark:border-slate-600 text-slate-700 dark:text-slate-300 hover:bg-slate-100` | Reset |
| Error | `border-red-400`, `text-red-600 dark:text-red-400`, `bg-red-50 dark:bg-red-900/30` | Validation + failure banner |
| Success accent | `text-green-600` | Save-success glyph |
| Optional pill | `text-xs text-slate-500 bg-slate-100 dark:bg-slate-700 rounded-full px-2 py-0.5` | Optional-field badge |
| Spacing | `space-y-8` (between cards), `space-y-5` (between field rows) | Matches existing Settings column |

---

## 14. Test-ID inventory

Pattern: `{component}-{element}`. The issue mandates the first four; the rest are derived for component + e2e coverage.

| Test ID | Element |
|---|---|
| `settings-rules-form` | The Trading Rules section root (the `<form>`). **(issue-mandated)** |
| `settings-save-rules` | Save trading rules button. **(issue-mandated)** |
| `settings-reset-rules` | Reset to defaults button. **(issue-mandated)** |
| `rules-field-{key}` | Per-field input — one per field key in §5–§8. **(issue-mandated pattern)** |
| `settings-rules-tab` | The "Trading Rules" tab in the Settings tab bar (Option B). |
| `settings-tab-general` | The "General" tab (Option B). |
| `rules-field-{key}-error` | Per-field inline validation error message (also the `aria-describedby` target). |
| `rules-field-dte_range_min` / `_max` | The two inputs of the DTE range field. |
| `rules-field-delta_range_csp_min` / `_max` | The two inputs of the CSP delta range field. |
| `rules-field-delta_range_cc_min` / `_max` | The two inputs of the CC delta range field. |
| `rules-field-{key}-clear` | Clear button on a set Optional field (`min_iv_percentile`, `max_open_positions`, `hard_max_loss_pct`, `max_consecutive_rolls`). |
| `rules-group-{universe\|entry\|position\|risk\|management}` | Each group card. |
| `settings-rules-loading` | Skeleton form (loading state). |
| `settings-rules-load-error` | Load-failure error block + Retry. |
| `settings-rules-save-error` | Save-failure inline error banner. |
| `settings-rules-save-success` | Save-success confirmation glyph. |
| `settings-rules-defaults-note` | The "all defaults / never edited" note. |
| `settings-rules-unsaved-hint` | The unsaved-changes hint in the footer. |
| `settings-rules-reset-confirm` | The Reset `ConfirmDialog` (the dialog component already exposes its own test id — pass this through). |

Per-field key list for `rules-field-{key}` (21 single + 3 range = 24 logical fields):
`min_open_interest`, `max_bid_ask_spread_pct`, `min_iv_rank`, `min_iv_percentile`, `dte_range` (→ `_min`/`_max`), `delta_range_csp` (→ `_min`/`_max`), `delta_range_cc` (→ `_min`/`_max`), `min_monthly_return_pct`, `earnings_buffer_days`, `min_call_distance_pct`, `min_call_distance_from_cost_basis_pct`, `sizing_cap_dollars`, `max_ticker_concentration_pct`, `max_open_positions`, `loss_review_threshold_pct`, `hard_max_loss_pct`, `max_consecutive_rolls`, `profit_review_pct`, `dte_review_days`, `expiration_warning_days`, `assignment_risk_review`.

---

## 15. Accessibility checklist

- Every input has a programmatically associated `<label htmlFor>`. Range fields have a visible group label plus a visually-hidden per-input label.
- Error fields set `aria-invalid="true"`; valid fields set `aria-invalid="false"` (or omit).
- `aria-describedby` links each input to its helper text id and, when invalid, its error id.
- The save-failure and load-failure banners use `role="alert"` so they're announced.
- The tab bar (Option B) uses `role="tablist"` / `role="tab"` / `role="tabpanel"` with `aria-selected`.
- Focus order follows visual order: group by group, top to bottom, footer last.
- Color is never the only signal — errors carry text, the success glyph carries a checkmark shape, Optional state carries the "Optional" word.

---

## 16. Figma Make prompt

```
Design a "Trading Rules" settings section for a data-dense engineering / trading dashboard.

Layout:
- A Settings page with a horizontal tab bar at top: "General" and "Trading Rules" (active).
- The Trading Rules tab shows a section header: title "Trading Rules", subtitle "Configure your system. Set once."
- Below it, five stacked group cards: Universe, Entry, Position, Risk, Management triggers.
- Each card has a title, a one-line grey description, a divider, and a vertical list of field rows.
- A field row: label on top, a number input with a small units-suffix box on its right ($, %, days, contracts), and grey helper text below. Some fields show two inputs joined by "to" (a min–max range).
- Four fields show an "Optional" pill next to the label, an empty input with placeholder "Not set — no limit", and a small "Clear" link when filled.
- One field shows a red-ringed input with a red error message below it (invalid state).
- A footer with a grey "Reset to defaults" button (left) and a blue "Save trading rules" button (right), plus a small "You have unsaved changes" line.
- Also show: a loading skeleton variant (shimmer rows) and an inline red error banner variant.

Tokens:
- Page background: white / dark slate-900
- Card background: slate-50 / dark slate-800, 1px slate-200/700 border, rounded-xl, 24px padding
- Primary accent: blue-600
- Text: slate-900 headings, slate-500 helper text
- Error: red-400 border, red-600 text, red-50 background
- Font: system sans-serif
- Border radius: rounded-lg inputs, rounded-xl cards

Context: data-dense personal wheel-strategy trading dashboard, Next.js 16, React 19, Tailwind CSS 4, class-based dark mode. Match a dense, utilitarian settings-form density — compact rows, small text, no decorative imagery.
```

---

## 17. Implementation notes for the Developer agent

1. **Confirm the §3 decision first.** Option B (tabbed Settings page) is recommended; Option A (long single section) is the fallback. The field-group design is identical either way — only the page wrapper differs. Do not start until the user has picked.
2. **Confirm against #156's `RulesConfig` model before wiring:** (a) percent convention — whole-percent assumed (§9); (b) `assignment_risk_review` type — enum `Off/Low/Medium/High` assumed (§4.4); (c) field key names exactly. If #156 isn't merged yet, this issue depends on it — sequence accordingly.
3. **Endpoint is intentionally abstracted** (§10.1). Build `getRulesConfig()` / `saveRulesConfig()` in `api/client.js` against whichever endpoint #156 ships. The component must not hard-code the `{key,value}` vs typed-route choice.
4. **Unset ≠ 0.** The four Optional fields (§8) save as `null` when blank. Empty-string is the only unset signal — `0` is a real value for some required fields. The component test for "Optional field renders empty and saves as unset without inventing a default" hangs on this.
5. **Reuse, don't fork:** Settings-card shell (`bg-slate-50`), `ConfirmDialog`, `react-hot-toast`, the existing button classes. Do not pull in `Card.jsx` / `StatCard.jsx`.
6. **Reconcile with #207.** #207 ships a V0.5.8.1 stopgap with a subset of these inputs (sizing cap + target yield). When this section lands, those stopgap inputs should be reconciled / removed — note the anchors, confirm with the user, out of scope to fix here but flag it in the PR.
7. **Tests** (per CLAUDE.md — every AC gets coverage on the implementing PR): component tests for field render (label + helper), whole-percent convention guard, boundary validation (`min<max`, ranges), and the Optional-unset-saves-as-null case; Playwright e2e for edit→save→reload→persists and invalid→save-fails→inline-generic-error; accessibility assertions for label association and `aria-invalid`/`aria-describedby`.
8. **Generic errors only** (CLAUDE.md): the save/load failure copy is fixed generic text — never interpolate an API exception.

---

## 18. Open questions

1. **§3 — Option A vs Option B.** Tabbed Settings page (recommended) vs long single section. Blocks layout; needs a decision before implementation.
2. **§4.4 — `assignment_risk_review` shape.** PRD gives default "High" but no value set. Enum `Off/Low/Medium/High` proposed; confirm against #156's `RulesConfig` model.
3. **§9 — percent convention.** Spec assumes whole-percent per #156. If #156 stores fractions, a conversion layer is needed in the form's load/save mapping.
4. **§10.1 — endpoint.** Generic `{key,value}` vs typed `/api/settings/rules` — undecided by design; resolved when #156 lands. Not a blocker for this spec.
5. **Sequencing vs #156.** This issue's form depends on #156's `rules_config` model and persistence. Confirm #156 merges first, or that the field keys/shape are frozen.
6. **§6 — `min_call_distance_pct` vs `min_call_distance_from_cost_basis_pct`.** Both are cost-basis-relative covered-call distance rules; #156 must define their distinct semantics (percentage margin vs hard floor) before this field's label and helper text can be finalised. An earlier draft's "from spot" description of `min_call_distance_pct` was a factual error, corrected per the #217 reconciliation of PRD #209.
