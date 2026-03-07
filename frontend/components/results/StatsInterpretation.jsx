import { formatNumber, formatPercent } from '../../utils/formatters';

function interpretLinear(result, asset) {
  const slope = result.slope;
  const r2 = result.r_squared;
  const pSignificant = result.p_value < 0.05;

  // Rough annualized % (assuming daily data, ~252 trading days)
  const firstVal = result.actual_values[0];
  const annualizedPct = firstVal > 0 ? ((slope * 252) / firstVal * 100).toFixed(1) : 'N/A';

  const direction = slope > 0 ? 'appreciated' : 'declined';
  const strength = r2 > 0.8 ? 'strong' : r2 > 0.5 ? 'moderate' : 'weak';

  let text;
  if (!pSignificant) {
    text = `${asset} shows no statistically significant trend over this period (p-value: ${formatNumber(result.p_value, 4)}). The apparent ${direction.replace('d', 'ing')} trend explains only ${formatPercent(r2)} of price variation and may be due to random fluctuations.`;
  } else {
    text = `${asset} has ${direction} at approximately ${annualizedPct}% annually over this period, with the trend explaining ${formatPercent(r2)} of price variation. This is a ${strength} and statistically significant trend (p < 0.05).`;
  }

  // DW warning
  if (result.durbin_watson != null && (result.durbin_watson < 1.5 || result.durbin_watson > 2.5)) {
    text += ` Note: The Durbin-Watson statistic (${formatNumber(result.durbin_watson, 2)}) suggests autocorrelation in residuals, which may inflate the significance of the trend.`;
  }

  text += ' Correlation does not imply causation.';
  return text;
}

function interpretMultiFactor(result) {
  const factors = Object.entries(result.coefficients);
  const significant = factors.filter(([name]) => result.p_values[name] < 0.05);
  const r2 = result.r_squared;

  let text;
  if (significant.length === 0) {
    text = `None of the selected factors show a statistically significant relationship with the dependent variable. The model explains ${formatPercent(r2)} of the variation, but this may not be meaningful.`;
  } else {
    const descriptions = significant
      .sort((a, b) => Math.abs(b[1]) - Math.abs(a[1]))
      .map(([name, coef]) => {
        const direction = coef > 0 ? 'positive' : 'negative';
        const strength = Math.abs(result.p_values[name]) < 0.01 ? 'strongly' : 'moderately';
        return `${strength} correlated with ${name} (${direction} relationship)`;
      });

    const joined = descriptions.length === 1
      ? descriptions[0]
      : descriptions.slice(0, -1).join(', ') + ' and ' + descriptions[descriptions.length - 1];

    text = `The dependent variable is ${joined}. Together, these factors explain ${formatPercent(r2)} of the variation (Adjusted R²: ${formatPercent(result.adjusted_r_squared)}).`;
  }

  // Stationarity caveat
  if (result.stationarity) {
    const nonStationary = Object.entries(result.stationarity)
      .filter(([, v]) => !v.is_stationary)
      .map(([k]) => k === '__dependent__' ? 'the dependent variable' : k);
    if (nonStationary.length > 0) {
      text += ` Caution: ${nonStationary.join(', ')} ${nonStationary.length === 1 ? 'is' : 'are'} non-stationary (trending), which can produce spurious correlations.`;
    }
  }

  // DW warning
  if (result.durbin_watson != null && (result.durbin_watson < 1.5 || result.durbin_watson > 2.5)) {
    text += ` The Durbin-Watson statistic (${formatNumber(result.durbin_watson, 2)}) indicates autocorrelation in residuals, which may undermine model reliability.`;
  }

  // VIF warning
  if (result.vif) {
    const highVif = Object.entries(result.vif).filter(([, v]) => v >= 5);
    if (highVif.length > 0) {
      const names = highVif.map(([n, v]) => `${n} (VIF: ${formatNumber(v, 1)})`).join(', ');
      text += ` Multicollinearity detected: ${names}. Coefficient estimates for these factors may be unreliable.`;
    }
  }

  // Differenced mode note
  if (result._isDifferenced) {
    text += ' This analysis uses first-differenced data (period-over-period changes) to remove trends and test for genuine relationships.';
  }

  text += ' Correlation does not imply causation.';
  return text;
}

function interpretRolling(result) {
  const slopes = result.slope_over_time;
  const r2s = result.r_squared_over_time;
  const n = slopes.length;

  if (n < 2) return 'Insufficient data for rolling analysis interpretation.';

  const recentR2 = r2s[n - 1];
  const earlierR2 = r2s[Math.floor(n * 0.5)];
  const recentSlope = slopes[n - 1];

  const trendDirection = recentSlope > 0 ? 'upward' : 'downward';
  const trendStrength = recentR2 > 0.7 ? 'strong' : recentR2 > 0.4 ? 'moderate' : 'weak';

  let change = '';
  if (recentR2 > earlierR2 + 0.15) {
    change = `, strengthening from R² ${formatNumber(earlierR2, 2)} to ${formatNumber(recentR2, 2)}`;
  } else if (recentR2 < earlierR2 - 0.15) {
    change = `, weakening significantly from R² ${formatNumber(earlierR2, 2)} to ${formatNumber(recentR2, 2)}`;
  } else {
    change = ` with relatively stable trend strength (R² around ${formatNumber(recentR2, 2)})`;
  }

  return `The asset shows a ${trendStrength} ${trendDirection} trend in the most recent window${change}. Current slope: ${formatNumber(recentSlope, 4)} per period.`;
}

function interpretCompare(result) {
  if (!result.stats || result.stats.length === 0) return '';

  const sorted = [...result.stats].sort((a, b) => b.annualized_return - a.annualized_return);
  const best = sorted[0];
  const worst = sorted[sorted.length - 1];

  return `${best.identifier} had the highest annualized return at ${formatPercent(best.annualized_return)} with ${formatPercent(best.volatility)} volatility. ${worst.identifier} had the lowest at ${formatPercent(worst.annualized_return)}. ${sorted[0].r_squared > 0.7 ? `${sorted[0].identifier} showed the most consistent trend (R²: ${formatNumber(sorted[0].r_squared, 2)}).` : 'None of the assets showed a particularly consistent trend.'}`;
}

export default function StatsInterpretation({ result, mode, asset }) {
  if (!result) return null;

  let text = '';
  if (mode === 'linear') text = interpretLinear(result, asset);
  else if (mode === 'multi-factor') text = interpretMultiFactor(result);
  else if (mode === 'rolling') text = interpretRolling(result);
  else if (mode === 'compare') text = interpretCompare(result);

  if (!text) return null;

  return (
    <div className="px-4 py-3 bg-slate-50 dark:bg-slate-800/50 border border-slate-200 dark:border-slate-700 rounded-lg">
      <div className="text-xs font-medium text-slate-500 dark:text-slate-400 mb-1">Interpretation</div>
      <p className="text-sm text-slate-700 dark:text-slate-300 leading-relaxed">{text}</p>
    </div>
  );
}
