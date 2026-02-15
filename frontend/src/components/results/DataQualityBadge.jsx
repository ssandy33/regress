import { formatDate } from '../../utils/formatters';

export default function DataQualityBadge({ meta }) {
  if (!meta) return null;

  const items = Array.isArray(meta) ? meta : [meta];

  return (
    <div className="flex flex-wrap gap-1.5">
      {items.map((m, i) => (
        <div
          key={i}
          className="inline-flex items-center gap-1.5 px-2 py-1 text-[11px] rounded-full border border-slate-200 dark:border-slate-600 bg-white dark:bg-slate-800"
        >
          <span className={`w-1.5 h-1.5 rounded-full ${
            m.is_stale ? 'bg-yellow-400' : 'bg-green-400'
          }`} />
          <span className="font-medium text-slate-700 dark:text-slate-200">{m.source}</span>
          <span className="text-slate-400">|</span>
          <span className="text-slate-500 dark:text-slate-400">{m.frequency}</span>
          <span className="text-slate-400">|</span>
          <span className="text-slate-500 dark:text-slate-400">{formatDate(m.fetched_at)}</span>
        </div>
      ))}
    </div>
  );
}
