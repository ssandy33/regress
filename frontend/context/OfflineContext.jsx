import { createContext, useContext } from 'react';
import { useSourceHealth } from '../hooks/useSourceHealth';

const OfflineContext = createContext({ health: null, allDown: false, refresh: () => {} });

export function OfflineProvider({ children }) {
  const sourceHealth = useSourceHealth();
  return (
    <OfflineContext.Provider value={sourceHealth}>
      {children}
    </OfflineContext.Provider>
  );
}

export function useOffline() {
  return useContext(OfflineContext);
}
