// Rejected Strikes "Relax to X" preview popover (issue #258, V1.0.8).
//
// Anchors below the rule chip the parent (ScannerRejectedStrikes.jsx) clicked.
// Pure presentational + lifecycle: the fetch is owned by the parent so the
// popover can be tested in isolation against the four state branches —
// `loading`, `ready` (with `recovered_count > 0` or `== 0`), `error`. Closed
// is `open === false` → returns `null`.
//
// Placement: roll-your-own (no library — V1 plan §S4). The component reads
// the chip's `getBoundingClientRect()` on open, places itself 8px below the
// chip, and flips above when the popover would overflow the viewport bottom.
// On resize or scroll it closes (per spec §4.1 — no live tracking).
// Renders to a `document.body` portal so its stacking context is independent
// of the scrollable rejected-strikes container.
//
// ARIA: `role="dialog"` + `aria-modal="true"` + focus-on-open + Escape +
// click-outside dismiss. Focus returns to the trigger chip (parent owns the
// focus-return wiring via the close handler).
//
// Spec: frontend/design-specs/issue-258-relax-to-x-preview.md

import { useEffect, useLayoutEffect, useRef, useState } from 'react';
import { createPortal } from 'react-dom';

import { REJECTION_RULE_LABELS } from './scannerRejectionLabels';

const POPOVER_WIDTH = 320; // matches the spec's `w-80`
const ANCHOR_GAP = 8;

function computePlacement(anchorEl) {
  if (!anchorEl || typeof window === 'undefined') {
    return { top: 0, left: 0, placement: 'below' };
  }
  const rect = anchorEl.getBoundingClientRect();
  const viewportH = window.innerHeight;
  const viewportW = window.innerWidth;

  // We do not know the popover's measured height before paint; use a rough
  // estimate (max-h-96 = 384px) to decide whether to flip. The actual rendered
  // height varies per state but is always <= 384px.
  const ESTIMATED_HEIGHT = 320;

  const fitsBelow =
    rect.bottom + ESTIMATED_HEIGHT + ANCHOR_GAP <= viewportH;
  const placement = fitsBelow ? 'below' : 'above';

  const top =
    placement === 'below'
      ? rect.bottom + ANCHOR_GAP + window.scrollY
      : rect.top - ESTIMATED_HEIGHT - ANCHOR_GAP + window.scrollY;

  // Horizontal — left-align to chip, then clamp into viewport with an 8px
  // gutter. ``window.scrollX`` lets the absolute-positioned portal handle a
  // horizontally-scrolled page (rare).
  let left = rect.left + window.scrollX;
  const maxLeft = window.scrollX + viewportW - POPOVER_WIDTH - 8;
  if (left > maxLeft) left = maxLeft;
  if (left < window.scrollX + 8) left = window.scrollX + 8;

  return { top, left, placement };
}

function SkeletonBody() {
  return (
    <div className="space-y-2">
      <div className="bg-slate-200 dark:bg-slate-700 rounded h-3 animate-pulse w-3/4" />
      <div className="bg-slate-200 dark:bg-slate-700 rounded h-3 animate-pulse w-1/2" />
      <div className="bg-slate-200 dark:bg-slate-700 rounded h-3 animate-pulse w-2/3" />
      <div className="bg-slate-200 dark:bg-slate-700 rounded h-3 animate-pulse w-2/3" />
    </div>
  );
}

function ErrorBody({ onRetry, retryRef }) {
  return (
    <div className="space-y-3">
      <p className="text-sm text-yellow-700 dark:text-yellow-300">
        <span aria-hidden className="mr-1">
          ⚠
        </span>
        Couldn&apos;t compute preview.
      </p>
      <button
        ref={retryRef}
        type="button"
        onClick={onRetry}
        className="text-sm text-blue-600 dark:text-blue-400 hover:underline focus:outline-none focus:ring-2 focus:ring-blue-500 rounded"
      >
        Try again
      </button>
    </div>
  );
}

function ReadyBody({ rule, data }) {
  const label = REJECTION_RULE_LABELS[rule] || rule;
  const lower = label.toLowerCase();
  const count = Number(data?.recovered_count ?? 0);
  const strikes = Array.isArray(data?.recovered_strikes)
    ? data.recovered_strikes
    : [];
  const previewStrikes = strikes.slice(0, 5);
  const overflow = Math.max(0, count - previewStrikes.length);

  return (
    <div className="space-y-3">
      <p className="text-xs">
        <span className="text-slate-500 dark:text-slate-400">
          Loosen {lower} from{' '}
        </span>
        <span className="tabular-nums text-slate-700 dark:text-slate-200">
          {data?.current_threshold_text ?? '—'}
        </span>
        <span className="text-slate-400 mx-1" aria-hidden>
          →
        </span>
        <span className="tabular-nums text-emerald-700 dark:text-emerald-300">
          {data?.relaxed_threshold_text ?? '—'}
        </span>
      </p>

      {count > 0 ? (
        <p className="text-sm font-medium">
          <span aria-hidden className="mr-1 text-emerald-600 dark:text-emerald-300">
            ▸
          </span>
          <span
            data-testid="scanner-rejected-strikes-relax-recovered-count"
            data-count={count}
            className="text-emerald-700 dark:text-emerald-300"
          >
            {count === 1 ? '1 strike' : `${count} strikes`}
          </span>{' '}
          <span className="text-slate-700 dark:text-slate-200 font-normal">
            would recover
          </span>
        </p>
      ) : (
        <p
          data-testid="scanner-rejected-strikes-relax-recovered-count"
          data-count="0"
          className="text-sm text-slate-500 dark:text-slate-400"
        >
          No strikes would recover at the relaxed threshold.
        </p>
      )}

      {count > 0 && previewStrikes.length > 0 && (
        <ul className="space-y-1 text-xs tabular-nums text-slate-700 dark:text-slate-200">
          {previewStrikes.map((s, i) => (
            <li key={`${s.strike}-${s.expiration}-${i}`}>
              ${Number(s.strike).toFixed(2)} · {s.expiration}
            </li>
          ))}
          {overflow > 0 && (
            <li className="text-slate-500 dark:text-slate-400">
              + {overflow} more
            </li>
          )}
        </ul>
      )}

      <p className="text-[11px] text-slate-500 dark:text-slate-400 mt-3">
        Preview only — does not re-run the scan.
      </p>
    </div>
  );
}

