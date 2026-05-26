/**
 * pages/AdminUsagePage.tsx — Admin usage statistics dashboard
 *
 * Shows per-user token + compute consumption. Admin-only access.
 */

import { useEffect, useState } from 'react'
import { getStoredUser } from '../lib/auth'
import { fetchJSON } from '../api/client'
import {
  Shield, Users, Cpu, Coins, Zap, ArrowLeft, Loader2,
} from 'lucide-react'

// ─── 格式化辅助 ──────────────────────────────────────────────────

function formatTokens(n: number): string {
  if (n >= 1_000_000) {
    return (n / 1_000_000).toFixed(1) + 'M'
  }
  return (n / 1000).toFixed(0) + 'K'
}

function formatCost(n: number, currency: string): string {
  return currency + ' ' + n.toFixed(2)
}

interface AdminUsageSummary {
  period_days: number
  total_users: number
  total_core_hours: number
  total_gpu_hours: number
  total_tokens: number
  total_estimated_cost: number
  users: AdminUserUsage[]
}

interface AdminUserUsage {
  username: string
  token_usage: {
    total_calls: number
    total_input_tokens: number
    total_output_tokens: number
    total_tokens: number
    estimated_cost: number
  }
  compute_usage: {
    total_core_hours: number
    total_gpu_hours: number
    total_workflows: number
    estimated_cost: number
  }
}

