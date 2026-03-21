import { useState } from 'react';

const STRATEGIES = [
  { value: 'csp', label: 'Cash Secured Put' },
  { value: 'cc', label: 'Covered Call' },
  { value: 'wheel', label: 'Wheel' },
];

export default function PositionForm({ onSubmit, onCancel }) {
  const [form, setForm] = useState({
    ticker: '',
    shares: '100',
    broker_cost_basis: '',
    strategy: 'csp',
    opened_at: new Date().toISOString().split('T')[0],
    notes: '',
  });

  const handleChange = (e) => {
    setForm((prev) => ({ ...prev, [e.target.name]: e.target.value }));
  };

  const handleSubmit = (e) => {
    e.preventDefault();
    const date = new Date(form.opened_at);
    if (isNaN(date.getTime())) return;
    onSubmit({
      ticker: form.ticker.toUpperCase().trim(),
      shares: parseInt(form.shares) || 100,
      broker_cost_basis: parseFloat(form.broker_cost_basis),
      strategy: form.strategy,
      opened_at: date.toISOString(),
      notes: form.notes || null,
    });
  };

  const inputClass = 'w-full border border-slate-300 dark:border-slate-600 rounded-lg px-3 py-2 text-sm bg-white dark:bg-slate-700 text-slate-900 dark:text-white';
  const labelClass = 'block text-sm font-medium text-slate-700 dark:text-slate-300 mb-1';

  return (
    <div className="fixed inset-0 bg-black/50 flex items-center justify-center z-50">
      <form data-testid="position-form" onSubmit={handleSubmit} className="bg-white dark:bg-slate-800 rounded-xl p-6 w-full max-w-md space-y-4 shadow-xl">
        <h2 className="text-lg font-semibold text-slate-900 dark:text-white">New Position</h2>
        <div>
          <label className={labelClass}>Ticker</label>
          <input name="ticker" value={form.ticker} onChange={handleChange} required placeholder="AAPL" className={inputClass} />
        </div>
        <div className="grid grid-cols-2 gap-4">
          <div>
            <label className={labelClass}>Shares</label>
            <input name="shares" type="number" min="1" value={form.shares} onChange={handleChange} className={inputClass} />
          </div>
          <div>
            <label className={labelClass}>Broker Cost Basis ($)</label>
            <input name="broker_cost_basis" type="number" step="0.01" value={form.broker_cost_basis} onChange={handleChange} required placeholder="15000.00" className={inputClass} />
          </div>
        </div>
        <div className="grid grid-cols-2 gap-4">
          <div>
            <label className={labelClass}>Strategy</label>
            <select name="strategy" value={form.strategy} onChange={handleChange} className={inputClass}>
              {STRATEGIES.map((s) => <option key={s.value} value={s.value}>{s.label}</option>)}
            </select>
          </div>
          <div>
            <label className={labelClass}>Opened Date</label>
            <input name="opened_at" type="date" value={form.opened_at} onChange={handleChange} required className={inputClass} />
          </div>
        </div>
        <div>
          <label className={labelClass}>Notes (optional)</label>
          <textarea name="notes" value={form.notes} onChange={handleChange} rows={2} className={inputClass} />
        </div>
        <div className="flex gap-2 pt-2">
          <button type="submit" className="px-4 py-2 bg-blue-600 text-white text-sm font-medium rounded-lg hover:bg-blue-700">
            Create Position
          </button>
          <button type="button" onClick={onCancel} className="px-4 py-2 bg-slate-200 dark:bg-slate-700 text-slate-700 dark:text-slate-300 text-sm font-medium rounded-lg hover:bg-slate-300 dark:hover:bg-slate-600">
            Cancel
          </button>
        </div>
      </form>
    </div>
  );
}
