const MODES = [
  { value: 'linear', label: 'Linear' },
  { value: 'multi-factor', label: 'Multi' },
  { value: 'rolling', label: 'Rolling' },
  { value: 'compare', label: 'Compare' },
];

export default function RegressionMode({ mode, setMode }) {
  return (
    <div>
      <label className="block text-xs font-medium text-slate-500 dark:text-slate-400 mb-1.5">
        Regression Mode
      </label>
      <div className="flex rounded-lg border border-slate-300 dark:border-slate-600 overflow-hidden">
        {MODES.map(({ value, label }) => (
          <button
            key={value}
            onClick={() => setMode(value)}
            className={`flex-1 py-2 text-xs font-medium transition-colors ${
              mode === value
                ? 'bg-blue-600 text-white'
                : 'bg-white dark:bg-slate-700 text-slate-600 dark:text-slate-300 hover:bg-slate-50 dark:hover:bg-slate-600'
            }`}
          >
            {label}
          </button>
        ))}
      </div>
    </div>
  );
}
