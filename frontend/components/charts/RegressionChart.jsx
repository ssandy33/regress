import Plot from './PlotlyChart';
import { useTheme } from '../../context/ThemeContext';

export default function RegressionChart({ result, annotations = [], earningsDates = null }) {
  const { dark } = useTheme();

  if (!result) return null;

  const plotAnnotations = annotations.map((a) => ({
    x: a.date,
    y: result.actual_values[result.dates.indexOf(a.date)] || result.actual_values[0],
    text: a.text,
    showarrow: true,
    arrowhead: 2,
    ax: 0,
    ay: -30,
    font: { size: 11, color: dark ? '#e2e8f0' : '#1e293b' },
    bgcolor: dark ? '#334155' : '#f1f5f9',
    bordercolor: dark ? '#475569' : '#cbd5e1',
    borderpad: 4,
  }));

  // Earnings date annotations (small "E" labels at top)
  const earningsAnnotations = (earningsDates || []).map((date) => ({
    x: date,
    y: 1,
    yref: 'paper',
    text: 'E',
    showarrow: false,
    font: { size: 9, color: '#f59e0b', weight: 'bold' },
    yanchor: 'bottom',
  }));

  // Earnings date vertical lines
  const earningsShapes = (earningsDates || []).map((date) => ({
    type: 'line',
    x0: date,
    x1: date,
    y0: 0,
    y1: 1,
    yref: 'paper',
    line: { color: dark ? '#fbbf24' : '#d97706', width: 1, dash: 'dot' },
  }));

  const layout = {
    paper_bgcolor: 'transparent',
    plot_bgcolor: 'transparent',
    font: { color: dark ? '#e2e8f0' : '#1e293b', size: 12 },
    margin: { t: 40, r: 30, b: 50, l: 60 },
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
    annotations: [...plotAnnotations, ...earningsAnnotations],
    shapes: earningsShapes,
  };

  const traces = [
    {
      x: result.dates,
      y: result.confidence_interval_upper,
      type: 'scatter',
      mode: 'lines',
      line: { width: 0 },
      showlegend: false,
      hoverinfo: 'skip',
    },
    {
      x: result.dates,
      y: result.confidence_interval_lower,
      type: 'scatter',
      mode: 'lines',
      fill: 'tonexty',
      fillcolor: dark ? 'rgba(37, 99, 235, 0.15)' : 'rgba(37, 99, 235, 0.1)',
      line: { width: 0 },
      name: '95% CI',
    },
    {
      x: result.dates,
      y: result.actual_values,
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
      name: 'Trend',
      line: { color: '#2563eb', width: 2.5 },
      hovertemplate: 'Predicted: %{y:.2f}<extra></extra>',
    },
  ];

  return (
    <Plot
      data={traces}
      layout={layout}
      config={{ responsive: true, displayModeBar: true, toImageButtonOptions: { filename: 'regression_chart' } }}
      useResizeHandler
      style={{ width: '100%', height: '100%' }}
    />
  );
}
