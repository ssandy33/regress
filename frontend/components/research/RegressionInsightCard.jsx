/**
 * Section E — Regression decomposition card (issue #280, design spec §4 Section E).
 *
 * Three blocks side-by-side:
 *   1. Plain-English summary (verbatim from the backend payload)
 *   2. Donut chart (native SVG — 4 wedges in fixed colors)
 *   3. Beta table (factor / beta / p-value / share-of-variance)
 *
 * The summary is rendered verbatim from `data.summary`; the rule set
 * lives in `backend/app/services/regression_summary.py`. The page never
 * runs its own NLG over the regression numbers.
 *
 * Donut color map (frozen — spec §4 Section E):
 *   - Market (SPY)  → blue-500
 *   - Sector (XL*)  → emerald-500
 *   - Rates (DGS10) → amber-500
 *   - Idiosyncratic → slate-400
 */

const FACTOR_COLOR = {
  market: '#3b82f6',
  sector: '#10b981',
  rates: '#f59e0b',
  idiosyncratic: '#94a3b8',
};

const FACTOR_BORDER = {
  market: 'border-blue-500',
  sector: 'border-emerald-500',
  rates: 'border-amber-500',
  idiosyncratic: 'border-slate-400',
};

function FailureTile({ source, onRetry }) {
  return (
    <div data-testid="research-e-error" className="text-sm">
      <p className="text-amber-600 dark:text-amber-400">
        <span aria-hidden="true">⚠</span> We couldn&apos;t load this — retry
      </p>
      <p className="text-slate-500 dark:text-slate-400 mt-1">
        Source unavailable: {source || 'regression'}
      </p>
      <button
        type="button"
        onClick={onRetry}
        className="mt-3 px-3 py-1.5 rounded-lg bg-slate-100 dark:bg-slate-700 text-slate-700 dark:text-slate-200 text-sm font-medium hover:bg-slate-200 dark:hover:bg-slate-600"
      >
        Retry
      </button>
    </div>
  );
}

function Skeleton() {
  return (
    <div
      data-testid="research-e-skeleton"
      className="space-y-3"
      aria-busy="true"
    >
      <div className="h-4 rounded bg-slate-200 dark:bg-slate-700 animate-pulse w-3/4" />
      <div className="grid grid-cols-1 md:grid-cols-2 gap-4 mt-3">
        <div className="h-44 rounded bg-slate-200 dark:bg-slate-700 animate-pulse" />
        <div className="h-44 rounded bg-slate-200 dark:bg-slate-700 animate-pulse" />
      </div>
    </div>
  );
}

function Donut({ wedges, size = 180 }) {
  // wedges: [{ name, share, color }] — share ∈ [0,1]
  const total = wedges.reduce((sum, w) => sum + (w.share || 0), 0) || 1;
  const radius = size / 2;
  const strokeWidth = 28;
  const inner = radius - strokeWidth;
  const circumference = 2 * Math.PI * (radius - strokeWidth / 2);

  // Pre-compute each wedge's dash offset via a fold so we don't mutate
  // a closure variable across the .map callbacks (react-hooks/immutability).
  const wedgeArcs = wedges.reduce((acc, w) => {
    const length = (w.share / total) * circumference;
    const offset = acc.length
      ? acc[acc.length - 1].offset + acc[acc.length - 1].length
      : 0;
    acc.push({ ...w, length, offset });
    return acc;
  }, []);

  const srLabel = wedges
    .map((w) => `${w.name} ${(w.share * 100).toFixed(0)}%`)
    .join(', ');

  return (
    <svg
      width={size}
      height={size}
      viewBox={`0 0 ${size} ${size}`}
      role="img"
      aria-label={srLabel}
      data-testid="research-e-donut"
    >
      <circle
        cx={radius}
        cy={radius}
        r={radius - strokeWidth / 2}
        fill="none"
        stroke="rgb(226 232 240)"
        strokeWidth={strokeWidth}
      />
      <g transform={`rotate(-90 ${radius} ${radius})`}>
        {wedgeArcs.map((w) => {
          const dash = `${w.length} ${circumference - w.length}`;
          return (
            <circle
              key={w.name}
              cx={radius}
              cy={radius}
              r={radius - strokeWidth / 2}
              fill="none"
              stroke={w.color}
              strokeWidth={strokeWidth}
              strokeDasharray={dash}
              strokeDashoffset={-w.offset}
            />
          );
        })}
      </g>
      <circle
        cx={radius}
        cy={radius}
        r={inner}
        fill="white"
        className="dark:fill-slate-800"
      />
    </svg>
  );
}

