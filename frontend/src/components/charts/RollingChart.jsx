import Plot from 'react-plotly.js';
import { useTheme } from '../../context/ThemeContext';

export default function RollingChart({ result }) {
  const { dark } = useTheme();

  if (!result) return null;

  const commonLayout = {
    paper_bgcolor: 'transparent',
    plot_bgcolor: 'transparent',
    font: { color: dark ? '#e2e8f0' : '#1e293b', size: 12 },
    hovermode: 'x unified',
    showlegend: true,
    legend: { orientation: 'h', y: -0.15 },
  };

  // Top chart: asset price with colored segments based on R²
  const priceColors = result.r_squared_over_time.map((r2) => {
    if (r2 >= 0.7) return 'rgba(22, 163, 74, 0.8)';   // green - strong
    if (r2 >= 0.4) return 'rgba(234, 179, 8, 0.8)';    // yellow - moderate
    return 'rgba(220, 38, 38, 0.8)';                     // red - weak
  });

  const priceTraces = [
    {
      x: result.dates,
      y: result.actual_values.slice(result.actual_values.length - result.dates.length),
      type: 'scatter',
      mode: 'lines+markers',
      name: 'Price',
      marker: { color: priceColors, size: 3 },
      line: { color: dark ? '#94a3b8' : '#64748b', width: 1 },
      hovertemplate: 'Price: %{y:.2f}<extra></extra>',
    },
  ];

  const priceLayout = {
    ...commonLayout,
    margin: { t: 30, r: 30, b: 10, l: 60 },
    xaxis: { gridcolor: dark ? '#334155' : '#e2e8f0', showticklabels: false },
    yaxis: { gridcolor: dark ? '#334155' : '#e2e8f0', title: 'Price' },
  };

  // Bottom chart: rolling slope + R² (dual y-axis)
  const metricsTraces = [
    {
      x: result.dates,
      y: result.slope_over_time,
      type: 'scatter',
      mode: 'lines',
      name: 'Slope',
      line: { color: '#2563eb', width: 2 },
      yaxis: 'y1',
      hovertemplate: 'Slope: %{y:.4f}<extra></extra>',
    },
    {
      x: result.dates,
      y: result.r_squared_over_time,
      type: 'scatter',
      mode: 'lines',
      name: 'R²',
      line: { color: '#f59e0b', width: 2 },
      yaxis: 'y2',
      hovertemplate: 'R²: %{y:.4f}<extra></extra>',
    },
  ];

  // Auto-annotate trend breaks (R² drops below 0.5 after being above)
  const trendBreaks = [];
  for (let i = 1; i < result.r_squared_over_time.length; i++) {
    if (result.r_squared_over_time[i] < 0.5 && result.r_squared_over_time[i - 1] >= 0.5) {
      trendBreaks.push({
        x: result.dates[i],
        y: result.r_squared_over_time[i],
        text: 'Trend break',
        showarrow: true,
        arrowhead: 2,
        ax: 0,
        ay: -25,
        font: { size: 10, color: '#dc2626' },
        bgcolor: dark ? '#1e293b' : '#fef2f2',
        bordercolor: '#dc2626',
        borderpad: 3,
      });
    }
  }

  const metricsLayout = {
    ...commonLayout,
    margin: { t: 10, r: 60, b: 50, l: 60 },
    annotations: trendBreaks,
    xaxis: { gridcolor: dark ? '#334155' : '#e2e8f0', title: 'Date' },
    yaxis: {
      gridcolor: dark ? '#334155' : '#e2e8f0',
      title: 'Slope',
      titlefont: { color: '#2563eb' },
    },
    yaxis2: {
      title: 'R²',
      titlefont: { color: '#f59e0b' },
      overlaying: 'y',
      side: 'right',
      range: [0, 1],
      gridcolor: 'transparent',
    },
  };

  return (
    <div className="flex flex-col h-full">
      <div className="flex-1 min-h-0" style={{ height: '55%' }}>
        <Plot
          data={priceTraces}
          layout={priceLayout}
          config={{ responsive: true, displayModeBar: true }}
          useResizeHandler
          style={{ width: '100%', height: '100%' }}
        />
      </div>
      <div className="flex-1 min-h-0" style={{ height: '45%' }}>
        <Plot
          data={metricsTraces}
          layout={metricsLayout}
          config={{ responsive: true, displayModeBar: false }}
          useResizeHandler
          style={{ width: '100%', height: '100%' }}
        />
      </div>
    </div>
  );
}
