/**
 * RuleRangeField — a `{min, max}` range row in the Trading Rules section (#158).
 *
 * Renders the three `rules_config` range rules — `dte_range`, `delta_range_csp`,
 * `delta_range_cc` — as two `<input type="number">` joined by "to", with a
 * shared visible group label and a visually-hidden per-input label so screen
 * readers can distinguish minimum from maximum.
 *
 * The two inputs share one validation slot: `error` is the combined message for
 * the pair (e.g. "Minimum must be less than maximum.", or a bounds error). When
 * present, both inputs get the red ring and `aria-invalid="true"`, and both
 * reference the single error id via `aria-describedby`.
 *
 * Values are held as strings (mirroring `RuleField`) so an in-progress empty
 * input does not get coerced; `TradingRulesSection` owns the numeric parse.
 */
export default function RuleRangeField({
  fieldKey,
  label,
  minValue,
  maxValue,
  onChangeMin,
  onChangeMax,
  onBlur,
  helper,
  error,
  minLabel,
  maxLabel,
  suffix = null,
  minPlaceholder = '',
  maxPlaceholder = '',
  disabled = false,
  step = 'any',
}) {
  const base = `rules-field-${fieldKey}`;
  const minId = `${base}_min`;
  const maxId = `${base}_max`;
  const helpId = `${base}-help`;
  const errorId = `${base}-error`;
  const describedBy = error ? `${helpId} ${errorId}` : helpId;

  const inputClass = [
    'w-full px-3 py-2 text-sm border rounded-lg bg-white dark:bg-slate-700',
    'text-slate-900 dark:text-slate-100 outline-none focus:ring-2',
    'disabled:opacity-50 disabled:cursor-not-allowed',
    error
      ? 'border-red-400 dark:border-red-500 focus:ring-red-500'
      : 'border-slate-300 dark:border-slate-600 focus:ring-blue-500',
  ].join(' ');

  return (
    <div>
      <label
        htmlFor={minId}
        className="block text-sm text-slate-700 dark:text-slate-300 mb-1"
      >
        {label}
      </label>

      <div className="flex items-center gap-2">
        <label htmlFor={minId} className="sr-only">
          {minLabel}
        </label>
        <input
          id={minId}
          data-testid={minId}
          type="number"
          inputMode="decimal"
          step={step}
          value={minValue}
          onChange={(e) => onChangeMin(e.target.value)}
          onBlur={onBlur}
          disabled={disabled}
          placeholder={minPlaceholder}
          aria-invalid={error ? 'true' : 'false'}
          aria-describedby={describedBy}
          className={inputClass}
        />
        <span className="text-xs text-slate-500 dark:text-slate-400 shrink-0">
          to
        </span>
        <label htmlFor={maxId} className="sr-only">
          {maxLabel}
        </label>
        <input
          id={maxId}
          data-testid={maxId}
          type="number"
          inputMode="decimal"
          step={step}
          value={maxValue}
          onChange={(e) => onChangeMax(e.target.value)}
          onBlur={onBlur}
          disabled={disabled}
          placeholder={maxPlaceholder}
          aria-invalid={error ? 'true' : 'false'}
          aria-describedby={describedBy}
          className={inputClass}
        />
        {suffix && (
          <span
            aria-hidden="true"
            className="text-xs text-slate-500 dark:text-slate-400 shrink-0"
          >
            {suffix}
          </span>
        )}
      </div>

      <p id={helpId} className="text-xs text-slate-500 dark:text-slate-400 mt-1">
        {helper}
      </p>
      {error && (
        <p
          id={errorId}
          data-testid={errorId}
          role="alert"
          className="text-xs text-red-600 dark:text-red-400 mt-1"
        >
          {error}
        </p>
      )}
    </div>
  );
}
