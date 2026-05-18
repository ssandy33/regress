// Maps a path's `suppression_reason` string to an inline CTA.
//
// Design spec §3.3 — string-match rules. The backend does not emit a
// structured suppression code in V0.5.8, so the mapping lives entirely on
// the frontend. Pure function so it can be exercised in isolation via the
// Playwright spec or a future node test.

export function suppressionReasonToCta(reason) {
  if (!reason || typeof reason !== 'string') return null;
  const low = reason.toLowerCase();
  if (low.includes('sizing cap') || low.includes('sizing rule')) {
    // The sizing cap is a Trading Rule (issue #156) — route to the Settings
    // → Trading Rules tab via the `?tab=rules` deep link (issue #235).
    return { label: 'Adjust cap →', href: '/settings?tab=rules' };
  }
  if (low.includes('target yield')) {
    // Target yield is a genuine OKR. Intentionally left pointing at
    // `/settings#okrs`: there is no Settings → OKRs UI until V1.1, so this
    // CTA still dead-ends — that half of #207 stays open and out of scope
    // for #235 (which only fixes the sizing-cap CTA).
    return { label: 'Set target yield →', href: '/settings#okrs' };
  }
  return null;
}
