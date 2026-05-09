import { useState, useEffect, useRef } from 'react';
import { useSearchParams } from 'next/navigation';
import { useJournal } from '../../hooks/useJournal';
import Header from '../layout/Header';
import PositionsTable from './PositionsTable';
import TradeHistory from './TradeHistory';
import PositionForm from './PositionForm';
import ImportModal from './ImportModal';
import ConfirmDialog from '../common/ConfirmDialog';

export default function JournalPage() {
  const journal = useJournal();
  const [showNewPosition, setShowNewPosition] = useState(false);
  const [showImport, setShowImport] = useState(false);
  const [pendingDeletePositionId, setPendingDeletePositionId] = useState(null);
  const [deleteBusy, setDeleteBusy] = useState(false);
  const searchParams = useSearchParams();
  const positionParam = searchParams?.get('position') ?? null;
  const consumedDeepLinkRef = useRef(false);

  // Pull stable refs out of the journal hook for the deep-link effect's
  // dependency list — keeps `react-hooks/exhaustive-deps` honest without
  // re-running on every unrelated journal field change.
  const { loading: journalLoading, selectPosition } = journal;

  // Deep-link consumer: when arriving at /journal?position=<id> (e.g. from a
  // dashboard PositionsCard or RecentActivityCard row), select that position
  // once the initial positions fetch settles. We only honor the param once
  // per mount so the user can later click another row without the deep-link
  // snapping back to the original selection.
  useEffect(() => {
    if (!positionParam) {
      consumedDeepLinkRef.current = false;
      return;
    }
    if (journalLoading) return;
    if (consumedDeepLinkRef.current) return;
    consumedDeepLinkRef.current = true;
    selectPosition(positionParam);
  }, [positionParam, journalLoading, selectPosition]);

  const handleCreatePosition = async (data) => {
    try {
      await journal.addPosition(data);
      setShowNewPosition(false);
    } catch {
      // Form stays open for retry; error toast handled by hook
    }
  };

  const handleCloseImport = () => {
    setShowImport(false);
    journal.clearImportPreview();
  };

  const pendingDeletePosition = pendingDeletePositionId
    ? journal.positions.find((p) => p.id === pendingDeletePositionId) || null
    : null;

  const handleConfirmDeletePosition = async () => {
    if (!pendingDeletePositionId) return;
    setDeleteBusy(true);
    try {
      await journal.removePosition(pendingDeletePositionId);
      setPendingDeletePositionId(null);
    } finally {
      setDeleteBusy(false);
    }
  };

  return (
    <div data-testid="journal-page" className="h-screen flex flex-col bg-slate-100 dark:bg-slate-900">
      <Header sessions={[]} onLoadSession={() => {}} />

      <main className="flex-1 overflow-y-auto p-6 space-y-6">
        <div className="flex items-center justify-between">
          <h1 className="text-xl font-semibold text-slate-900 dark:text-white">Positions</h1>
          <div className="flex gap-2">
            <button
              data-testid="import-schwab-btn"
              onClick={() => setShowImport(true)}
              className="px-4 py-2 bg-emerald-600 text-white text-sm font-medium rounded-lg hover:bg-emerald-700"
            >
              Import from Schwab
            </button>
            <button
              data-testid="new-position-btn"
              onClick={() => setShowNewPosition(true)}
              className="px-4 py-2 bg-blue-600 text-white text-sm font-medium rounded-lg hover:bg-blue-700"
            >
              New Position
            </button>
          </div>
        </div>

        <PositionsTable
          positions={journal.positions}
          loading={journal.loading}
          onSelectPosition={journal.selectPosition}
          selectedPositionId={journal.selectedPosition?.id || null}
          onDeletePosition={(id) => setPendingDeletePositionId(id)}
        />

        {journal.selectedPosition && (
          <TradeHistory
            position={journal.selectedPosition}
            onAddTrade={journal.addTrade}
            onDeleteTrade={journal.removeTrade}
          />
        )}

        {showNewPosition && (
          <PositionForm
            onSubmit={handleCreatePosition}
            onCancel={() => setShowNewPosition(false)}
          />
        )}

        {showImport && (
          <ImportModal
            onClose={handleCloseImport}
            onPreview={journal.previewImport}
            onImport={journal.confirmImport}
            onPreviewCsv={journal.previewCsvImport}
            onImportCsv={journal.confirmCsvImport}
            preview={journal.importPreview}
            loading={journal.importLoading}
          />
        )}

        {pendingDeletePositionId && (
          <ConfirmDialog
            title="Delete position?"
            message={
              pendingDeletePosition ? (
                <p>
                  Delete{' '}
                  <strong>{pendingDeletePosition.ticker}</strong>? This will permanently
                  remove the position and{' '}
                  <strong>{pendingDeletePosition.trades?.length ?? 0} trades</strong>.
                </p>
              ) : (
                <p>Delete this position? This will permanently remove the position and all of its trades.</p>
              )
            }
            confirmLabel="Delete"
            busy={deleteBusy}
            onConfirm={handleConfirmDeletePosition}
            onCancel={() => {
              if (!deleteBusy) setPendingDeletePositionId(null);
            }}
          />
        )}
      </main>
    </div>
  );
}
