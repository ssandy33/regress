import { formatNumber, formatPercent, formatPValue, pValueColor } from '../../utils/formatters';

function StatsSection({ title, first, children }) {
  return (
    <div className={!first ? 'pt-4 border-t border-slate-200 dark:border-slate-700' : ''}>
      <h4 className="text-[11px] font-semibold uppercase tracking-wider text-slate-400 dark:text-slate-500 mb-3">
        {title}
      </h4>
      {children}
    </div>
  );
}

function StatCard({ label, value, tooltip, colorClass }) {
  return (
    <div className="bg-white dark:bg-slate-800 border border-slate-200 dark:border-slate-700 rounded-lg p-4 relative group">
      <div className="text-xs text-slate-500 dark:text-slate-400 mb-1">{label}</div>
      <div className={`text-lg font-semibold ${colorClass || 'text-slate-900 dark:text-white'}`}>
        {value}
      </div>
      {tooltip && (
        <div className="absolute bottom-full left-1/2 -translate-x-1/2 mb-2 px-3 py-2 bg-slate-800 dark:bg-slate-600 text-white text-xs rounded-lg opacity-0 group-hover:opacity-100 transition-opacity pointer-events-none whitespace-nowrap z-10">
          {tooltip}
        </div>
      )}
    </div>
  );
}

function dwColor(dw) {
  if (dw === null || dw === undefined) return '';
  return (dw >= 1.5 && dw <= 2.5) ? 'text-green-600 dark:text-green-400' : 'text-yellow-600 dark:text-yellow-400';
}

function LinearStats({ result }) {
  return (
    <div className="space-y-4">
      <StatsSection title="Model Fit" first>
        <div className="grid grid-cols-2 gap-3">
          <StatCard
            label="R-Squared"
            value={formatNumber(result.r_squared, 4)}
            tooltip="Proportion of variance explained by the model (0-1)"
          />
          <StatCard
            label="P-Value"
            value={formatPValue(result.p_value)}
            colorClass={pValueColor(result.p_value)}
            tooltip="Statistical significance: < 0.05 is significant"
          />
        </div>
      </StatsSection>

      <StatsSection title="Trend">
        <div className="grid grid-cols-2 md:grid-cols-3 gap-3">
          <StatCard
            label="Slope (per period)"
            value={formatNumber(result.slope, 4)}
            tooltip="Change in value per time period"
          />
          <StatCard
            label="Intercept"
            value={formatNumber(result.intercept, 2)}
            tooltip="Starting value when time = 0"
          />
          <StatCard
            label="Std Error"
            value={formatNumber(result.std_error, 4)}
            tooltip="Standard error of the slope estimate"
          />
        </div>
      </StatsSection>

      {result.durbin_watson != null && (
        <StatsSection title="Diagnostics">
          <div className="grid grid-cols-2 gap-3">
            <StatCard
              label="Durbin-Watson"
              value={formatNumber(result.durbin_watson, 3)}
              colorClass={dwColor(result.durbin_watson)}
              tooltip="Tests for autocorrelation in residuals. Values near 2 indicate no autocorrelation (1.5-2.5 is good)"
            />
          </div>
        </StatsSection>
      )}
    </div>
  );
}

function vifBg(vif) {
  if (vif == null) return '';
  if (vif >= 10) return 'bg-red-100 dark:bg-red-900/40';
  if (vif >= 5) return 'bg-yellow-100 dark:bg-yellow-900/40';
  return '';
}

