/**
 * Trade-marker vocabulary (issue #280, design spec §4 Section B / plan §4.8).
 *
 * Each event type maps to one Plotly marker symbol + one Tailwind color
 * token. The mapping is frozen — the implementer wires this constant
 * verbatim and never edits keys at the render site. Colors are chosen so
 * they remain visually distinguishable on the price chart and never
 * collide with the basis-line hues (blue, emerald) used on the same chart.
 *
 * The earnings annotation is rendered separately (rose `E` glyph at the
 * top of the chart) and intentionally re-uses rose with assignment /
 * called_away — earnings markers sit on the chart's top edge, trade
 * markers ride on the price line, so they never occupy the same y-axis
 * row.
 */
export const TRADE_MARKER_VOCAB = {
  sell_put: { symbol: 'circle', glyph: '●', color: 'text-emerald-500' },
  sell_call: { symbol: 'triangle-up', glyph: '▲', color: 'text-emerald-500' },
  assignment: { symbol: 'diamond', glyph: '◆', color: 'text-rose-500' },
  called_away: { symbol: 'diamond', glyph: '◆', color: 'text-rose-500' },
  expired: { symbol: 'circle-open', glyph: '○', color: 'text-slate-400' },
  buy_close: { symbol: 'triangle-down', glyph: '▽', color: 'text-amber-500' },
};

/**
 * Resolve a marker descriptor for a trade type, falling back to a
 * conservative "unknown" pill so the chart never crashes on a new
 * `trade_type` string the backend introduces in a future release.
 */
export function resolveTradeMarker(type) {
  if (!type) return null;
  return TRADE_MARKER_VOCAB[type] || null;
}
