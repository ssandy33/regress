import Link from 'next/link';

/**
 * NextActionCard — one action card inside ``NextActionsSection``.
 *
 * Visual treatment is driven by ``action.priority`` (``"P0" | "P1" | "P2"``).
 * Severity is encoded in the ``[P0]`` / ``[P1]`` / ``[P2]`` badge text + a
 * leading glyph (``⛔`` / ``⚠`` / ``ℹ``), with color as reinforcement only —
 * spec §2.2 and the AC in #152.
 *
 * Card root is a ``<Link>`` when ``action.cta.kind === "link"`` and a
 * ``<button>`` when ``action.cta.kind === "inline"`` (e.g.
 * ``data.cache_very_stale`` calls ``refreshStaleCache()`` in place). The
 * trailing ``→`` is ``aria-hidden`` decoration.
 *
 * V1.0.4 (issue #240): an optional ``action.tone`` (``"opportunity" |
 * "warning"``, default ``"warning"``) drives the *valence* of the card.
 * ``priority`` keeps doing exactly one job — urgency/ranking + the ``[P1]``
 * badge — while ``tone === "opportunity"`` overrides the border/bg/glyph to
 * emerald + ``✓`` so a profit-take win does not render as a warning. Every
 * existing card omits ``tone`` and is byte-identical.
 */

const PRIORITY_VISUALS = {
  P0: {
    badgeClass: 'bg-red-600 text-white',
    borderClass: 'border-red-300 dark:border-red-700',
    bgClass: 'bg-red-50 dark:bg-red-900/20',
    glyph: '⛔',
    glyphClass: 'text-red-600 dark:text-red-300',
  },
  P1: {
    badgeClass: 'bg-yellow-500 text-slate-900',
    borderClass: 'border-yellow-300 dark:border-yellow-700',
    bgClass: 'bg-yellow-50 dark:bg-yellow-900/20',
    glyph: '⚠',
    glyphClass: 'text-yellow-700 dark:text-yellow-300',
  },
  P2: {
    badgeClass: 'bg-slate-200 dark:bg-slate-600 text-slate-700 dark:text-slate-200',
    borderClass: 'border-slate-200 dark:border-slate-700',
    bgClass: 'bg-white dark:bg-slate-800',
    glyph: 'ℹ',
    glyphClass: 'text-slate-500 dark:text-slate-400',
  },
};

// Tone overrides — `priority` ranks urgency; `tone` carries valence (§4.3
// Q6). Only `opportunity` is a non-default tone: it repaints the border,
// background, and glyph emerald so a profit-take win is not miscolored as a
// warning. `badgeClass` is intentionally NOT overridden — the `[P1]` badge
// stays priority-driven. No new token: emerald is already in the palette.
const TONE_VISUALS = {
  opportunity: {
    borderClass: 'border-emerald-300 dark:border-emerald-700',
    bgClass: 'bg-emerald-50 dark:bg-emerald-900/20',
    glyph: '✓',
    glyphClass: 'text-emerald-600 dark:text-emerald-300',
  },
};

function subjectLine(subject) {
  if (!subject) return null;
  const ticker = subject.ticker;
  const amount = subject.amount;
  if (!ticker && !amount) return null;
  if (ticker && amount) return `${ticker}  ${amount}`;
  return ticker || amount;
}

function CardBody({ action, visuals }) {
  const subject = subjectLine(action.subject);
  return (
    <>
      <div className="flex items-center gap-2">
        <span aria-hidden="true" className={`text-base leading-none ${visuals.glyphClass}`}>
          {visuals.glyph}
        </span>
        <span
          className={`inline-flex items-center px-1.5 py-0.5 text-xs font-semibold rounded ${visuals.badgeClass}`}
        >
          [{action.priority}]
        </span>
        <span className="text-sm font-semibold text-slate-900 dark:text-white">
          {action.title}
        </span>
      </div>
      {subject && (
        <div className="mt-2 text-sm tabular-nums text-slate-700 dark:text-slate-200">
          {subject}
        </div>
      )}
      {action.reason && (
        <div className="mt-1 text-sm text-slate-600 dark:text-slate-300">
          {action.reason}
        </div>
      )}
      {action.trigger_basis === 'raw' && (
        <div
          data-testid="next-actions-card-basis-tag"
          className="mt-1 text-xs text-slate-500 dark:text-slate-400"
        >
          fired on raw basis
        </div>
      )}
      <div className="mt-3 text-sm font-medium text-blue-600 dark:text-blue-400">
        {action.cta?.label}
        <span aria-hidden="true"> →</span>
      </div>
    </>
  );
}

export default function NextActionCard({ action, onInlineCta }) {
  const priorityVisuals = PRIORITY_VISUALS[action.priority] || PRIORITY_VISUALS.P2;
  // tone defaults to "warning" — every existing card is byte-identical.
  const toneOverride = TONE_VISUALS[action.tone];
  const visuals = toneOverride
    ? { ...priorityVisuals, ...toneOverride }
    : priorityVisuals;
  const baseClasses = `block text-left p-4 border rounded-xl transition-colors hover:shadow-sm focus:outline-none focus-visible:ring-2 focus-visible:ring-blue-500 ${visuals.bgClass} ${visuals.borderClass}`;
  // Use the unique ``action.id`` (e.g. ``position.cc_candidate.aapl``) so a
   // family that emits multiple cards (e.g. 3 ITM legs) does not collide on
   // ``data-testid``. The family slug is exposed separately on
   // ``data-action-id`` for filtering.
  const testId = `next-actions-card-${action.id}`;
  // R6 (#422 / ADR #416) — optional passthrough mirroring the `action.tone`
  // pattern. Only the raw-fired largest-loser card carries it; omitted (attr
  // absent) on every other card so they stay byte-identical.
  const triggerBasis = action.trigger_basis || undefined;

  if (action.cta?.kind === 'inline') {
    return (
      <button
        type="button"
        onClick={() => onInlineCta?.(action)}
        data-testid={testId}
        data-priority={action.priority}
        data-action-id={action.action_id}
        data-trigger-basis={triggerBasis}
        className={`${baseClasses} w-full`}
      >
        <CardBody action={action} visuals={visuals} />
      </button>
    );
  }

  return (
    <Link
      href={action.cta?.href || '#'}
      data-testid={testId}
      data-priority={action.priority}
      data-action-id={action.action_id}
      data-trigger-basis={triggerBasis}
      className={baseClasses}
    >
      <CardBody action={action} visuals={visuals} />
    </Link>
  );
}
