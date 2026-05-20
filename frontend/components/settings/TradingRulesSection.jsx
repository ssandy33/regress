import { useEffect, useMemo, useState } from 'react';
import toast from 'react-hot-toast';
import {
  dismissSizingCapMigration,
  getAccountValue,
  getRulesConfig,
  refreshAccountValue,
  saveRulesConfig,
} from '../../api/client';
import ConfirmDialog from '../common/ConfirmDialog';
import RuleField from './RuleField';
import RuleRangeField from './RuleRangeField';
import { FIELDS, GROUP_META, GROUP_ORDER } from './rulesFieldCatalog';
import { validateRange, validateScalar } from './rulesValidation';

/**
 * Settings → Trading Rules section (issue #158).
 *
 * The frontend edit surface for the `rules_config` keystone (#156): five group
 * cards (Universe, Entry, Position, Risk, Management triggers, ~24 fields), a
 * single Save and a single Reset-to-defaults control, inline per-field
 * validation that mirrors the backend Pydantic validators, and the standard
 * loading / saving / success / failure states.
 *
 * Reads and writes via the typed `GET`/`PUT /api/settings/rules` endpoint
 * (chosen over the generic `{key,value}` upsert because the generic
 * `GET /api/settings` returns a fixed shape and cannot read `rules_config`
 * back). The `getRulesConfig` / `saveRulesConfig` helpers in `api/client.js`
 * keep this component agnostic of the endpoint shape.
 *
 * Form state: every field value is held as a *string* so an empty Optional
 * field (`""`, the honest "unset" signal) stays distinct from a real entered
 * zero (`"0"`). On save, blank Optional fields serialize to `null` — never to
 * `0` and never to a default. Percentages are whole-percent, 1:1 with the
 * stored value (no human↔fraction conversion — `rules_config` standardises on
 * whole-percent per #156).
 *
 * Failure copy is fixed generic text (CLAUDE.md) — a raw exception is never
 * surfaced.
 */

const LOAD_ERROR = "Couldn't load your trading rules.";
const SAVE_ERROR = "Couldn't save your trading rules. Please try again.";

/** Flatten a `RulesConfig` object into a `{ "<group>.<key>": <string> }` form
 * state. Range fields expand to `<key>_min` / `<key>_max`. `null`/missing →
 * `""` so Optional fields render blank. */
function configToForm(config) {
  const form = {};
  GROUP_ORDER.forEach((group) => {
    const stored = (config && config[group]) || {};
    FIELDS[group].forEach((field) => {
      if (field.kind === 'range') {
        const r = stored[field.key] || {};
        form[`${group}.${field.key}_min`] =
          r.min === null || r.min === undefined ? '' : String(r.min);
        form[`${group}.${field.key}_max`] =
          r.max === null || r.max === undefined ? '' : String(r.max);
      } else {
        const v = stored[field.key];
        form[`${group}.${field.key}`] =
          v === null || v === undefined ? '' : String(v);
      }
    });
  });
  return form;
}

/** Build a `{ "<group>.<key>": <string> }` form state from catalog defaults.
 * Optional fields reset to unset (`""`), not to a proposed number. */
function defaultsToForm() {
  const form = {};
  GROUP_ORDER.forEach((group) => {
    FIELDS[group].forEach((field) => {
      if (field.kind === 'range') {
        form[`${group}.${field.key}_min`] = String(field.default.min);
        form[`${group}.${field.key}_max`] = String(field.default.max);
      } else {
        form[`${group}.${field.key}`] =
          field.default === null ? '' : String(field.default);
      }
    });
  });
  return form;
}

/** Serialize the string-keyed form back into a `RulesConfig` payload.
 * Blank Optional scalars → `null`; non-enum scalars → `Number`. */
function formToConfig(form, schemaVersion) {
  const config = { schema_version: schemaVersion };
  GROUP_ORDER.forEach((group) => {
    config[group] = {};
    FIELDS[group].forEach((field) => {
      if (field.kind === 'range') {
        config[group][field.key] = {
          min: Number(form[`${group}.${field.key}_min`]),
          max: Number(form[`${group}.${field.key}_max`]),
        };
      } else if (field.kind === 'enum') {
        config[group][field.key] = form[`${group}.${field.key}`];
      } else {
        const raw = form[`${group}.${field.key}`];
        if (field.optional && (raw === '' || raw === null || raw === undefined)) {
          config[group][field.key] = null;
        } else {
          config[group][field.key] = Number(raw);
        }
      }
    });
  });
  return config;
}

