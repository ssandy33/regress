/**
 * Trading Rules client-side validation (issue #158).
 *
 * Mirrors the backend Pydantic validators in
 * `backend/app/services/rules_config.py` so a value rejected by the form would
 * also be rejected by `PUT /api/settings/rules`. The form blocks Save while any
 * field is invalid; the backend remains the final authority.
 *
 * Messages are fixed, generic, human copy (design spec §10.2) — they never
 * interpolate an API exception or a raw value.
 *
 * The form holds every value as a string so `""` (Optional unset) is
 * distinguishable from `"0"` (a real entered zero). These helpers therefore
 * take raw string input.
 */

const MSG = {
  number: 'Enter a number.',
  integer: 'Enter a whole number.',
  nonNeg: 'Enter a value of 0 or greater.',
  positive: 'Enter a value greater than 0.',
  pct0to100: 'Enter a percentage between 0 and 100.',
  pctOpen100: 'Enter a percentage greater than 0 and up to 100.',
  delta: 'Delta must be between 0 and 1.',
  loss: 'Enter a loss as a negative percentage (0 or below).',
  posInt: 'Enter a whole number of 1 or greater.',
  nonNegInt: 'Enter a whole number of 0 or greater.',
  rangeOrder: 'Minimum must be less than maximum.',
};

/** True when the string is empty / whitespace — the Optional "unset" signal. */
export function isBlank(v) {
  return v === '' || v === null || v === undefined || String(v).trim() === '';
}

function asNumber(v) {
  const n = Number(v);
  return Number.isFinite(n) ? n : null;
}

/**
 * Validate one scalar field. Returns an error string, or `null` when valid.
 *
 * @param {string} kind   - the `validate` kind from the field catalog.
 * @param {string} value  - the raw input string.
 * @param {boolean} optional - when true, a blank value is always valid.
 */
export function validateScalar(kind, value, optional = false) {
  if (isBlank(value)) {
    // A required field left blank is invalid; an Optional one is honest unset.
    return optional ? null : MSG.number;
  }
  const n = asNumber(value);
  if (n === null) return MSG.number;

  const isInt = Number.isInteger(n);

  switch (kind) {
    case 'oi':
      if (!isInt) return MSG.integer;
      return n < 0 ? MSG.nonNeg : null;
    case 'spreadPct':
      return n <= 0 ? MSG.positive : null;
    case 'pct0to100':
      return n < 0 || n > 100 ? MSG.pct0to100 : null;
    case 'pctOpen100':
      return n <= 0 || n > 100 ? MSG.pctOpen100 : null;
    case 'nonNeg':
      return n < 0 ? MSG.nonNeg : null;
    case 'capPos':
      return n <= 0 ? MSG.positive : null;
    case 'lossPct':
      return n > 0 ? MSG.loss : null;
    case 'posInt':
      if (!isInt) return MSG.integer;
      return n < 1 ? MSG.posInt : null;
    case 'nonNegInt':
      if (!isInt) return MSG.integer;
      return n < 0 ? MSG.nonNegInt : null;
    default:
      return null;
  }
}

/**
 * Validate one `{min, max}` range field. Returns an error string, or `null`.
 *
 * @param {'dte'|'delta'} kind
 * @param {string} minValue
 * @param {string} maxValue
 */
export function validateRange(kind, minValue, maxValue) {
  if (isBlank(minValue) || isBlank(maxValue)) return MSG.number;
  const lo = asNumber(minValue);
  const hi = asNumber(maxValue);
  if (lo === null || hi === null) return MSG.number;

  if (kind === 'dte') {
    if (lo < 0) return MSG.nonNeg;
  } else if (kind === 'delta') {
    if (lo < 0 || lo > 1 || hi < 0 || hi > 1) return MSG.delta;
  }
  // `min < max` is the shared cross-field invariant (RangeRule model_validator).
  if (lo >= hi) return MSG.rangeOrder;
  return null;
}

export { MSG as RULE_ERROR_MESSAGES };
