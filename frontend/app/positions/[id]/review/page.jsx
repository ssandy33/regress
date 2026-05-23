"use client";

import { use } from 'react';
import dynamic from 'next/dynamic';
import LoadingSkeleton from '@/components/layout/LoadingSkeleton';

// Route shell for /positions/[id]/review — the per-position Stock Research
// page (issue #280). The dashboard Positions card's per-row "Review" CTA
// routes here (replacing the legacy /journal?position={id} target).
const StockResearchPage = dynamic(
  () => import('@/components/research/StockResearchPage'),
  {
    loading: () => (
      <div className="h-screen flex items-center justify-center bg-slate-100 dark:bg-slate-900">
        <LoadingSkeleton />
      </div>
    ),
    ssr: false,
  },
);

export default function PositionReview({ params }) {
  // Next 16: route params are delivered as a Promise; `use()` unwraps it.
  const { id } = use(params);
  return <StockResearchPage positionId={id} />;
}
