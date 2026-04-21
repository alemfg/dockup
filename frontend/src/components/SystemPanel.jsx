/**
 * System Panel (v6.8)
 * Config export/import and database backup/restore.
 */
import React, { useState, useRef } from 'react'
import { Card } from './ui'

const SECTIONS = [
  { id: 'config',  label: '⚙ Config Export/Import' },
  { id: 'backup',  label: '💾 DB Backup/Restore' },
]

// ── Config Export/Import ──────────────────────────────────────────────────────
function ConfigSection() {
  const [importing, setImporting]   = useState(false)
  const [importResult, setImportResult] = useState(null)
  const [dryRun, setDryRun]         = useState(true)
  const fileRef = useRef(null)

  const exportConfig = () => {
    window.open('/api/system/config/export', '_blank')
  }

  const handleImportFile = async (e) => {
    const file = e.target.files?.[0]
    if (!file) return
    setImporting(true); setImportResult(null)
    try {
      const text = await file.text()
      const config = JSON.parse(text)
      const r = await fetch('/api/system/config/import', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ config, dry_run: dryRun }),
      }).then(x => x.json())
      setImportResult(r)
    } catch(e) {
      setImportResult({ ok: false, message: e.message })
    } finally {
      setImporting(false)
      if (fileRef.current) fileRef.current.value = ''
    }
  }

  return (
    <div className="space-y-4">
      {/* Export */}
      <div className="border border-gray-800 rounded-xl p-4 space-y-3">
        <div>
          <p className="text-sm font-semibold text-gray-200">Export Configuration</p>
          <p className="text-xs text-gray-500 mt-1">
            Downloads current ARBX settings as JSON. Safe to share or commit to git.
            Does NOT include secrets (API keys, webhook URLs, passwords).
          </p>
        </div>
        <div className="text-[10px] text-gray-600 space-y-0.5">
          <p>Includes: risk limits, decision rules, graph settings, worker config, alert categories</p>
          <p>Excludes: API keys, webhook URLs, SMTP passwords, ARBX_MASTER_KEY</p>
        </div>
        <button onClick={exportConfig}
          className="text-xs px-4 py-2 bg-blue-700 hover:bg-blue-600 text-white rounded-lg font-medium">
          ⬇ Download Config JSON
        </button>
      </div>

      {/* Import */}
      <div className="border border-gray-800 rounded-xl p-4 space-y-3">
        <div>
          <p className="text-sm font-semibold text-gray-200">Import Configuration</p>
          <p className="text-xs text-gray-500 mt-1">
            Import a previously exported config file. Applies risk, decision, and graph settings.
            Run as dry-run first to validate without applying.
          </p>
        </div>

        <label className="flex items-center gap-2 cursor-pointer text-xs text-gray-400">
          <input type="checkbox" checked={dryRun} onChange={e => setDryRun(e.target.checked)} />
          Dry run — validate only, don't apply changes
        </label>

        <div className="flex items-center gap-3">
          <input ref={fileRef} type="file" accept=".json"
            onChange={handleImportFile} disabled={importing}
            className="text-xs text-gray-400 file:mr-3 file:py-1.5 file:px-3 file:rounded
              file:border-0 file:text-xs file:bg-gray-700 file:text-gray-200 file:cursor-pointer
              hover:file:bg-gray-600" />
          {importing && <span className="text-xs text-gray-500">⟳ Processing...</span>}
        </div>

        {importResult && (
          <div className={`border rounded-lg p-3 space-y-2 ${
            importResult.ok
              ? 'bg-green-900/20 border-green-800'
              : 'bg-red-900/20 border-red-800'}`}>
            <p className={`text-xs font-semibold ${importResult.ok ? 'text-green-300' : 'text-red-300'}`}>
              {importResult.ok ? '✓' : '✗'} {importResult.message}
            </p>
            {importResult.dry_run && importResult.ok && (
              <p className="text-[10px] text-yellow-400">
                ⚠ Dry run — no changes applied. Uncheck "Dry run" and re-import to apply.
              </p>
            )}
            {importResult.applied?.length > 0 && (
              <div>
                <p className="text-[10px] text-gray-500 mb-1">Settings {importResult.dry_run ? 'that would be' : ''} applied:</p>
                <div className="flex flex-wrap gap-1">
                  {importResult.applied.map(k => (
                    <span key={k} className="text-[9px] px-1.5 py-0.5 bg-gray-800 text-gray-400 rounded font-mono">{k}</span>
                  ))}
                </div>
              </div>
            )}
            {importResult.warnings?.length > 0 && (
              <div className="text-[10px] text-yellow-500">
                {importResult.warnings.map((w, i) => <div key={i}>⚠ {w}</div>)}
              </div>
            )}
            {importResult.meta && (
              <p className="text-[10px] text-gray-600">
                Exported from ARBX v{importResult.meta.arbx_version} at {importResult.meta.exported_at?.slice(0, 19)}
              </p>
            )}
          </div>
        )}
      </div>
    </div>
  )
}

