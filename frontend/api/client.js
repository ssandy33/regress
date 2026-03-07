import axios from 'axios';

const api = axios.create({
  baseURL: process.env.NEXT_PUBLIC_API_URL || '',
  timeout: 30000,
});

// --- Assets ---

export async function searchAssets(query, offline = false) {
  const { data } = await api.get('/api/assets/search', { params: { q: query, offline } });
  return data.results;
}

export async function getCaseShillerMetros() {
  const { data } = await api.get('/api/assets/case-shiller');
  return data.metros;
}

export async function suggestTickers(query) {
  const { data } = await api.get('/api/assets/suggest', { params: { q: query } });
  return data.suggestions;
}

// --- Data ---

export async function fetchHistoricalData(ticker, start, end) {
  const { data } = await api.get(`/api/data/${encodeURIComponent(ticker)}`, {
    params: { start, end },
  });
  return data;
}

export async function fetchZillowData(zipCode, start, end) {
  const { data } = await api.get(`/api/data/zillow/${zipCode}`, {
    params: { start, end },
  });
  return data;
}

// --- Regression ---

export async function runLinearRegression(asset, startDate, endDate) {
  const { data } = await api.post('/api/regression/linear', {
    asset,
    start_date: startDate,
    end_date: endDate,
  });
  return data;
}

export async function runMultiFactorRegression(dependent, independents, startDate, endDate) {
  const { data } = await api.post('/api/regression/multi-factor', {
    dependent,
    independents,
    start_date: startDate,
    end_date: endDate,
  });
  return data;
}

export async function runRollingRegression(asset, startDate, endDate, windowSize) {
  const { data } = await api.post('/api/regression/rolling', {
    asset,
    start_date: startDate,
    end_date: endDate,
    window_size: windowSize,
  });
  return data;
}

export async function runCompareRegression(assets, startDate, endDate) {
  const { data } = await api.post('/api/regression/compare', {
    assets,
    start_date: startDate,
    end_date: endDate,
  });
  return data;
}

// --- Sessions ---

export async function createSession(name, config) {
  const { data } = await api.post('/api/sessions', { name, config });
  return data;
}

export async function listSessions() {
  const { data } = await api.get('/api/sessions');
  return data.sessions;
}

export async function getSession(id) {
  const { data } = await api.get(`/api/sessions/${id}`);
  return data;
}

export async function deleteSession(id) {
  await api.delete(`/api/sessions/${id}`);
}

// --- Settings ---

export async function getSettings() {
  const { data } = await api.get('/api/settings');
  return data;
}

export async function updateSetting(key, value) {
  const { data } = await api.put('/api/settings', { key, value });
  return data;
}

export async function getCacheStats() {
  const { data } = await api.get('/api/settings/cache');
  return data;
}

export async function clearCache() {
  const { data } = await api.delete('/api/settings/cache');
  return data;
}

export async function checkFredHealth() {
  const { data } = await api.get('/api/settings/health/fred');
  return data;
}

export async function checkSchwabHealth() {
  const { data } = await api.get('/api/settings/health/schwab');
  return data;
}

// --- Health ---

export async function checkSourceHealth() {
  const { data } = await api.get('/api/health/sources');
  return data;
}

// --- Backups ---

export async function getBackups() {
  const { data } = await api.get('/api/settings/backups');
  return data.backups;
}

export async function restoreBackup(filename) {
  const { data } = await api.post('/api/settings/backups/restore', null, {
    params: { filename },
  });
  return data;
}

// --- Cache Freshness ---

export async function getCacheFreshness() {
  const { data } = await api.get('/api/settings/cache/freshness');
  return data.entries;
}

export async function refreshAllCache() {
  const { data } = await api.post('/api/settings/cache/refresh-all');
  return data.results;
}

export async function refreshStaleCache() {
  const { data } = await api.post('/api/settings/cache/refresh-stale');
  return data.results;
}

// --- Options Scanner ---

export async function scanOptions(request) {
  const { data } = await api.post('/api/options/scan', request);
  return data;
}

export async function getEarningsDate(ticker) {
  const { data } = await api.get(`/api/options/earnings/${encodeURIComponent(ticker)}`);
  return data;
}

export async function getOptionChain(ticker, expiration = null) {
  const { data } = await api.get(`/api/options/chain/${encodeURIComponent(ticker)}`, {
    params: expiration ? { expiration } : {},
  });
  return data;
}

export default api;
