import { useState } from 'react';
import DatePicker from 'react-datepicker';
import 'react-datepicker/dist/react-datepicker.css';

const PRESETS = [
  { label: '1Y', years: 1 },
  { label: '3Y', years: 3 },
  { label: '5Y', years: 5 },
  { label: '10Y', years: 10 },
  { label: 'Max', years: 30 },
];

export default function DateRangePicker({ startDate, endDate, onStartChange, onEndChange }) {
  const [activePreset, setActivePreset] = useState('5Y');
  const start = startDate ? new Date(startDate + 'T00:00:00') : null;
  const end = endDate ? new Date(endDate + 'T00:00:00') : null;

  const applyPreset = (label, years) => {
    const now = new Date();
    const past = new Date();
    past.setFullYear(now.getFullYear() - years);
    onStartChange(past.toISOString().split('T')[0]);
    onEndChange(now.toISOString().split('T')[0]);
    setActivePreset(label);
  };

  const toDateStr = (date) => {
    if (!date) return '';
    return date.toISOString().split('T')[0];
  };

  const handleManualChange = (setter) => (date) => {
    setter(toDateStr(date));
    setActivePreset(null);
  };

  return (
    <div>
      <label className="block text-xs font-medium text-slate-500 dark:text-slate-400 mb-1.5">
        Date Range
      </label>

      {/* Preset buttons */}
      <div className="flex gap-1 mb-2">
        {PRESETS.map(({ label, years }) => (
          <button
            key={label}
            onClick={() => applyPreset(label, years)}
            className={`flex-1 py-1 text-xs font-medium rounded border transition-colors ${
              activePreset === label
                ? 'bg-blue-600 border-blue-600 text-white'
                : 'border-slate-300 dark:border-slate-600 text-slate-600 dark:text-slate-300 hover:bg-slate-100 dark:hover:bg-slate-700'
            }`}
          >
            {label}
          </button>
        ))}
      </div>

      {/* Date inputs */}
      <div className="flex gap-2">
        <div className="flex-1">
          <DatePicker
            selected={start}
            onChange={handleManualChange(onStartChange)}
            dateFormat="yyyy-MM-dd"
            placeholderText="Start"
            maxDate={end}
            className="w-full px-2 py-1.5 text-sm border border-slate-300 dark:border-slate-600 rounded bg-white dark:bg-slate-700 text-slate-900 dark:text-slate-100 outline-none focus:ring-2 focus:ring-blue-500"
          />
        </div>
        <div className="flex-1">
          <DatePicker
            selected={end}
            onChange={handleManualChange(onEndChange)}
            dateFormat="yyyy-MM-dd"
            placeholderText="End"
            minDate={start}
            maxDate={new Date()}
            className="w-full px-2 py-1.5 text-sm border border-slate-300 dark:border-slate-600 rounded bg-white dark:bg-slate-700 text-slate-900 dark:text-slate-100 outline-none focus:ring-2 focus:ring-blue-500"
          />
        </div>
      </div>
    </div>
  );
}
