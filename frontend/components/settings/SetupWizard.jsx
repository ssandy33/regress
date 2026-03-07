import { useState } from 'react';
import toast from 'react-hot-toast';
import { updateSetting, checkFredHealth } from '../../api/client';

export default function SetupWizard({ onComplete }) {
  const [fredKey, setFredKey] = useState('');
  const [validating, setValidating] = useState(false);
  const [step, setStep] = useState('welcome'); // welcome | key | done

  const handleValidate = async () => {
    if (!fredKey.trim()) return;
    setValidating(true);
    try {
      await updateSetting('fred_api_key', fredKey.trim());
      const result = await checkFredHealth();
      if (result.valid) {
        setStep('done');
      } else {
        toast.error('Key saved but validation failed. You can still proceed — some features may not work.');
        setStep('done');
      }
    } catch {
      toast.error('Failed to save key');
    } finally {
      setValidating(false);
    }
  };

  if (step === 'welcome') {
    return (
      <div className="fixed inset-0 z-50 flex items-center justify-center bg-slate-900/80">
        <div className="bg-white dark:bg-slate-800 rounded-2xl shadow-2xl w-full max-w-lg mx-4 p-8 text-center">
          <div className="w-16 h-16 bg-blue-100 dark:bg-blue-900 rounded-2xl flex items-center justify-center mx-auto mb-6">
            <svg className="w-8 h-8 text-blue-600" fill="none" viewBox="0 0 24 24" stroke="currentColor">
              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M9 19v-6a2 2 0 00-2-2H5a2 2 0 00-2 2v6a2 2 0 002 2h2a2 2 0 002-2zm0 0V9a2 2 0 012-2h2a2 2 0 012 2v10m-6 0a2 2 0 002 2h2a2 2 0 002-2m0 0V5a2 2 0 012-2h2a2 2 0 012 2v14a2 2 0 01-2 2h-2a2 2 0 01-2-2z" />
            </svg>
          </div>

          <h1 className="text-2xl font-bold text-slate-900 dark:text-white mb-2">
            Welcome to Regression Analysis Tool
          </h1>
          <p className="text-slate-500 dark:text-slate-400 mb-6">
            Analyze financial trends with linear, multi-factor, and rolling regression models.
          </p>

          <div className="space-y-3">
            <button
              onClick={() => setStep('key')}
              className="w-full py-3 bg-blue-600 hover:bg-blue-700 text-white rounded-xl font-medium"
            >
              Set Up FRED API Key
            </button>
            <button
              onClick={onComplete}
              className="w-full py-3 text-slate-500 hover:text-slate-700 dark:text-slate-400 dark:hover:text-slate-200 text-sm"
            >
              Skip for now (stock data will still work)
            </button>
          </div>
        </div>
      </div>
    );
  }

  if (step === 'key') {
    return (
      <div className="fixed inset-0 z-50 flex items-center justify-center bg-slate-900/80">
        <div className="bg-white dark:bg-slate-800 rounded-2xl shadow-2xl w-full max-w-lg mx-4 p-8">
          <h2 className="text-xl font-bold text-slate-900 dark:text-white mb-2">
            FRED API Key
          </h2>
          <p className="text-sm text-slate-500 dark:text-slate-400 mb-4">
            A free API key from the Federal Reserve Economic Data service.
            This enables interest rate, housing index, and economic data.
          </p>

          <div className="mb-4 p-3 bg-blue-50 dark:bg-blue-900/30 border border-blue-200 dark:border-blue-800 rounded-lg text-sm text-blue-700 dark:text-blue-300">
            Get your free key at{' '}
            <a href="https://fred.stlouisfed.org/docs/api/api_key.html" target="_blank" rel="noopener noreferrer" className="underline font-medium">
              fred.stlouisfed.org
            </a>
          </div>

          <input
            type="text"
            value={fredKey}
            onChange={(e) => setFredKey(e.target.value)}
            placeholder="Paste your 32-character API key"
            className="w-full px-4 py-3 mb-4 border border-slate-300 dark:border-slate-600 rounded-xl bg-white dark:bg-slate-700 text-slate-900 dark:text-slate-100 outline-none focus:ring-2 focus:ring-blue-500 font-mono text-sm"
          />

          <div className="flex gap-3">
            <button
              onClick={onComplete}
              className="flex-1 py-3 text-slate-500 hover:text-slate-700 dark:text-slate-400 dark:hover:text-slate-200 rounded-xl"
            >
              Skip
            </button>
            <button
              onClick={handleValidate}
              disabled={!fredKey.trim() || validating}
              className="flex-1 py-3 bg-blue-600 hover:bg-blue-700 disabled:bg-blue-400 text-white rounded-xl font-medium"
            >
              {validating ? 'Validating...' : 'Save & Continue'}
            </button>
          </div>
        </div>
      </div>
    );
  }

  // Done
  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-slate-900/80">
      <div className="bg-white dark:bg-slate-800 rounded-2xl shadow-2xl w-full max-w-lg mx-4 p-8 text-center">
        <div className="w-16 h-16 bg-green-100 dark:bg-green-900 rounded-2xl flex items-center justify-center mx-auto mb-6">
          <svg className="w-8 h-8 text-green-600" fill="none" viewBox="0 0 24 24" stroke="currentColor">
            <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M5 13l4 4L19 7" />
          </svg>
        </div>

        <h2 className="text-xl font-bold text-slate-900 dark:text-white mb-2">
          You&apos;re all set!
        </h2>
        <p className="text-slate-500 dark:text-slate-400 mb-6">
          Your FRED API key has been saved. You can now access interest rates, housing indices, and more.
        </p>

        <button
          onClick={onComplete}
          className="w-full py-3 bg-blue-600 hover:bg-blue-700 text-white rounded-xl font-medium"
        >
          Start Analyzing
        </button>
      </div>
    </div>
  );
}
