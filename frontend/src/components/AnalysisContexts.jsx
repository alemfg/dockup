import React from 'react'
import { usePolling, fetchContexts, fetchSignals } from '../utils/api'
import { Card, ConfidenceBadge, EmptyState, Spinner } from './ui'
import { Tip, TipIcon } from './Tooltip'

const PLUGIN_TIPS = {
  rsi:         'RSI (Relative Strength Index): momentum oscillator 0–100. Above 70 = overbought (bearish signal), below 30 = oversold (bullish signal).',
  macd:        'MACD (Moving Average Convergence Divergence): trend-following momentum. Positive histogram = bullish, negative = bearish.',
  bollinger:   'Bollinger Bands: price relative to 2-standard-deviation bands. Near upper band = overbought; near lower band = oversold.',
  cr_9am:      '9AM CRT plugin: Bruce_Loki Candle Range Theory model. Analyses 1AM/5AM session candles for NY session reversal or continuation setups.',
  arima:       'ARIMA predictor: statistical time-series model. Forecasts short-term price direction based on historical autocorrelation patterns.',
  lstm:        'LSTM neural network predictor. Trained on price sequences to predict next N candles. Requires tensorflow — disabled if not installed.',
  volume:      'Volume Profile: analyses buying vs selling volume to identify high-volume nodes, value area, and point of control.',
  sentiment:   'Sentiment: external news/social signal. Requires a configured data source (e.g. CryptoPanic or Twitter API key).',
}

function PluginDots({ signal }) {
  const plugins = signal?.plugins ?? []
  return (
    <div className="flex gap-1 flex-wrap">
      {plugins.map((p, i) => {
        const name = p.plugin?.toLowerCase().replace(/[^a-z0-9]/g, '') ?? ''
        const matchKey = Object.keys(PLUGIN_TIPS).find(k => name.includes(k))
        const tip = matchKey
          ? `${p.plugin}: score ${p.signal_score?.toFixed(3)}. ${PLUGIN_TIPS[matchKey]}`
          : `${p.plugin}: score ${p.signal_score?.toFixed(3)}`
        return (
          <Tip key={i} text={tip} pos="top" wide>
            <span className={`w-2.5 h-2.5 rounded-full cursor-help ${
              p.signal_score > 0.6 ? 'bg-green-500' :
              p.signal_score > 0.4 ? 'bg-yellow-500' : 'bg-red-500'
            }`} />
          </Tip>
        )
      })}
    </div>
  )
}

const TREND_TIPS = {
  BULLISH: 'Aggregated plugin signals lean bullish — more plugins show positive momentum than negative.',
  BEARISH: 'Aggregated plugin signals lean bearish — more plugins show negative momentum than positive.',
  NEUTRAL: 'Plugin signals are mixed or inconclusive — no clear directional bias.',
}

const VOLATILITY_TIPS = {
  HIGH:   'Price is moving more than usual relative to recent history. Higher volatility = wider Bollinger Bands, larger ATR.',
  MEDIUM: 'Moderate price movement. Normal market conditions for this pair.',
  LOW:    'Price is compressed, moving less than usual. Breakout risk: low volatility often precedes sharp moves.',
}

