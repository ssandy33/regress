import Plot from 'react-plotly.js';
import { useTheme } from '../../context/ThemeContext';

export default function ResidualChart({ result }) {
  const { dark } = useTheme();

  if (!result || !result.residuals) return null;

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
      title: 'Residual',
      zeroline: true,
      zerolinecolor: dark ? '#64748b' : '#94a3b8',
    },
    hovermode: 'x unified',
    showlegend: false,
  };

  const traces = [
    {
      x: result.dates,
      y: result.residuals,
      type: 'bar',
      marker: {
        color: result.residuals.map((r) =>
          r >= 0
            ? (dark ? 'rgba(34, 197, 94, 0.6)' : 'rgba(22, 163, 74, 0.6)')
            : (dark ? 'rgba(239, 68, 68, 0.6)' : 'rgba(220, 38, 38, 0.6)')
        ),
      },
      hovertemplate: 'Residual: %{y:.4f}<extra></extra>',
    },
  ];

  return (
    <Plot
      data={traces}
      layout={layout}
      config={{ responsive: true, displayModeBar: false }}
      useResizeHandler
      style={{ width: '100%', height: '100%' }}
    />
  );
}
