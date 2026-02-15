import Plot from './PlotlyChart';
import { useTheme } from '../../context/ThemeContext';
import { COMPARE_COLORS } from '../controls/ComparePicker';

/**
 * Compare mode: Normalized (base 100) multi-asset overlay chart.
 */
export default function CompareChart({ result, annotations = [] }) {
  const { dark } = useTheme();

  if (!result || !result.series) return null;

  const layout = {
    paper_bgcolor: 'transparent',
    plot_bgcolor: 'transparent',
    font: { color: dark ? '#e2e8f0' : '#1e293b', size: 12 },
    margin: { t: 30, r: 30, b: 50, l: 60 },
    xaxis: {
      gridcolor: dark ? '#334155' : '#e2e8f0',
      title: 'Date',
    },
    yaxis: {
      gridcolor: dark ? '#334155' : '#e2e8f0',
      title: 'Normalized Value (Base 100)',
    },
    hovermode: 'x unified',
    showlegend: true,
    legend: { orientation: 'h', y: -0.15 },
    annotations: annotations.map((a) => ({
      x: a.date,
      y: a.y || 100,
      text: a.text,
      showarrow: true,
      arrowhead: 2,
      ax: 0,
      ay: -30,
      font: { size: 11, color: dark ? '#e2e8f0' : '#1e293b' },
      bgcolor: dark ? '#334155' : '#f1f5f9',
      bordercolor: dark ? '#475569' : '#cbd5e1',
      borderpad: 4,
    })),
  };

  const assetNames = Object.keys(result.series);
  const traces = assetNames.map((name, i) => ({
    x: result.dates,
    y: result.series[name],
    type: 'scatter',
    mode: 'lines',
    name,
    line: { color: COMPARE_COLORS[i % COMPARE_COLORS.length], width: 2 },
    hovertemplate: `${name}: %{y:.1f}<extra></extra>`,
  }));

  return (
    <Plot
      data={traces}
      layout={layout}
      config={{ responsive: true, displayModeBar: true, toImageButtonOptions: { filename: 'compare_chart' } }}
      useResizeHandler
      style={{ width: '100%', height: '100%' }}
    />
  );
}
