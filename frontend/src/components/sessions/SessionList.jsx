import { useState } from 'react';
import { formatDate } from '../../utils/formatters';

export default function SessionList({ sessions, onLoad, onDelete }) {
  const [confirmId, setConfirmId] = useState(null);

  if (!sessions || sessions.length === 0) return null;

  const handleDelete = (id) => {
    if (confirmId === id) {
      onDelete(id);
      setConfirmId(null);
    } else {
      setConfirmId(id);
      setTimeout(() => setConfirmId(null), 3000);
    }
  };

  return (
    <div className="space-y-1">
      {sessions.map((s) => (
        <div
          key={s.id}
          className="flex items-center justify-between px-3 py-2 rounded-lg hover:bg-slate-100 dark:hover:bg-slate-700 group"
        >
          <button
            onClick={() => onLoad(s.id)}
            className="text-left flex-1 min-w-0"
          >
            <div className="text-sm text-slate-900 dark:text-white truncate">{s.name}</div>
            <div className="text-xs text-slate-400">{formatDate(s.created_at)}</div>
          </button>
          <button
            onClick={() => handleDelete(s.id)}
            className={`ml-2 p-1 rounded text-xs shrink-0 transition-colors ${
              confirmId === s.id
                ? 'bg-red-100 dark:bg-red-900 text-red-600 dark:text-red-300'
                : 'text-slate-400 hover:text-red-500 opacity-0 group-hover:opacity-100'
            }`}
          >
            {confirmId === s.id ? 'Confirm?' : (
              <svg className="w-4 h-4" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M19 7l-.867 12.142A2 2 0 0116.138 21H7.862a2 2 0 01-1.995-1.858L5 7m5 4v6m4-6v6m1-10V4a1 1 0 00-1-1h-4a1 1 0 00-1 1v3M4 7h16" />
              </svg>
            )}
          </button>
        </div>
      ))}
    </div>
  );
}
