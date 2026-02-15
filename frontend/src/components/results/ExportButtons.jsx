import { exportCSV } from '../../utils/export';

export default function ExportButtons({ result, mode, asset }) {
  if (!result) return null;

  const filename = `regression_${asset}_${mode}_${new Date().toISOString().split('T')[0]}`;

  return (
    <div className="flex gap-2">
      <button
        onClick={() => exportCSV(filename, result, mode)}
        className="px-3 py-1.5 text-xs font-medium border border-slate-300 dark:border-slate-600 rounded-lg text-slate-600 dark:text-slate-300 hover:bg-slate-50 dark:hover:bg-slate-700 transition-colors flex items-center gap-1.5"
      >
        <svg className="w-3.5 h-3.5" fill="none" viewBox="0 0 24 24" stroke="currentColor">
          <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M12 10v6m0 0l-3-3m3 3l3-3m2 8H7a2 2 0 01-2-2V5a2 2 0 012-2h5.586a1 1 0 01.707.293l5.414 5.414a1 1 0 01.293.707V19a2 2 0 01-2 2z" />
        </svg>
        Export CSV
      </button>
    </div>
  );
}
