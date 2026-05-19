import { useEffect, useState } from 'react';
import toast from 'react-hot-toast';
import { getSettings, updateSetting } from '../../api/client';
import { isBlank, validateScalar } from './rulesValidation';

/**
 * Settings → Trading Objectives section (issue #207).
 *
 * The V1.0.3 minimal stopgap that gives the dead-ending Recovery Plan
 * "Set target yield →" CTA a real destination and un-suppresses the
 * Sell & redeploy path. A single field — Target yield.
 *
 * This is NOT the full V1.1 OKR Scorecard. The flat `okr_target_yield`
 * app-setting key migrates into the typed `okr_config` namespace in V1.1
 * (ADR-001 / Discussion #210); this tab is the seed of that surface — V1.1
 * extends it rather than replacing it.
 *
 * Unit convention (design spec §4): the field accepts/displays WHOLE PERCENT
 * (the trader types `12`); the backend stores `okr_target_yield` as a FRACTION
 * (`0.12`). The conversion lives only in this component — `*100` on load (with
 * a `toFixed(4)` clean-up for float artefacts) and `/100` on save. The backend
 * storage and the recovery engine stay untouched.
 *
 * Form state holds the value as a *string* so blank `""` (the honest "unset"
 * signal) stays distinct from a real entered `"0"`. Validation reuses the pure
 * `validateScalar('pctOpen100', …)` / `isBlank` helpers from `rulesValidation`
 * — no new validator. Failure copy is fixed generic text (CLAUDE.md).
 */

const LOAD_ERROR = "Couldn't load your target yield.";
const SAVE_ERROR = "Couldn't save your target yield. Please try again.";

/** Convert the stored fraction (or null) into the whole-percent form string.
 * `0.12 * 100` is `12.000000000000002` in JS floating point — `toFixed(4)`
 * cleans the artefact, then `Number` strips trailing zeros. */
function fractionToFormValue(fraction) {
  if (fraction === null || fraction === undefined) return '';
  return String(Number((fraction * 100).toFixed(4)));
}

