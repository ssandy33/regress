import Plot from './PlotlyChart';
import { useTheme } from '../../context/ThemeContext';

/**
 * Multi-factor mode: Actual vs Predicted dual line chart.
 */
export default function ComparisonChart({ result }) {
  const { dark } = useTheme();

  if (!result) return null;

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
      title: 'Value',
    },
    hovermode: 'x unified',
    showlegend: true,
    legend: { orientation: 'h', y: -0.15 },
  };

  const traces = [
    {
      x: result.dates,
      y: result.dependent_values,
      type: 'scatter',
      mode: 'lines',
      name: 'Actual',
      line: { color: dark ? '#94a3b8' : '#64748b', width: 1.5 },
      hovertemplate: 'Actual: %{y:.2f}<extra></extra>',
    },
    {
      x: result.dates,
      y: result.predicted_values,
      type: 'scatter',
      mode: 'lines',
      name: 'Predicted',
      line: { color: '#2563eb', width: 2.5 },
      hovertemplate: 'Predicted: %{y:.2f}<extra></extra>',
    },
  ];

  return (
    <Plot
      data={traces}
      layout={layout}
      config={{ responsive: true, displayModeBar: true, toImageButtonOptions: { filename: 'multifactor_chart' } }}
      useResizeHandler
      style={{ width: '100%', height: '100%' }}
    />
  );
}
