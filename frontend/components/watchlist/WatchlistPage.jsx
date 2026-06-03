"use client";

import Header from '../layout/Header';
import WatchlistSection from '../settings/WatchlistSection';

/**
 * Watchlist page shell (issue #327, builds on #323).
 *
 * Promotes the watchlist out of the Settings tab into a dedicated top-level
 * route. This is a thin sibling-page shell — the Journal/Options/Positions
 * recipe (h-screen flex column + <Header/> + scrolling <main>) — wrapping the
 * existing, unchanged <WatchlistSection/>. The section is constrained to a
 * readable `max-w-2xl` column so it keeps the visual width it had in the
 * Settings centered column.
 *
 * No page-level <h1>: WatchlistSection owns its own "Watchlist" <h2> + framing
 * line, so the section heading is the page title (avoids a double heading — see
 * spec §7.2 Q5). WatchlistSection is reused as-is; this page does not modify it.
 */
export default function WatchlistPage() {
  return (
    <div data-testid="watchlist-page" className="h-screen flex flex-col bg-slate-100 dark:bg-slate-900">
      <Header sessions={[]} onLoadSession={() => {}} />
      <main className="flex-1 overflow-y-auto p-6">
        <div className="max-w-2xl mx-auto">
          <WatchlistSection />
        </div>
      </main>
    </div>
  );
}
