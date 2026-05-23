import { useCallback, useEffect, useState } from 'react';
import {
  getPosition,
  getResearchBusiness,
  getResearchFinancials,
  getResearchPriceHistory,
  getResearchRegression,
  getResearchThesis,
  putResearchThesis,
} from '../api/client';

/**
 * useStockResearch — fetch all six sections of the research page in parallel.
 *
 * Returns:
 *
 * ```
 * {
 *   position: { data, loading, error, status },  // 404 if position missing
 *   business: { data, loading, error },
 *   priceHistory: { data, loading, error },
 *   financials: { data, loading, error },
 *   regression: { data, loading, error },
 *   thesis: {
 *     data, loading, error,
 *     save: (body) => Promise<{ ok, version, updatedAt, error? }>,
 *   },
 *   refetchSection: (name) => void,   // re-runs a single section's fetch
 *   refetchAll: () => void,
 * }
 * ```
 *
 * The position fetch is awaited first because it gates the entire page —
 * a 404 on the position skips every section fetch (we render the
 * `research-not-found` empty state). When the position resolves, the five
 * section fetches fire in parallel via `Promise.allSettled` so a single
 * section failure does NOT poison the others (NFR-3, design spec §7).
 */

const SECTIONS = ['business', 'priceHistory', 'financials', 'regression', 'thesis'];

const SECTION_FETCHERS = {
  business: getResearchBusiness,
  priceHistory: (positionId) => getResearchPriceHistory(positionId, '1Y'),
  financials: getResearchFinancials,
  regression: (positionId) => getResearchRegression(positionId, '1Y'),
  thesis: getResearchThesis,
};

function extractDetail(e, fallback) {
  return e?.response?.data?.detail || fallback;
}

function initialSectionsState() {
  return Object.fromEntries(
    SECTIONS.map((name) => [name, { data: null, loading: true, error: null }]),
  );
}

export function useStockResearch(positionId) {
  const [position, setPosition] = useState({
    data: null,
    loading: true,
    error: null,
    status: null,
  });
  const [sections, setSections] = useState(() => initialSectionsState());

  const fetchSection = useCallback(
    async (name) => {
      if (!positionId) return;
      setSections((prev) => ({
        ...prev,
        [name]: { ...prev[name], loading: true, error: null },
      }));
      try {
        const data = await SECTION_FETCHERS[name](positionId);
        setSections((prev) => ({
          ...prev,
          [name]: { data, loading: false, error: null },
        }));
      } catch (e) {
        setSections((prev) => ({
          ...prev,
          [name]: {
            data: null,
            loading: false,
            error: extractDetail(e, 'Section unavailable'),
          },
        }));
      }
    },
    [positionId],
  );

  const refetchAll = useCallback(async () => {
    if (!positionId) {
      setPosition({ data: null, loading: false, error: null, status: null });
      setSections(initialSectionsState());
      return;
    }
    // Reset the position gate; section state resets via Promise.allSettled below.
    setPosition({ data: null, loading: true, error: null, status: null });
    setSections(initialSectionsState());
    try {
      const positionPayload = await getPosition(positionId);
      setPosition({
        data: positionPayload,
        loading: false,
        error: null,
        status: 200,
      });
    } catch (e) {
      const status = e?.response?.status ?? null;
      setPosition({
        data: null,
        loading: false,
        error: extractDetail(e, 'Failed to load position'),
        status,
      });
      // Position fetch failed — short-circuit sections so the UI doesn't spin forever.
      setSections(
        Object.fromEntries(
          SECTIONS.map((name) => [
            name,
            { data: null, loading: false, error: null },
          ]),
        ),
      );
      return;
    }
    // Position resolved — fan the five section fetches out in parallel.
    await Promise.allSettled(SECTIONS.map((name) => fetchSection(name)));
  }, [positionId, fetchSection]);

  useEffect(() => {
    refetchAll();
  }, [refetchAll]);

  // Thesis writes — owned by the hook so the editor doesn't reimplement
  // optimistic-locking + status reducer.
  const saveThesis = useCallback(
    async (body) => {
      if (!positionId) {
        return { ok: false, error: 'No position id' };
      }
      try {
        const updated = await putResearchThesis(positionId, body ?? '');
        setSections((prev) => ({
          ...prev,
          thesis: { data: updated, loading: false, error: null },
        }));
        return {
          ok: true,
          version: updated.version,
          updatedAt: updated.updated_at,
        };
      } catch (e) {
        return {
          ok: false,
          error: extractDetail(e, 'Failed to save thesis'),
          status: e?.response?.status ?? null,
        };
      }
    },
    [positionId],
  );

  return {
    position,
    business: sections.business,
    priceHistory: sections.priceHistory,
    financials: sections.financials,
    regression: sections.regression,
    thesis: { ...sections.thesis, save: saveThesis },
    refetchSection: fetchSection,
    refetchAll,
  };
}
