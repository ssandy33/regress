export function exportCSV(filename, result, mode) {
  let csv = '';

  if (mode === 'linear') {
    csv = 'Date,Actual,Predicted,CI_Upper,CI_Lower\n';
    result.dates.forEach((d, i) => {
      csv += `${d},${result.actual_values[i]},${result.predicted_values[i]},${result.confidence_interval_upper[i]},${result.confidence_interval_lower[i]}\n`;
    });
  } else if (mode === 'multi-factor') {
    csv = 'Date,Dependent,Predicted,Residual\n';
    result.dates.forEach((d, i) => {
      csv += `${d},${result.dependent_values[i]},${result.predicted_values[i]},${result.residuals[i]}\n`;
    });
  } else if (mode === 'rolling') {
    csv = 'Date,Slope,R_Squared\n';
    result.dates.forEach((d, i) => {
      csv += `${d},${result.slope_over_time[i]},${result.r_squared_over_time[i]}\n`;
    });
  } else if (mode === 'compare') {
    const assets = Object.keys(result.series);
    csv = 'Date,' + assets.join(',') + '\n';
    result.dates.forEach((d, i) => {
      const vals = assets.map((a) => result.series[a][i]);
      csv += `${d},${vals.join(',')}\n`;
    });
  }

  const blob = new Blob([csv], { type: 'text/csv' });
  const url = URL.createObjectURL(blob);
  const a = document.createElement('a');
  a.href = url;
  a.download = `${filename}.csv`;
  a.click();
  URL.revokeObjectURL(url);
}
