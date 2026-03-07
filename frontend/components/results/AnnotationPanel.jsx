import { useState } from 'react';
import DatePicker from 'react-datepicker';
import 'react-datepicker/dist/react-datepicker.css';

export default function AnnotationPanel({ annotations, onAdd, onRemove, dates }) {
  const [open, setOpen] = useState(false);
  const [date, setDate] = useState(null);
  const [text, setText] = useState('');

  const handleAdd = () => {
    if (!date || !text.trim()) return;
    onAdd({ date: date.toISOString().split('T')[0], text: text.trim() });
    setDate(null);
    setText('');
    setOpen(false);
  };

  const minDate = dates?.length ? new Date(dates[0] + 'T00:00:00') : undefined;
  const maxDate = dates?.length ? new Date(dates[dates.length - 1] + 'T00:00:00') : undefined;

  return (
    <div>
      <div className="flex items-center justify-between mb-2">
        <h3 className="text-sm font-medium text-slate-700 dark:text-slate-200">
          Annotations
        </h3>
        <button
          onClick={() => setOpen(!open)}
          className="text-xs text-blue-600 hover:text-blue-700 dark:text-blue-400"
        >
          {open ? 'Cancel' : '+ Add'}
        </button>
      </div>

      {/* Add annotation form */}
      {open && (
        <div className="mb-3 p-3 bg-slate-50 dark:bg-slate-800 border border-slate-200 dark:border-slate-700 rounded-lg space-y-2">
          <div>
            <label className="block text-xs text-slate-500 dark:text-slate-400 mb-1">Date</label>
            <DatePicker
              selected={date}
              onChange={setDate}
              dateFormat="yyyy-MM-dd"
              minDate={minDate}
              maxDate={maxDate}
              placeholderText="Select date"
              className="w-full px-2 py-1.5 text-sm border border-slate-300 dark:border-slate-600 rounded bg-white dark:bg-slate-700 text-slate-900 dark:text-slate-100 outline-none focus:ring-2 focus:ring-blue-500"
            />
          </div>
          <div>
            <label className="block text-xs text-slate-500 dark:text-slate-400 mb-1">Note</label>
            <input
              type="text"
              value={text}
              onChange={(e) => setText(e.target.value)}
              onKeyDown={(e) => e.key === 'Enter' && handleAdd()}
              placeholder="e.g., Fed rate hike"
              className="w-full px-2 py-1.5 text-sm border border-slate-300 dark:border-slate-600 rounded bg-white dark:bg-slate-700 text-slate-900 dark:text-slate-100 outline-none focus:ring-2 focus:ring-blue-500"
            />
          </div>
          <button
            onClick={handleAdd}
            disabled={!date || !text.trim()}
            className="px-3 py-1.5 text-xs bg-blue-600 text-white rounded hover:bg-blue-700 disabled:bg-blue-400"
          >
            Add Annotation
          </button>
        </div>
      )}

      {/* Annotation list */}
      {annotations.length > 0 && (
        <div className="space-y-1">
          {annotations.map((a, i) => (
            <div key={i} className="flex items-center justify-between px-2 py-1 text-xs bg-slate-50 dark:bg-slate-800 rounded group">
              <span>
                <span className="text-slate-400 mr-1.5">{a.date}</span>
                <span className="text-slate-700 dark:text-slate-200">{a.text}</span>
              </span>
              <button
                onClick={() => onRemove(i)}
                className="text-slate-400 hover:text-red-500 opacity-0 group-hover:opacity-100"
              >
                &times;
              </button>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}
