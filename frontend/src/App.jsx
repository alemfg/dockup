import React, { useState } from 'react'
import StatusBar from './components/StatusBar'
import FleetHealth from './components/FleetHealth'
import CoverageMap from './components/CoverageMap'
import WorkerInspector from './components/WorkerInspector'
import AnalysisContexts from './components/AnalysisContexts'
import CRPanel from './components/CRPanel'
import MarketFeed from './components/MarketFeed'
import BalancesPanel from './components/BalancesPanel'
import SecurityPanel from './components/SecurityPanel'
import EventLog from './components/EventLog'
import GraphPanel from './components/GraphPanel'

import TradingModePanel from './components/TradingModePanel'
import ConfigReloadPanel from './components/ConfigReloadPanel'
import FinancialsPanel from './components/FinancialsPanel'
import RiskPanel from './components/RiskPanel'
import LogViewerPanel from './components/LogViewerPanel'
import FinancialEventsPanel from './components/FinancialEventsPanel'

const TABS = [
  { id: 'fleet',    label: '🖥  Fleet Health' },
  { id: 'market',   label: '📊 Market Feed' },
  { id: 'graph',    label: '🕸  Graph Arb' },
  { id: 'cr',       label: '🕘 9AM CR Model' },
  { id: 'analysis', label: '🧠 Analysis' },
  { id: 'coverage', label: '🗺  Coverage' },
  { id: 'balances', label: '💰 Balances' },
  { id: 'trading',    label: '⚡ Trading Mode' },
  { id: 'config',     label: '⚙️ Config & Reload' },
  { id: 'financials', label: '💹 Financials' },
  { id: 'risk',       label: '🛡 Risk & Rules' },
  { id: 'logs',       label: '🖥 Logs' },
  { id: 'fin_events', label: '📡 Fin. Events' },
  { id: 'security', label: '🔐 Security' },
  { id: 'events',   label: '📋 Fleet Events' },
]

export default function App() {
  const [tab, setTab] = useState('fleet')
  const [selectedWorker, setSelectedWorker] = useState(null)

  return (
    <div className="min-h-screen flex flex-col bg-gray-950 text-gray-100">
      {/* Header */}
      <header className="bg-gray-900 border-b border-gray-800 px-6 py-3 flex items-center justify-between">
        <div className="flex items-center gap-3">
          <div className="w-8 h-8 rounded-lg bg-gradient-to-br from-green-500 to-emerald-700 flex items-center justify-center font-bold text-sm">
            v4
          </div>
          <div>
            <h1 className="text-sm font-bold text-white tracking-tight">ARBX v4.6</h1>
            <p className="text-xs text-gray-500">Distributed · Secure · Modular</p>
          </div>
        </div>
        <div className="hidden sm:flex items-center gap-1 flex-wrap justify-end">
          {TABS.map(t => (
            <button key={t.id} onClick={() => { setTab(t.id); setSelectedWorker(null); }}
              className={`text-xs px-3 py-1.5 rounded transition-colors
                ${tab === t.id ? 'bg-green-700 text-white font-medium' : 'text-gray-400 hover:text-gray-200 hover:bg-gray-800'}`}>
              {t.label}
            </button>
          ))}
        </div>
      </header>

      <StatusBar />

      {/* Mobile tabs */}
      <div className="sm:hidden flex overflow-x-auto gap-1 p-2 bg-gray-900 border-b border-gray-800">
        {TABS.map(t => (
          <button key={t.id} onClick={() => setTab(t.id)}
            className={`text-xs px-3 py-1.5 rounded whitespace-nowrap transition-colors
              ${tab === t.id ? 'bg-green-700 text-white' : 'text-gray-400 bg-gray-800'}`}>
            {t.label}
          </button>
        ))}
      </div>

      <main className="flex-1 p-4 lg:p-6">
        {/* Fleet Health tab */}
        {tab === 'fleet' && !selectedWorker && (
          <FleetHealth onSelectWorker={setSelectedWorker} />
        )}
        {tab === 'fleet' && selectedWorker && (
          <WorkerInspector
            workerId={selectedWorker}
            onBack={() => setSelectedWorker(null)}
          />
        )}

        {tab === 'market'   && <MarketFeed />}
        {tab === 'graph'    && <GraphPanel />}
        {tab === 'cr'       && <CRPanel />}
        {tab === 'analysis' && <AnalysisContexts />}
        {tab === 'coverage' && <CoverageMap onSelectWorker={(id) => { setSelectedWorker(id); setTab('fleet'); }} />}
        {tab === 'balances' && <BalancesPanel />}
        {tab === 'trading'    && <TradingModePanel />}
        {tab === 'config'     && <ConfigReloadPanel />}
        {tab === 'financials' && <FinancialsPanel />}
        {tab === 'risk'       && <RiskPanel />}
        {tab === 'logs'       && <LogViewerPanel />}
        {tab === 'fin_events' && <FinancialEventsPanel />}
        {tab === 'security' && <SecurityPanel />}
        {tab === 'events'   && <EventLog />}
      </main>

      <footer className="border-t border-gray-800 px-6 py-3 text-center text-xs text-gray-700">
        ARBX v4.4 — .env.local · Graph Config · BF+FW Dual-Run · Per-Exchange Fees · Tooltips
      </footer>
    </div>
  )
}
