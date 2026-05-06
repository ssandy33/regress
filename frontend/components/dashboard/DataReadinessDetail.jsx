import { useState } from 'react';
import toast from 'react-hot-toast';
import Card from '../common/Card';
import { refreshStaleCache } from '../../api/client';

/**
 * DataReadinessDetail — only rendered when at least one source is non-green.
 *
 * Shows a row per source with the same structural treatment as the Settings
 * page detail block, plus a "Refresh stale" button that calls the existing
 * refreshStaleCache endpoint.
 */
function StatusRow({ label, ok, hint }) {
  return (
    <div className="flex items-center justify-between py-2 text-sm">
      <span className="text-slate-700 dark:text-slate-200">{label}</span>
      <span
        className={ok ? 'text-emerald-600 dark:text-emerald-400' : 'text-red-600 dark:text-red-400'}
      >
        {hint}
      </span>
    </div>
  );
}

export default function DataReadinessDetail({ status, onRefreshed }) {
  const [busy, setBusy] = useState(false);

  if (!status) return null;

  const schwabOk = status.schwab?.configured && status.schwab?.valid;
  const fredOk = status.fred?.configured && status.fred?.valid;
  const cacheOk = (status.cache?.stale ?? 0) === 0 && (status.cache?.very_stale ?? 0) === 0;

  if (schwabOk && fredOk && cacheOk) return null;

  async function handleRefresh() {
    setBusy(true);
    try {
      await refreshStaleCache();
      toast.success('Refreshed stale cache entries');
      onRefreshed?.();
    } catch {
      toast.error('Failed to refresh stale cache');
    } finally {
      setBusy(false);
    }
  }

  return (
    <Card title="Data readiness" dataTestid="dashboard-readiness-card">
      <StatusRow
        label="Schwab"
        ok={schwabOk}
        hint={schwabOk ? 'Connected' : 'Disconnected — open Settings to reconnect'}
      />
      <StatusRow
        label="FRED"
        ok={fredOk}
        hint={fredOk ? 'Configured' : 'Not configured — add an API key in Settings'}
      />
      <StatusRow
        label="Cache"
        ok={cacheOk}
        hint={
          cacheOk
            ? 'Fresh'
            : `${status.cache?.stale ?? 0} stale, ${status.cache?.very_stale ?? 0} very stale`
        }
      />
      {!cacheOk && (
        <div className="pt-3">
          <button
            type="button"
            onClick={handleRefresh}
            disabled={busy}
            className="px-3 py-1.5 text-sm rounded-lg bg-blue-600 text-white hover:bg-blue-700 disabled:opacity-50"
          >
            {busy ? 'Refreshing…' : 'Refresh stale data'}
          </button>
        </div>
      )}
    </Card>
  );
}
