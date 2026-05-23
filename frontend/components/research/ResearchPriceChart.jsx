import dynamic from 'next/dynamic';
import { TRADE_MARKER_VOCAB } from './tradeMarkerVocabulary';

// Plotly is heavy + browser-only. Dynamic-import so the page shell
// renders the skeleton before the chart bundle arrives.
const Plot = dynamic(() => import('../charts/PlotlyChart'), { ssr: false });

/**
 * Section B + C — Price chart with basis lines, trade markers, and
 * earnings annotations (issue #280, design spec §4 Section B + C).
 *
 * Sections B and C share one chart by design:
 *   - Layer 1: daily close prices (slate line)
 *   - Layer 2: broker basis (blue, dotted) + adjusted basis (emerald, solid)
 *              — shape lines at fixed y-values
 *   - Layer 3: trade markers per `TRADE_MARKER_VOCAB`
 *   - Layer 4: earnings annotations (rose `E` glyphs at chart top with a
 *              dashed vertical line down to the price)
 *
 * Accessibility: a visually-hidden table below the chart (`research-b-sr-table`)
 * lists every trade and earnings event in chronological order, with the
 * date/type/detail columns the design spec §8 calls for. Screen readers
 * announce this; the chart wrapper has an explanatory `aria-label`.
 */

function FailureTile({ source, onRetry }) {
  return (
    <div data-testid="research-b-error" className="text-sm">
      <p className="text-amber-600 dark:text-amber-400">
        <span aria-hidden="true">⚠</span> We couldn&apos;t load this — retry
      </p>
      <p className="text-slate-500 dark:text-slate-400 mt-1">
        Source unavailable: {source || 'price source'}
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
      data-testid="research-b-skeleton"
      className="h-[360px] rounded-lg bg-slate-200 dark:bg-slate-700 animate-pulse"
      aria-busy="true"
    />
  );
}

function PlotlyImpl({ data }) {
  const prices = data?.prices || [];
  const dates = prices.map((p) => p.date);
  const closes = prices.map((p) => p.close);
  const broker = data?.basis?.broker ?? null;
  const adjusted = data?.basis?.adjusted ?? null;
  const tradeEvents = data?.trade_events || [];
  const earningsEvents = data?.earnings_events || [];

  const colorFor = (token) => {
    switch (token) {
      case 'text-emerald-500':
        return '#10b981';
      case 'text-rose-500':
        return '#f43f5e';
      case 'text-slate-400':
        return '#94a3b8';
      case 'text-amber-500':
        return '#f59e0b';
      default:
        return '#64748b';
    }
  };

  const tradesByType = tradeEvents.reduce((acc, ev) => {
    const key = ev.type;
    if (!acc[key]) acc[key] = [];
    acc[key].push(ev);
    return acc;
  }, {});

  const priceByDate = Object.fromEntries(prices.map((p) => [p.date, p.close]));

  const tradeTraces = Object.entries(tradesByType).map(([type, events]) => {
    const vocab = TRADE_MARKER_VOCAB[type];
    if (!vocab) return null;
    return {
      x: events.map((e) => e.date),
      y: events.map((e) => priceByDate[e.date] ?? null),
      type: 'scatter',
      mode: 'markers',
      name: type,
      marker: {
        symbol: vocab.symbol,
        size: 10,
        color: colorFor(vocab.color),
      },
      hoverinfo: 'x+name',
    };
  }).filter(Boolean);

  const traces = [
    {
      x: dates,
      y: closes,
      type: 'scatter',
      mode: 'lines',
      name: 'Close',
      line: { color: '#94a3b8', width: 1.5 },
      hovertemplate: '%{x|%Y-%m-%d} · $%{y:.2f}<extra></extra>',
    },
    ...tradeTraces,
  ];

  const shapes = [];
  if (broker !== null && broker !== undefined) {
    shapes.push({
      type: 'line',
      xref: 'paper',
      x0: 0,
      x1: 1,
      y0: broker,
      y1: broker,
      line: { color: '#3b82f6', width: 1, dash: 'dot' },
    });
  }
  if (adjusted !== null && adjusted !== undefined) {
    shapes.push({
      type: 'line',
      xref: 'paper',
      x0: 0,
      x1: 1,
      y0: adjusted,
      y1: adjusted,
      line: { color: '#10b981', width: 1.5 },
    });
  }
  // Earnings vertical dashes
  earningsEvents.forEach((ev) => {
    shapes.push({
      type: 'line',
      x0: ev.date,
      x1: ev.date,
      y0: 0,
      y1: 1,
      yref: 'paper',
      line: { color: '#fb7185', width: 1, dash: 'dash' },
    });
  });

  const annotations = earningsEvents.map((ev) => ({
    x: ev.date,
    y: 1,
    yref: 'paper',
    text: 'E',
    showarrow: false,
    font: { size: 11, color: '#fb7185', weight: 'bold' },
    yanchor: 'bottom',
  }));

  const layout = {
    paper_bgcolor: 'transparent',
    plot_bgcolor: 'transparent',
    margin: { l: 50, r: 16, t: 32, b: 36 },
    height: 360,
    hovermode: 'closest',
    showlegend: false,
    xaxis: {
      gridcolor: 'rgba(148,163,184,0.2)',
    },
    yaxis: {
      gridcolor: 'rgba(148,163,184,0.2)',
    },
    shapes,
    annotations,
  };

  return (
    <Plot
      data={traces}
      layout={layout}
      config={{ displayModeBar: false, responsive: true }}
      style={{ width: '100%', height: '360px' }}
    />
  );
}

