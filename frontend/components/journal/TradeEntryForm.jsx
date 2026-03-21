import { useState } from 'react';

const TRADE_TYPES = [
  { value: 'sell_put', label: 'Sell Put' },
  { value: 'buy_put_close', label: 'Buy Put Close' },
  { value: 'assignment', label: 'Assignment' },
  { value: 'sell_call', label: 'Sell Call' },
  { value: 'buy_call_close', label: 'Buy Call Close' },
  { value: 'called_away', label: 'Called Away' },
];

const CLOSE_REASONS = [
  { value: '', label: 'None' },
  { value: 'fifty_pct_target', label: '50% Target' },
  { value: 'full_expiration', label: 'Full Expiration' },
  { value: 'rolled', label: 'Rolled' },
  { value: 'closed_early', label: 'Closed Early' },
  { value: 'assigned', label: 'Assigned' },
  { value: 'called_away', label: 'Called Away' },
];

export default function TradeEntryForm({ positionId, onSubmit, onCancel }) {
  const [form, setForm] = useState({
    trade_type: 'sell_put',
    strike: '',
    expiration: '',
    premium: '',
    fees: '0',
    quantity: '1',
    close_reason: '',
  });

  const handleChange = (e) => {
    setForm((prev) => ({ ...prev, [e.target.name]: e.target.value }));
  };

  const handleSubmit = (e) => {
    e.preventDefault();
    onSubmit({
      position_id: positionId,
      trade_type: form.trade_type,
      strike: parseFloat(form.strike),
      expiration: form.expiration,
      premium: parseFloat(form.premium),
      fees: parseFloat(form.fees) || 0,
      quantity: parseInt(form.quantity) || 1,
      opened_at: new Date().toISOString(),
      close_reason: form.close_reason || null,
    });
  };

  const inputClass = 'w-full border border-slate-300 dark:border-slate-600 rounded-lg px-3 py-2 text-sm bg-white dark:bg-slate-700 text-slate-900 dark:text-white';
  const labelClass = 'block text-sm font-medium text-slate-700 dark:text-slate-300 mb-1';

  return (
    <form data-testid="trade-entry-form" onSubmit={handleSubmit} className="bg-slate-50 dark:bg-slate-800/50 border border-slate-200 dark:border-slate-700 rounded-xl p-4 space-y-4">
      <h3 className="text-sm font-semibold text-slate-900 dark:text-white">New Trade</h3>
      <div className="grid grid-cols-2 md:grid-cols-4 gap-4">
        <div>
          <label className={labelClass}>Type</label>
          <select name="trade_type" value={form.trade_type} onChange={handleChange} className={inputClass}>
            {TRADE_TYPES.map((t) => <option key={t.value} value={t.value}>{t.label}</option>)}
          </select>
        </div>
        <div>
          <label className={labelClass}>Strike</label>
          <input name="strike" type="number" step="0.01" value={form.strike} onChange={handleChange} required placeholder="145.00" className={inputClass} />
        </div>
        <div>
          <label className={labelClass}>Expiration</label>
          <input name="expiration" type="date" value={form.expiration} onChange={handleChange} required className={inputClass} />
        </div>
        <div>
          <label className={labelClass}>Premium</label>
          <input name="premium" type="number" step="0.01" value={form.premium} onChange={handleChange} required placeholder="1.50" className={inputClass} />
        </div>
        <div>
          <label className={labelClass}>Fees</label>
          <input name="fees" type="number" step="0.01" value={form.fees} onChange={handleChange} className={inputClass} />
        </div>
        <div>
          <label className={labelClass}>Quantity</label>
          <input name="quantity" type="number" min="1" value={form.quantity} onChange={handleChange} className={inputClass} />
        </div>
        <div>
          <label className={labelClass}>Close Reason</label>
          <select name="close_reason" value={form.close_reason} onChange={handleChange} className={inputClass}>
            {CLOSE_REASONS.map((r) => <option key={r.value} value={r.value}>{r.label}</option>)}
          </select>
        </div>
      </div>
      <div className="flex gap-2">
        <button type="submit" className="px-4 py-2 bg-blue-600 text-white text-sm font-medium rounded-lg hover:bg-blue-700">
          Save Trade
        </button>
        <button type="button" onClick={onCancel} className="px-4 py-2 bg-slate-200 dark:bg-slate-700 text-slate-700 dark:text-slate-300 text-sm font-medium rounded-lg hover:bg-slate-300 dark:hover:bg-slate-600">
          Cancel
        </button>
      </div>
    </form>
  );
}
