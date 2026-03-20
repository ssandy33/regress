import { useState } from 'react';
import { useJournal } from '../../hooks/useJournal';
import Header from '../layout/Header';
import PositionsTable from './PositionsTable';
import TradeHistory from './TradeHistory';
import PositionForm from './PositionForm';

export default function JournalPage() {
  const journal = useJournal();
  const [showNewPosition, setShowNewPosition] = useState(false);

  const handleCreatePosition = async (data) => {
    await journal.addPosition(data);
    setShowNewPosition(false);
  };

  return (
    <div data-testid="journal-page" className="h-screen flex flex-col bg-slate-100 dark:bg-slate-900">
      <Header sessions={[]} onLoadSession={() => {}} />

      <main className="flex-1 overflow-y-auto p-6 space-y-6">
        <div className="flex items-center justify-between">
          <h1 className="text-xl font-semibold text-slate-900 dark:text-white">Positions</h1>
          <button
            data-testid="new-position-btn"
            onClick={() => setShowNewPosition(true)}
            className="px-4 py-2 bg-blue-600 text-white text-sm font-medium rounded-lg hover:bg-blue-700"
          >
            New Position
          </button>
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
            onEditTrade={journal.editTrade}
            onDeleteTrade={journal.removeTrade}
          />
        )}

        {showNewPosition && (
          <PositionForm
            onSubmit={handleCreatePosition}
            onCancel={() => setShowNewPosition(false)}
          />
        )}
      </main>
    </div>
  );
}