export default function TradingObjectivesSection() {
  // `value` / `savedValue` are whole-percent strings. `""` is the unset state.
  const [value, setValue] = useState('');
  const [savedValue, setSavedValue] = useState('');
  const [error, setError] = useState(null);
  const [touched, setTouched] = useState(false);
  const [loading, setLoading] = useState(true);
  const [loadError, setLoadError] = useState(false);
  const [saving, setSaving] = useState(false);
  const [saveError, setSaveError] = useState(false);
  const [saveSuccess, setSaveSuccess] = useState(false);
  const [lastSaved, setLastSaved] = useState(null);

  const load = () => {
    setLoading(true);
    setLoadError(false);
    getSettings()
      .then((settings) => {
        const v = fractionToFormValue(settings?.okr_target_yield);
        setValue(v);
        setSavedValue(v);
      })
      .catch(() => setLoadError(true))
      .finally(() => setLoading(false));
  };

  useEffect(load, []);

  const dirty = value !== savedValue;
  // Blank is the legitimate unset state — it disables Save rather than showing
  // an error. Any non-blank value runs through the `pctOpen100` validator.
  const canSave = dirty && !isBlank(value) && !error && !saving;

  // Re-validate once the field has been touched (blur) so a fix clears the
  // error live — the `touched`/`revalidate` pattern from TradingRulesSection.
  useEffect(() => {
    if (!touched) return;
    setError(isBlank(value) ? null : validateScalar('pctOpen100', value));
  }, [value, touched]);

  const handleChange = (next) => {
    setValue(next);
    setSaveError(false);
    setSaveSuccess(false);
  };

  const handleBlur = () => {
    setTouched(true);
    setError(isBlank(value) ? null : validateScalar('pctOpen100', value));
  };

  const handleSave = async () => {
    setTouched(true);
    if (isBlank(value)) return;
    const found = validateScalar('pctOpen100', value);
    setError(found);
    if (found) return;

    setSaving(true);
    setSaveError(false);
    try {
      // Whole-percent → fraction at the one boundary (design spec §4.2).
      const fraction = Number(value) / 100;
      await updateSetting('okr_target_yield', String(fraction));
      setSavedValue(value);
      setLastSaved(new Date());
      setSaveSuccess(true);
      toast.success('Target yield saved');
      setTimeout(() => setSaveSuccess(false), 2500);
    } catch {
      setSaveError(true);
      toast.error('Failed to save target yield');
    } finally {
      setSaving(false);
    }
  };

  const header = (
    <div>
      <h2 className="text-lg font-semibold text-slate-900 dark:text-white">
        Trading Objectives
      </h2>
      <p className="text-sm text-slate-500 dark:text-slate-400">
        The targets your strategy aims for. Used by the Recovery Plan.
      </p>
    </div>
  );

  if (loading) {
    return (
      <div
        data-testid="settings-objectives-loading"
        className="bg-slate-50 dark:bg-slate-800 rounded-xl p-6 border border-slate-200 dark:border-slate-700 animate-pulse"
      >
        <div className="h-5 w-44 bg-slate-200 dark:bg-slate-700 rounded mb-4" />
        <div className="space-y-2">
          <div className="h-3 w-24 bg-slate-200 dark:bg-slate-700 rounded" />
          <div className="h-9 w-48 bg-slate-200 dark:bg-slate-700 rounded-lg" />
        </div>
        <div className="h-9 w-32 bg-slate-200 dark:bg-slate-700 rounded-lg mt-6" />
      </div>
    );
  }

  if (loadError) {
    return (
      <div className="bg-slate-50 dark:bg-slate-800 rounded-xl p-6 border border-slate-200 dark:border-slate-700">
        {header}
        <div
          data-testid="settings-objectives-load-error"
          role="alert"
          className="bg-red-50 dark:bg-red-900/30 border border-red-200 dark:border-red-800 text-red-700 dark:text-red-300 rounded-lg px-4 py-3 mt-4 flex items-center justify-between gap-4"
        >
          <span className="text-sm">{LOAD_ERROR}</span>
          <button
            type="button"
            onClick={load}
            className="px-3 py-1.5 text-xs border border-red-300 dark:border-red-700 rounded-lg hover:bg-red-100 dark:hover:bg-red-900/50"
          >
            Retry
          </button>
        </div>
      </div>
    );
  }

  return (
    <form
      data-testid="settings-objectives-section"
      className="bg-slate-50 dark:bg-slate-800 rounded-xl p-6 border border-slate-200 dark:border-slate-700"
      onSubmit={(e) => {
        e.preventDefault();
        handleSave();
      }}
    >
      <h2 className="text-lg font-semibold text-slate-900 dark:text-white">
        Trading Objectives
      </h2>
      <p className="text-sm text-slate-500 dark:text-slate-400 mb-4 pb-4 border-b border-slate-200 dark:border-slate-700">
        The targets your strategy aims for. Used by the Recovery Plan.
      </p>

      {saveError && (
        <div
          data-testid="settings-objectives-save-error"
          role="alert"
          className="bg-red-50 dark:bg-red-900/30 border border-red-200 dark:border-red-800 text-red-700 dark:text-red-300 rounded-lg px-4 py-3 mb-5 flex items-center justify-between gap-4"
        >
          <span className="text-sm">{SAVE_ERROR}</span>
          <button
            type="button"
            onClick={() => setSaveError(false)}
            className="text-xs text-red-500 hover:text-red-700 dark:hover:text-red-300"
            aria-label="Dismiss error"
          >
            Dismiss
          </button>
        </div>
      )}

      <label
        htmlFor="settings-objectives-target-yield"
        className="block text-sm text-slate-700 dark:text-slate-300 mb-1"
      >
        Target yield
      </label>
      <div className={`flex items-stretch w-48 ${saving ? 'opacity-50' : ''}`}>
        <input
          id="settings-objectives-target-yield"
          data-testid="settings-objectives-target-yield"
          type="number"
          inputMode="decimal"
          step="any"
          value={value}
          placeholder="e.g. 12"
          disabled={saving}
          onChange={(e) => handleChange(e.target.value)}
          onBlur={handleBlur}
          aria-invalid={error ? 'true' : 'false'}
          aria-describedby={
            error
              ? 'settings-objectives-target-yield-help settings-objectives-target-yield-error'
              : 'settings-objectives-target-yield-help'
          }
          className={`w-full px-3 py-2 text-sm border rounded-l-lg rounded-r-none bg-white dark:bg-slate-700 text-slate-900 dark:text-slate-100 outline-none focus:ring-2 disabled:cursor-not-allowed ${
            error
              ? 'border-red-400 dark:border-red-500 focus:ring-red-500'
              : 'border-slate-300 dark:border-slate-600 focus:ring-blue-500'
          }`}
        />
        <span
          aria-hidden="true"
          className="inline-flex items-center px-2.5 text-xs text-slate-500 dark:text-slate-400 border border-l-0 border-slate-300 dark:border-slate-600 rounded-r-lg bg-slate-100 dark:bg-slate-800"
        >
          %
        </span>
      </div>
      <p
        id="settings-objectives-target-yield-help"
        className="text-xs text-slate-500 dark:text-slate-400 mt-1 max-w-xl"
      >
        The annual return you expect redeployed capital to earn. The Recovery
        Plan uses this to score the Sell &amp; redeploy path — how a position&apos;s
        trapped capital would perform if freed and put to work elsewhere.
      </p>
      {error && (
        <p
          id="settings-objectives-target-yield-error"
          data-testid="settings-objectives-target-yield-error"
          role="alert"
          className="text-xs text-red-600 dark:text-red-400 mt-1"
        >
          {error}
        </p>
      )}

      {/* Unset note — the analogue of TradingRulesSection's defaults-note.
          Shown until a value is saved. Closes the loop for the trader who
          arrived via the recovery "Set target yield →" CTA. */}
      {isBlank(savedValue) && (
        <p
          data-testid="settings-objectives-unset-note"
          className="text-sm text-slate-500 dark:text-slate-400 mt-4"
        >
          No target yield set yet. Until you set one, the Recovery Plan&apos;s
          Sell &amp; redeploy path stays unavailable.
        </p>
      )}

      {/* Action footer */}
      <div className="flex items-center gap-3 mt-6 pt-5 border-t border-slate-200 dark:border-slate-700">
        <button
          type="submit"
          data-testid="settings-objectives-save"
          data-state={saving ? 'saving' : 'idle'}
          disabled={!canSave}
          className="px-4 py-2 text-sm bg-blue-600 text-white rounded-lg hover:bg-blue-700 disabled:bg-blue-400 disabled:cursor-not-allowed"
        >
          {saving ? 'Saving…' : 'Save objective'}
        </button>
        {saveSuccess && (
          <span
            data-testid="settings-objectives-save-success"
            className="text-green-600 dark:text-green-400"
            aria-label="Saved"
          >
            <svg
              className="w-5 h-5"
              viewBox="0 0 24 24"
              fill="none"
              stroke="currentColor"
              strokeWidth="2"
            >
              <path
                strokeLinecap="round"
                strokeLinejoin="round"
                d="M5 13l4 4L19 7"
              />
            </svg>
          </span>
        )}
        {dirty && !saving && (
          <span className="text-xs text-slate-500 dark:text-slate-400">
            You have unsaved changes
          </span>
        )}
        {!dirty && lastSaved && (
          <span className="text-xs text-slate-500 dark:text-slate-400">
            Last saved{' '}
            {lastSaved.toLocaleTimeString([], {
              hour: 'numeric',
              minute: '2-digit',
            })}
          </span>
        )}
      </div>
    </form>
  );
}