function ScreenReaderTable({ data }) {
  const trades = data?.trade_events || [];
  const earnings = data?.earnings_events || [];
  const rows = [
    ...trades.map((t) => ({
      date: t.date,
      type: t.type,
      detail: `Strike ${t.strike ?? '—'}`,
    })),
    ...earnings.map((e) => ({
      date: e.date,
      type: 'earnings',
      detail: e.label || 'Quarterly earnings',
    })),
  ].sort((a, b) => (a.date < b.date ? -1 : 1));

  return (
    <table data-testid="research-b-sr-table" className="sr-only">
      <caption>Trade and earnings events on the price chart</caption>
      <thead>
        <tr>
          <th>Date</th>
          <th>Event type</th>
          <th>Detail</th>
        </tr>
      </thead>
      <tbody>
        {rows.map((r, i) => (
          <tr key={`${r.date}-${r.type}-${i}`}>
            <td>{r.date}</td>
            <td>{r.type}</td>
            <td>{r.detail}</td>
          </tr>
        ))}
      </tbody>
    </table>
  );
}

function Legend() {
  const entries = [
    { type: 'sell_put', label: 'Sell put' },
    { type: 'sell_call', label: 'Sell call' },
    { type: 'assignment', label: 'Assignment' },
    { type: 'expired', label: 'Expired' },
    { type: 'buy_close', label: 'Buy to close' },
  ];
  return (
    <div
      data-testid="research-b-legend"
      className="mt-2 flex flex-wrap gap-x-4 gap-y-1 text-xs text-slate-500 dark:text-slate-400"
    >
      {entries.map((e) => {
        const v = TRADE_MARKER_VOCAB[e.type];
        if (!v) return null;
        return (
          <span key={e.type} className={`inline-flex items-center ${v.color}`}>
            <span aria-hidden="true">{v.glyph}</span>
            <span className="ml-1">{e.label}</span>
          </span>
        );
      })}
    </div>
  );
}

export default function ResearchPriceChart({ data, loading, error, onRetry }) {
  return (
    <section
      data-testid="research-b"
      aria-labelledby="research-b-heading"
      className="rounded-xl border border-slate-200 dark:border-slate-700 bg-white dark:bg-slate-800 p-5"
    >
      <div className="flex items-center justify-between">
        <h2
          id="research-b-heading"
          className="text-xs font-semibold uppercase tracking-wide text-slate-500 dark:text-slate-400"
        >
          B · Price chart with basis &amp; events
        </h2>
        <button
          type="button"
          data-testid="research-b-window-selector"
          disabled
          title="Window picker coming soon"
          className="text-xs px-2 py-1 rounded border border-slate-200 dark:border-slate-700 text-slate-400 dark:text-slate-500 opacity-50 cursor-not-allowed"
        >
          1Y ▾
        </button>
      </div>

      <div className="mt-3">
        {loading && !data ? (
          <Skeleton />
        ) : error && !data ? (
          <FailureTile source="price source" onRetry={onRetry} />
        ) : data ? (
          <>
            <div
              data-testid="research-b-chart"
              aria-label={`Price chart for ${data.ticker || ''} with basis lines and ${
                (data.trade_events || []).length
              } trade events.`}
            >
              <PlotlyImpl data={data} />
            </div>
            <Legend />
            <ScreenReaderTable data={data} />
          </>
        ) : null}
      </div>
    </section>
  );
}
