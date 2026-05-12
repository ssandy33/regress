import { useState } from 'react';
import Link from 'next/link';
import toast from 'react-hot-toast';
import { refreshStaleCache } from '../../api/client';

/**
 * DataReadinessBanner — single-line, severity-ranked, page-level trust signal.
 *
 * Replaces ``StaleBanner`` from #114 as the dashboard's data-trust surface.
 * Hidden entirely when all sources are healthy. Severity ranking (worst-wins)
 * picks one of the following conditions to surface, per design-spec §2.1 and
 * §14.1:
 *
 *   1. error — Schwab not configured / token invalid           (red)
 *   2. error — Cache very-stale > 0                            (red)
 *   3. warn  — Schwab token expiring within 7 days             (yellow)
 *   4. warn  — Cache stale > 0                                 (yellow)
 *   5. ok    — banner hidden
 *
 * FRED is deliberately NOT surfaced on the dashboard banner — it stays on
 * `/analysis` only (spec §2.1 + §10 Q5).
 *
 * Dismissal is session-only (React state). Reloading the page restores the
 * banner if the underlying condition still holds (spec §14.1).
 */

const TOKEN_EXPIRING_DAYS = 7;
const MS_PER_DAY = 24 * 60 * 60 * 1000;

function tokenExpiresSoon(expiresAt) {
  if (!expiresAt) return false;
  const expiry = new Date(expiresAt);
  if (Number.isNaN(expiry.getTime())) return false;
  const diffMs = expiry.getTime() - Date.now();
  return diffMs > 0 && diffMs <= TOKEN_EXPIRING_DAYS * MS_PER_DAY;
}

/**
 * Resolve the worst-wins banner condition. Returns ``null`` when all-clear.
 *
 * Each condition carries the bits the banner renders: severity, glyph, the
 * message clauses, and CTA descriptors. The CTA shape mirrors EmptyState —
 * ``{ label, href }`` or ``{ label, onClick }``.
 */
function resolveBannerCondition(status) {
  if (!status) return null;

  const schwab = status.schwab || {};
  const cache = status.cache || {};
  const veryStale = Number(cache.very_stale || 0);
  const stale = Number(cache.stale || 0);

  // 1) Schwab disconnected / token invalid → error
  if (schwab.configured === false || schwab.valid === false) {
    return {
      severity: 'error',
      condition: 'schwab_disconnected',
      glyph: '⛔',
      prefix: 'Schwab disconnected',
      message: 'live prices and trade import unavailable.',
      primary: { label: 'Reconnect Schwab →', href: '/settings#schwab' },
    };
  }

  // 2) Cache very-stale > 0 → error
  if (veryStale > 0) {
    return {
      severity: 'error',
      condition: 'cache_very_stale',
      glyph: '⛔',
      prefix: 'Market data very stale',
      message: `${veryStale} cached item${veryStale === 1 ? '' : 's'} over 90 days old.`,
      primary: { label: 'Refresh stale data →', kind: 'inline' },
      secondary: { label: 'Open Settings →', href: '/settings#cache' },
    };
  }

  // 3) Schwab token expiring within 7 days → warn
  if (tokenExpiresSoon(schwab.expires_at)) {
    return {
      severity: 'warn',
      condition: 'schwab_token_expiring',
      glyph: '⚠',
      prefix: 'Schwab token expiring',
      message: 'renew before it lapses to keep imports running.',
      primary: { label: 'Open Settings →', href: '/settings#schwab' },
    };
  }

  // 4) Cache stale > 0 → warn
  if (stale > 0) {
    return {
      severity: 'warn',
      condition: 'cache_stale',
      glyph: '⚠',
      prefix: 'Quotes stale',
      message: `${stale} cached item${stale === 1 ? '' : 's'} stale — review before trading.`,
      primary: { label: 'Refresh stale data →', kind: 'inline' },
      secondary: { label: 'Open Settings →', href: '/settings#cache' },
    };
  }

  return null;
}

