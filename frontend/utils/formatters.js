export function formatNumber(value, decimals = 2) {
  if (value == null || isNaN(value)) return '—';
  return Number(value).toLocaleString('en-US', {
    minimumFractionDigits: decimals,
    maximumFractionDigits: decimals,
  });
}

export function formatPercent(value, decimals = 2) {
  if (value == null || isNaN(value)) return '—';
  return (Number(value) * 100).toFixed(decimals) + '%';
}

export function formatPValue(value) {
  if (value == null || isNaN(value)) return '—';
  if (value < 0.001) return '< 0.001';
  return Number(value).toFixed(4);
}

export function formatDate(dateStr) {
  if (!dateStr) return '—';
  return new Date(dateStr).toLocaleDateString('en-US', {
    year: 'numeric',
    month: 'short',
    day: 'numeric',
  });
}

export function formatCurrency(value) {
  if (value == null || isNaN(value)) return '—';
  return Number(value).toLocaleString('en-US', {
    style: 'currency',
    currency: 'USD',
  });
}

export function pValueColor(p) {
  if (p == null) return 'text-slate-500';
  if (p < 0.05) return 'text-green-600 dark:text-green-400';
  if (p < 0.10) return 'text-yellow-600 dark:text-yellow-400';
  return 'text-red-600 dark:text-red-400';
}

export function formatRelativeTime(iso) {
  if (!iso) return '—';
  const dt = new Date(iso);
  if (Number.isNaN(dt.getTime())) return '—';
  const now = new Date();

  const sameDay =
    dt.getFullYear() === now.getFullYear() &&
    dt.getMonth() === now.getMonth() &&
    dt.getDate() === now.getDate();
  if (sameDay) {
    const hh = String(dt.getHours()).padStart(2, '0');
    const mm = String(dt.getMinutes()).padStart(2, '0');
    return `${hh}:${mm}`;
  }

  const yesterday = new Date(now);
  yesterday.setDate(now.getDate() - 1);
  if (
    dt.getFullYear() === yesterday.getFullYear() &&
    dt.getMonth() === yesterday.getMonth() &&
    dt.getDate() === yesterday.getDate()
  ) {
    return 'yest';
  }

  return dt.toLocaleDateString('en-US', { month: 'short', day: 'numeric' });
}

export function categoryLabel(category) {
  const labels = {
    stock: 'Stocks',
    indices: 'Indices',
    interest_rates: 'Interest Rates',
    housing: 'Real Estate',
    economic_indicators: 'Economic Indicators',
    commodities: 'Precious Metals',
    other: 'Other',
  };
  return labels[category] || category;
}
