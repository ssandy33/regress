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
    return { label: 'Adjust cap →', href: '/settings#okrs' };
  }
  if (low.includes('target yield')) {
    return { label: 'Set target yield →', href: '/settings#okrs' };
  }
  return null;
}
