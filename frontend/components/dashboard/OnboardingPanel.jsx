import Card from '../common/Card';
import EmptyState from '../common/EmptyState';

/**
 * OnboardingPanel — full-bleed CTA card shown only when the install is
 * brand-new (no Schwab, no FRED key, no positions). Per spec §4.
 */
function CTA({ step, title, description, href, label }) {
  return (
    <div className="flex-1 min-w-[220px] border border-slate-200 dark:border-slate-700 rounded-lg p-4 bg-white dark:bg-slate-800">
      <div className="text-xs uppercase tracking-wide text-slate-400 dark:text-slate-500 mb-2">
        Step {step}
      </div>
      <h4 className="text-base font-semibold text-slate-900 dark:text-white">{title}</h4>
      <p className="text-sm text-slate-500 dark:text-slate-400 mt-1 mb-3">{description}</p>
      <a
        href={href}
        className="inline-flex items-center px-3 py-1.5 rounded-lg bg-blue-600 text-white text-sm font-medium hover:bg-blue-700"
      >
        {label}
      </a>
    </div>
  );
}

export default function OnboardingPanel() {
  return (
    <Card dataTestid="dashboard-onboarding">
      <EmptyState
        title="Welcome to Regress"
        description="Set up the basics so the dashboard can show your portfolio."
      />
      <div className="flex flex-wrap gap-3 mt-2">
        <CTA
          step={1}
          title="Connect Schwab"
          description="Live prices, option chains, trade import."
          href="/settings#schwab"
          label="Open Settings"
        />
        <CTA
          step={2}
          title="Add a FRED API key"
          description="Macro context for regression analysis."
          href="/settings#fred"
          label="Open Settings"
        />
        <CTA
          step={3}
          title="Import or add a position"
          description="Import from Schwab or add manually."
          href="/journal"
          label="Open Journal"
        />
      </div>
    </Card>
  );
}