export default function AnalysisContexts() {
  const { data: ctxData, loading: ctxLoading } = usePolling(fetchContexts, 8000)
  const { data: sigData }                       = usePolling(fetchSignals,  8000)

  if (ctxLoading) return <Card title="Analysis Contexts"><Spinner /></Card>

  const contexts = ctxData?.contexts ?? []
  const signals  = sigData?.signals  ?? []
  const sigMap   = Object.fromEntries(signals.map(s => [`${s.exchange}:${s.pair}`, s]))

  const headers = [
    { label: 'Context',    tip: 'Exchange and trading pair this analysis context belongs to. Each (exchange × pair) combination has its own independent price history and plugin state.' },
    { label: 'Ticks',      tip: 'Total number of price ticks received for this context since startup. More ticks = longer history for indicator calculations.' },
    { label: 'Score',      tip: 'Aggregated signal score (0.0–1.0) computed by combining all enabled plugin outputs weighted by their configured importance. Above 0.65 = strong signal.' },
    { label: 'Trend',      tip: 'Overall directional bias determined by majority vote across plugins. BULLISH / BEARISH / NEUTRAL.' },
    { label: 'Volatility', tip: 'Current volatility regime for this pair. Determined by ATR relative to recent history. HIGH/MEDIUM/LOW.' },
    { label: 'Plugins',    tip: 'Each dot = one analysis plugin. Green = bullish signal (score > 0.6), Yellow = neutral (0.4–0.6), Red = bearish (< 0.4). Hover a dot for details.' },
    { label: 'Conf.',      tip: 'Confidence level of the aggregate signal. HIGH = strong agreement across plugins. MEDIUM = mixed. LOW = conflicting or insufficient data.' },
  ]

  return (
    <Card
      title="Analysis Contexts"
      subtitle={`${contexts.length} active contexts — per (exchange × pair)`}
    >
      {contexts.length === 0 ? (
        <EmptyState message="No contexts yet — waiting for worker data" icon="🧠" />
      ) : (
        <div className="overflow-x-auto">
          <table className="w-full text-sm">
            <thead>
              <tr className="border-b border-gray-800">
                {headers.map((h, i) => (
                  <th key={i} className="text-left text-xs text-gray-500 uppercase tracking-wider pb-2 pr-4">
                    <Tip text={h.tip} pos="bottom" wide>
                      <span className="cursor-help border-b border-dashed border-gray-700">{h.label}</span>
                    </Tip>
                  </th>
                ))}
              </tr>
            </thead>
            <tbody>
              {contexts.map((ctx, i) => {
                const sig = sigMap[ctx.key]
                return (
                  <tr key={i} className="border-b border-gray-800/40 hover:bg-gray-800/20">
                    <td className="py-2.5 pr-4">
                      <span className="text-xs font-mono text-blue-400">{ctx.exchange}</span>
                      <span className="text-gray-500 mx-1">:</span>
                      <span className="text-gray-200 font-medium">{ctx.pair}</span>
                    </td>
                    <td className="py-2.5 pr-4 text-gray-500 text-xs font-mono">
                      <Tip text={`${ctx.tick_count?.toLocaleString()} price ticks received. Indicators need at least 14–200 ticks to produce reliable outputs depending on the plugin.`} pos="right">
                        <span className="cursor-help">{ctx.tick_count?.toLocaleString()}</span>
                      </Tip>
                    </td>
                    <td className="py-2.5 pr-4 font-mono">
                      {sig ? (
                        <Tip text={
                          sig.signal_score > 0.65
                            ? `Strong signal (${sig.signal_score?.toFixed(3)}). Above the default 0.65 threshold — eligible for order creation if R:R and other conditions pass.`
                            : sig.signal_score > 0.45
                            ? `Moderate signal (${sig.signal_score?.toFixed(3)}). Below default threshold. Monitor — may strengthen.`
                            : `Weak signal (${sig.signal_score?.toFixed(3)}). Plugin consensus is low or conflicting.`
                        } pos="right">
                          <span className={`cursor-help ${
                            sig.signal_score > 0.65 ? 'text-green-400' :
                            sig.signal_score > 0.45 ? 'text-yellow-400' : 'text-red-400'
                          }`}>
                            {sig.signal_score?.toFixed(3)}
                          </span>
                        </Tip>
                      ) : <span className="text-gray-600">—</span>}
                    </td>
                    <td className="py-2.5 pr-4 text-xs">
                      <Tip text={sig?.trend ? TREND_TIPS[sig.trend] ?? sig.trend : 'No trend data yet — waiting for enough ticks.'} pos="right">
                        <span className={`cursor-help ${
                          sig?.trend === 'BULLISH' ? 'text-green-400' :
                          sig?.trend === 'BEARISH' ? 'text-red-400' : 'text-gray-500'
                        }`}>
                          {sig?.trend ?? '—'}
                        </span>
                      </Tip>
                    </td>
                    <td className="py-2.5 pr-4 text-xs">
                      <Tip text={sig?.volatility ? VOLATILITY_TIPS[sig.volatility] ?? sig.volatility : 'Volatility not yet calculated — waiting for sufficient price history.'} pos="right">
                        <span className="cursor-help text-gray-500">{sig?.volatility ?? '—'}</span>
                      </Tip>
                    </td>
                    <td className="py-2.5 pr-4">
                      {sig
                        ? <PluginDots signal={sig} />
                        : <span className="text-gray-600 text-xs">{ctx.plugins_active} loaded</span>
                      }
                    </td>
                    <td className="py-2.5 pr-4">
                      {sig
                        ? <ConfidenceBadge value={sig.confidence} />
                        : <span className="text-gray-600 text-xs">—</span>
                      }
                    </td>
                  </tr>
                )
              })}
            </tbody>
          </table>
        </div>
      )}
    </Card>
  )
}
