import { useState } from 'react';
import { useJournal } from '../../hooks/useJournal';
import Header from '../layout/Header';
import PositionsTable from './PositionsTable';
import TradeHistory from './TradeHistory';
import PositionForm from './PositionForm';
import ImportModal from './ImportModal';

export default function JournalPage() {
  const journal = useJournal();
  const [showNewPosition, setShowNewPosition] = useState(false);
  const [showImport, setShowImport] = useState(false);

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
            preview={journal.importPreview}
            loading={journal.importLoading}
          />
        )}
      </main>
    </div>
  );
}
