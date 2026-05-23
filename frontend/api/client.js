import axios from 'axios';
import { getSession as getAuthSession } from 'next-auth/react';

const api = axios.create({
  baseURL: process.env.NEXT_PUBLIC_API_URL || '',
  timeout: 30000,
});

// Cache the access token to avoid per-request session lookups
let _cachedToken = null;
let _tokenExpiresAt = 0;
const TOKEN_CACHE_MS = 5 * 60 * 1000; // refresh cached token every 5 min

export function clearAuthCache() {
  _cachedToken = null;
  _tokenExpiresAt = 0;
}

api.interceptors.request.use(async (config) => {
  const now = Date.now();
  if (!_cachedToken || now >= _tokenExpiresAt) {
    const session = await getAuthSession();
    _cachedToken = session?.accessToken || null;
    _tokenExpiresAt = now + TOKEN_CACHE_MS;
  }
  if (_cachedToken) {
    config.headers.Authorization = `Bearer ${_cachedToken}`;
  }
  return config;
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

// Trading Rules config (issue #158) — typed read/write for the `rules_config`
// keystone (#156). The generic `GET /api/settings` returns a fixed shape and
// cannot read `rules_config` back, so #158 added `GET`/`PUT /api/settings/rules`.
// These helpers keep the component agnostic of the endpoint shape.
export async function getRulesConfig() {
  const { data } = await api.get('/api/settings/rules');
  return data;
}

export async function saveRulesConfig(config) {
  const { data } = await api.put('/api/settings/rules', config);
  return data;
}

// Schwab account-value endpoints (issue #234) — back the per-position sizing-cap
// percentage's resolved-context line ("25% of $52,400 ≈ $13,100"). `getAccountValue`
// is cache-respecting (cheap, called once on Trading Rules mount); `refreshAccountValue`
// is force-refresh (drives the explicit "Refresh" button + the API-error "Retry").
// Both return an `AccountValueResult` shape:
//   { status: 'ok' | 'disconnected' | 'expired' | 'error',
//     total_capital, account_id_masked, account_type, accounts, cached_at, error_detail }
export async function getAccountValue() {
  const { data } = await api.get('/api/settings/account-value');
  return data;
}

export async function refreshAccountValue() {
  const { data } = await api.post('/api/settings/account-value/refresh');
  return data;
}

// Marks the one-time v1→v2 sizing-cap migration banner as dismissed (#234 §13.5).
// Idempotent — a second call simply re-stamps `dismissed_at`. Server returns the
// updated migration object under the same shape carried by `GET /api/settings/rules`
// under `migration.sizing_cap`.
export async function dismissSizingCapMigration() {
  const { data } = await api.post('/api/settings/rules/migration/sizing-cap/dismiss');
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

export async function getSchwabAuthUrl(appKey) {
  const { data } = await api.post('/api/settings/schwab/auth-url', { app_key: appKey });
  return data;
}

export async function exchangeSchwabCallback(appKey, appSecret, callbackUrl) {
  const { data } = await api.post('/api/settings/schwab/callback', {
    app_key: appKey,
    app_secret: appSecret,
    callback_url: callbackUrl,
  });
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

// Rejected-strikes "Relax to X" preview (issue #258, v1.0.8).
// Stateless what-if — client echoes the `rejected[]` array from the most
// recent scan; the server never re-fetches market data. Mirrored test IDs
// in `ScannerRejectedStrikesRelaxPopover.jsx`.
export async function postRelaxPreview({ ticker, strategy, rule, rejected }) {
  const { data } = await api.post('/api/options/scan/relax', {
    ticker,
    strategy,
    rule,
    rejected,
  });
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

// --- Journal ---

export async function listPositions(status = null) {
  const params = status ? { status } : {};
  const { data } = await api.get('/api/journal/positions', { params });
  return data.positions;
}

export async function getPosition(id) {
  const { data } = await api.get(`/api/journal/positions/${encodeURIComponent(id)}`);
  return data;
}

export async function createPosition(positionData) {
  const { data } = await api.post('/api/journal/positions', positionData);
  return data;
}

export async function updatePosition(id, positionData) {
  const { data } = await api.put(`/api/journal/positions/${encodeURIComponent(id)}`, positionData);
  return data;
}

export async function createTrade(tradeData) {
  const { data } = await api.post('/api/journal/trades', tradeData);
  return data;
}

export async function updateTrade(id, tradeData) {
  const { data } = await api.put(`/api/journal/trades/${encodeURIComponent(id)}`, tradeData);
  return data;
}

export async function deleteTrade(id) {
  await api.delete(`/api/journal/trades/${encodeURIComponent(id)}`);
}

export async function deletePosition(id) {
  await api.delete(`/api/journal/positions/${encodeURIComponent(id)}`);
}

export async function clearAllJournal() {
  const { data } = await api.delete('/api/journal/all');
  return data;
}

export async function reconcileJournal(dryRun) {
  const { data } = await api.post('/api/journal/reconcile', { dry_run: dryRun });
  return data;
}

// --- Schwab Import ---

export async function previewSchwabImport(startDate, endDate) {
  const { data } = await api.get('/api/journal/import/preview', {
    params: { start_date: startDate, end_date: endDate },
  });
  return data;
}

export async function executeSchwabImport(startDate, endDate) {
  // ``position_strategy`` is no longer sent — issue #131 derives the
  // displayed label from each position's lifecycle state.
  const { data } = await api.post('/api/journal/import', {
    start_date: startDate,
    end_date: endDate,
  });
  return data;
}

export async function previewSchwabCsvImport(file) {
  const form = new FormData();
  form.append('file', file);
  const { data } = await api.post('/api/journal/import/csv/preview', form);
  return data;
}

export async function executeSchwabCsvImport(file) {
  // ``position_strategy`` form field removed in issue #131.
  const form = new FormData();
  form.append('file', file);
  const { data } = await api.post('/api/journal/import/csv', form);
  return data;
}

// --- Dashboard ---

export async function getDashboard() {
  const { data } = await api.get('/api/dashboard');
  return data;
}

// --- Recovery Plan (V0.5.8, issue #182) ---

export async function getRecoveryPlan(id) {
  const { data } = await api.post(
    `/api/positions/${encodeURIComponent(id)}/recovery-plan`,
  );
  return data;
}

// --- Buy-to-close leg detail (V1.0.6, issue #244) ---

export async function getBtcDetail(positionId, legId) {
  const { data } = await api.get(
    `/api/positions/${encodeURIComponent(positionId)}` +
      `/legs/${encodeURIComponent(legId)}/btc`,
  );
  return data;
}

// --- Combined covered-call P&L + if-assigned (V1.0.6, issue #247) ---

export async function getCoveredCallView(positionId) {
  const { data } = await api.get(
    `/api/positions/${encodeURIComponent(positionId)}/covered-call`,
  );
  return data;
}


// --- Stock Research page (v1.1.0, issue #280) ---
//
// Five GET endpoints + one PUT for the per-position `/positions/{id}/review`
// screen. Sections A, B+C, D, E, F all hang off this prefix; the page hook
// fans them out with `Promise.allSettled` so a single endpoint failure
// degrades to a per-section tile instead of failing the whole page (NFR-3).

export async function getResearchBusiness(positionId) {
  const { data } = await api.get(
    `/api/positions/${encodeURIComponent(positionId)}/research/business`,
  );
  return data;
}

export async function getResearchPriceHistory(positionId, window = '1Y') {
  const { data } = await api.get(
    `/api/positions/${encodeURIComponent(positionId)}/research/price-history`,
    { params: { window } },
  );
  return data;
}

export async function getResearchFinancials(positionId) {
  const { data } = await api.get(
    `/api/positions/${encodeURIComponent(positionId)}/research/financials`,
  );
  return data;
}

export async function getResearchRegression(positionId, window = '1Y') {
  const { data } = await api.get(
    `/api/positions/${encodeURIComponent(positionId)}/research/regression`,
    { params: { window } },
  );
  return data;
}

export async function getResearchThesis(positionId) {
  const { data } = await api.get(
    `/api/positions/${encodeURIComponent(positionId)}/research/thesis`,
  );
  return data;
}

export async function putResearchThesis(positionId, thesis) {
  const { data } = await api.put(
    `/api/positions/${encodeURIComponent(positionId)}/research/thesis`,
    { thesis },
  );
  return data;
}

export default api;
