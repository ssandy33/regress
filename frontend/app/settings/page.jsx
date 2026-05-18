"use client";

import { Suspense } from 'react';
import SettingsPage from '@/components/settings/SettingsPage';

export default function Settings() {
  // SettingsPage calls useSearchParams() to read the `?tab=` deep-link
  // param (issue #235). The App Router de-opts to client-side rendering
  // without a Suspense boundary around a useSearchParams() consumer, so
  // wrap it here. fallback={null} matches the page's own loading states.
  return (
    <Suspense fallback={null}>
      <SettingsPage />
    </Suspense>
  );
}
