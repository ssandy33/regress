"use client";

import dynamic from 'next/dynamic';
import LoadingSkeleton from '@/components/layout/LoadingSkeleton';

const OptionScanner = dynamic(() => import('@/components/options/OptionScanner'), {
  loading: () => <div className="h-screen flex items-center justify-center bg-slate-100 dark:bg-slate-900"><LoadingSkeleton /></div>,
  ssr: false,
});

export default function OptionsPage() {
  return <OptionScanner />;
}
