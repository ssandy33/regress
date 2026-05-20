"use client";

import { use } from 'react';
import dynamic from 'next/dynamic';
import LoadingSkeleton from '@/components/layout/LoadingSkeleton';

// Route shell for /positions/[id]/covered-call — the per-position
// combined-P&L + if-assigned screen (issue #247). Reachable from the
// dashboard's per-position row via a secondary `Covered call view →` link
// on CC/Wheel rows (spec §4 / planner Q4).
const CoveredCallPage = dynamic(
  () => import('@/components/positions/CoveredCallPage'),
  {
    loading: () => (
      <div className="h-screen flex items-center justify-center bg-slate-100 dark:bg-slate-900">
        <LoadingSkeleton />
      </div>
    ),
    ssr: false,
  },
);

export default function PositionCoveredCall({ params }) {
  // Next 16: route params are delivered as a Promise; `use()` unwraps it.
  const { id } = use(params);
  return <CoveredCallPage positionId={id} />;
}
