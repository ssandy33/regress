const MODES = [
  {
    value: 'linear',
    label: 'Linear',
    description: 'Single variable regression',
    icon: (
      <svg className="w-5 h-5" fill="none" viewBox="0 0 24 24" stroke="currentColor">
        <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={1.5} d="M3 13h2v8H3zM8 9h2v12H8zM13 5h2v16h-2zM18 1h2v20h-2z" />
      </svg>
    ),
  },
  {
    value: 'multi-factor',
    label: 'Multi-Factor',
    description: 'Multiple independents',
    icon: (
      <svg className="w-5 h-5" fill="none" viewBox="0 0 24 24" stroke="currentColor">
        <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={1.5} d="M4.745 3A23.933 23.933 0 003 12c0 3.183.62 6.22 1.745 9M19.255 3C20.38 5.78 21 8.817 21 12s-.62 6.22-1.745 9M12 3v18M8 12h8" />
      </svg>
    ),
  },
  {
    value: 'rolling',
    label: 'Rolling',
    description: 'Time-windowed analysis',
    icon: (
      <svg className="w-5 h-5" fill="none" viewBox="0 0 24 24" stroke="currentColor">
        <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={1.5} d="M12 6v6h4.5m4.5 0a9 9 0 11-18 0 9 9 0 0118 0z" />
      </svg>
    ),
  },
  {
    value: 'compare',
    label: 'Compare',
    description: 'Side-by-side assets',
    icon: (
      <svg className="w-5 h-5" fill="none" viewBox="0 0 24 24" stroke="currentColor">
        <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={1.5} d="M12 3v18M3 7.5L7.5 3 12 7.5M12 16.5L16.5 21 21 16.5" />
      </svg>
    ),
  },
];

export default function ModeBar({ mode, setMode }) {
  return (
    <div className="w-full border-b border-slate-200 dark:border-slate-700 bg-white dark:bg-slate-900">
      <div className="flex">
        {MODES.map(({ value, label, description, icon }) => {
          const active = mode === value;
          return (
            <button
              key={value}
              onClick={() => setMode(value)}
              aria-pressed={active}
              className={`flex-1 flex items-center justify-center gap-2 px-4 py-3 text-sm font-medium transition-colors border-b-2 ${
                active
                  ? 'border-blue-600 bg-blue-50 dark:bg-blue-900/20 text-blue-700 dark:text-blue-300'
                  : 'border-transparent text-slate-600 dark:text-slate-400 hover:text-slate-900 dark:hover:text-slate-200 hover:bg-slate-50 dark:hover:bg-slate-800'
              }`}
            >
              {icon}
              <div className="flex flex-col items-start">
                <span>{label}</span>
                <span className="text-xs font-normal text-slate-500 dark:text-slate-500 hidden sm:block">
                  {description}
                </span>
              </div>
            </button>
          );
        })}
      </div>
    </div>
  );
}
