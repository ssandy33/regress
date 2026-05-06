import Header from '../layout/Header';
import { useDashboard } from '../../hooks/useDashboard';
import { formatDate } from '../../utils/formatters';
import StatusStrip from './StatusStrip';
import KpiRow from './KpiRow';
import UpcomingExpirationsCard from './UpcomingExpirationsCard';
import OpenLegsCard from './OpenLegsCard';
import DashboardPositionsCard from './DashboardPositionsCard';
import RecentActivityCard from './RecentActivityCard';
import DataReadinessDetail from './DataReadinessDetail';
import OnboardingPanel from './OnboardingPanel';

function StaleBanner({ meta }) {
  if (!meta?.is_stale) return null;
  return (
    <div className="px-4 py-2 bg-yellow-50 dark:bg-yellow-900/30 border border-yellow-200 dark:border-yellow-800 rounded-lg text-sm text-yellow-800 dark:text-yellow-200">
      Some data sources are unavailable — values shown may be cached or incomplete.
    </div>
  );
}

function lastSyncLabel(meta) {
  if (!meta?.fetched_at) return null;
  const d = new Date(meta.fetched_at);
  if (Number.isNaN(d.getTime())) return null;
  const hh = String(d.getHours()).padStart(2, '0');
  const mm = String(d.getMinutes()).padStart(2, '0');
  return `Last sync ${hh}:${mm}`;
}

function isAllEmpty(data) {
  if (!data) return false;
  const schwab = data.status?.schwab?.configured;
  const fred = data.status?.fred?.configured;
  const positions = data.status?.journal?.positions_count ?? 0;
  return !schwab && !fred && positions === 0;
}

export default function DashboardPage() {
  const { data, loading, error, refetch } = useDashboard();

  return (
    <div data-testid="dashboard-page" className="h-screen flex flex-col bg-slate-100 dark:bg-slate-900">
      <Header sessions={[]} onLoadSession={() => {}} />

      <main className="flex-1 overflow-y-auto p-6 space-y-4">
        <div className="flex items-center justify-between flex-wrap gap-2">
          <h1 className="text-xl font-semibold text-slate-900 dark:text-white">
            Dashboard
          </h1>
          <div className="text-sm text-slate-500 dark:text-slate-400">
            {lastSyncLabel(data?.data_meta)}
          </div>
        </div>

        {error ? (
          <div
            data-testid="dashboard-error"
            className="bg-red-50 dark:bg-red-900/20 border border-red-200 dark:border-red-800 rounded-lg p-4 text-sm text-red-700 dark:text-red-300 flex items-center justify-between"
          >
            <span>{error}</span>
            <button
              type="button"
              onClick={refetch}
              className="px-3 py-1.5 rounded-lg bg-red-600 text-white text-sm font-medium hover:bg-red-700"
            >
              Retry
            </button>
          </div>
        ) : (
          <>
            <StaleBanner meta={data?.data_meta} />
            <StatusStrip status={data?.status} />

            {isAllEmpty(data) ? (
              <OnboardingPanel />
            ) : (
              <>
                <KpiRow kpis={data?.kpis} />

                <div className="grid grid-cols-1 lg:grid-cols-12 gap-4">
                  <div className="lg:col-span-7">
                    <UpcomingExpirationsCard
                      expirations={data?.upcoming_expirations}
                      loading={loading}
                    />
                  </div>
                  <div className="lg:col-span-5">
                    <OpenLegsCard legs={data?.open_legs} loading={loading} />
                  </div>
                </div>

                <DashboardPositionsCard
                  positions={data?.positions}
                  loading={loading}
                />
              </>
            )}

            <RecentActivityCard events={data?.recent_activity} loading={loading} />
            <DataReadinessDetail status={data?.status} onRefreshed={refetch} />
          </>
        )}
      </main>
    </div>
  );
}
