"use client";

import dynamic from 'next/dynamic';
import LoadingSkeleton from '@/components/layout/LoadingSkeleton';

const DashboardPage = dynamic(() => import('@/components/dashboard/DashboardPage'), {
  loading: () => (
    <div className="h-screen flex items-center justify-center bg-slate-100 dark:bg-slate-900">
      <LoadingSkeleton />
    </div>
  ),
  ssr: false,
});

export default function Dashboard() {
  return <DashboardPage />;
}
