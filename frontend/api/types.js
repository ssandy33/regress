// frontend/api/types.js
//
// Contract v1 Wave 3 (#307) — thin alias layer over the generated OpenAPI types.
// Per PRD #262 R-3, the deeply-nested `paths['/api/...']['method']['responses']
// ['200']['content']['application/json']` form does NOT bleed into call sites.
// Consumers reference friendly aliases defined here.
//
// To add a new alias when you add an endpoint:
//   1. Run `npm run types:regen` after backend snapshot regen.
//   2. Add a `@typedef` block here pointing at the relevant `paths[...]` slot.
//   3. Reference the friendly name in `frontend/api/client.js` JSDoc.
//
// Do NOT write hand-maintained interfaces here. Every typedef must trace back
// to a `paths[...]` index expression — that's what guarantees drift detection.

// --- Family A: positions (per-position research, recovery, btc, covered-call) ---

/**
 * Response from `POST /api/positions/{id}/recovery-plan`.
 * @typedef {import('./generated/types').paths['/api/positions/{position_id}/recovery-plan']['post']['responses']['200']['content']['application/json']} RecoveryPlanResponse
 */

/**
 * Response from `GET /api/positions/{id}/covered-call`.
 * @typedef {import('./generated/types').paths['/api/positions/{position_id}/covered-call']['get']['responses']['200']['content']['application/json']} CoveredCallView
 */

/**
 * Response from `GET /api/positions/{id}/legs/{leg_id}/btc`.
 * @typedef {import('./generated/types').paths['/api/positions/{position_id}/legs/{leg_id}/btc']['get']['responses']['200']['content']['application/json']} BtcDetail
 */

/**
 * Response from `GET /api/positions/{id}/research/business`.
 * @typedef {import('./generated/types').paths['/api/positions/{position_id}/research/business']['get']['responses']['200']['content']['application/json']} BusinessResponse
 */

/**
 * Response from `GET /api/positions/{id}/research/price-history`.
 * @typedef {import('./generated/types').paths['/api/positions/{position_id}/research/price-history']['get']['responses']['200']['content']['application/json']} PriceHistoryResponse
 */

/**
 * Response from `GET /api/positions/{id}/research/financials`.
 * @typedef {import('./generated/types').paths['/api/positions/{position_id}/research/financials']['get']['responses']['200']['content']['application/json']} FinancialsResponse
 */

/**
 * Response from `GET /api/positions/{id}/research/regression`.
 * @typedef {import('./generated/types').paths['/api/positions/{position_id}/research/regression']['get']['responses']['200']['content']['application/json']} ResearchRegressionResponse
 */

/**
 * Response from `GET /api/positions/{id}/research/thesis`.
 * @typedef {import('./generated/types').paths['/api/positions/{position_id}/research/thesis']['get']['responses']['200']['content']['application/json']} ThesisResponse
 */

/**
 * Request body for `PUT /api/positions/{id}/research/thesis`.
 * @typedef {import('./generated/types').paths['/api/positions/{position_id}/research/thesis']['put']['requestBody']['content']['application/json']} ThesisUpdateRequest
 */

// --- Family B: regression (analysis page) ---

/**
 * Request body for `POST /api/regression/linear`.
 * @typedef {import('./generated/types').paths['/api/regression/linear']['post']['requestBody']['content']['application/json']} LinearRegressionRequest
 */

/**
 * Response from `POST /api/regression/linear`.
 * @typedef {import('./generated/types').paths['/api/regression/linear']['post']['responses']['200']['content']['application/json']} LinearRegressionResponse
 */

/**
 * Response from `POST /api/regression/multi-factor`.
 * @typedef {import('./generated/types').paths['/api/regression/multi-factor']['post']['responses']['200']['content']['application/json']} MultiFactorRegressionResponse
 */

/**
 * Response from `POST /api/regression/rolling`.
 * @typedef {import('./generated/types').paths['/api/regression/rolling']['post']['responses']['200']['content']['application/json']} RollingRegressionResponse
 */

/**
 * Response from `POST /api/regression/compare`.
 * @typedef {import('./generated/types').paths['/api/regression/compare']['post']['responses']['200']['content']['application/json']} CompareRegressionResponse
 */

export {};