function formatBeta(value) {
  if (value === null || value === undefined) return '—';
  const sign = value < 0 ? '−' : '';
  return `${sign}${Math.abs(value).toFixed(2)}`;
}

function formatPValue(value) {
  if (value === null || value === undefined) return '—';
  if (value > 0.05) {
    return (
      <span className="italic text-slate-400" title="Not statistically significant (p > 0.05)">
        n.s.
      </span>
    );
  }
  return value.toFixed(3);
}

function formatShare(value) {
  if (value === null || value === undefined) return '—';
  return `${Math.round(value * 100)}%`;
}

function BetaRow({ rowId, color, name, label, beta, pValue, share, omitted }) {
  return (
    <tr
      data-testid={rowId}
      className={`border-l-4 ${color} bg-white dark:bg-slate-800`}
    >
      <td className="py-1.5 px-2 text-sm text-slate-700 dark:text-slate-200">
        {name}
        {label ? (
          <span className="ml-1 text-slate-500 dark:text-slate-400 text-xs">
            ({label})
          </span>
        ) : null}
        {omitted ? (
          <span className="ml-1 italic text-slate-400 text-xs">
            (omitted: sector unmapped)
          </span>
        ) : null}
      </td>
      <td className="py-1.5 px-2 text-sm tabular-nums text-slate-700 dark:text-slate-200">
        {omitted ? '—' : formatBeta(beta)}
      </td>
      <td className="py-1.5 px-2 text-sm tabular-nums text-slate-700 dark:text-slate-200">
        {omitted ? '—' : formatPValue(pValue)}
      </td>
      <td className="py-1.5 px-2 text-sm tabular-nums text-right text-slate-700 dark:text-slate-200">
        {formatShare(share)}
      </td>
    </tr>
  );
}

/**
 * Map a backend `factor` row to the {key,label,name} we render under.
 * The backend names factors by ticker (e.g. "SPY", "XLF", "DGS10"); the
 * frontend groups them under the four canonical buckets per the spec.
 */
function categorizeFactor(factor) {
  const name = (factor?.name || '').toUpperCase();
  if (name === 'SPY' || name === '^GSPC') {
    return { key: 'market', label: name, displayName: 'Market' };
  }
  if (name === 'DGS10' || name.endsWith('YIELD')) {
    return { key: 'rates', label: name, displayName: 'Rates' };
  }
  if (name.startsWith('XL') || factor?.role === 'sector') {
    return { key: 'sector', label: name, displayName: 'Sector' };
  }
  return { key: 'sector', label: name, displayName: 'Sector' };
}