// ── DB Backup/Restore ─────────────────────────────────────────────────────────
function BackupSection() {
  const [restoring, setRestoring]     = useState(false)
  const [restoreResult, setRestoreResult] = useState(null)
  const fileRef = useRef(null)

  const downloadFullBackup = () => {
    window.open('/api/system/backup', '_blank')
  }

  const downloadTablesBackup = () => {
    window.open('/api/system/backup/tables', '_blank')
  }

  const handleRestoreFile = async (e) => {
    const file = e.target.files?.[0]
    if (!file) return
    if (!confirm('Restore database tables from this backup? Existing data will be merged (not deleted).')) {
      if (fileRef.current) fileRef.current.value = ''; return
    }
    setRestoring(true); setRestoreResult(null)
    try {
      const text = await file.text()
      const body = JSON.parse(text)
      const r = await fetch('/api/system/restore/tables', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(body),
      }).then(x => x.json())
      setRestoreResult(r)
    } catch(e) {
      setRestoreResult({ ok: false, message: e.message })
    } finally {
      setRestoring(false)
      if (fileRef.current) fileRef.current.value = ''
    }
  }

  return (
    <div className="space-y-4">
      {/* Full pg_dump */}
      <div className="border border-gray-800 rounded-xl p-4 space-y-3">
        <div>
          <p className="text-sm font-semibold text-gray-200">Full Database Backup</p>
          <p className="text-xs text-gray-500 mt-1">
            Downloads a complete PostgreSQL dump (pg_dump) as a gzip file.
            Includes all tables: config, API keys (encrypted), wallets, fees, order history.
          </p>
        </div>
        <div className="bg-yellow-900/20 border border-yellow-800/50 rounded-lg px-3 py-2 text-[10px] text-yellow-400">
          ⚠ API keys are encrypted with ARBX_MASTER_KEY. The backup is useless without the master key.
          Store both together securely.
        </div>
        <div className="text-[10px] text-gray-600">
          Restore: <code className="bg-gray-800 px-1 rounded">gunzip backup.sql.gz | psql -U arbitrage -d arbitrage</code>
        </div>
        <button onClick={downloadFullBackup}
          className="text-xs px-4 py-2 bg-indigo-700 hover:bg-indigo-600 text-white rounded-lg font-medium">
          ⬇ Download Full Backup (.sql.gz)
        </button>
      </div>

      {/* JSON tables export */}
      <div className="border border-gray-800 rounded-xl p-4 space-y-3">
        <div>
          <p className="text-sm font-semibold text-gray-200">Tables Export (JSON)</p>
          <p className="text-xs text-gray-500 mt-1">
            Exports key tables as JSON: config, fees, withdrawal fees, wallet addresses.
            Excludes API keys and order history. Easier to inspect and restore selectively.
          </p>
        </div>
        <div className="flex gap-3 flex-wrap">
          <button onClick={downloadTablesBackup}
            className="text-xs px-4 py-2 bg-green-700 hover:bg-green-600 text-white rounded-lg font-medium">
            ⬇ Export Tables JSON
          </button>
        </div>
      </div>

      {/* Restore */}
      <div className="border border-gray-800 rounded-xl p-4 space-y-3">
        <div>
          <p className="text-sm font-semibold text-gray-200">Restore from Tables JSON</p>
          <p className="text-xs text-gray-500 mt-1">
            Restore from a JSON tables export. Merges into existing data (upsert — will not delete records).
            Only accepts the JSON format from "Export Tables JSON" above.
          </p>
        </div>
        <div className="flex items-center gap-3">
          <input ref={fileRef} type="file" accept=".json"
            onChange={handleRestoreFile} disabled={restoring}
            className="text-xs text-gray-400 file:mr-3 file:py-1.5 file:px-3 file:rounded
              file:border-0 file:text-xs file:bg-gray-700 file:text-gray-200 file:cursor-pointer
              hover:file:bg-gray-600" />
          {restoring && <span className="text-xs text-gray-500">⟳ Restoring...</span>}
        </div>

        {restoreResult && (
          <div className={`border rounded-lg p-3 space-y-2 ${
            restoreResult.ok
              ? 'bg-green-900/20 border-green-800'
              : 'bg-red-900/20 border-red-800'}`}>
            <p className={`text-xs font-semibold ${restoreResult.ok ? 'text-green-300' : 'text-red-300'}`}>
              {restoreResult.ok ? '✓ Restore complete' : `✗ ${restoreResult.message}`}
            </p>
            {restoreResult.restored && (
              <div className="flex gap-3 text-[10px] text-gray-400">
                {Object.entries(restoreResult.restored).map(([t, n]) => (
                  <span key={t}><span className="text-gray-300 font-mono">{t}</span>: {n} rows</span>
                ))}
              </div>
            )}
          </div>
        )}
      </div>

      <div className="text-[10px] text-gray-700 space-y-1 pt-2 border-t border-gray-800">
        <p>📌 Backup checklist before upgrades: (1) Tables JSON export, (2) config export, (3) note your .env.local settings, (4) note ARBX_MASTER_KEY.</p>
        <p>📌 After a fresh install: restore tables JSON, re-enter API keys in Vault (cannot be restored without master key match).</p>
      </div>
    </div>
  )
}

// ── Main ──────────────────────────────────────────────────────────────────────
export default function SystemPanel() {
  const [section, setSection] = useState('config')
  return (
    <div className="space-y-3">
      <div className="flex gap-1">
        {SECTIONS.map(({ id, label }) => (
          <button key={id} onClick={() => setSection(id)}
            className={`text-xs px-3 py-1.5 rounded transition-colors
              ${section === id ? 'bg-indigo-700 text-white font-medium' : 'bg-gray-800 text-gray-400 hover:bg-gray-700'}`}>
            {label}
          </button>
        ))}
      </div>
      {section === 'config' && (
        <Card title="Config Export / Import" subtitle="Portable config snapshot — no secrets included">
          <ConfigSection />
        </Card>
      )}
      {section === 'backup' && (
        <Card title="Database Backup / Restore" subtitle="PostgreSQL dump and JSON table exports">
          <BackupSection />
        </Card>
      )}
    </div>
  )
}