/** Run every field's validator over the form. Returns a `{ "<group>.<key>":
 * <message> }` map of just the invalid fields. Enum fields never fail here. */
function validateForm(form) {
  const errors = {};
  GROUP_ORDER.forEach((group) => {
    FIELDS[group].forEach((field) => {
      const id = `${group}.${field.key}`;
      if (field.kind === 'range') {
        const err = validateRange(
          field.validate,
          form[`${id}_min`],
          form[`${id}_max`],
        );
        if (err) errors[id] = err;
      } else if (field.kind !== 'enum') {
        const err = validateScalar(field.validate, form[id], field.optional);
        if (err) errors[id] = err;
      }
    });
  });
  return errors;
}

/** Whole-dollar formatter for the sizing-cap resolved-context line (#234 §5.2):
 * thousands separators, no cents. Matches the recovery-engine `_format_dollar`
 * convention so the same ceiling reads identically across surfaces. */
function formatDollars(amount) {
  if (amount === null || amount === undefined || Number.isNaN(amount)) return '';
  const rounded = Math.round(Number(amount));
  return `$${rounded.toLocaleString('en-US')}`;
}

/** Build the resolved-context slot for the sizing-cap field (#234 §5–§6).
 *
 * Four variants, keyed off `accountValue.status`:
 *  - "ok"           — "25% of …4471 (≈ $5,240)" + Refresh button. Slate background.
 *  - "disconnected" — "Schwab not connected — Reconnect Schwab" (amber). Tab-switch
 *                     to General per #234 §6.3 — NOT a hash anchor.
 *  - "expired"      — "Schwab session expired — Reconnect Schwab" (amber). Same button.
 *  - "error"        — "Schwab error — Retry" (amber). Retry force-refreshes.
 *
 * While `loading` (initial fetch) the slot shows "Resolving…". The slot's
 * wrapper carries `data-testid="rules-field-sizing_cap_pct-resolved"` and
 * `data-state=<status>` so e2e can pick the variant. Per CLAUDE.md, no raw
 * exception text is interpolated — only the four fixed lead clauses. */
