import { useCallback, useEffect, useRef, useState } from 'react';

/**
 * Section F — Thesis editor (issue #280, design spec §4 Section F).
 *
 * Plain-text autosave with four visible lifecycle states:
 *
 *   idle    → mounted, no edits yet OR no recent edits
 *   saving  → 500ms after the last keystroke, a PUT is in flight
 *   saved   → 200 from the PUT, < ~2s ago — transitions back to idle
 *   failed  → non-2xx, network error, OR a cross-tab version conflict
 *
 * Save-on-blur is layered on top of the debounce so unsaved work is
 * flushed when the user navigates away. The hard cap (4000 chars) is
 * enforced both client-side (`maxLength` on the textarea) and server-side
 * (the router returns 422 if the body squeaks past somehow).
 *
 * The save function is injected by the parent so this component does not
 * own its own axios client. The function returns
 * `{ ok, version, updatedAt, error?, status? }`.
 */

const THESIS_MAX = 4000;
const DEBOUNCE_MS = 500;

const STATUS_IDLE = 'idle';
const STATUS_SAVING = 'saving';
const STATUS_SAVED = 'saved';
const STATUS_FAILED = 'failed';

function formatRelative(ts) {
  if (!ts) return '';
  const updated = new Date(ts);
  if (Number.isNaN(updated.getTime())) return '';
  const seconds = Math.max(1, Math.round((Date.now() - updated.getTime()) / 1000));
  if (seconds < 60) return `Saved ${seconds} seconds ago`;
  if (seconds < 3600) return `Saved ${Math.round(seconds / 60)} minutes ago`;
  return `Saved ${updated.toISOString().slice(0, 16).replace('T', ' ')}`;
}

function FailureTile({ onRetry }) {
  return (
    <div data-testid="research-f-error" className="text-sm">
      <p className="text-amber-600 dark:text-amber-400">
        <span aria-hidden="true">⚠</span> We couldn&apos;t load your thesis — retry
      </p>
      <button
        type="button"
        onClick={onRetry}
        className="mt-3 px-3 py-1.5 rounded-lg bg-slate-100 dark:bg-slate-700 text-slate-700 dark:text-slate-200 text-sm font-medium hover:bg-slate-200 dark:hover:bg-slate-600"
      >
        Retry
      </button>
    </div>
  );
}

function Skeleton() {
  return (
    <div
      data-testid="research-f-skeleton"
      className="h-56 rounded-lg bg-slate-200 dark:bg-slate-700 animate-pulse"
      aria-busy="true"
    />
  );
}