export default function ScannerRejectedStrikesRelaxPopover({
  open,
  anchorEl,
  rule,
  state,
  data,
  onClose,
  onRetry,
}) {
  const rootRef = useRef(null);
  const closeBtnRef = useRef(null);
  const retryBtnRef = useRef(null);

  const [position, setPosition] = useState({ top: 0, left: 0, placement: 'below' });
  const [mounted, setMounted] = useState(false);

  // SSR safety — `createPortal(..., document.body)` would crash during SSR
  // because `document` is undefined. Only render the portal after mount.
  useEffect(() => {
    setMounted(true);
  }, []);

  // Recompute placement when opening or when the rule (and therefore the
  // anchor) changes.
  useLayoutEffect(() => {
    if (!open || !anchorEl) return;
    setPosition(computePlacement(anchorEl));
  }, [open, anchorEl, rule]);

  // Resize + scroll close the popover (per spec §4.1 — no live tracking).
  useEffect(() => {
    if (!open) return undefined;
    const handler = () => onClose && onClose();
    window.addEventListener('resize', handler);
    window.addEventListener('scroll', handler, true);
    return () => {
      window.removeEventListener('resize', handler);
      window.removeEventListener('scroll', handler, true);
    };
  }, [open, onClose]);

  // Escape key + click-outside dismiss + focus management.
  useEffect(() => {
    if (!open) return undefined;
    const handleKey = (e) => {
      if (e.key === 'Escape') {
        e.preventDefault();
        onClose && onClose();
      } else if (e.key === 'Tab') {
        // Tiny focus trap — cycle between close and retry (when present).
        const focusables = [closeBtnRef.current, retryBtnRef.current].filter(
          Boolean,
        );
        if (focusables.length <= 1) {
          e.preventDefault();
          if (focusables[0]) focusables[0].focus();
          return;
        }
        const idx = focusables.indexOf(document.activeElement);
        e.preventDefault();
        const next = e.shiftKey
          ? focusables[(idx - 1 + focusables.length) % focusables.length]
          : focusables[(idx + 1) % focusables.length];
        next && next.focus();
      }
    };
    const handlePointer = (e) => {
      const root = rootRef.current;
      if (!root) return;
      if (root.contains(e.target)) return;
      if (anchorEl && anchorEl.contains(e.target)) return; // chip click handled by parent
      onClose && onClose();
    };
    document.addEventListener('keydown', handleKey);
    document.addEventListener('pointerdown', handlePointer, true);
    // Focus the close button after paint — gives screen-readers the popover
    // semantics before they fight the trapping logic.
    queueMicrotask(() => {
      if (closeBtnRef.current) closeBtnRef.current.focus();
    });
    return () => {
      document.removeEventListener('keydown', handleKey);
      document.removeEventListener('pointerdown', handlePointer, true);
    };
  }, [open, anchorEl, onClose]);

  if (!open || !mounted) return null;

  const label = REJECTION_RULE_LABELS[rule] || rule;

  const popover = (
    <div
      ref={rootRef}
      data-testid="scanner-rejected-strikes-relax-popover"
      data-state={state}
      data-rule={rule}
      role="dialog"
      aria-modal="true"
      aria-label={`Relax ${label}`}
      style={{
        position: 'absolute',
        top: position.top,
        left: position.left,
        width: POPOVER_WIDTH,
      }}
      className="z-50 max-h-96 overflow-y-auto bg-white dark:bg-slate-800 border border-slate-200 dark:border-slate-700 rounded-xl shadow-lg p-4"
    >
      <div
        data-testid={`scanner-rejected-strikes-relax-rule-${rule}`}
        className="flex items-start justify-between gap-2 mb-3"
      >
        <p className="text-sm font-medium text-slate-900 dark:text-slate-100">
          Relax · {label}
        </p>
        <button
          ref={closeBtnRef}
          type="button"
          onClick={onClose}
          aria-label="Close"
          data-testid="scanner-rejected-strikes-relax-popover-close"
          className="text-slate-400 hover:text-slate-700 dark:hover:text-slate-200 focus:outline-none focus:ring-2 focus:ring-blue-500 rounded w-6 h-6 flex items-center justify-center"
        >
          <span aria-hidden>×</span>
        </button>
      </div>

      {state === 'loading' && <SkeletonBody />}
      {state === 'error' && (
        <ErrorBody onRetry={onRetry} retryRef={retryBtnRef} />
      )}
      {state === 'ready' && <ReadyBody rule={rule} data={data} />}
    </div>
  );

  return createPortal(popover, document.body);
}
