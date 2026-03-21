"use client";

import dynamic from 'next/dynamic';
import LoadingSkeleton from '@/components/layout/LoadingSkeleton';

const JournalPage = dynamic(() => import('@/components/journal/JournalPage'), {
  loading: () => <div className="h-screen flex items-center justify-center bg-slate-100 dark:bg-slate-900"><LoadingSkeleton /></div>,
  ssr: false,
});

export default function Journal() {
  return <JournalPage />;
}
