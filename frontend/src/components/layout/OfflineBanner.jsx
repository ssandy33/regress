import { useOffline } from '../../context/OfflineContext';

export default function OfflineBanner() {
  const { allDown } = useOffline();

  if (!allDown) return null;

  return (
    <div className="bg-red-600 text-white text-sm text-center py-2 px-4">
      All data sources are currently unreachable. Using cached data only.
    </div>
  );
}
