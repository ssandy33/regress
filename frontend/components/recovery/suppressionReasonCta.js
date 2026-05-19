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
    // Target yield is a genuine OKR — route to the Settings → Trading
    // Objectives tab via the `?tab=` deep link (issue #207, the same pattern
    // #235 introduced for the sizing cap). The old `/settings#okrs` anchor
    // dead-ended; #207 added the Trading Objectives tab as its destination.
    return { label: 'Set target yield →', href: '/settings?tab=objectives' };
  }
  return null;
}
