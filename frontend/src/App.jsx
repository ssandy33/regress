import { useState, useCallback, useEffect, lazy, Suspense } from 'react';
import { Routes, Route } from 'react-router-dom';
import { Toaster } from 'react-hot-toast';
import Layout from './components/layout/Layout';
import LoadingSkeleton from './components/layout/LoadingSkeleton';
const RegressionChart = lazy(() => import('./components/charts/RegressionChart'));
const ComparisonChart = lazy(() => import('./components/charts/ComparisonChart'));
const CompareChart = lazy(() => import('./components/charts/CompareChart'));
const ResidualChart = lazy(() => import('./components/charts/ResidualChart'));
const RollingChart = lazy(() => import('./components/charts/RollingChart'));
const OptionScannerPage = lazy(() => import('./components/options/OptionScanner'));
import StatsPanel from './components/results/StatsPanel';
import StatsInterpretation from './components/results/StatsInterpretation';
import DataQualityBadge from './components/results/DataQualityBadge';
import ExportButtons from './components/results/ExportButtons';
import AnnotationPanel from './components/results/AnnotationPanel';
import SaveSession from './components/sessions/SaveSession';
import SetupWizard from './components/settings/SetupWizard';
import SettingsPage from './components/settings/SettingsPage';
import HelpPage from './components/help/HelpPage';
import OfflineBanner from './components/layout/OfflineBanner';
import { useRegression } from './hooks/useRegression';
import { useSessions } from './hooks/useSessions';
import { checkFredHealth } from './api/client';
import { formatDate, formatNumber, formatPercent } from './utils/formatters';

function StationarityWarning({ result }) {
  if (!result?.stationarity) return null;

  const nonStationary = Object.entries(result.stationarity)
    .filter(([, v]) => !v.is_stationary)
    .map(([k]) => k === '__dependent__' ? 'dependent variable' : k);

  if (nonStationary.length === 0) return null;

  let extraNote = '';
  if (result.differenced && result.r_squared > 0 && result.differenced.r_squared < result.r_squared * 0.5) {
    extraNote = ` When trends are removed, R² drops to ${formatNumber(result.differenced.r_squared, 4)}, suggesting the relationship is driven by coinciding trends.`;
  }

  return (
    <div className="mb-3 px-4 py-2 bg-yellow-50 dark:bg-yellow-900/30 border border-yellow-200 dark:border-yellow-800 rounded-lg text-sm text-yellow-800 dark:text-yellow-200">
      <strong>Spurious correlation risk:</strong> {nonStationary.join(', ')} {nonStationary.length === 1 ? 'is' : 'are'} trending (non-stationary).
      High R² may reflect shared trends rather than a real relationship.
      {result.differenced && ' See differenced regression for a more reliable measure.'}
      {extraNote}
    </div>
  );
}

function DifferencedToggle({ showDifferenced, onToggle }) {
  return (
    <div className="inline-flex rounded-lg border border-slate-200 dark:border-slate-700 overflow-hidden text-sm">
      <button
        onClick={() => onToggle(false)}
        className={`px-3 py-1.5 ${!showDifferenced ? 'bg-blue-600 text-white' : 'bg-white dark:bg-slate-800 text-slate-700 dark:text-slate-300 hover:bg-slate-50 dark:hover:bg-slate-700'}`}
      >
        Levels
      </button>
      <button
        onClick={() => onToggle(true)}
        className={`px-3 py-1.5 ${showDifferenced ? 'bg-blue-600 text-white' : 'bg-white dark:bg-slate-800 text-slate-700 dark:text-slate-300 hover:bg-slate-50 dark:hover:bg-slate-700'}`}
      >
        First Differences
      </button>
    </div>
  );
}

function SampleSizeWarning({ sampleSize }) {
  if (!sampleSize || sampleSize >= 30) return null;

  return (
    <div className="mb-3 px-4 py-2 bg-orange-50 dark:bg-orange-900/30 border border-orange-200 dark:border-orange-800 rounded-lg text-sm text-orange-800 dark:text-orange-200">
      <strong>Small sample size:</strong> Only {sampleSize} observations. Results may not be statistically reliable (30+ recommended).
    </div>
  );
}

