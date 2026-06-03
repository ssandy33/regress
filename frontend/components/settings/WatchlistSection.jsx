import { useEffect, useState } from 'react';
import toast from 'react-hot-toast';
import {
  getWatchlist,
  addWatchlistTicker,
  removeWatchlistTicker,
} from '../../api/client';
import EmptyState from '../common/EmptyState';

/**
 * Settings → Watchlist section (issue #323, PRD #213 UC1–UC4).
 *
 * The minimal approved-universe gate: an add input, the current list with a
 * per-row Remove, and an empty state. Symbols only — no columns, scores, or
 * tags (those are PRD #213 v2). The Options scanner filters its candidates to
 * this list; the framing line + count pill (UC4) make that gate legible while
 * the trader curates.
 *
 * The section owns the mount fetch and all add/remove state for the tab (it is
 * self-contained like TradingObjectivesSection — the tab panel just renders it).
 *
 * Data flow (Q4): the three `/api/watchlist` endpoints (#321) each return the
 * full, current `{ tickers }` (uppercase-normalized, backend-ordered), so we
 * use the returned list directly rather than issuing a follow-up GET. The
 * backend is authoritative for normalization + ordering — the input only
 * *displays* uppercase as a courtesy (CSS), it does not normalize.
 *
 * Failure copy is fixed generic text — never the raw server detail (CLAUDE.md).
 */

const LOAD_ERROR = "Couldn't load your watchlist.";

/**
 * Light client-side shape guard (spec §7.1). The backend is the authority on
 * ticker validity (PRD #213 defers options-existence checks to v2); this only
 * rejects obviously-bad input (digits-only, spaces, symbols) to avoid firing a
 * doomed POST. Allows 1–6 letters with a single optional `.` or `-` (e.g.
 * `BRK.B`).
 */
function isValidTickerShape(value) {
  return /^[A-Za-z]{1,6}([.-][A-Za-z]{1,4})?$/.test(value);
}