export function AdminUsagePage() {
  const storedUser = getStoredUser()
  const [days, setDays] = useState(30)
  const [data, setData] = useState<AdminUsageSummary | null>(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)

  // ── Access control ──────────────────────────────────────────────────────
  if (storedUser?.role !== 'admin') {
    return (
      <div className="min-h-screen bg-mf-bg flex items-center justify-center">
        <div className="text-center">
          <Shield className="mx-auto mb-4 text-red-400" size={48} />
          <h1 className="text-xl font-bold text-mf-text-primary mb-2">Access Denied</h1>
          <p className="text-mf-text-secondary text-sm">
            Admin access required to view usage statistics.
          </p>
          <a
            href="/"
            className="mt-4 inline-block text-blue-400 hover:text-blue-300 text-sm transition-colors"
          >
            ← Back to Gallery
          </a>
        </div>
      </div>
    )
  }

  // ── Data fetching ───────────────────────────────────────────────────────
  useEffect(() => {
    let cancelled = false
    setLoading(true)
    setError(null)

    fetchJSON<AdminUsageSummary>(`/admin/usage?days=${days}`)
      .then((res) => {
        if (!cancelled) setData(res)
      })
      .catch((err) => {
        if (!cancelled) setError(err instanceof Error ? err.message : 'Failed to load usage data')
      })
      .finally(() => {
        if (!cancelled) setLoading(false)
      })

    return () => { cancelled = true }
  }, [days])

  // ── Render ──────────────────────────────────────────────────────────────
  return (
    <div className="min-h-screen bg-mf-bg">
      {/* Header */}
      <div className="flex items-center gap-3 px-6 h-14 border-b border-mf-border bg-mf-panel">
        <a
          href="/"
          className="p-1.5 rounded hover:bg-mf-hover text-mf-text-muted hover:text-mf-text-primary transition-colors"
          title="Back to Gallery"
        >
          <ArrowLeft size={16} />
        </a>
        <Shield size={18} className="text-yellow-400" />
        <span className="text-sm font-semibold">Usage Statistics</span>
        <span className="text-[11px] text-mf-text-muted ml-2">
          Token + compute consumption overview
        </span>

        <div className="flex-1" />

        {/* Period selector */}
        <div className="flex gap-1 bg-mf-card border border-mf-border rounded-lg p-0.5">
          {[7, 30, 90].map((d) => (
            <button
              key={d}
              onClick={() => setDays(d)}
              className={`px-3 py-1 text-xs rounded-md transition-colors ${
                days === d
                  ? 'bg-blue-600 text-white'
                  : 'text-mf-text-secondary hover:text-mf-text-primary'
              }`}
            >
              {d}d
            </button>
          ))}
        </div>
      </div>

      {/* Content */}
      <div className="max-w-6xl mx-auto px-6 py-6 space-y-4">
        {/* Error */}
        {error && (
          <div className="px-3 py-2 rounded bg-red-900/30 border border-red-900/50 text-xs text-red-400">
            {error}
          </div>
        )}

        {/* Loading */}
        {loading && (
          <div className="flex items-center gap-2 text-xs text-mf-text-muted py-12 justify-center">
            <Loader2 size={14} className="animate-spin" />
            Loading statistics...
          </div>
        )}

        {/* Data */}
        {data && !loading && (
          <>
            {/* Summary cards */}
            <div className="grid grid-cols-2 md:grid-cols-5 gap-3">
              {[
                { label: 'Users', value: data.total_users, icon: Users, color: 'text-blue-400' },
                { label: 'Core Hours', value: data.total_core_hours.toFixed(1), icon: Cpu, color: 'text-green-400' },
                { label: 'GPU Hours', value: data.total_gpu_hours.toFixed(1), icon: Zap, color: 'text-purple-400' },
                { label: 'Tokens', value: formatTokens(data.total_tokens), icon: Coins, color: 'text-yellow-400' },
                { label: 'Est. Cost', value: formatCost(data.total_estimated_cost, data.currency || 'USD'), icon: Coins, color: 'text-orange-400' },
              ].map((card) => (
                <div
                  key={card.label}
                  className="bg-mf-card border border-mf-border rounded-lg p-3"
                >
                  <div className="flex items-center gap-1.5 text-mf-text-muted text-[10px] uppercase tracking-wide mb-1">
                    <card.icon size={12} className={card.color} />
                    {card.label}
                  </div>
                  <div className="text-lg font-bold text-mf-text-primary">
                    {card.value}
                  </div>
                </div>
              ))}
            </div>

            {/* Users table */}
            <div className="bg-mf-card border border-mf-border rounded-lg overflow-hidden">
              <div className="overflow-x-auto">
                <table className="w-full text-xs">
                  <thead>
                    <tr className="border-b border-mf-border bg-mf-hover/50">
                      <th className="text-left px-4 py-2 text-mf-text-secondary font-semibold">
                        User
                      </th>
                      <th className="text-right px-3 py-2 text-mf-text-secondary font-semibold">
                        Calls
                      </th>
                      <th className="text-right px-3 py-2 text-mf-text-secondary font-semibold">
                        Tokens
                      </th>
                      <th className="text-right px-3 py-2 text-mf-text-secondary font-semibold">
                        Token Cost
                      </th>
                      <th className="text-right px-3 py-2 text-mf-text-secondary font-semibold">
                        Core Hrs
                      </th>
                      <th className="text-right px-3 py-2 text-mf-text-secondary font-semibold">
                        GPU Hrs
                      </th>
                      <th className="text-right px-3 py-2 text-mf-text-secondary font-semibold">
                        WFs
                      </th>
                      <th className="text-right px-3 py-2 text-mf-text-secondary font-semibold">
                        Comp Cost
                      </th>
                      <th className="text-right px-4 py-2 text-mf-text-secondary font-semibold">
                        Total
                      </th>
                    </tr>
                  </thead>
                  <tbody className="divide-y divide-mf-border/50">
                    {data.users.map((user) => {
                      const totalCost =
                        user.token_usage.estimated_cost +
                        user.compute_usage.estimated_cost
                      return (
                        <tr
                          key={user.username}
                          className="hover:bg-mf-hover/30 transition-colors"
                        >
                          <td className="px-4 py-2.5 text-mf-text-primary font-medium">
                            {user.username}
                          </td>
                          <td className="px-3 py-2.5 text-right text-mf-text-secondary">
                            {user.token_usage.total_calls}
                          </td>
                          <td className="px-3 py-2.5 text-right text-mf-text-secondary">
                            {formatTokens(user.token_usage.total_tokens)}
                          </td>
                          <td className="px-3 py-2.5 text-right text-mf-text-secondary">
                            {formatCost(user.token_usage.estimated_cost, data.currency || 'USD')}
                          </td>
                          <td className="px-3 py-2.5 text-right text-mf-text-secondary">
                            {user.compute_usage.total_core_hours.toFixed(1)}
                          </td>
                          <td className="px-3 py-2.5 text-right text-mf-text-secondary">
                            {user.compute_usage.total_gpu_hours.toFixed(1)}
                          </td>
                          <td className="px-3 py-2.5 text-right text-mf-text-secondary">
                            {user.compute_usage.total_workflows}
                          </td>
                          <td className="px-3 py-2.5 text-right text-mf-text-secondary">
                            {formatCost(user.compute_usage.estimated_cost, data.currency || 'USD')}
                          </td>
                          <td className="px-4 py-2.5 text-right text-mf-text-primary font-semibold">
                            {formatCost(totalCost, data.currency || 'USD')}
                          </td>
                        </tr>
                      )
                    })}
                    {data.users.length === 0 && (
                      <tr>
                        <td
                          colSpan={9}
                          className="text-center py-8 text-mf-text-muted"
                        >
                          No usage data in this period.
                        </td>
                      </tr>
                    )}
                  </tbody>
                </table>
              </div>
            </div>

            <p className="text-[10px] text-mf-text-muted text-right">
              Last {data.period_days} days · Costs ({data.currency || 'USD'}) based on models.yaml &amp; compute_pricing.yaml
            </p>
          </>
        )}
      </div>
    </div>
  )
}