function StaleBanner({ meta }) {
  if (!meta) return null;
  const isStale = Array.isArray(meta) ? meta.some((m) => m.is_stale) : meta.is_stale;
  if (!isStale) return null;
  const staleSource = Array.isArray(meta) ? meta.find((m) => m.is_stale) : meta;

  return (
    <div className="mb-3 px-4 py-2 bg-yellow-50 dark:bg-yellow-900/30 border border-yellow-200 dark:border-yellow-800 rounded-lg text-sm text-yellow-800 dark:text-yellow-200">
      Using cached data from {formatDate(staleSource.fetched_at)}. Live source unavailable.
    </div>
  );
}

function AlignmentNotes({ notes }) {
  if (!notes || notes.length === 0) return null;

  return (
    <div className="mb-3 px-4 py-2 bg-blue-50 dark:bg-blue-900/30 border border-blue-200 dark:border-blue-800 rounded-lg text-sm text-blue-800 dark:text-blue-200">
      {notes.map((note, i) => (
        <div key={i}>{note}</div>
      ))}
    </div>
  );
}

function EmptyState() {
  return (
    <div className="h-full flex items-center justify-center">
      <div className="text-center max-w-md">
        <svg className="w-20 h-20 mx-auto mb-4 text-slate-200 dark:text-slate-700" fill="none" viewBox="0 0 24 24" stroke="currentColor">
          <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={1} d="M9 19v-6a2 2 0 00-2-2H5a2 2 0 00-2 2v6a2 2 0 002 2h2a2 2 0 002-2zm0 0V9a2 2 0 012-2h2a2 2 0 012 2v10m-6 0a2 2 0 002 2h2a2 2 0 002-2m0 0V5a2 2 0 012-2h2a2 2 0 012 2v14a2 2 0 01-2 2h-2a2 2 0 01-2-2z" />
        </svg>
        <h2 className="text-lg font-medium text-slate-600 dark:text-slate-300 mb-2">
          Select an asset and run analysis
        </h2>
        <p className="text-sm text-slate-400 dark:text-slate-500">
          Choose a stock, index, or economic indicator from the sidebar, set your date range, and click "Run Analysis" to see regression results.
        </p>
      </div>
    </div>
  );
}

function getModeLabel(mode) {
  const labels = { linear: 'Linear Trend', 'multi-factor': 'Multi-Factor', rolling: 'Rolling', compare: 'Comparison' };
  return labels[mode] || mode;
}

