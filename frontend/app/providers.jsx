"use client";

import { ThemeProvider } from '@/context/ThemeContext';
import { OfflineProvider } from '@/context/OfflineContext';
import { Toaster } from 'react-hot-toast';
import OfflineBanner from '@/components/layout/OfflineBanner';

export default function Providers({ children }) {
  return (
    <ThemeProvider>
      <OfflineProvider>
        <Toaster
          position="top-right"
          toastOptions={{
            className: 'text-sm',
            duration: 4000,
            success: { duration: 4000 },
            error: { duration: 8000 },
          }}
        />
        <OfflineBanner />
        {children}
      </OfflineProvider>
    </ThemeProvider>
  );
}
