import Header from './Header';
import ModeBar from '../controls/ModeBar';
import Sidebar from './Sidebar';

export default function Layout({
  children,
  regression,
  sessions,
  onLoadSession,
  onRun,
  onSave,
}) {
  return (
    <div className="h-screen flex flex-col bg-white dark:bg-slate-900">
      <Header
        sessions={sessions.sessions}
        onLoadSession={onLoadSession}
      />
      <ModeBar mode={regression.mode} setMode={regression.setMode} />
      <div className="flex flex-1 overflow-hidden">
        <Sidebar
          mode={regression.mode}
          asset={regression.asset}
          setAsset={regression.setAsset}
          dependents={regression.dependents}
          setDependents={regression.setDependents}
          compareAssets={regression.compareAssets}
          setCompareAssets={regression.setCompareAssets}
          startDate={regression.startDate}
          setStartDate={regression.setStartDate}
          endDate={regression.endDate}
          setEndDate={regression.setEndDate}
          windowSize={regression.windowSize}
          setWindowSize={regression.setWindowSize}
          sidebarTab={regression.sidebarTab}
          setSidebarTab={regression.setSidebarTab}
          showEarnings={regression.showEarnings}
          setShowEarnings={regression.setShowEarnings}
          onRun={onRun}
          loading={regression.loading}
          onSave={onSave}
          onReset={regression.reset}
        />
        <main className="flex-1 overflow-y-auto p-6">
          {children}
        </main>
      </div>
    </div>
  );
}