export default function RegressionInsightCard({ data, loading, error, onRetry }) {
  let body;
  if (loading && !data) {
    body = <Skeleton />;
  } else if (error && !data) {
    body = <FailureTile source="regression" onRetry={onRetry} />;
  } else if (data) {
    const factors = data.factors || [];
    const idioShare = data.idiosyncratic_share ?? Math.max(0, 1 - (data.r_squared ?? 0));
    const sectorOmitted = !!data.sector_omitted;

    // Bucket factors by category so each row in the table maps to a wedge.
    const categorized = factors.map((f) => ({ ...categorizeFactor(f), raw: f }));
    const find = (key) => categorized.find((c) => c.key === key);
    const market = find('market');
    const sector = find('sector');
    const rates = find('rates');

    const wedges = [
      {
        name: 'market',
        share: market?.raw?.share ?? 0,
        color: FACTOR_COLOR.market,
      },
      ...(sectorOmitted || !sector
        ? []
        : [
            {
              name: 'sector',
              share: sector.raw?.share ?? 0,
              color: FACTOR_COLOR.sector,
            },
          ]),
      {
        name: 'rates',
        share: rates?.raw?.share ?? 0,
        color: FACTOR_COLOR.rates,
      },
      {
        name: 'idiosyncratic',
        share: idioShare,
        color: FACTOR_COLOR.idiosyncratic,
      },
    ];

    const basket = (data.basket || []).join(' + ');
    body = (
      <>
        <p
          data-testid="research-e-summary"
          className="text-sm text-slate-700 dark:text-slate-200"
        >
          {data.summary || '—'}
        </p>
        <div className="mt-4 grid grid-cols-1 md:grid-cols-[auto_1fr] items-center gap-6">
          <div className="flex justify-center">
            <Donut wedges={wedges} />
          </div>
          <div className="overflow-x-auto">
            <table
              data-testid="research-e-beta-table"
              className="w-full text-sm border-separate border-spacing-y-1"
            >
              <thead className="text-xs uppercase tracking-wide text-slate-500 dark:text-slate-400">
                <tr>
                  <th className="text-left px-2">Factor</th>
                  <th className="text-left px-2">Beta</th>
                  <th className="text-left px-2">p-value</th>
                  <th className="text-right px-2">Share</th>
                </tr>
              </thead>
              <tbody>
                <BetaRow
                  rowId="research-e-row-market"
                  color={FACTOR_BORDER.market}
                  name="Market"
                  label={market?.label}
                  beta={market?.raw?.beta}
                  pValue={market?.raw?.p_value}
                  share={market?.raw?.share}
                />
                <BetaRow
                  rowId="research-e-row-sector"
                  color={FACTOR_BORDER.sector}
                  name="Sector"
                  label={sectorOmitted ? '—' : sector?.label}
                  beta={sector?.raw?.beta}
                  pValue={sector?.raw?.p_value}
                  share={sector?.raw?.share}
                  omitted={sectorOmitted}
                />
                <BetaRow
                  rowId="research-e-row-rates"
                  color={FACTOR_BORDER.rates}
                  name="Rates"
                  label={rates?.label || 'DGS10'}
                  beta={rates?.raw?.beta}
                  pValue={rates?.raw?.p_value}
                  share={rates?.raw?.share}
                />
                <BetaRow
                  rowId="research-e-row-idiosyncratic"
                  color={FACTOR_BORDER.idiosyncratic}
                  name="Idiosyncratic"
                  label={null}
                  beta={null}
                  pValue={null}
                  share={idioShare}
                />
              </tbody>
            </table>
          </div>
        </div>
        <p
          data-testid="research-e-basket-caption"
          className="mt-3 text-xs text-slate-500 dark:text-slate-400"
        >
          {basket ? `Basket: ${basket} · ` : ''}
          {data.window || '1Y'} daily · n={data.sample_size ?? '—'} · R²=
          {data.r_squared !== null && data.r_squared !== undefined
            ? data.r_squared.toFixed(2)
            : '—'}
        </p>
      </>
    );
  }

  return (
    <section
      data-testid="research-e"
      aria-labelledby="research-e-heading"
      className="rounded-xl border border-slate-200 dark:border-slate-700 bg-white dark:bg-slate-800 p-5"
    >
      <h2
        id="research-e-heading"
        className="text-xs font-semibold uppercase tracking-wide text-slate-500 dark:text-slate-400"
      >
        E · What drives this stock?
      </h2>
      <div className="mt-3">{body}</div>
    </section>
  );
}
