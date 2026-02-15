import { useState, useEffect } from 'react';
import { getCaseShillerMetros } from '../../api/client';

export default function RealEstateSelector({ asset, onAssetChange, onBack }) {
  const [metros, setMetros] = useState([]);
  const [zipCode, setZipCode] = useState('');
  const [zipError, setZipError] = useState('');
  const [selectedMetro, setSelectedMetro] = useState('');

  useEffect(() => {
    getCaseShillerMetros().then(setMetros).catch(() => {});
  }, []);

  const handleMetroChange = (e) => {
    const id = e.target.value;
    setSelectedMetro(id);
    if (id) onAssetChange(id);
  };

  const handleZipSubmit = () => {
    const cleaned = zipCode.trim();
    if (!/^\d{5}$/.test(cleaned)) {
      setZipError('Enter a valid 5-digit zip code');
      return;
    }
    setZipError('');
    // For zip codes, we use a special prefix so the frontend knows to use the zillow endpoint
    onAssetChange(`ZIP:${cleaned}`);
  };

  return (
    <div className="space-y-4">
      <div className="flex items-center justify-between">
        <label className="text-xs font-medium text-slate-500 dark:text-slate-400">
          Real Estate
        </label>
        <button
          onClick={onBack}
          className="text-xs text-blue-600 hover:text-blue-700 dark:text-blue-400"
        >
          Back to Assets
        </button>
      </div>

      {/* Info note */}
      <div className="px-3 py-2 bg-blue-50 dark:bg-blue-900/30 border border-blue-200 dark:border-blue-800 rounded-lg text-xs text-blue-700 dark:text-blue-300">
        Case-Shiller data is monthly with ~2 month lag
      </div>

      {/* Case-Shiller Metro dropdown */}
      <div>
        <label className="block text-xs font-medium text-slate-500 dark:text-slate-400 mb-1.5">
          Case-Shiller Metro
        </label>
        <select
          value={selectedMetro}
          onChange={handleMetroChange}
          className="w-full px-3 py-2 text-sm border border-slate-300 dark:border-slate-600 rounded-lg bg-white dark:bg-slate-700 text-slate-900 dark:text-slate-100 outline-none focus:ring-2 focus:ring-blue-500"
        >
          <option value="">Select a metro...</option>
          {metros.map((m) => (
            <option key={m.identifier} value={m.identifier}>
              {m.name.replace('Case-Shiller ', '')}
            </option>
          ))}
        </select>
      </div>

      {/* Zillow Zip Code search */}
      <div>
        <label className="block text-xs font-medium text-slate-500 dark:text-slate-400 mb-1.5">
          Zillow Zip Code (ZHVI)
        </label>
        <div className="flex gap-2">
          <input
            type="text"
            value={zipCode}
            onChange={(e) => { setZipCode(e.target.value); setZipError(''); }}
            onKeyDown={(e) => e.key === 'Enter' && handleZipSubmit()}
            placeholder="e.g., 85254"
            maxLength={5}
            className="flex-1 px-3 py-2 text-sm border border-slate-300 dark:border-slate-600 rounded-lg bg-white dark:bg-slate-700 text-slate-900 dark:text-slate-100 outline-none focus:ring-2 focus:ring-blue-500"
          />
          <button
            onClick={handleZipSubmit}
            className="px-3 py-2 text-sm bg-blue-600 text-white rounded-lg hover:bg-blue-700"
          >
            Go
          </button>
        </div>
        {zipError && <p className="text-xs text-red-500 mt-1">{zipError}</p>}
      </div>

      {/* Current selection */}
      {asset && (
        <div className="px-3 py-2 bg-slate-100 dark:bg-slate-700 rounded-lg">
          <div className="text-xs text-slate-500 dark:text-slate-400">Selected</div>
          <div className="text-sm font-medium text-slate-900 dark:text-white">{asset}</div>
        </div>
      )}
    </div>
  );
}