function AnalysisPage() {
  const regression = useRegression();
  const sessions = useSessions();
  const [saveOpen, setSaveOpen] = useState(false);
  const [showWizard, setShowWizard] = useState(false);

  // Check if FRED key is configured on first load
  useEffect(() => {
    const checked = sessionStorage.getItem('setupChecked');
    if (!checked) {
      checkFredHealth().then((result) => {
        if (!result.configured) {
          setShowWizard(true);
        }
        sessionStorage.setItem('setupChecked', '1');
      }).catch(() => {
        sessionStorage.setItem('setupChecked', '1');
      });
    }
  }, []);

  const handleRun = useCallback(() => {
    regression.runAnalysis();
  }, [regression.runAnalysis]);

  const handleSave = useCallback((name) => {
    sessions.save(name, regression.getConfig());
  }, [sessions.save, regression.getConfig]);

  const handleLoadSession = useCallback(async (id) => {
    const session = await sessions.load(id);
    if (session?.config) {
      regression.restoreParams(session.config);
    }
  }, [sessions.load, regression.restoreParams]);

  const [showDifferenced, setShowDifferenced] = useState(false);

  const { result, mode, loading, error, asset, compareAssets, annotations, addAnnotation, removeAnnotation } = regression;
  const meta = result?.data_meta;
  const displayAsset = mode === 'compare' ? compareAssets.join(', ') : asset;

  // Compute the active result for display: either levels or differenced
  const activeResult = (showDifferenced && result?.differenced)
    ? {
        ...result,
        dates: result.differenced.dates,
        dependent_values: result.differenced.dependent_values,
        predicted_values: result.differenced.predicted_values,
        coefficients: result.differenced.coefficients,
        intercept: result.differenced.intercept,
        r_squared: result.differenced.r_squared,
        adjusted_r_squared: result.differenced.adjusted_r_squared,
        p_values: result.differenced.p_values,
        f_statistic: result.differenced.f_statistic,
        residuals: result.differenced.residuals,
        durbin_watson: result.differenced.durbin_watson,
        _isDifferenced: true,
      }
    : result;

  return (
    <>
      {showWizard && <SetupWizard onComplete={() => setShowWizard(false)} />}
      <SaveSession
        open={saveOpen}
        onClose={() => setSaveOpen(false)}
        onSave={handleSave}
      />
      <Layout
        regression={regression}
        sessions={sessions}
        onLoadSession={handleLoadSession}
        onRun={handleRun}
        onSave={() => setSaveOpen(true)}
      >
        {loading ? (
          <LoadingSkeleton />
        ) : error && !result ? (
          <div className="h-full flex items-center justify-center">
            <div className="max-w-md text-center">
              <svg className="w-16 h-16 mx-auto mb-4 text-red-300 dark:text-red-700" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={1.5} d="M12 9v3.75m9-.75a9 9 0 11-18 0 9 9 0 0118 0zm-9 3.75h.008v.008H12v-.008z" />
              </svg>
              <h2 className="text-lg font-medium text-slate-700 dark:text-slate-200 mb-2">Analysis failed</h2>
              <p className="text-sm text-red-600 dark:text-red-400">{error}</p>
            </div>
          </div>
        ) : !result ? (
          <EmptyState />
        ) : (
          <div className="space-y-4">
            {/* Header row */}
            <div className="flex items-start justify-between flex-wrap gap-2">
              <div className="space-y-1">
                <h2 className="text-lg font-semibold text-slate-900 dark:text-white">
                  {displayAsset} — {getModeLabel(mode)} Analysis
                </h2>
                <DataQualityBadge meta={meta} />
              </div>
              <ExportButtons result={result} mode={mode} asset={displayAsset} />
            </div>

            <StaleBanner meta={meta} />
            <SampleSizeWarning sampleSize={result.sample_size} />
            {mode === 'multi-factor' && <StationarityWarning result={result} />}
            {(mode === 'multi-factor' || mode === 'compare') && (
              <AlignmentNotes notes={result.alignment_notes} />
            )}

            {/* Differenced toggle for multi-factor */}
            {mode === 'multi-factor' && result.differenced && (
              <DifferencedToggle showDifferenced={showDifferenced} onToggle={setShowDifferenced} />
            )}

            {/* Chart */}
            <Suspense fallback={<LoadingSkeleton />}>
              <div className="bg-white dark:bg-slate-800 border border-slate-200 dark:border-slate-700 rounded-xl" style={{ height: mode === 'rolling' ? '600px' : '400px' }}>
                {mode === 'linear' && <RegressionChart result={result} annotations={annotations} earningsDates={regression.showEarnings ? result?.earnings_dates : null} />}
                {mode === 'multi-factor' && <ComparisonChart result={activeResult} />}
                {mode === 'rolling' && <RollingChart result={result} />}
                {mode === 'compare' && <CompareChart result={result} annotations={annotations} />}
              </div>

              {/* Residuals chart for multi-factor */}
              {mode === 'multi-factor' && activeResult.residuals && (
                <div className="bg-white dark:bg-slate-800 border border-slate-200 dark:border-slate-700 rounded-xl" style={{ height: '200px' }}>
                  <ResidualChart result={activeResult} />
                </div>
              )}
            </Suspense>

            {/* Annotations */}
            {(mode === 'linear' || mode === 'compare') && (
              <AnnotationPanel
                annotations={annotations}
                onAdd={addAnnotation}
                onRemove={removeAnnotation}
                dates={result.dates}
              />
            )}

            {/* Stats panel */}
            <StatsPanel result={activeResult} mode={mode} />

            {/* Plain-English interpretation */}
            <StatsInterpretation result={activeResult} mode={mode} asset={displayAsset} />
          </div>
        )}
      </Layout>
    </>
  );
}

export default function App() {
  return (
    <>
      <Toaster
        position="top-right"
        toastOptions={{
          className: 'text-sm',
          duration: 4000,
          success: { duration: 4000 },
          error: { duration: 8000 },
        }}
      />
      <OfflineBanner />
      <Routes>
        <Route path="/" element={<AnalysisPage />} />
        <Route path="/options" element={<Suspense fallback={<div className="h-screen flex items-center justify-center bg-slate-100 dark:bg-slate-900"><LoadingSkeleton /></div>}><OptionScannerPage /></Suspense>} />
        <Route path="/settings" element={<SettingsPage />} />
        <Route path="/help" element={<HelpPage />} />
      </Routes>
    </>
  );
}