function renderSizingCapContext({
  pctRaw,
  loading,
  refreshing,
  accountValue,
  onRefresh,
  onReconnect,
}) {
  const baseRow =
    'mt-1.5 flex items-start gap-2 text-xs rounded-md px-2.5 py-1.5';
  const slateTone = 'bg-slate-100 dark:bg-slate-900/40 text-slate-600 dark:text-slate-300';
  const amberTone =
    'bg-amber-50 dark:bg-amber-900/30 border border-amber-200 dark:border-amber-800 text-amber-800 dark:text-amber-200';

  if (loading || !accountValue) {
    return (
      <div
        data-testid="rules-field-sizing_cap_pct-resolved"
        data-state="loading"
        className={`${baseRow} ${slateTone}`}
        role="status"
      >
        <span aria-hidden="true" className="text-slate-400 dark:text-slate-500">
          ⓘ
        </span>
        <span>Resolving…</span>
      </div>
    );
  }

  if (accountValue.status === 'ok') {
    const pctNum = Number(pctRaw);
    const validPct =
      pctRaw !== '' && pctRaw !== null && !Number.isNaN(pctNum) && pctNum > 0;
    const account = accountValue.account_id_masked || '';
    const ceiling = validPct
      ? formatDollars((pctNum * (accountValue.total_capital || 0)) / 100)
      : null;
    return (
      <div
        data-testid="rules-field-sizing_cap_pct-resolved"
        data-state="ok"
        className={`${baseRow} ${slateTone}`}
        role="status"
      >
        <span aria-hidden="true" className="text-slate-400 dark:text-slate-500">
          ⓘ
        </span>
        <span className="flex-1">
          {validPct ? (
            <>
              <span className="font-semibold text-slate-800 dark:text-slate-100">
                {pctNum}%
              </span>
              {' of '}
              {account ? <span>{account}</span> : <span>your account</span>}
              {ceiling ? (
                <>
                  {' (≈ '}
                  <span className="font-semibold text-slate-800 dark:text-slate-100">
                    {ceiling}
                  </span>
                  {')'}
                </>
              ) : null}
            </>
          ) : (
            <span>
              Enter a percentage to see the resolved dollar ceiling.
            </span>
          )}
        </span>
        <button
          type="button"
          data-testid="rules-field-sizing_cap_pct-refresh"
          onClick={onRefresh}
          disabled={refreshing}
          className="text-blue-600 dark:text-blue-400 hover:text-blue-700 dark:hover:text-blue-300 disabled:opacity-50 disabled:cursor-not-allowed whitespace-nowrap"
        >
          {refreshing ? 'Refreshing…' : 'Refresh'}
        </button>
      </div>
    );
  }

  if (accountValue.status === 'disconnected' || accountValue.status === 'expired') {
    const lead =
      accountValue.status === 'disconnected'
        ? 'Schwab not connected'
        : 'Schwab session expired';
    return (
      <div
        data-testid="rules-field-sizing_cap_pct-resolved"
        data-state={accountValue.status}
        className={`${baseRow} ${amberTone}`}
        role="status"
      >
        <span aria-hidden="true" className="text-amber-500">
          ⚠
        </span>
        <span className="flex-1">{lead} —{' '}</span>
        <button
          type="button"
          data-testid="rules-field-sizing_cap_pct-reconnect"
          onClick={onReconnect}
          className="font-medium text-amber-800 dark:text-amber-200 hover:underline whitespace-nowrap"
        >
          Reconnect Schwab
        </button>
      </div>
    );
  }

  // status === 'error' (or any unknown future status — fall through here so
  // the user sees an honest amber treatment rather than a silently-resolved
  // dollar figure built on partial data).
  return (
    <div
      data-testid="rules-field-sizing_cap_pct-resolved"
      data-state="error"
      className={`${baseRow} ${amberTone}`}
      role="status"
    >
      <span aria-hidden="true" className="text-amber-500">
        ⚠
      </span>
      <span className="flex-1">Schwab error —{' '}</span>
      <button
        type="button"
        data-testid="rules-field-sizing_cap_pct-retry"
        onClick={onRefresh}
        disabled={refreshing}
        className="font-medium text-amber-800 dark:text-amber-200 hover:underline disabled:opacity-50 disabled:cursor-not-allowed whitespace-nowrap"
      >
        {refreshing ? 'Retrying…' : 'Retry'}
      </button>
    </div>
  );
}

function SkeletonRow() {
  return (
    <div className="space-y-2">
      <div className="h-3 w-40 bg-slate-200 dark:bg-slate-700 rounded" />
      <div className="h-9 w-full bg-slate-200 dark:bg-slate-700 rounded-lg" />
    </div>
  );
}

