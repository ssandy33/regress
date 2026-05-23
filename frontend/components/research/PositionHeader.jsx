import Link from 'next/link';

/**
 * Position header (issue #280, design spec §3).
 *
 * Renders the ticker, name, sector pill, basis metadata, and the three
 * link-out pills (Recovery / Scan CCs / Trade ledger). The link-outs are
 * intentionally styled as **secondary outline pills** — they are
 * navigation, not primary actions, per spec §3.
 *
 * Sticky behavior: the header does not stick on scroll. Spec §1 calls
 * this out — link-outs are not primary actions and shouldn't pin to the
 * viewport.
 */

function formatBasis(value) {
  if (value === null || value === undefined) return null;
  return `$${Number(value).toFixed(2)}`;
}

function formatDate(value) {
  if (!value) return null;
  // The journal returns ISO 8601 — slice to YYYY-MM-DD.
  return String(value).slice(0, 10);
}

function LinkPill({ href, testId, label }) {
  return (
    <Link
      href={href}
      data-testid={testId}
      className="inline-flex items-center px-3 py-1.5 rounded-lg border border-slate-300 dark:border-slate-600 bg-white dark:bg-slate-800 text-sm font-medium text-slate-700 dark:text-slate-200 hover:bg-slate-50 dark:hover:bg-slate-700"
    >
      {label}
      <span aria-hidden="true">&nbsp;→</span>
    </Link>
  );
}

export default function PositionHeader({ position, business }) {
  if (!position) return null;
  const id = position.id;
  const ticker = position.ticker;
  const name = business?.name || '';
  const sector = business?.sector || position.sector || null;
  const broker = formatBasis(position.broker_cost_basis);
  const adjusted = formatBasis(position.adjusted_cost_basis);
  const openedAt = formatDate(position.opened_at);
  const shares = position.shares ?? 0;

  return (
    <div
      data-testid="research-header"
      className="rounded-xl border border-slate-200 dark:border-slate-700 bg-white dark:bg-slate-800 p-4"
    >
      <div className="flex items-baseline gap-3 flex-wrap">
        <h1
          data-testid="research-header-ticker"
          className="text-2xl font-semibold text-slate-900 dark:text-white"
        >
          {ticker}
        </h1>
        <span
          data-testid="research-header-name"
          className="text-base text-slate-500 dark:text-slate-400"
        >
          {name}
        </span>
        {sector && (
          <span
            data-testid="research-header-sector-pill"
            className="inline-block px-2 py-0.5 text-xs rounded-full bg-slate-100 dark:bg-slate-700 text-slate-700 dark:text-slate-200"
          >
            {sector}
          </span>
        )}
      </div>
      <p
        data-testid="research-header-basis"
        className="mt-1 text-sm text-slate-500 dark:text-slate-400"
      >
        {`${shares} sh`}
        {adjusted ? ` · basis ${adjusted} (adj)` : ''}
        {broker ? ` · ${broker} (broker)` : ''}
        {openedAt ? ` · open since ${openedAt}` : ''}
      </p>
      <div className="mt-3 flex flex-wrap gap-2">
        <LinkPill
          testId="research-header-recovery-link"
          href={`/positions/${encodeURIComponent(id)}/recovery`}
          label="Recovery plan"
        />
        <LinkPill
          testId="research-header-scanner-link"
          href={`/options?ticker=${encodeURIComponent(ticker)}`}
          label="Scan CCs"
        />
        <LinkPill
          testId="research-header-journal-link"
          href={`/journal?position=${encodeURIComponent(id)}`}
          label="Trade ledger"
        />
      </div>
    </div>
  );
}