function MultiFactorStats({ result }) {
  const hasVif = result.vif && Object.keys(result.vif).length > 0;

  return (
    <div className="space-y-4">
      <StatsSection title="Summary" first>
        <div className="grid grid-cols-2 md:grid-cols-5 gap-3">
          <StatCard
            label="R-Squared"
            value={formatNumber(result.r_squared, 4)}
            tooltip="Proportion of variance explained by all factors"
          />
          <StatCard
            label="Adjusted R-Squared"
            value={formatNumber(result.adjusted_r_squared, 4)}
            tooltip="R-squared adjusted for number of predictors"
          />
          <StatCard
            label="F-Statistic"
            value={formatNumber(result.f_statistic, 2)}
            tooltip="Overall significance of the regression model"
          />
          <StatCard
            label="Intercept"
            value={formatNumber(result.intercept, 4)}
            tooltip="Constant term in the regression equation"
          />
          {result.durbin_watson != null && (
            <StatCard
              label="Durbin-Watson"
              value={formatNumber(result.durbin_watson, 3)}
              colorClass={dwColor(result.durbin_watson)}
              tooltip="Tests for autocorrelation in residuals. Values near 2 indicate no autocorrelation (1.5-2.5 is good)"
            />
          )}
        </div>
      </StatsSection>

      <StatsSection title="Coefficients">
        <div className="bg-white dark:bg-slate-800 border border-slate-200 dark:border-slate-700 rounded-lg overflow-hidden">
          <table className="w-full text-sm">
            <thead>
              <tr className="border-b border-slate-200 dark:border-slate-700">
                <th className="text-left px-4 py-2 text-xs font-medium text-slate-500 dark:text-slate-400">Factor</th>
                <th className="text-right px-4 py-2 text-xs font-medium text-slate-500 dark:text-slate-400">Coefficient</th>
                <th className="text-right px-4 py-2 text-xs font-medium text-slate-500 dark:text-slate-400">P-Value</th>
                {hasVif && <th className="text-right px-4 py-2 text-xs font-medium text-slate-500 dark:text-slate-400">VIF</th>}
                <th className="text-right px-4 py-2 text-xs font-medium text-slate-500 dark:text-slate-400">Significance</th>
              </tr>
            </thead>
            <tbody>
              {Object.entries(result.coefficients).map(([name, coef]) => {
                const p = result.p_values[name];
                const vif = result.vif?.[name];
                return (
                  <tr key={name} className="border-b border-slate-100 dark:border-slate-700/50">
                    <td className="px-4 py-2 font-medium text-slate-900 dark:text-white">{name}</td>
                    <td className="px-4 py-2 text-right text-slate-700 dark:text-slate-300">{formatNumber(coef, 4)}</td>
                    <td className={`px-4 py-2 text-right ${pValueColor(p)}`}>{formatPValue(p)}</td>
                    {hasVif && (
                      <td className={`px-4 py-2 text-right text-slate-700 dark:text-slate-300 relative group ${vifBg(vif)}`}>
                        {vif != null ? formatNumber(vif, 2) : '—'}
                        {vif != null && vif >= 5 && (
                          <div className="absolute bottom-full left-1/2 -translate-x-1/2 mb-2 px-3 py-2 bg-slate-800 dark:bg-slate-600 text-white text-xs rounded-lg opacity-0 group-hover:opacity-100 transition-opacity pointer-events-none whitespace-nowrap z-10">
                            {vif >= 10 ? 'Severe multicollinearity' : 'Moderate multicollinearity'}
                          </div>
                        )}
                      </td>
                    )}
                    <td className="px-4 py-2 text-right">
                      <span className={`text-xs px-2 py-0.5 rounded-full ${
                        p < 0.05 ? 'bg-green-100 dark:bg-green-900 text-green-800 dark:text-green-200'
                        : p < 0.10 ? 'bg-yellow-100 dark:bg-yellow-900 text-yellow-800 dark:text-yellow-200'
                        : 'bg-red-100 dark:bg-red-900 text-red-800 dark:text-red-200'
                      }`}>
                        {p < 0.05 ? 'Significant' : p < 0.10 ? 'Marginal' : 'Not Significant'}
                      </span>
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
      </StatsSection>

      {result.stationarity && (
        <StatsSection title="Stationarity">
          <div className="text-xs text-slate-500 dark:text-slate-400 space-y-1">
            <div className="flex flex-wrap gap-2">
              {Object.entries(result.stationarity).map(([name, s]) => (
                <span key={name} className={`px-2 py-0.5 rounded-full ${s.is_stationary ? 'bg-green-100 dark:bg-green-900/50 text-green-700 dark:text-green-300' : 'bg-yellow-100 dark:bg-yellow-900/50 text-yellow-700 dark:text-yellow-300'}`}>
                  {name === '__dependent__' ? 'Dependent' : name}: {s.is_stationary ? 'Stationary' : 'Non-stationary'} (p={formatNumber(s.p_value, 3)})
                </span>
              ))}
            </div>
          </div>
        </StatsSection>
      )}
    </div>
  );
}

function RollingStats({ result }) {
  const slopes = result.slope_over_time;
  const r2s = result.r_squared_over_time;

  const avg = (arr) => arr.reduce((a, b) => a + b, 0) / arr.length;
  const min = (arr) => Math.min(...arr);
  const max = (arr) => Math.max(...arr);

  return (
    <div className="space-y-4">
      <StatsSection title="Current Window" first>
        <div className="grid grid-cols-2 gap-3">
          <StatCard
            label="Current Slope"
            value={formatNumber(slopes[slopes.length - 1], 4)}
            tooltip="Most recent window's slope"
          />
          <StatCard
            label="Current R-Squared"
            value={formatNumber(r2s[r2s.length - 1], 4)}
            tooltip="Most recent window's R-squared"
          />
        </div>
      </StatsSection>

      <StatsSection title="Historical Range">
        <div className="grid grid-cols-2 md:grid-cols-3 gap-3">
          <StatCard
            label="Avg Slope"
            value={formatNumber(avg(slopes), 4)}
            tooltip="Average slope across all windows"
          />
          <StatCard
            label="Min Slope"
            value={formatNumber(min(slopes), 4)}
            tooltip="Minimum slope observed"
          />
          <StatCard
            label="Max Slope"
            value={formatNumber(max(slopes), 4)}
            tooltip="Maximum slope observed"
          />
          <StatCard
            label="Avg R-Squared"
            value={formatNumber(avg(r2s), 4)}
            tooltip="Average R-squared across all windows"
          />
          <StatCard
            label="Min R-Squared"
            value={formatNumber(min(r2s), 4)}
            tooltip="Weakest trend fit observed"
          />
          <StatCard
            label="Max R-Squared"
            value={formatNumber(max(r2s), 4)}
            tooltip="Strongest trend fit observed"
          />
        </div>
      </StatsSection>
    </div>
  );
}

function CompareStats({ result }) {
  if (!result.stats) return null;

  return (
    <div className="bg-white dark:bg-slate-800 border border-slate-200 dark:border-slate-700 rounded-lg overflow-hidden">
      <table className="w-full text-sm">
        <thead>
          <tr className="border-b border-slate-200 dark:border-slate-700">
            <th className="text-left px-4 py-2 text-xs font-medium text-slate-500 dark:text-slate-400">Asset</th>
            <th className="text-right px-4 py-2 text-xs font-medium text-slate-500 dark:text-slate-400">Ann. Return</th>
            <th className="text-right px-4 py-2 text-xs font-medium text-slate-500 dark:text-slate-400">Volatility</th>
            <th className="text-right px-4 py-2 text-xs font-medium text-slate-500 dark:text-slate-400">Trend R-Squared</th>
          </tr>
        </thead>
        <tbody>
          {result.stats.map((s) => (
            <tr key={s.identifier} className="border-b border-slate-100 dark:border-slate-700/50">
              <td className="px-4 py-2 font-medium text-slate-900 dark:text-white">{s.identifier}</td>
              <td className={`px-4 py-2 text-right ${s.annualized_return >= 0 ? 'text-green-600 dark:text-green-400' : 'text-red-600 dark:text-red-400'}`}>
                {formatPercent(s.annualized_return)}
              </td>
              <td className="px-4 py-2 text-right text-slate-700 dark:text-slate-300">{formatPercent(s.volatility)}</td>
              <td className="px-4 py-2 text-right text-slate-700 dark:text-slate-300">{formatNumber(s.r_squared, 4)}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

export default function StatsPanel({ result, mode }) {
  if (!result) return null;

  return (
    <div>
      <h3 className="text-sm font-medium text-slate-700 dark:text-slate-200 mb-3">
        Statistics
      </h3>
      {mode === 'linear' && <LinearStats result={result} />}
      {mode === 'multi-factor' && <MultiFactorStats result={result} />}
      {mode === 'rolling' && <RollingStats result={result} />}
      {mode === 'compare' && <CompareStats result={result} />}
    </div>
  );
}