export default function ThesisNoteEditor({
  ticker,
  data,
  loading,
  error,
  onRetry,
  saveThesis,
}) {
  const [body, setBody] = useState('');
  const [status, setStatus] = useState(STATUS_IDLE);
  const [lastSavedAt, setLastSavedAt] = useState(null);
  const [conflictMessage, setConflictMessage] = useState(null);
  // The version we expect on the server. State (not ref) so the
  // render-phase hydration below can update it without violating the
  // react-hooks/refs rule.
  const [expectedVersion, setExpectedVersion] = useState(0);
  // Tracks the most recent server payload we've reflected into local state.
  // This is the React-recommended "store previous prop to derive state during
  // render" pattern — preferred over useEffect+setState for hydration.
  const [hydratedFrom, setHydratedFrom] = useState(null);
  const debounceTimer = useRef(null);
  // Last-saved body snapshot — used by handleBlur (CR #10) to skip the
  // redundant PUT when the user clicks away without editing.
  const lastSavedBodyRef = useRef('');

  // Render-phase hydration from the GET payload. Runs exactly once per
  // distinct server payload identity (object reference comparison) —
  // subsequent server-side echoes (e.g., from our own saves) update
  // `data` but the editor's local body is already in sync.
  if (data && !loading && hydratedFrom !== data) {
    setHydratedFrom(data);
    setBody(data.thesis || '');
    setLastSavedAt(data.updated_at || null);
    setExpectedVersion(data.version ?? 0);
  }

  // Mirror the hydrated body into the last-saved snapshot. Done in an
  // effect (not render-phase) so the react-hooks/refs linter is happy
  // — refs must not be written during render.
  useEffect(() => {
    if (data && hydratedFrom === data) {
      lastSavedBodyRef.current = data.thesis || '';
    }
  }, [data, hydratedFrom]);

  const flush = useCallback(
    async (current) => {
      const trimmed = (current ?? '').slice(0, THESIS_MAX);
      setStatus(STATUS_SAVING);
      setConflictMessage(null);
      const expected = expectedVersion;
      const result = await saveThesis(trimmed);
      if (result?.ok) {
        setLastSavedAt(result.updatedAt || new Date().toISOString());
        // Remember what we just persisted so the next blur can skip a
        // redundant PUT (CR #10).
        lastSavedBodyRef.current = trimmed;
        // If the server jumped more than +1 version since our last write,
        // another tab beat us — flag the conflict per spec §4 Section F.
        if (
          typeof result.version === 'number' &&
          result.version > expected + 1
        ) {
          setStatus(STATUS_FAILED);
          setConflictMessage(
            'Your thesis was edited in another tab · Reload to see the latest',
          );
        } else {
          setStatus(STATUS_SAVED);
          // Transition back to idle after the "saved just now" window
          // lapses (spec §4 Section F autosave lifecycle table).
          window.setTimeout(() => {
            setStatus((s) => (s === STATUS_SAVED ? STATUS_IDLE : s));
          }, 2000);
        }
        if (typeof result.version === 'number') {
          setExpectedVersion(result.version);
        }
      } else {
        setStatus(STATUS_FAILED);
        setConflictMessage(null);
      }
    },
    [expectedVersion, saveThesis],
  );

  const queueSave = useCallback(
    (next) => {
      if (debounceTimer.current) {
        window.clearTimeout(debounceTimer.current);
      }
      debounceTimer.current = window.setTimeout(() => {
        debounceTimer.current = null;
        flush(next);
      }, DEBOUNCE_MS);
    },
    [flush],
  );

  const handleChange = (e) => {
    let next = e.target.value;
    if (next.length > THESIS_MAX) {
      next = next.slice(0, THESIS_MAX);
    }
    setBody(next);
    queueSave(next);
  };

  const handleBlur = () => {
    if (debounceTimer.current) {
      window.clearTimeout(debounceTimer.current);
      debounceTimer.current = null;
    }
    // Only flush when we have pending input the server doesn't already
    // have (CR #10). A debounce cancel is fine — the next render will
    // re-queue if needed.
    if (status === STATUS_SAVING) {
      // An in-flight debounce was already cleared above; force the flush.
      flush(body);
      return;
    }
    if (status === STATUS_IDLE && body !== lastSavedBodyRef.current) {
      flush(body);
    }
  };

  const handleRetry = () => {
    flush(body);
  };

  // Cleanup any pending debounce on unmount.
  useEffect(() => () => {
    if (debounceTimer.current) {
      window.clearTimeout(debounceTimer.current);
    }
  }, []);

  const countClass =
    body.length >= 3900
      ? 'text-rose-600 dark:text-rose-400'
      : body.length >= 3600
        ? 'text-amber-600 dark:text-amber-400'
        : 'text-slate-500 dark:text-slate-400';

  let statusRow;
  if (status === STATUS_SAVING) {
    statusRow = (
      <span
        data-testid="research-f-status-saving"
        className="text-slate-500 dark:text-slate-400"
      >
        Saving…
      </span>
    );
  } else if (status === STATUS_SAVED) {
    statusRow = (
      <span
        data-testid="research-f-status-saved"
        className="text-emerald-600 dark:text-emerald-400"
      >
        ✓ Saved just now
      </span>
    );
  } else if (status === STATUS_FAILED) {
    statusRow = (
      <span
        data-testid="research-f-status-failed"
        className="text-rose-600 dark:text-rose-400"
      >
        ⚠ {conflictMessage || "Couldn't save"}
        {' · '}
        <button
          type="button"
          data-testid="research-f-status-retry"
          onClick={handleRetry}
          className="underline"
        >
          Retry
        </button>
      </span>
    );
  } else {
    statusRow = (
      <span
        data-testid="research-f-status-idle"
        className="text-slate-500 dark:text-slate-400"
      >
        {formatRelative(lastSavedAt) || 'No edits yet'}
      </span>
    );
  }

  return (
    <section
      data-testid="research-f"
      aria-labelledby="research-f-heading"
      className="rounded-xl border border-slate-200 dark:border-slate-700 bg-white dark:bg-slate-800 p-5"
    >
      <h2
        id="research-f-heading"
        className="text-xs font-semibold uppercase tracking-wide text-slate-500 dark:text-slate-400"
      >
        F · Your thesis
      </h2>
      <p className="mt-1 text-sm text-slate-500 dark:text-slate-400">
        Why you bought, what would change your mind.
      </p>

      <div className="mt-3">
        {loading && !data ? (
          <Skeleton />
        ) : error && !data ? (
          <FailureTile onRetry={onRetry} />
        ) : (
          <>
            <textarea
              data-testid="research-f-textarea"
              aria-label={`Your thesis for ${ticker || 'this position'}`}
              value={body}
              onChange={handleChange}
              onBlur={handleBlur}
              maxLength={THESIS_MAX}
              rows={12}
              placeholder={'Bull case: ...\nBear case: ...\nWhat changes my mind: ...'}
              className="w-full max-w-3xl rounded-lg border border-slate-300 dark:border-slate-600 bg-slate-50 dark:bg-slate-900/40 p-3 text-sm text-slate-900 dark:text-white"
            />
            <div
              aria-live="polite"
              className="mt-2 flex items-center justify-between text-sm"
            >
              {statusRow}
              <span
                data-testid="research-f-char-count"
                aria-live="off"
                className={`tabular-nums text-xs ${countClass}`}
              >
                {body.length} / {THESIS_MAX} chars
              </span>
            </div>
          </>
        )}
      </div>
    </section>
  );
}
