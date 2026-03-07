import { useState, useCallback } from 'react';
import toast from 'react-hot-toast';
import { scanOptions } from '../api/client';

export function useOptionScanner() {
  const [result, setResult] = useState(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState(null);

  const [ticker, setTicker] = useState('');
  const [strategy, setStrategy] = useState('cash_secured_put');
  const [costBasis, setCostBasis] = useState('');
  const [sharesHeld, setSharesHeld] = useState(100);
  const [capitalAvailable, setCapitalAvailable] = useState('');
  const [minDte, setMinDte] = useState(25);
  const [maxDte, setMaxDte] = useState(50);
  const [returnTarget, setReturnTarget] = useState(1.0);
  const [callDistance, setCallDistance] = useState(10.0);
  const [minDelta, setMinDelta] = useState(0.15);
  const [maxDelta, setMaxDelta] = useState(0.35);
  const [earningsBuffer, setEarningsBuffer] = useState(5);

  const [selectedStrikes, setSelectedStrikes] = useState([]);

  const runScan = useCallback(async () => {
    if (!ticker.trim()) {
      toast.error('Please enter a ticker symbol');
      return;
    }
    if (strategy === 'covered_call' && !costBasis) {
      toast.error('Cost basis is required for covered calls');
      return;
    }
    if (strategy === 'cash_secured_put' && !capitalAvailable) {
      toast.error('Capital available is required for cash-secured puts');
      return;
    }

    setLoading(true);
    setError(null);

    try {
      const request = {
        ticker: ticker.toUpperCase().trim(),
        strategy,
        cost_basis: strategy === 'covered_call' ? parseFloat(costBasis) : null,
        shares_held: strategy === 'covered_call' ? parseInt(sharesHeld) : null,
        capital_available: strategy === 'cash_secured_put' ? parseFloat(capitalAvailable) : null,
        min_dte: minDte,
        max_dte: maxDte,
        min_return_pct: returnTarget,
        min_call_distance_pct: callDistance,
        max_delta: maxDelta,
        min_delta: minDelta,
        exclude_earnings_dte: earningsBuffer,
      };

      const data = await scanOptions(request);
      setResult(data);
      setSelectedStrikes([]);
    } catch (err) {
      const message = err.response?.data?.detail || err.message || 'Scan failed';
      setError(message);
    } finally {
      setLoading(false);
    }
  }, [ticker, strategy, costBasis, sharesHeld, capitalAvailable,
      minDte, maxDte, returnTarget, callDistance, minDelta, maxDelta, earningsBuffer]);

  const toggleStrikeSelection = useCallback((strike) => {
    setSelectedStrikes((prev) => {
      const key = `${strike.strike}-${strike.expiration}`;
      const exists = prev.find((s) => `${s.strike}-${s.expiration}` === key);
      if (exists) {
        return prev.filter((s) => `${s.strike}-${s.expiration}` !== key);
      }
      if (prev.length >= 3) {
        toast.error('Maximum 3 strikes for comparison');
        return prev;
      }
      return [...prev, strike];
    });
  }, []);

  const reset = useCallback(() => {
    setTicker('');
    setStrategy('cash_secured_put');
    setCostBasis('');
    setSharesHeld(100);
    setCapitalAvailable('');
    setMinDte(25);
    setMaxDte(50);
    setReturnTarget(1.0);
    setCallDistance(10.0);
    setMinDelta(0.15);
    setMaxDelta(0.35);
    setEarningsBuffer(5);
    setResult(null);
    setError(null);
    setSelectedStrikes([]);
  }, []);

  return {
    ticker, setTicker,
    strategy, setStrategy,
    costBasis, setCostBasis,
    sharesHeld, setSharesHeld,
    capitalAvailable, setCapitalAvailable,
    minDte, setMinDte,
    maxDte, setMaxDte,
    returnTarget, setReturnTarget,
    callDistance, setCallDistance,
    minDelta, setMinDelta,
    maxDelta, setMaxDelta,
    earningsBuffer, setEarningsBuffer,
    selectedStrikes, toggleStrikeSelection,
    result, loading, error,
    runScan, reset,
  };
}
