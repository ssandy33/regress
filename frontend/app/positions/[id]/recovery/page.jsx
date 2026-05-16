"use client";

import { use } from 'react';
import dynamic from 'next/dynamic';
import LoadingSkeleton from '@/components/layout/LoadingSkeleton';

// Route shell for /positions/[id]/recovery — the Recovery Plan panel
// (issue #182). The largest-loser dashboard CTA navigates here.
const RecoveryPlanPage = dynamic(
  () => import('@/components/recovery/RecoveryPlanPage'),
  {
    loading: () => (
      <div className="h-screen flex items-center justify-center bg-slate-100 dark:bg-slate-900">
        <LoadingSkeleton />
      </div>
    ),
    ssr: false,
  },
);

export default function PositionRecovery({ params }) {
  // Next 16: route params are delivered as a Promise; `use()` unwraps it.
  const { id } = use(params);
  return <RecoveryPlanPage positionId={id} />;
}
