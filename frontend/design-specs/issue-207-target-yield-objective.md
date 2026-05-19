# Design Spec: Settings — Trading Objectives tab (Target Yield)

- **Issue:** [#207 — Recovery Plan "Set target yield →" CTA dead-ends — no way to set a target yield](https://github.com/ssandy33/regress/issues/207)
- **Milestone:** V1.0.3 — Recovery Plan bug fixes
- **Date:** 2026-05-18
- **Author:** Designer agent
- **Status:** Draft — for user review before implementation
- **Scope:** Frontend visual + structural spec for a **new third Settings tab, "Trading Objectives"**, holding a **single field — Target Yield**. This is the **V1.0.3 minimal stopgap** that gives the dead-ending "Set target yield →" recovery CTA a real destination and un-suppresses the Recovery Plan's *Sell & redeploy* path. It is **explicitly NOT** the full V1.1 OKR Scorecard — see §1.2 for the line. The backend (`okr_target_yield` read/write plumbing) is referenced where it drives UI states; the only net-new backend ask is a way to *read the current value back* (§7).

---

## 1. Overview

### 1.1 The bug being fixed

On the Recovery Plan page (`/positions/[id]/recovery`), the **Sell & redeploy** path is permanently suppressed with `⚠ Target yield not configured` and a **"Set target yield →"** CTA. The CTA routes to `/settings#okrs` — an anchor that does not exist. There is no UI anywhere in the app to set a target yield, so the Sell & redeploy path computes nothing (capital tied up / months to breakeven / opportunity cost all blank) for every position, and its self-remediation CTA dead-ends.

`#235` (v1.0.2) fixed the sibling "Adjust cap →" CTA and introduced the `/settings?tab=…` deep-link pattern. This spec applies the same pattern to the target-yield half: a real Settings destination, reached via `/settings?tab=objectives`.

### 1.2 What this stopgap is — and is not

| | This V1.0.3 stopgap | The V1.1 OKR Scorecard |
|---|---|---|
| Surface | One new Settings tab, **one field** | A full OKR config surface — multiple objectives, scoring, history |
| Storage | The existing flat `okr_target_yield` app-setting key | The typed `okr_config` namespace (ADR-001) |
| Goal | Un-dead-end the CTA; let Sell & redeploy compute | Full objectives/scorecard product |

The flat `okr_target_yield` key already exists and is already consumed by the backend recovery engine (`backend/app/routers/positions.py`, `recovery_engine.py`). This stopgap **does not invent storage** — it builds the *missing input UI* for a key the backend already reads. When V1.1 builds the typed `okr_config` layer, this flat key migrates into it; the tab and field designed here are the natural seed of the V1.1 "Objectives" surface, so V1.1 extends rather than replaces.

### 1.3 The hard constraint — objective, not rule

**Target yield is an objective / OKR, not a Trading Rule.** It must read as an objective and must NOT be folded into the existing "Trading Rules" tab. `#235` just corrected exactly this OKR-vs-rule mislabeling (the sizing cap was wrongly treated as an OKR; it is a rule). The inverse error — folding an OKR into Trading Rules — is just as wrong. The whole reason this spec creates a *separate tab* rather than adding a field to `TradingRulesSection` is to keep that line clean. ADR-001 (Discussion #210) is the canonical authority: target yield is an OKR; the sizing cap is a rule.

The two concepts differ in kind:
- A **Trading Rule** is a *constraint* on what you may do ("never tie up more than X%").
- An **Objective / OKR** is a *target* you are aiming at ("the redeployed capital should earn X%").

Target yield is the second. The tab label, the section heading, and the field copy must all carry that framing.

---

## 2. Stack context (detected)

Detected from the repo before authoring — confirmed against the live `#158` / `#235` implementation, not assumed:

- **Framework:** Next.js 16.2.4, App Router (`frontend/app/`).
- **Language:** JavaScript / JSX. `jsconfig.json` only — **no TypeScript.** Data shapes below are JSDoc-style notes.
- **Styling:** Tailwind CSS v4 (`@tailwindcss/postcss`). No `tailwind.config.js` — default token scale. Dark mode is class-based (`.dark` on `<html>`), re-bound via `@custom-variant dark` in `app/globals.css`.
- **Toasts:** `react-hot-toast` — already wired in `SettingsPage.jsx` and `TradingRulesSection.jsx`.
- **Settings page is already tabbed.** `components/settings/SettingsPage.jsx` shipped page-scoped tabs in `#158` (Option B): a `general` tab and a `rules` tab, with `?tab=` deep-link lazy-init added in `#235`. **Its own comments anticipate this exact tab** — `SettingsPage.jsx:36` ("A V1.1 'Trading OKRs' tab slots in here with zero rework") and `:197` ("'Trading OKRs' joins here in V1.1"). This spec fills that slot, **now**, for V1.0.3.
- **Backend already consumes the key.** `okr_target_yield` is read in `positions.py` via `_get_app_setting` and parsed with `float(...)`; the recovery engine multiplies `capital * target_yield` and renders it with `_format_pct` (`pct * 100`). **The stored value is a fraction** (e.g. `0.12` = 12%). See §4 — this is the crux of the unit decision.
- **Generic setting write already exists.** `PUT /api/settings` accepts any `{key, value}` and upserts the `app_settings` row; the `updateSetting(key, value)` helper in `api/client.js` wraps it. Writing `okr_target_yield` needs **no new write endpoint**.
- **No `docs/DESIGN_SYSTEM.md`** exists. Tokens in §10 were derived from the codebase and from the `#158` / `#234` specs, which are the canonical reference for the Settings surface.

---

## 3. Tab — "Trading Objectives"

### 3.1 Label — confirmed: **"Trading Objectives"**

The milestone plan proposed "Trading Objectives". **Confirmed — adopt it.** Rationale:

- It is structurally parallel to the existing **"Trading Rules"** tab (`Trading ___`), which makes the tab bar read as a coherent set: *General · Trading Rules · Trading Objectives*. The shared "Trading " prefix signals these two tabs are siblings — both about *how you trade* — while "Rules" vs "Objectives" carries the constraint-vs-target distinction of §1.3.
- "Objectives" is the correct register for an OKR (the **O** in OKR). The `SettingsPage.jsx` comments say "Trading OKRs"; **do not use the literal string "OKRs" in the tab label** — "OKRs" is internal jargon, "Objectives" is the plain-language word a trader reads. The code comments can keep saying OKR; the *UI* says Objectives.
- It scales to V1.1: when the OKR Scorecard adds more objectives, the tab is already correctly named — V1.1 adds fields under the same tab, no rename.

Rejected alternatives: "OKRs" (jargon), "Goals" (less precise than "Objectives", and not parallel with "Rules"), "Targets" (conflates with the field name "Target Yield" — the tab would read "Targets ▸ Target Yield").

### 3.2 Position in the tab bar — **after "Trading Rules"**

The tab bar becomes a three-tab strip, in this order:

```
[ General ]  [ Trading Rules ]  [ Trading Objectives ]
```

- **General** stays first — it is the catch-all infrastructure tab and the default landing tab.
- **Trading Objectives** goes **last, immediately after Trading Rules.** The two "Trading ___" tabs sit adjacent so the sibling relationship is visually obvious.
- The active-tab default is unchanged: `general` unless a `?tab=` param says otherwise.

### 3.3 Deep-link param — `?tab=objectives`

`SettingsPage.jsx` already lazy-inits `activeTab` from `searchParams.get('tab')` (`#235`). Today it only recognises `'rules'`. Extend the lazy initializer to also recognise `'objectives'`:

```js
const [activeTab, setActiveTab] = useState(() => {
  const t = searchParams?.get('tab');
  if (t === 'rules') return 'rules';
  if (t === 'objectives') return 'objectives';
  return 'general';
});
```

The recovery CTA (`suppressionReasonCta.js`) is updated in the same PR to point the target-yield reason at `/settings?tab=objectives` (§8). Query params are the established codebase pattern; URL hashes (`#okrs`) are used nowhere — the dead `#okrs` anchor is the bug.

### 3.4 Tab button — markup mirrors the existing two

The new tab button is the existing two with the label and ids swapped. It reuses the existing `tabClass(tab)` helper unchanged.

```jsx
<button
  type="button"
  role="tab"
  data-testid="settings-objectives-tab"
  aria-selected={activeTab === 'objectives'}
  onClick={() => setActiveTab('objectives')}
  className={tabClass('objectives')}
>
  Trading Objectives
</button>
```

> **Test-ID naming note.** The existing tabs are inconsistent — `settings-tab-general` (verb-first) vs `settings-rules-tab` (noun-first). The issue specifies `settings-objectives-tab`, which matches the **newer** `settings-rules-tab` form. Adopt `settings-objectives-tab` as the issue states. Do not "fix" the older `settings-tab-general` id in this PR — that is unrelated churn and would break any `#158`-era e2e spec.

The tab panel:

```jsx
{activeTab === 'objectives' ? (
  <div role="tabpanel" aria-label="Trading Objectives">
    <TradingObjectivesSection />
  </div>
) : activeTab === 'rules' ? (
  /* …existing rules panel… */
) : loading ? ( /* … */ ) : ( /* …general panel… */ )}
```

`TradingObjectivesSection` mounts independently of the `general`-tab data load — like `TradingRulesSection`, it owns its own fetch and is not gated by the page-level `loading` flag.

---

## 4. Unit convention — RESOLVED

This is the decision the issue flags as "must resolve". It has two halves: what the **field accepts/displays**, and what the **save layer stores**.

### 4.1 The two units in play

- **Backend storage:** `okr_target_yield` is stored as a **fraction**. Confirmed by reading the code, not assumed:
  - `recovery_engine.py:_format_pct` → `f"{pct * 100:.0f}%"` — multiplies by 100 to display, so the stored value is a fraction.
  - `recovery_engine.py` → `annual_return = freed_capital * target_yield` — multiplied directly against a dollar amount, which only works if it is a fraction.
  - So `okr_target_yield = "0.12"` means **12%**.
- **Existing Trading Rules UI:** standardises on **whole-percent** — `rules_config` stores `25` to mean 25%, and `RuleField` does no human↔fraction conversion (`RuleField.jsx` docblock is explicit about this).

These two conventions disagree. The stopgap field must pick one for the *user-facing input* and convert at the boundary.

### 4.2 Decision — **field accepts WHOLE PERCENT; save layer converts to/from the stored fraction**

**Confirmed — adopt the issue's recommended convention.** The Target Yield field:

- **Displays and accepts a whole percent.** The trader types `12` for 12%. The input carries a trailing **`%` adornment** (the same `RuleField` `suffix: '%'` treatment used by every percent field in Trading Rules).
- **The save layer converts.** On save: `fraction = wholePercent / 100` → `updateSetting('okr_target_yield', String(fraction))`. On load: `wholePercent = fraction * 100` → shown in the input.

Rationale:

1. **Consistency with the rest of Settings.** Every percentage the trader edits today (in Trading Rules) is whole-percent with a `%` affix. Asking them to type `0.12` in one lone field — when every neighbouring percent field takes `12` — is an inconsistency that *will* cause mis-entry (a trader types `12` meaning 12%, the backend reads it as 1200%). Whole-percent is the convention the user already has in their hands.
2. **A `%` affix only makes sense next to a whole number.** "`0.12` %" reads as 0.12 percent. "`12` %" reads as 12 percent. The affix and the value must agree.
3. **The conversion is trivial, total, and lossless** at the one boundary (`/100` on save, `*100` on load) — and it is isolated in the section component, exactly as `RuleField`'s docblock prescribes ("If the model ever switched to fractions, the conversion would live in `TradingRulesSection`'s load/save mapping, not here"). This spec puts that conversion in `TradingObjectivesSection`.
4. **The backend storage does not change.** `okr_target_yield` stays a fraction; the recovery engine is untouched. The conversion is purely a frontend presentation concern. This keeps the stopgap tight and risk-free on the backend.

**Displayed unit: whole percent, with a trailing `%` affix.** Stored unit: fraction. The conversion lives only in `TradingObjectivesSection`'s load/save mapping.

### 4.3 Precision

- The input accepts **decimals** — `12.5` is valid (→ stored `0.125`). The backend `float` parse accepts it and `_format_pct` rounds to whole-percent for *display in the recovery banner* (`:.0f`), which is acceptable — the stored precision is preserved, only the recovery-banner label rounds. This matches Trading Rules' percent fields, which also accept decimals (§4.4 of the `#234` spec).
- Step: `step="any"` on the number input (the `RuleField` default) so the spinner does not force integers.
- On load, `fraction * 100` can produce a float artefact (`0.12 * 100` → `12.000000000000002` in JS). The load mapping must clean this: `Number((fraction * 100).toFixed(4))` → `12`. Specified again in §7 and §11.

---

## 5. The Target Yield field

A single field, rendered inside one Settings card. It reuses the visual vocabulary of `RuleField` (label row, number input, trailing affix, helper text, inline error) — but because the section has exactly **one** field and a different save model (one flat key, not a typed `rules_config` document), it does **not** reuse the `RuleField`/`rulesFieldCatalog` machinery wholesale. See §9 for the build-vs-reuse call. Visually, it is indistinguishable from a Trading Rules percent field.

### 5.1 Anatomy

```
┌─ Card: Trading Objectives ────────────────────────────────────────────┐
│  Trading Objectives                                                    │
│  The targets your strategy aims for. Used by the Recovery Plan.         │
│  ──────────────────────────────────────────────────────────────────────│
│                                                                         │
│  Target yield                                                          │
│  ┌────────────────────────────────────────────────────┐ ┌─────┐        │
│  │  12                                                 │ │  %  │        │
│  └────────────────────────────────────────────────────┘ └─────┘        │
│  The annual return you expect redeployed capital to earn. The Recovery │
│  Plan uses this to score the Sell & redeploy path — how a position's    │
│  trapped capital would perform if freed and put to work elsewhere.      │
│                                                                         │
│  [ Save objective ]            You have unsaved changes                 │
└─────────────────────────────────────────────────────────────────────────┘
```

### 5.2 Copy

| Element | Copy |
|---|---|
| Tab label | **Trading Objectives** |
| Section heading (`<h2>`) | **Trading Objectives** |
| Section description | **"The targets your strategy aims for. Used by the Recovery Plan."** |
| Field label | **Target yield** |
| Field affix | **`%`** (trailing) |
| Field placeholder | **`e.g. 12`** — a non-numeric example, so an empty field reads as genuinely unset, not as a real `0` (the same honest-unset principle as `RuleField`'s Optional fields). |
| Helper text | **"The annual return you expect redeployed capital to earn. The Recovery Plan uses this to score the Sell & redeploy path — how a position's trapped capital would perform if freed and put to work elsewhere."** |
| Save button | **"Save objective"** |

The helper text does the work the issue asks for in requirement 2 — it explicitly states that *this objective drives the Recovery Plan's Sell & redeploy path*. That sentence is the connective tissue: a trader arriving via the "Set target yield →" CTA reads the helper and immediately understands why they are here.

### 5.3 Input affordance

- `<input type="number" inputMode="decimal" step="any">` — identical to `RuleField`'s number input.
- Trailing `%` affix box: `inline-flex items-center px-2.5 text-xs text-slate-500 dark:text-slate-400 border border-l-0 border-slate-300 dark:border-slate-600 rounded-r-lg bg-slate-100 dark:bg-slate-800` — the exact affix markup `RuleField` renders for trailing-suffix fields. The input itself gets `rounded-r-none` so input + affix read as one control.
- Width: the input is **not** full-bleed. A yield is a 2–4 character value; a full-width input looks unbalanced. Constrain the input+affix group to a sensible max width (`max-w-[12rem]` / `w-48`) left-aligned, with the helper text below at full card width. This differs from `RuleField` (which is full-width because it sits in a dense multi-field grid) — a one-field card can afford a right-sized input.

### 5.4 Field framing — why it reads as an objective

Per §1.3, the framing must say "objective", not "rule":

- The section heading is **"Trading Objectives"** (not "OKRs", not "Goals").
- The description — *"The targets your strategy aims for"* — names them as *targets*, the language of objectives.
- The helper uses *"expect … to earn"* and *"score"* — aspirational/measurement language, not constraint language. A Trading Rule helper says "the most you may…"; this says "the return you expect…".
- The save button says **"Save objective"** (singular — there is one), parallel to Trading Rules' "Save trading rules" but unmistakably a different noun.

---

## 6. States

The section mirrors the state conventions of `TradingRulesSection.jsx` exactly — same loading / load-error / saving / save-success / save-failure shapes, same generic-copy discipline (CLAUDE.md), simplified to one field. Because it is one field there is **no** "Reset to defaults" control and **no** per-group machinery.

### 6.1 Loading

The section's own fetch (read the current `okr_target_yield`, §7) is in flight. Render a skeleton: the card shell with a `h-3 w-24` label bar and a `h-9 w-48` input bar, both `bg-slate-200 dark:bg-slate-700 animate-pulse` — the `SkeletonRow` pattern from `TradingRulesSection.jsx`, scoped to one row.
`data-testid="settings-objectives-loading"`.

### 6.2 Unset / empty — the first-run state

This is the state every trader sees until they set a value, and the state the recovery CTA delivers them into. The backend returns no `okr_target_yield` (or empty string) → `target_yield` is `None` → Sell & redeploy is suppressed.

- The input renders **blank** with the `e.g. 12` placeholder. Blank is honest "unset" — never pre-fill a `0` or a guessed default. `0` is not even a valid value (§7 — `0.0 <` exclusive), and a guessed default would silently un-suppress the recovery path with a number the trader never chose.
- Below the helper, an **unset note** — the analogue of `TradingRulesSection`'s `settings-rules-defaults-note`:
  > **"No target yield set yet. Until you set one, the Recovery Plan's Sell & redeploy path stays unavailable."**
  Styling: `text-sm text-slate-500 dark:text-slate-400`. This closes the loop — the trader who clicked "Set target yield →" sees, in plain words, the consequence of the empty field and what setting it unlocks.
- `data-testid="settings-objectives-unset-note"`.
- The Save button is **disabled** while the field is blank (nothing to save) — consistent with `TradingRulesSection`'s `canSave` gate (`dirty && no errors`).

### 6.3 Populated — a value is set

Backend returns a fraction → the load mapping converts to whole-percent (§4.2, §11) → the input shows e.g. `12`. The unset note is gone. The Save button is disabled until the field is edited (`dirty`). When not dirty and a value exists, show a passive **"Last saved {time}"** line — the `TradingRulesSection` pattern (`lastSaved.toLocaleTimeString`).

### 6.4 Saving

The trader clicked Save and the `PUT /api/settings` call is in flight.
- The input is `disabled` (`disabled:opacity-50`), the Save button shows **"Saving…"** and is disabled. The `RuleField` already styles a disabled input; mirror that.
- `data-testid` on the button stays `settings-objectives-save`; the implementer may add `data-state="saving"` for e2e.

### 6.5 Save success

The `PUT` resolved.
- `toast.success('Target yield saved')` — `react-hot-toast`, already wired.
- A transient inline green check next to the button for ~2.5s — the exact `settings-rules-save-success` SVG-check pattern from `TradingRulesSection.jsx:431`. `data-testid="settings-objectives-save-success"`.
- The field's value is re-derived from the save response / re-fetch and becomes the new "saved" baseline; `dirty` clears; the "Last saved {time}" line updates.
- **Cross-surface consequence (not rendered here, but the reason the feature exists):** with a value now stored, the next load of any Recovery Plan page un-suppresses Sell & redeploy. The stopgap does not need to live-refresh the recovery page — a normal navigation/reload picks it up. (If the user is *deep-linked* from the recovery CTA, see §8.3.)

### 6.6 Save failure

The `PUT` rejected (network, server error).
- A dismissible red banner above the field — the exact `settings-rules-save-error` treatment from `TradingRulesSection.jsx:307`: `bg-red-50 dark:bg-red-900/30 border border-red-200 dark:border-red-800 text-red-700 dark:text-red-300`, `role="alert"`, a "Dismiss" button.
- Copy — **fixed generic text**, per CLAUDE.md ("never return raw exception messages"): **"Couldn't save your target yield. Please try again."**
- `toast.error('Failed to save target yield')`.
- The entered value is **retained** in the input (not cleared) so the trader can retry without re-typing.
- `data-testid="settings-objectives-save-error"`.

### 6.7 Load failure

The section's read of `okr_target_yield` (§7) rejected.
- The card renders a red error block with a **Retry** button — the exact `settings-rules-load-error` treatment from `TradingRulesSection.jsx:264`.
- Copy: **"Couldn't load your target yield."**
- Retry re-runs the fetch.
- `data-testid="settings-objectives-load-error"`.

---

## 7. Validation

The value is a yield percentage. The backend bound on the **stored fraction** is `0.0 < fraction <= 1.0` (per the issue). Converted to the **whole-percent the field accepts**, that is:

> **Valid: greater than 0 and up to 100 (`0 < x ≤ 100`).** `0` is invalid (a 0% target yield is meaningless and the backend rejects it). `100` is valid (a 100% target — aggressive, but in-bounds). Blank is invalid *for save* (you cannot save an empty objective) but is the legitimate **unset** display state (§6.2) — a blank field simply disables Save rather than showing an error.

This is **exactly the existing `pctOpen100` validation kind** in `rulesValidation.js` (`n <= 0 || n > 100`), with the existing generic message:

> **"Enter a percentage greater than 0 and up to 100."**

### 7.1 Validation behaviour

- **Reuse `validateScalar('pctOpen100', value)`** from `components/settings/rulesValidation.js` — do not write a new validator. It is a pure exported function; importing it into `TradingObjectivesSection` is clean reuse and guarantees the stopgap agrees with the Trading Rules percent fields and (transitively) with the backend Pydantic validators that `rulesValidation.js` mirrors. Note `pctOpen100` treats blank as invalid (`MSG.number`) when `optional=false`; the section treats blank specially (it is the unset state) — so the section checks `isBlank()` *first* and only runs `validateScalar` on a non-blank value. `isBlank` is also exported from `rulesValidation.js`.
- **When the error shows:** on blur after the trader has touched the field, and live once a save has been attempted — the `touched` / `revalidate` pattern from `TradingRulesSection.jsx`.
- **Error display:** the inline `RuleField`-style message — `text-xs text-red-600 dark:text-red-400 mt-1`, `role="alert"`, and the input gets the red-ring treatment (`border-red-400 dark:border-red-500 focus:ring-red-500`, `aria-invalid="true"`). `data-testid="settings-objectives-target-yield-error"`.
- **Save gate:** Save is disabled when the field is blank OR invalid OR not dirty OR currently saving — the `canSave` shape from `TradingRulesSection`.
- **Inline message before save:** the issue's requirement 5 ("inline validation message before save") is satisfied — the message appears on blur, before the trader ever reaches the Save button, exactly as in Trading Rules.

### 7.2 Backend read — the one net-new backend ask

⚠️ **DECISION NEEDED — implementation constraint, recommended option in bold.**

The generic `GET /api/settings` returns a **fixed `SettingsResponse` Pydantic model** (`backend/app/routers/settings.py:38`) that does **not** include `okr_target_yield`. So the new section **cannot read the current value back via the existing `getSettings()` helper.** The *write* side is fine (`PUT /api/settings` with `{key, value}` is generic and already works); only the *read* is missing. The section needs the current value to render the populated state (§6.3) and to know whether to show the unset note (§6.2).

Options:

- **(a) Add `okr_target_yield` to the `SettingsResponse` model.** One field on an existing Pydantic model, read with the existing `_get(...)` helper in `get_settings`. The frontend's existing `getSettings()` helper then carries it for free. **✅ Recommended** — smallest, most idiomatic change; `SettingsResponse` is already the home for assorted app settings (`default_date_range_years`, `theme`). The field would be `okr_target_yield: float | None` (the stored fraction; the frontend converts to whole-percent per §4.2).
- (b) A dedicated `GET /api/settings/okr` endpoint. Heavier; parallels `GET /api/settings/rules` but a one-key read does not justify a typed sub-resource for a *stopgap* (the V1.1 OKR Scorecard may well introduce `/api/settings/okr` — but that is V1.1's call, not this stopgap's).
- (c) Generic key read (`GET /api/settings/{key}`). No such endpoint exists; adding a generic getter is broader surface than needed.

**Recommendation: (a).** It is one line on `SettingsResponse` + one line in `get_settings`. The frontend then reads via the existing `getSettings()`; no new client helper. This is a backend touch but a minimal one, and it is genuinely required — without a read path the section cannot render its populated/unset distinction. Flag for the user; this is the only backend change the stopgap needs beyond what already exists.

> The data-shape and load/save mapping in §11 assume option (a). If the user picks (b) or (c), only the client helper name in §9 / §11 changes.

---

## 8. The recovery CTA — closing the dead-end

The `suppressionReasonToCta` function in `frontend/components/recovery/suppressionReasonCta.js` maps the `target yield` suppression reason to a dead `/settings#okrs` link. This PR updates that one mapping.

### 8.1 The change

```js
if (low.includes('target yield')) {
  // Target yield is an OKR/objective. Routes to Settings → Trading Objectives
  // via the ?tab= deep link (the pattern #235 introduced for the sizing cap).
  return { label: 'Set target yield →', href: '/settings?tab=objectives' };
}
```

- The **label is unchanged** — "Set target yield →" is still correct copy.
- Only the `href` changes: `/settings#okrs` → `/settings?tab=objectives`.
- The stale code comment in `suppressionReasonCta.js` (lines 18–21, which explains *why* the link intentionally dead-ends) must be **replaced** — it now describes resolved behaviour, and leaving it would be misleading dead documentation.

### 8.2 No other recovery-page change

The Recovery Plan page, `RecoveryPathCard`, and the suppression banner are otherwise untouched by this spec. `RecoveryPathCard.jsx:179` already renders `cta.href` into an anchor with `data-testid="recovery-path-card-{slug}-suppression-cta"` — it just follows the new href. Once a target yield is set and the recovery page reloads, the backend stops emitting the `target yield` suppression reason for Sell & redeploy, so the CTA naturally disappears and the path's metrics populate. No frontend logic needed for that transition — it falls out of the backend already consuming `okr_target_yield`.

### 8.3 Round-trip back to the recovery page — out of scope, noted

A trader deep-linked from the CTA, who sets and saves a yield, currently has to navigate back to the recovery page manually. A "← Back to recovery" return link would be a nice touch but requires passing the originating position id through the deep link (e.g. `?tab=objectives&from=/positions/SOFI/recovery`). **This is deliberately out of scope for the V1.0.3 stopgap** — it is a polish item, the issue's AC does not ask for it, and it adds a parameter-threading surface. Flagged as open question §13 Q2 for V1.1. The stopgap's job is to make the destination *exist and work*; the return trip is a normal browser back-button away.

---

## 9. Component mapping

| UI element | Component | Status | Notes |
|---|---|---|---|
| "Trading Objectives" tab button + panel | `components/settings/SettingsPage.jsx` | **Edit** | Add the third tab button (§3.4), extend the `?tab=` lazy-init to recognise `'objectives'` (§3.3), add the `activeTab === 'objectives'` panel branch. |
| Trading Objectives section | `components/settings/TradingObjectivesSection.jsx` | **Create** | New component — the card, the one field, all six states (§6). The single new component this spec introduces. |
| Target-yield field row | inline in `TradingObjectivesSection` | **Create (inline)** | One label + number input + `%` affix + helper + inline error. Visually a `RuleField`, but built inline — see the build-vs-reuse note below. |
| Validation | `components/settings/rulesValidation.js` | **Reuse** | Import `validateScalar` (kind `pctOpen100`) and `isBlank`. No new validation code. |
| Setting write | `frontend/api/client.js` → `updateSetting` | **Reuse** | `updateSetting('okr_target_yield', String(fraction))`. The generic `PUT /api/settings` already exists. |
| Setting read | `frontend/api/client.js` → `getSettings` | **Reuse (after backend §7a)** | Once `okr_target_yield` is added to `SettingsResponse` (§7 option a), `getSettings()` carries it. No new client helper. |
| CTA mapping | `components/recovery/suppressionReasonCta.js` | **Edit** | One `href`: `/settings#okrs` → `/settings?tab=objectives` (§8). Replace the stale comment. |
| Toasts | `react-hot-toast` | **Reuse** | Save success / failure. |
| Backend — settings read | `backend/app/routers/settings.py` `SettingsResponse` + `get_settings` | **Edit** | Add `okr_target_yield: float | None` (§7a). The only backend change. |

**Build-vs-reuse — why `TradingObjectivesSection` is a new component and does NOT reuse `RuleField`/`rulesFieldCatalog`:**

`RuleField` is reusable in principle, but its whole ecosystem (`rulesFieldCatalog.js`, `configToForm`/`formToConfig`/`validateForm` in `TradingRulesSection`) is built around a **typed multi-field `rules_config` document** read/written through `GET`/`PUT /api/settings/rules`. Target yield is **one flat `app_settings` key** with a **fraction↔percent conversion** at the boundary. Threading a single OKR key through the `rules_config` catalog and form-mapping machinery would (a) drag a fraction-valued OKR into the whole-percent `rules_config` model the catalog assumes, and (b) blur the very rule-vs-objective line §1.3 exists to protect. So:

- **Do not** add the field to `rulesFieldCatalog.js` or render it via `TradingRulesSection`.
- **Do** build `TradingObjectivesSection` as a small standalone component that *visually matches* `RuleField` (same label row, input, `%` affix, helper, error markup — copy the classes) and *reuses the pure validators* from `rulesValidation.js`.
- Reusing `RuleField` as the inner field *renderer* is acceptable if the implementer prefers (it takes plain `value`/`onChange`/`suffix`/`error` props and is catalog-agnostic). But it is a one-field section; inlining the ~20 lines of field markup is equally fine and avoids importing a component whose docblock is all about `rules_config`. **Either is acceptable; the spec does not mandate one.** What is mandated: no `rulesFieldCatalog` entry, no `TradingRulesSection` coupling.

---

## 10. Design tokens applied

No `docs/DESIGN_SYSTEM.md` — tokens derived from the codebase and the `#158` / `#234` specs (canonical for the Settings surface). Tailwind v4 default scale. Every token below is already in use in `SettingsPage.jsx` / `TradingRulesSection.jsx` / `RuleField.jsx` — this section introduces **no new token**.

| Token | Value | Usage |
|---|---|---|
| Card shell | `bg-slate-50 dark:bg-slate-800` + `border border-slate-200 dark:border-slate-700` + `rounded-xl p-6` | The Trading Objectives card |
| Section heading | `text-lg font-semibold text-slate-900 dark:text-white` | "Trading Objectives" `<h2>` |
| Section description | `text-sm text-slate-500 dark:text-slate-400` | The description + the divider `border-b border-slate-200 dark:border-slate-700 pb-4` under it |
| Field label | `text-sm text-slate-700 dark:text-slate-300` | "Target yield" `<label>` |
| Number input | `px-3 py-2 text-sm border rounded-lg bg-white dark:bg-slate-700 text-slate-900 dark:text-slate-100 focus:ring-2 focus:ring-blue-500` | The yield input |
| Trailing `%` affix | `inline-flex items-center px-2.5 text-xs text-slate-500 dark:text-slate-400 border border-l-0 border-slate-300 dark:border-slate-600 rounded-r-lg bg-slate-100 dark:bg-slate-800` | The `%` adornment box |
| Helper text | `text-xs text-slate-500 dark:text-slate-400 mt-1` | Field helper |
| Unset note | `text-sm text-slate-500 dark:text-slate-400` | "No target yield set yet…" (§6.2) |
| Tab button — active | `bg-blue-600 text-white` (via existing `tabClass`) | Active "Trading Objectives" tab |
| Tab button — inactive | `text-slate-600 dark:text-slate-400 hover:bg-slate-100 dark:hover:bg-slate-800` | Inactive tab |
| Primary button | `bg-blue-600 text-white rounded-lg hover:bg-blue-700 disabled:bg-blue-400 disabled:cursor-not-allowed` | "Save objective" |
| Validation error | `border-red-400 dark:border-red-500 focus:ring-red-500`, `text-red-600 dark:text-red-400` | Invalid yield (existing `RuleField` treatment) |
| Save-error banner | `bg-red-50 dark:bg-red-900/30 border border-red-200 dark:border-red-800 text-red-700 dark:text-red-300 rounded-lg px-4 py-3` | Save-failure banner (§6.6) |
| Save-success check | `text-green-600 dark:text-green-400` SVG check | Transient success indicator (§6.5) |
| Skeleton | `bg-slate-200 dark:bg-slate-700 rounded animate-pulse` | Loading state (§6.1) |

---

## 11. Data shape

JSDoc-style (the project is JSX). The stopgap touches one flat `app_settings` key.

```js
/**
 * The stored value. `app_settings` row, key "okr_target_yield".
 * Stored as a FRACTION string — "0.12" means 12%. Consumed as a fraction by
 * the backend recovery engine (recovery_engine.py multiplies capital * yield).
 * Absent / "" / null  ==>  no target yield set ==> Sell & redeploy suppressed.
 * Backend bound on the fraction: 0.0 < value <= 1.0.
 */

/**
 * After §7 option (a): the field carried on the existing SettingsResponse.
 * @typedef {Object} SettingsResponse
 * @property {?number} okr_target_yield   - the stored FRACTION (e.g. 0.12), or null when unset.
 *                                          (…plus the existing fields: theme, default_date_range_years, etc.)
 */
```

**Load mapping (fraction → whole-percent for the input):**

```js
// settings.okr_target_yield is a fraction or null.
const fraction = settings.okr_target_yield;
const formValue =
  fraction === null || fraction === undefined
    ? ''                                        // unset — blank input, show unset note
    : String(Number((fraction * 100).toFixed(4)));  // 0.12 -> "12", clean float artefacts
```

**Save mapping (whole-percent input → fraction string):**

```js
// formValue is the whole-percent string the trader typed, already validated 0 < x <= 100.
const fraction = Number(formValue) / 100;          // "12" -> 0.12
await updateSetting('okr_target_yield', String(fraction));   // PUT /api/settings {key,value}
```

The `toFixed(4)` on load is required — `0.12 * 100` is `12.000000000000002` in JS floating point; without the clean-up the input would show a long ugly decimal. Four places is ample headroom for any realistic yield precision.

---

## 12. Test-ID inventory

Pattern `{component}-{element}`, consistent with `#158` / `#234` and the issue's requirement 1 (`settings-objectives-tab`).

| Test ID | Element |
|---|---|
| `settings-objectives-tab` | The "Trading Objectives" tab button. **(Issue requirement 1 — exact id.)** |
| `settings-objectives-loading` | The loading-skeleton container (§6.1). |
| `settings-objectives-section` | The Trading Objectives section root (the form/card). |
| `settings-objectives-target-yield` | The target-yield **number input**. |
| `settings-objectives-target-yield-error` | The inline validation error message (§7.1). |
| `settings-objectives-unset-note` | The "No target yield set yet…" note shown in the unset state (§6.2). |
| `settings-objectives-save` | The "Save objective" button. May carry `data-state="saving"` for e2e. |
| `settings-objectives-save-success` | The transient green-check success indicator (§6.5). |
| `settings-objectives-save-error` | The dismissible save-failure banner (§6.6). |
| `settings-objectives-load-error` | The load-failure block with Retry (§6.7). |

Unchanged / reused: `settings-tab-general`, `settings-rules-tab` (existing tabs — not renamed, §3.4). The recovery CTA test id `recovery-path-card-{slug}-suppression-cta` is unchanged — only the `href` it carries changes (§8).

---

## 13. Open questions

1. **§7 — the backend read path (the one real decision).** `GET /api/settings` does not currently return `okr_target_yield`, so the section cannot read the value back. **Recommended: option (a) — add `okr_target_yield: float | None` to the `SettingsResponse` model** (one line on the model + one line in `get_settings`). Confirm before implementation; the section's populated/unset states depend on it. This is the only backend change the stopgap needs.
2. **§8.3 — return-to-recovery link.** A trader deep-linked from the recovery CTA must currently use the browser back button to return. A "← Back to recovery" link is possible but needs the originating position id threaded through the deep link. **Recommended: defer to V1.1** — out of scope for the V1.0.3 stopgap; the issue AC does not ask for it.
3. **§4.3 — integer-only entry.** The field accepts decimals (`12.5`), consistent with the Trading Rules percent fields. The backend `_format_pct` rounds to whole-percent *for the recovery-banner label only* — stored precision is kept. If the product owner wants whole-integer-only entry, that is a small validation tweak (reject non-integers); **default assumption: accept decimals.**
4. **V1.1 migration.** When the OKR Scorecard builds the typed `okr_config` namespace, the flat `okr_target_yield` key migrates into it. The tab ("Trading Objectives") and this section are designed as the seed of that surface — V1.1 should *extend* `TradingObjectivesSection` (add objectives), not replace it. This is a note for V1.1 planning, not a V1.0.3 decision.

---

## 14. Implementation notes for the Developer agent

1. **Three files change, one is created, one backend file changes.** Edit `SettingsPage.jsx` (third tab + `?tab=objectives` lazy-init + panel branch), create `TradingObjectivesSection.jsx`, edit `suppressionReasonCta.js` (one href + replace the stale comment). Backend: add one field to `SettingsResponse` and read it in `get_settings` (§7a — confirm with the user first per §13 Q1).
2. **Unit conversion lives in `TradingObjectivesSection` only** (§4.2, §11). The field is whole-percent; storage is a fraction; convert `*100` on load (with `toFixed(4)` clean-up) and `/100` on save. The backend and `RuleField`'s whole-percent assumption are both untouched.
3. **Do not fold this into Trading Rules** (§1.3, §9). No `rulesFieldCatalog.js` entry, no coupling to `TradingRulesSection`. Target yield is an objective; ADR-001 (#210) is the authority. `#235` corrected the inverse mislabeling — do not reintroduce it.
4. **Reuse the validators, not the catalog** (§7.1, §9). Import `validateScalar('pctOpen100', …)` and `isBlank` from `rulesValidation.js`. Check `isBlank` first (blank = unset, not an error), then `validateScalar` on a non-blank value. No new validation code.
5. **Mirror `TradingRulesSection`'s state machinery** (§6) — loading skeleton, load-error + Retry, dirty-gated Save, saving-disabled, transient success check, dismissible save-error banner, "Last saved {time}". Simplified to one field: no Reset-to-defaults, no per-group cards.
6. **Generic error copy only** (CLAUDE.md). Save failure → "Couldn't save your target yield. Please try again." Load failure → "Couldn't load your target yield." Never surface a raw exception.
7. **Blank is the honest unset state** (§6.2) — never pre-fill `0` or a guessed default. `0` is out of bounds (`0 < x`), and a guessed default would silently un-suppress the recovery path with a number the trader never chose. Unset → blank input + the unset note + disabled Save.
8. **The CTA fix is one line + a comment rewrite** (§8). `/settings#okrs` → `/settings?tab=objectives`. Delete the now-false "intentionally left pointing at…" comment block in `suppressionReasonCta.js`.
9. **Tab test-id is `settings-objectives-tab`** exactly (issue requirement 1) — matches the newer `settings-rules-tab` form. Do not rename the older `settings-tab-general`; that is unrelated churn.
10. **Tests** (CLAUDE.md — every AC gets coverage on the PR):
    - **Backend pytest:** `okr_target_yield` round-trips through `PUT /api/settings` and is returned by `GET /api/settings` (after §7a); the recovery endpoint un-suppresses Sell & redeploy once `okr_target_yield` is set (capital tied up / months to breakeven / opportunity cost populate) — this is AC bullet 3, and it exercises the existing `positions.py` path.
    - **Frontend Playwright (`frontend/e2e/`):** the "Trading Objectives" tab is reachable from the tab bar and via `/settings?tab=objectives`; the "Set target yield →" CTA on a suppressed Recovery Plan path navigates to the Trading Objectives tab (no dead `#okrs`); entering a whole-percent value and saving persists it; reload shows the saved value; an out-of-range value (`0`, `150`) shows the inline error and blocks Save; the unset state shows the unset note.
    - **Conversion unit test:** `12` (input) ↔ `0.12` (stored) round-trips, and the `toFixed(4)` load mapping cleans `0.12 * 100`.
11. **`?tab=objectives` lazy-init** — extend, do not rewrite, the existing `useState` initializer in `SettingsPage.jsx` (§3.3). The lazy-init runs once on mount; later in-tab clicks are not re-overridden — that existing behaviour is correct and unchanged.
12. **Reconcile docs** — `#235` and the `#158` spec / mock describe the two-tab Settings page. They are historical; note in the PR that `#207` adds the third tab. `SettingsPage.jsx`'s own comments (lines 36, 197) already forecast this tab — update them from "V1.1" / "Trading OKRs" to reflect that the tab shipped in V1.0.3 as "Trading Objectives".

---

## 15. Figma Make prompt

```
Design a new "Trading Objectives" tab for the Settings page of Regress, a
data-dense wheel-strategy options-trading dashboard.

Context: the Settings page already has two tabs — "General" and "Trading Rules".
Add a third tab, "Trading Objectives", immediately after "Trading Rules". It holds
a single objective field. Match the existing Settings page density and visual
weight exactly — this tab must look like a sibling of the Trading Rules tab.

Layout (single card inside the tab panel):
- Section heading "Trading Objectives" with a description line
  "The targets your strategy aims for. Used by the Recovery Plan." and a thin
  divider under it.
- One field: label "Target yield", a number input constrained to ~12rem wide
  (left-aligned, not full bleed) with a trailing "%" adornment box fused to the
  input's right edge. Placeholder text "e.g. 12".
- Helper text under the input: "The annual return you expect redeployed capital
  to earn. The Recovery Plan uses this to score the Sell & redeploy path."
- A primary "Save objective" button, with an "unsaved changes" hint beside it.

Show four states stacked: (1) unset/empty — blank input, plus a muted note
"No target yield set yet. Until you set one, the Recovery Plan's Sell & redeploy
path stays unavailable.", Save disabled; (2) populated — input shows "12",
"Last saved" line; (3) inline validation error — input "0" with a red ring and
message "Enter a percentage greater than 0 and up to 100."; (4) save-failure —
a dismissible red banner "Couldn't save your target yield. Please try again."

Tokens (dark mode is the default):
- Page / body background: rgb(15 23 42)  (slate-900)
- Card background: rgb(30 41 59)  (slate-800), border slate-700, rounded-xl, p-6
- Primary accent / active tab / Save button: blue-600 (#2563eb)
- Body text: slate-100; secondary text: slate-400; helper text: slate-500
- Affix box background: slate-800; input background: slate-700
- Error: red ring border-red-400, message text red-400, banner red-900/30
- Font: ui-sans-serif / system-ui stack
- Border radius: rounded-lg on inputs, rounded-xl on cards

Tech context: data-dense engineering dashboard, Next.js 16, React 19,
Tailwind CSS v4. Match the existing Settings tab bar and Trading Rules card
chrome.
```
