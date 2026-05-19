"use client";

import { use } from 'react';
import dynamic from 'next/dynamic';
import LoadingSkeleton from '@/components/layout/LoadingSkeleton';

// Route shell for /positions/[id]/legs/[legId]/btc — the dedicated per-leg
// buy-to-close detail screen (issue #244). Reached from the rule-monitor
// "Inspect rule →" card CTA. Structural twin of recovery/page.jsx.
const BtcDetailPage = dynamic(
  () => import('@/components/btc/BtcDetailPage'),
  {
    loading: () => (
      <div className="h-screen flex items-center justify-center bg-slate-100 dark:bg-slate-900">
        <LoadingSkeleton />
      </div>
    ),
    ssr: false,
  },
);

export default function PositionLegBtc({ params }) {
  // Next 16: route params are delivered as a Promise; `use()` unwraps it.
  const { id, legId } = use(params);
  return <BtcDetailPage positionId={id} legId={legId} />;
}
