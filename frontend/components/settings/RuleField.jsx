/**
 * RuleField — one labeled number field in the Trading Rules section (#158).
 *
 * Renders a single `rules_config` scalar: a `<label>`, a `<input type="number">`
 * or a `<select>` (for the `assignment_risk_review` enum), an optional units
 * affix (`$` leading, or `%` / `days` / `contracts` / `×` trailing), helper
 * text, and an inline validation error.
 *
 * Whole-percent convention: `rules_config` stores percentages as whole numbers
 * (`25` means 25%, per backend `rules_config.py`). This component is 1:1 with
 * the stored value — it does no human↔fraction conversion. If the model ever
 * switched to fractions, the conversion would live in `TradingRulesSection`'s
 * load/save mapping, not here.
 *
 * Optional fields (`optional` prop): blank is a valid, honest "unset" state.
 * The input renders empty with a non-numeric placeholder, carries an `Optional`
 * pill, and shows a `Clear` button when it has a value. The value is held as a
 * string so `""` (unset) is distinguishable from `"0"` (a real entered zero) —
 * `TradingRulesSection` saves `""` as `null`, never as `0` or a default.
 *
 * Accessibility: the `<label htmlFor>` is bound to the input id; `aria-invalid`
 * reflects the error state; `aria-describedby` links the helper text, the
 * optional `contextSlot` content, and (when present) the error message.
 *
 * `contextSlot` (optional, node): caller-provided JSX rendered between the
 * helper text and the error. Used by the sizing-cap field (#234) to show a
 * "X% of $NLV = $ceiling" resolved-context line. The slot's container carries
 * `id="${fieldKey}-context"` and `data-testid="rules-field-${fieldKey}-context"`
 * so the caller's assertions and `aria-describedby` can reference it. The
 * caller owns the slot content's shape — `RuleField` does not validate it.
 */
export default function RuleField({
  fieldKey,
  label,
  value,
  onChange,
  onBlur,
  helper,
  error,
  suffix = null,
  suffixLeading = false,
  placeholder = '',
  optional = false,
  options = null,
  disabled = false,
  step = 'any',
  contextSlot = null,
}) {
  const inputId = `rules-field-${fieldKey}`;
  const helpId = `${inputId}-help`;
  const errorId = `${inputId}-error`;
  const contextId = `${fieldKey}-context`;
  const describedBy = [helpId, contextSlot ? contextId : null, error ? errorId : null]
    .filter(Boolean)
    .join(' ');
  const hasValue = value !== '' && value !== null && value !== undefined;

  const baseInput =
    'px-3 py-2 text-sm border rounded-lg bg-white dark:bg-slate-700 ' +
    'text-slate-900 dark:text-slate-100 outline-none focus:ring-2 ' +
    'disabled:opacity-50 disabled:cursor-not-allowed';
  const stateClasses = error
    ? 'border-red-400 dark:border-red-500 focus:ring-red-500'
    : 'border-slate-300 dark:border-slate-600 focus:ring-blue-500';

  return (
    <div>
      <div className="flex items-center justify-between mb-1">
        <label
          htmlFor={inputId}
          className="text-sm text-slate-700 dark:text-slate-300"
        >
          {label}
          {optional && (
            <span className="ml-2 text-xs text-slate-500 dark:text-slate-400 bg-slate-100 dark:bg-slate-700 rounded-full px-2 py-0.5">
              Optional
            </span>
          )}
        </label>
        {optional && hasValue && !disabled && (
          <button
            type="button"
            data-testid={`${inputId}-clear`}
            onClick={() => onChange('')}
            className="text-xs text-slate-500 hover:text-slate-700 dark:hover:text-slate-300"
          >
            Clear
          </button>
        )}
      </div>

      <div className="flex items-stretch">
        {suffix && suffixLeading && (
          <span
            aria-hidden="true"
            className="inline-flex items-center px-2.5 text-xs text-slate-500 dark:text-slate-400 border border-r-0 border-slate-300 dark:border-slate-600 rounded-l-lg bg-slate-100 dark:bg-slate-800"
          >
            {suffix}
          </span>
        )}

        {options ? (
          <select
            id={inputId}
            data-testid={inputId}
            value={value}
            onChange={(e) => onChange(e.target.value)}
            onBlur={onBlur}
            disabled={disabled}
            aria-invalid={error ? 'true' : 'false'}
            aria-describedby={describedBy}
            className={`w-full ${baseInput} ${stateClasses}`}
          >
            {options.map((opt) => (
              <option key={opt} value={opt}>
                {opt}
              </option>
            ))}
          </select>
        ) : (
          <input
            id={inputId}
            data-testid={inputId}
            type="number"
            inputMode="decimal"
            step={step}
            value={value}
            onChange={(e) => onChange(e.target.value)}
            onBlur={onBlur}
            disabled={disabled}
            placeholder={placeholder}
            aria-invalid={error ? 'true' : 'false'}
            aria-describedby={describedBy}
            className={[
              'w-full',
              baseInput,
              stateClasses,
              suffix && suffixLeading ? 'rounded-l-none' : '',
              suffix && !suffixLeading ? 'rounded-r-none' : '',
            ].join(' ')}
          />
        )}

        {suffix && !suffixLeading && (
          <span
            aria-hidden="true"
            className="inline-flex items-center px-2.5 text-xs text-slate-500 dark:text-slate-400 border border-l-0 border-slate-300 dark:border-slate-600 rounded-r-lg bg-slate-100 dark:bg-slate-800 whitespace-nowrap"
          >
            {suffix}
          </span>
        )}
      </div>

      <p id={helpId} className="text-xs text-slate-500 dark:text-slate-400 mt-1">
        {helper}
      </p>
      {contextSlot && (
        <div id={contextId} data-testid={`${inputId}-context`}>
          {contextSlot}
        </div>
      )}
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