function severityClasses(severity) {
  if (severity === 'error') {
    return {
      container:
        'bg-red-50 dark:bg-red-900/30 border-red-200 dark:border-red-800 text-red-800 dark:text-red-200',
      glyph: 'text-red-600 dark:text-red-300',
      primary:
        'inline-flex items-center text-sm font-medium text-red-700 dark:text-red-200 hover:underline focus:outline-none focus-visible:ring-2 focus-visible:ring-red-500 rounded',
      secondary:
        'inline-flex items-center text-sm text-red-700 dark:text-red-200 hover:underline focus:outline-none focus-visible:ring-2 focus-visible:ring-red-500 rounded',
      dismiss:
        'text-red-700 dark:text-red-200 hover:bg-red-100 dark:hover:bg-red-900/50 focus-visible:ring-red-500',
    };
  }
  return {
    container:
      'bg-yellow-50 dark:bg-yellow-900/30 border-yellow-200 dark:border-yellow-800 text-yellow-800 dark:text-yellow-200',
    glyph: 'text-yellow-700 dark:text-yellow-300',
    primary:
      'inline-flex items-center text-sm font-medium text-yellow-800 dark:text-yellow-100 hover:underline focus:outline-none focus-visible:ring-2 focus-visible:ring-yellow-500 rounded',
    secondary:
      'inline-flex items-center text-sm text-yellow-800 dark:text-yellow-100 hover:underline focus:outline-none focus-visible:ring-2 focus-visible:ring-yellow-500 rounded',
    dismiss:
      'text-yellow-800 dark:text-yellow-100 hover:bg-yellow-100 dark:hover:bg-yellow-900/50 focus-visible:ring-yellow-500',
  };
}

function BannerCta({ cta, classes, busy, onInline, dataTestid }) {
  if (!cta) return null;
  if (cta.kind === 'inline') {
    return (
      <button
        type="button"
        onClick={onInline}
        disabled={busy}
        data-testid={dataTestid}
        className={`${classes} disabled:opacity-60`}
      >
        {busy ? 'Refreshing…' : cta.label}
      </button>
    );
  }
  return (
    <Link href={cta.href} data-testid={dataTestid} className={classes}>
      {cta.label}
    </Link>
  );
}

export default function DataReadinessBanner({ status, loading, onRefreshed }) {
  const [dismissed, setDismissed] = useState(false);
  const [busy, setBusy] = useState(false);

  if (loading) {
    return (
      <div
        data-testid="data-readiness-banner-skeleton"
        aria-hidden="true"
        className="h-6 rounded-lg bg-slate-200 dark:bg-slate-700 animate-pulse"
      />
    );
  }

  const condition = resolveBannerCondition(status);
  if (!condition || dismissed) return null;

  const classes = severityClasses(condition.severity);
  const role = condition.severity === 'error' ? 'alert' : 'status';

  async function handleInlineRefresh() {
    setBusy(true);
    try {
      await refreshStaleCache();
      toast.success('Refreshed stale cache entries');
      onRefreshed?.();
    } catch {
      toast.error('Failed to refresh stale cache');
    } finally {
      setBusy(false);
    }
  }

  return (
    <div
      role={role}
      data-testid="data-readiness-banner"
      data-severity={condition.severity}
      data-condition={condition.condition}
      className={`flex flex-wrap items-center gap-x-4 gap-y-1 px-4 py-2 border rounded-lg ${classes.container}`}
    >
      <span aria-hidden="true" className={`text-base leading-none ${classes.glyph}`}>
        {condition.glyph}
      </span>
      <span className="text-sm font-medium">
        {condition.prefix}
        {condition.message ? `: ${condition.message}` : ''}
      </span>
      <div className="flex items-center gap-3 ml-auto">
        <BannerCta
          cta={condition.primary}
          classes={classes.primary}
          busy={busy}
          onInline={handleInlineRefresh}
          dataTestid="data-readiness-banner-cta-primary"
        />
        <BannerCta
          cta={condition.secondary}
          classes={classes.secondary}
          busy={busy}
          onInline={handleInlineRefresh}
          dataTestid="data-readiness-banner-cta-secondary"
        />
        <button
          type="button"
          onClick={() => setDismissed(true)}
          aria-label="Dismiss banner"
          data-testid="data-readiness-banner-dismiss"
          className={`inline-flex items-center justify-center w-7 h-7 rounded-md text-base leading-none focus:outline-none focus-visible:ring-2 ${classes.dismiss}`}
        >
          <span aria-hidden="true">×</span>
        </button>
      </div>
    </div>
  );
}