export default function WatchlistSection() {
  const [tickers, setTickers] = useState([]);
  const [loading, setLoading] = useState(true);
  const [loadError, setLoadError] = useState(false);
  const [input, setInput] = useState('');
  const [adding, setAdding] = useState(false);
  // One inline message slot for duplicate (info) / add-error / validation.
  const [inlineMsg, setInlineMsg] = useState(null); // { kind, text } | null
  const [removing, setRemoving] = useState(null); // symbol being DELETEd

  const load = () => {
    setLoading(true);
    setLoadError(false);
    getWatchlist()
      .then((list) => setTickers(list || []))
      .catch(() => setLoadError(true))
      .finally(() => setLoading(false));
  };

  useEffect(load, []);

  // Add controls stay disabled until the initial load resolves (you cannot add
  // to a universe you have not loaded) or while it is in error.
  const controlsDisabled = loading || loadError;
  const trimmed = input.trim();
  const canAdd = trimmed.length > 0 && !adding && !controlsDisabled;

  const handleInputChange = (next) => {
    setInput(next);
    // Any keystroke clears a stale inline message (spec §6.5 / §6.6).
    if (inlineMsg) setInlineMsg(null);
  };

  const handleAdd = async () => {
    const value = input.trim();
    if (!value || adding || controlsDisabled) return;

    // Client-side shape guard — block a doomed POST (spec §7.1).
    if (!isValidTickerShape(value)) {
      setInlineMsg({ kind: 'validation', text: 'Enter a valid ticker symbol.' });
      return;
    }

    setAdding(true);
    setInlineMsg(null);
    const prev = tickers;
    const submitted = value.toUpperCase();
    try {
      const updated = await addWatchlistTicker(value);
      setTickers(updated || []);
      // Idempotent no-op detection (spec §6.5): the symbol was already present
      // and the list length did not grow → duplicate, not a fresh add.
      const wasPresent = prev.includes(submitted);
      if (wasPresent && (updated || []).length === prev.length) {
        setInput('');
        setInlineMsg({
          kind: 'duplicate',
          text: `${submitted} is already on your watchlist.`,
        });
      } else {
        setInput('');
        toast.success(`${submitted} added`);
      }
    } catch {
      // Preserve the trader's typing; re-enable; generic copy only.
      setInlineMsg({
        kind: 'add-error',
        text: `Couldn't add ${submitted}. Try again.`,
      });
      toast.error('Failed to add ticker');
    } finally {
      setAdding(false);
    }
  };

  const handleRemove = async (symbol) => {
    if (removing) return;
    setRemoving(symbol);
    try {
      const updated = await removeWatchlistTicker(symbol);
      setTickers(updated || []);
      toast.success(`${symbol} removed`);
    } catch {
      // Row persists + re-enables; the toast carries the error (spec §6.8).
      toast.error('Failed to remove ticker');
    } finally {
      setRemoving(null);
    }
  };

  const header = (
    <div className="flex items-center justify-between mb-1">
      <h2 className="text-lg font-semibold text-slate-900 dark:text-white">
        Watchlist
      </h2>
      {/* Count pill — populated only; the at-a-glance universe-size cue (UC4). */}
      {!loading && !loadError && tickers.length > 0 && (
        <span
          data-testid="settings-watchlist-count"
          className="text-xs px-2 py-0.5 rounded-full bg-slate-100 dark:bg-slate-700 text-slate-600 dark:text-slate-300"
        >
          {tickers.length} {tickers.length === 1 ? 'ticker' : 'tickers'}
        </span>
      )}
    </div>
  );

  const framing = (
    <p className="text-sm text-slate-500 dark:text-slate-400 mb-4">
      The Options scanner only surfaces candidates from these approved names. Add
      the tickers you&apos;d be willing to own if assigned.
    </p>
  );

  const inputInvalid =
    inlineMsg?.kind === 'add-error' || inlineMsg?.kind === 'validation';

  const addRow = (
    <div className="flex gap-2">
      <input
        type="text"
        data-testid="settings-watchlist-add-input"
        value={input}
        onChange={(e) => handleInputChange(e.target.value)}
        onKeyDown={(e) => {
          if (e.key === 'Enter') {
            e.preventDefault();
            handleAdd();
          }
        }}
        placeholder="Add ticker (e.g. AAPL)"
        maxLength={6}
        disabled={controlsDisabled || adding}
        aria-label="Ticker symbol"
        aria-invalid={inputInvalid ? 'true' : 'false'}
        className={`flex-1 px-3 py-2 text-sm uppercase border rounded-lg bg-white dark:bg-slate-700 text-slate-900 dark:text-slate-100 outline-none focus:ring-2 disabled:opacity-60 disabled:cursor-not-allowed ${
          inputInvalid
            ? 'border-red-400 dark:border-red-500 focus:ring-red-500'
            : 'border-slate-300 dark:border-slate-600 focus:ring-blue-500'
        }`}
      />
      <button
        type="button"
        data-testid="settings-watchlist-add-button"
        onClick={handleAdd}
        disabled={!canAdd}
        className="px-4 py-2 text-sm bg-blue-600 text-white rounded-lg hover:bg-blue-700 disabled:bg-blue-400 disabled:cursor-not-allowed inline-flex items-center gap-2"
      >
        {adding && (
          <svg className="w-4 h-4 animate-spin" viewBox="0 0 24 24" fill="none">
            <circle
              className="opacity-25"
              cx="12"
              cy="12"
              r="10"
              stroke="currentColor"
              strokeWidth="4"
            />
            <path
              className="opacity-75"
              fill="currentColor"
              d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4z"
            />
          </svg>
        )}
        {adding ? 'Adding…' : 'Add'}
      </button>
    </div>
  );

  // Inline message slot — duplicate (info), add-error (red), validation (red).
  const inlineSlot = inlineMsg
    ? inlineMsg.kind === 'duplicate'
      ? (
        <p
          data-testid="settings-watchlist-duplicate-note"
          className="text-xs text-slate-500 dark:text-slate-400 mt-2"
        >
          {inlineMsg.text}
        </p>
      )
      : (
        <p
          data-testid={
            inlineMsg.kind === 'add-error'
              ? 'settings-watchlist-add-error'
              : 'settings-watchlist-validation-error'
          }
          role="alert"
          className="text-xs text-red-600 dark:text-red-400 mt-2"
        >
          {inlineMsg.text}
        </p>
      )
    : null;

  let body;
  if (loading) {
    body = (
      <div data-testid="settings-watchlist-loading" className="space-y-2 mt-5">
        <div className="h-9 bg-slate-200 dark:bg-slate-700 rounded-lg animate-pulse" />
        <div className="h-9 bg-slate-200 dark:bg-slate-700 rounded-lg animate-pulse" />
        <div className="h-9 bg-slate-200 dark:bg-slate-700 rounded-lg animate-pulse" />
      </div>
    );
  } else if (loadError) {
    body = (
      <div
        data-testid="settings-watchlist-load-error"
        role="alert"
        className="flex items-center gap-3 px-4 py-3 mt-5 rounded-lg border border-amber-300 dark:border-amber-700 bg-amber-50 dark:bg-amber-900/30 text-amber-800 dark:text-amber-200"
      >
        <svg
          className="w-5 h-5 shrink-0"
          fill="none"
          viewBox="0 0 24 24"
          stroke="currentColor"
        >
          <path
            strokeLinecap="round"
            strokeLinejoin="round"
            strokeWidth="1.5"
            d="M12 9v3.75m9-.75a9 9 0 11-18 0 9 9 0 0118 0zm-9 3.75h.008v.008H12v-.008z"
          />
        </svg>
        <span className="text-sm font-medium flex-1">{LOAD_ERROR}</span>
        <button
          type="button"
          data-testid="settings-watchlist-retry"
          onClick={load}
          className="px-3 py-1.5 text-xs border border-amber-400 dark:border-amber-600 text-amber-700 dark:text-amber-300 rounded-lg hover:bg-amber-100 dark:hover:bg-amber-900/40"
        >
          Retry
        </button>
      </div>
    );
  } else if (tickers.length === 0) {
    body = (
      <div className="mt-3">
        <EmptyState
          dataTestid="settings-watchlist-empty"
          icon={
            <svg
              className="w-12 h-12 mx-auto"
              fill="none"
              viewBox="0 0 24 24"
              stroke="currentColor"
            >
              <path
                strokeLinecap="round"
                strokeLinejoin="round"
                strokeWidth="1.5"
                d="M3.98 8.223A10.477 10.477 0 001.934 12C3.226 16.338 7.244 19.5 12 19.5c.993 0 1.953-.138 2.863-.395M6.228 6.228A10.45 10.45 0 0112 4.5c4.756 0 8.773 3.162 10.065 7.498a10.523 10.523 0 01-4.293 5.774M6.228 6.228L3 3m3.228 3.228l3.65 3.65m7.894 7.894L21 21m-3.228-3.228l-3.65-3.65m0 0a3 3 0 10-4.243-4.243m4.243 4.243L9.88 9.88"
              />
            </svg>
          }
          title="Your watchlist is empty"
          description="The Options scanner won't surface any candidates until you add names. Add the tickers you'd be willing to own — those are the only underlyings the scanner will consider."
        />
      </div>
    );
  } else {
    body = (
      <ul data-testid="settings-watchlist-list" className="space-y-2 mt-5">
        {tickers.map((symbol) => {
          const busy = removing === symbol;
          return (
            <li
              key={symbol}
              data-testid="settings-watchlist-item"
              data-ticker={symbol}
              className={`flex items-center justify-between px-3 py-2 bg-white dark:bg-slate-700 rounded-lg border border-slate-200 dark:border-slate-600 ${
                busy ? 'opacity-70' : ''
              }`}
            >
              <span className="text-sm font-medium font-mono tabular-nums text-slate-900 dark:text-white">
                {symbol}
              </span>
              <button
                type="button"
                data-testid="settings-watchlist-remove"
                onClick={() => handleRemove(symbol)}
                disabled={busy}
                className="px-3 py-1 text-xs border border-slate-300 dark:border-slate-600 text-slate-600 dark:text-slate-300 rounded-lg hover:bg-slate-100 dark:hover:bg-slate-600 disabled:cursor-not-allowed inline-flex items-center gap-1.5"
              >
                {busy && (
                  <svg
                    className="w-3.5 h-3.5 animate-spin"
                    viewBox="0 0 24 24"
                    fill="none"
                  >
                    <circle
                      className="opacity-25"
                      cx="12"
                      cy="12"
                      r="10"
                      stroke="currentColor"
                      strokeWidth="4"
                    />
                    <path
                      className="opacity-75"
                      fill="currentColor"
                      d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4z"
                    />
                  </svg>
                )}
                {busy ? 'Removing…' : 'Remove'}
              </button>
            </li>
          );
        })}
      </ul>
    );
  }

  return (
    <section
      data-testid="settings-watchlist-section"
      className="bg-slate-50 dark:bg-slate-800 rounded-xl p-6 border border-slate-200 dark:border-slate-700"
    >
      {header}
      {framing}
      {addRow}
      {inlineSlot}
      {body}
    </section>
  );
}
