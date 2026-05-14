// Canonical column-header tooltip copy for the Options Scanner table.
//
// Keyed by the same `field` strings used by StrikeTable's sort handler so
// the tooltip can be rendered next to the matching column without duplication.
// Each entry follows the 3-part shape spec'd in
// `frontend/design-specs/scanner-education-v0.5.7.md` §4.2:
//   - definition: what the metric measures, in plain English
//   - range: what's a good number for wheel-style strategies
//   - whyItMatters: why the trader should care about this column
//
// Keep sentences short and clarity-first. No jargon without a translation.

export const SCANNER_COLUMN_TOOLTIPS = {
  strike: {
    definition:
      "The price at which the option contract obligates a transaction at expiration.",
    range:
      "For wheel strategies: at or above your cost basis for covered calls (10% rule); at or below current price for cash-secured puts.",
    whyItMatters:
      "The strike is the line in the sand — call gets assigned above it, put gets assigned below it.",
  },
  dte: {
    definition: "Days to expiration — calendar days remaining on the contract.",
    range:
      "Wheel sweet spot is 25–45 DTE. Shorter = faster theta decay but less premium. Longer = more risk window for assignment.",
    whyItMatters:
      "Theta (time decay) accelerates in the last ~30 days. The right DTE balances premium income against tying up capital.",
  },
  bid_ask: {
    definition: "Highest current buy price (bid) and lowest current sell price (ask).",
    range:
      "Look for spreads under 5% of the mid-price. Wider spreads cost you on slippage.",
    whyItMatters:
      "A wide bid/ask means you give up real money every time you enter or exit. Liquidity matters more than chasing the headline premium.",
  },
  delta: {
    definition:
      "The option price's sensitivity to a $1 move in the underlying. Roughly the market-implied probability the option ends in the money.",
    range:
      "For wheel strategies: 0.20 to 0.35. Lower = safer, less premium. Higher = more income, more assignment risk.",
    whyItMatters:
      "Higher delta means more premium but a higher chance of assignment. Stay in your comfort zone.",
  },
  open_interest: {
    definition:
      "The number of outstanding contracts at this strike that have not been closed or exercised.",
    range:
      "Look for 500+ contracts. 100+ is acceptable on less liquid names. Below 50 is usually too thin to trade comfortably.",
    whyItMatters:
      "Higher open interest means tighter bid/ask spreads and easier exits. Thin contracts can cost you 5–10% on slippage.",
  },
  total_premium: {
    definition:
      "The dollar premium per contract — what you receive (for sells) or pay (for buys) for one contract of 100 shares.",
    range:
      "Use it alongside Return% and Ann.% — a high-dollar premium can be low-return if the capital tied up is large.",
    whyItMatters:
      "This is the actual cash that hits your account. Multiply by contracts to see total income on the trade.",
  },
  return_on_capital_pct: {
    definition: "Premium received divided by the capital required to back the trade.",
    range:
      "Target 1% or more per trade. Below 0.5% rarely justifies the assignment risk for short-DTE wheels.",
    whyItMatters:
      "Two trades with the same dollar premium can have very different return-on-capital if the strikes are far apart. This normalizes them.",
  },
  annualized_return_pct: {
    definition:
      "The return on capital scaled to a full year. Lets you compare 7-day premiums against 45-day premiums on equal footing.",
    range:
      "Target 20%+ annualized for wheel candidates. Below 15% is rarely worth the assignment risk.",
    whyItMatters:
      "A $1 premium on a 7-DTE contract beats a $1.50 premium on 45-DTE every time, once you scale it.",
  },
  distance_from_price_pct: {
    definition:
      "How far the strike sits above (covered call) or below (cash-secured put) the current underlying price, in percent.",
    range:
      "Covered calls: aim for 5–15% above current price. Cash-secured puts: 5–15% below.",
    whyItMatters:
      "Distance is your buffer. Bigger buffer = lower assignment risk but also lower premium. This column shows the trade-off directly.",
  },
};