export default function TradingRulesSection({ onSwitchToTab } = {}) {
  const [form, setForm] = useState(null);
  const [savedForm, setSavedForm] = useState(null);
  const [schemaVersion, setSchemaVersion] = useState(1);
  // `sizingCapAccount` is the multi-account selector value (#234 §7) — a
  // sibling of the scalar form because it isn't in the catalog (it's a card-
  // header selector, not a per-field input). `null` = default first account;
  // `"sum"` = sum of all linked accounts; `"…1234"` = explicit masked id.
  const [sizingCapAccount, setSizingCapAccount] = useState(null);
  const [savedSizingCapAccount, setSavedSizingCapAccount] = useState(null);
  // Migration banner state (#234 §13.5). `migration` is the inline
  // `migration.sizing_cap` sibling from GET /api/settings/rules (S4) —
  // `null` when no migration has happened. `bannerDismissed` is the local
  // optimistic flag set after a successful dismiss POST.
  const [migration, setMigration] = useState(null);
  const [bannerDismissed, setBannerDismissed] = useState(false);
  // Account-value state (#234 §5–§6). Fetched once on mount; the resolved-
  // context line below sizing_cap_pct renders one of four variants keyed
  // off `accountValue.status`.
  const [accountValue, setAccountValue] = useState(null);
  const [accountValueLoading, setAccountValueLoading] = useState(true);
  const [accountValueRefreshing, setAccountValueRefreshing] = useState(false);
  const [errors, setErrors] = useState({});
  const [touched, setTouched] = useState(false);
  const [loading, setLoading] = useState(true);
  const [loadError, setLoadError] = useState(false);
  const [saving, setSaving] = useState(false);
  const [saveError, setSaveError] = useState(false);
  const [saveSuccess, setSaveSuccess] = useState(false);
  const [lastSaved, setLastSaved] = useState(null);
  const [hasEverSaved, setHasEverSaved] = useState(false);
  const [confirmOpen, setConfirmOpen] = useState(false);

  const load = () => {
    setLoading(true);
    setLoadError(false);
    getRulesConfig()
      .then((config) => {
        const f = configToForm(config);
        setForm(f);
        setSavedForm(f);
        setSchemaVersion(config?.schema_version || 1);
        const acct = config?.position?.sizing_cap_account ?? null;
        setSizingCapAccount(acct);
        setSavedSizingCapAccount(acct);
        const m = config?.migration?.sizing_cap ?? null;
        setMigration(m);
        // Pre-dismissed banners (server-side `dismissed_at` not null) start
        // with the banner already hidden so a reload after dismiss doesn't
        // momentarily flash the banner.
        setBannerDismissed(Boolean(m?.dismissed_at));
      })
      .catch(() => setLoadError(true))
      .finally(() => setLoading(false));
  };

  useEffect(load, []);

  // Fetch the Schwab account value once on mount. The resolved-context line
  // is inert without it — it falls through to "Resolving…" until this lands,
  // then renders the ok / disconnected / expired / error variant. Failures
  // surface as status="error" so the user always sees an honest treatment
  // (never a stale dollar figure — design spec §6.4).
  useEffect(() => {
    let cancelled = false;
    setAccountValueLoading(true);
    getAccountValue()
      .then((result) => {
        if (!cancelled) setAccountValue(result);
      })
      .catch(() => {
        if (!cancelled) {
          setAccountValue({ status: 'error', error_detail: null });
        }
      })
      .finally(() => {
        if (!cancelled) setAccountValueLoading(false);
      });
    return () => {
      cancelled = true;
    };
  }, []);

  const handleRefreshAccountValue = async () => {
    setAccountValueRefreshing(true);
    try {
      const result = await refreshAccountValue();
      setAccountValue(result);
    } catch {
      setAccountValue({ status: 'error', error_detail: null });
    } finally {
      setAccountValueRefreshing(false);
    }
  };

  const handleSwitchToGeneral = () => {
    if (typeof onSwitchToTab === 'function') onSwitchToTab('general');
  };

  const handleDismissBanner = async () => {
    // Optimistic — flip locally so the banner disappears immediately and the
    // POST runs in the background. A failed dismiss is silent because the
    // server already has the record; a retry on next load will repeat it.
    setBannerDismissed(true);
    try {
      await dismissSizingCapMigration();
    } catch {
      // Swallow — the banner stays dismissed locally; next reload will
      // re-fetch the (un-stamped) server state and show the banner again,
      // which is the conservative behaviour.
    }
  };

  const dirty = useMemo(() => {
    if (!form || !savedForm) return false;
    if (JSON.stringify(form) !== JSON.stringify(savedForm)) return true;
    // sizing_cap_account isn't in the catalog (it's a card-header selector,
    // not a per-field input), so we track it separately and compare it
    // explicitly to keep the Save button honest.
    return sizingCapAccount !== savedSizingCapAccount;
  }, [form, savedForm, sizingCapAccount, savedSizingCapAccount]);

  const errorCount = Object.keys(errors).length;
  const canSave = dirty && errorCount === 0 && !saving;

  const setField = (id, value) => {
    setForm((prev) => ({ ...prev, [id]: value }));
    setSaveError(false);
    setSaveSuccess(false);
  };

  // Re-validate on blur so errors surface as the trader leaves a field; once
  // they've attempted a save, validate live so fixes clear the error.
  const revalidate = () => {
    if (form) setErrors(validateForm(form));
  };

  useEffect(() => {
    if (touched && form) setErrors(validateForm(form));
  }, [form, touched]);

  const handleSave = async () => {
    if (!form) return;
    setTouched(true);
    const found = validateForm(form);
    setErrors(found);
    if (Object.keys(found).length > 0) return;

    setSaving(true);
    setSaveError(false);
    try {
      const payload = formToConfig(form, schemaVersion);
      // Fold the multi-account selector (#234 §7) into the position group
      // before persisting. The catalog doesn't know about this key — it lives
      // at the Position card header, not on a field row — so we splice it in
      // here. `null` is the default-first-account signal and is serialised as
      // `null`, not omitted, to match the Pydantic Optional contract.
      payload.position = { ...payload.position, sizing_cap_account: sizingCapAccount };
      const saved = await saveRulesConfig(payload);
      const f = configToForm(saved);
      setForm(f);
      setSavedForm(f);
      const newAcct = saved?.position?.sizing_cap_account ?? null;
      setSizingCapAccount(newAcct);
      setSavedSizingCapAccount(newAcct);
      setSchemaVersion(saved?.schema_version || schemaVersion);
      setLastSaved(new Date());
      setHasEverSaved(true);
      setSaveSuccess(true);
      // Per #234 §13.5.3, a successful save implicitly acknowledges the
      // migration — hide the banner locally so the user doesn't see it after
      // saving an unchanged form. The server doesn't auto-stamp dismissal
      // on save in this slice; the explicit dismiss POST is the durable path.
      setBannerDismissed(true);
      toast.success('Trading rules saved');
      setTimeout(() => setSaveSuccess(false), 2500);
    } catch {
      setSaveError(true);
      toast.error('Failed to save trading rules');
    } finally {
      setSaving(false);
    }
  };

  const handleResetConfirm = () => {
    setForm(defaultsToForm());
    // The catalog default for sizing_cap_account is "first account" (null).
    setSizingCapAccount(null);
    setErrors({});
    setSaveError(false);
    setSaveSuccess(false);
    setConfirmOpen(false);
  };

  const header = (
    <div>
      <h2 className="text-lg font-semibold text-slate-900 dark:text-white">
        Trading Rules
      </h2>
      <p className="text-sm text-slate-500 dark:text-slate-400">
        Configure your system. Set once.
      </p>
    </div>
  );

  if (loading) {
    return (
      <div data-testid="settings-rules-loading" className="space-y-8">
        {header}
        {GROUP_ORDER.map((group) => (
          <div
            key={group}
            className="bg-slate-50 dark:bg-slate-800 rounded-xl p-6 border border-slate-200 dark:border-slate-700 animate-pulse"
          >
            <div className="h-5 w-32 bg-slate-200 dark:bg-slate-700 rounded mb-4" />
            <div className="space-y-5">
              {[0, 1, 2].map((i) => (
                <SkeletonRow key={i} />
              ))}
            </div>
          </div>
        ))}
      </div>
    );
  }

  if (loadError) {
    return (
      <div className="space-y-8">
        {header}
        <div
          data-testid="settings-rules-load-error"
          role="alert"
          className="bg-red-50 dark:bg-red-900/30 border border-red-200 dark:border-red-800 text-red-700 dark:text-red-300 rounded-lg px-4 py-3 flex items-center justify-between gap-4"
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
      data-testid="settings-rules-form"
      className="space-y-8"
      onSubmit={(e) => {
        e.preventDefault();
        handleSave();
      }}
    >
      {header}

      {!hasEverSaved && (
        <p
          data-testid="settings-rules-defaults-note"
          className="text-sm text-slate-500 dark:text-slate-400"
        >
          You haven&apos;t changed any rules yet — these are the recommended
          defaults.
        </p>
      )}

      {saveError && (
        <div
          data-testid="settings-rules-save-error"
          role="alert"
          className="bg-red-50 dark:bg-red-900/30 border border-red-200 dark:border-red-800 text-red-700 dark:text-red-300 rounded-lg px-4 py-3 flex items-center justify-between gap-4"
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

      {GROUP_ORDER.map((group) => (
        <div
          key={group}
          data-testid={`rules-group-${group}`}
          className="bg-slate-50 dark:bg-slate-800 rounded-xl p-6 border border-slate-200 dark:border-slate-700"
        >
          <h3 className="text-lg font-semibold text-slate-900 dark:text-white mb-1">
            {GROUP_META[group].title}
          </h3>
          <p className="text-sm text-slate-500 dark:text-slate-400 mb-4 pb-4 border-b border-slate-200 dark:border-slate-700">
            {GROUP_META[group].description}
          </p>

          <div className="space-y-5">
            {FIELDS[group].map((field) => {
              const id = `${group}.${field.key}`;
              if (field.kind === 'range') {
                return (
                  <RuleRangeField
                    key={field.key}
                    fieldKey={field.key}
                    label={field.label}
                    helper={field.helper}
                    suffix={field.suffix}
                    minLabel={field.minLabel}
                    maxLabel={field.maxLabel}
                    step={field.step}
                    minValue={form[`${id}_min`]}
                    maxValue={form[`${id}_max`]}
                    minPlaceholder={String(field.default.min)}
                    maxPlaceholder={String(field.default.max)}
                    onChangeMin={(v) => setField(`${id}_min`, v)}
                    onChangeMax={(v) => setField(`${id}_max`, v)}
                    onBlur={revalidate}
                    error={errors[id]}
                    disabled={saving}
                  />
                );
              }
              // The sizing-cap field gets the resolved-context slot (#234 §5):
              // a small line below the helper that resolves "25% of account → $X"
              // or surfaces the disconnected / expired / error variant. The slot
              // is sizing-cap-only, so we build it inline instead of extracting
              // a reusable primitive (per the plan's gap-resolution table).
              const isSizingCap =
                group === 'position' && field.key === 'sizing_cap_pct';
              const contextSlot = isSizingCap
                ? renderSizingCapContext({
                    pctRaw: form[id],
                    loading: accountValueLoading,
                    refreshing: accountValueRefreshing,
                    accountValue,
                    onRefresh: handleRefreshAccountValue,
                    onReconnect: handleSwitchToGeneral,
                  })
                : null;
              return (
                <RuleField
                  key={field.key}
                  fieldKey={field.key}
                  label={field.label}
                  helper={field.helper}
                  suffix={field.suffix}
                  suffixLeading={field.suffixLeading}
                  optional={field.optional}
                  options={field.options}
                  step={field.step}
                  value={form[id]}
                  placeholder={
                    field.optional
                      ? 'Not set — no limit'
                      : field.default === null
                        ? ''
                        : String(field.default)
                  }
                  onChange={(v) => setField(id, v)}
                  onBlur={revalidate}
                  error={errors[id]}
                  disabled={saving}
                  contextSlot={contextSlot}
                />
              );
            })}
          </div>
        </div>
      ))}

      {/* Action footer */}
      <div className="flex items-center justify-between gap-4 flex-wrap">
        <div className="flex items-center gap-3">
          <button
            type="button"
            data-testid="settings-reset-rules"
            onClick={() => setConfirmOpen(true)}
            disabled={saving}
            className="px-4 py-2 text-sm border border-slate-300 dark:border-slate-600 text-slate-700 dark:text-slate-300 rounded-lg hover:bg-slate-100 dark:hover:bg-slate-700 disabled:opacity-50 disabled:cursor-not-allowed"
          >
            Reset to defaults
          </button>
          {dirty && (
            <span
              data-testid="settings-rules-unsaved-hint"
              className="text-xs text-slate-500 dark:text-slate-400"
            >
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

        <div className="flex items-center gap-3">
          {errorCount > 0 && touched && (
            <span className="text-xs text-red-600 dark:text-red-400">
              Fix {errorCount} field{errorCount === 1 ? '' : 's'} before saving
            </span>
          )}
          {saveSuccess && (
            <span
              data-testid="settings-rules-save-success"
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
          <button
            type="submit"
            data-testid="settings-save-rules"
            disabled={!canSave}
            className="px-4 py-2 text-sm bg-blue-600 text-white rounded-lg hover:bg-blue-700 disabled:bg-blue-400 disabled:cursor-not-allowed"
          >
            {saving ? 'Saving…' : 'Save trading rules'}
          </button>
        </div>
      </div>

      {confirmOpen && (
        <ConfirmDialog
          title="Reset trading rules"
          message="Reset every trading rule to its recommended default? This discards your unsaved edits. Nothing is saved until you click Save."
          confirmLabel="Reset to defaults"
          confirmVariant="primary"
          onConfirm={handleResetConfirm}
          onCancel={() => setConfirmOpen(false)}
        />
      )}
    </form>
  );
}
