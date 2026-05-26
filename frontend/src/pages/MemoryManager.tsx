/**
 * pages/MemoryManager.tsx — Memory 系统管理页面
 *
 * 浏览和删除 Node Generator Agent 的经验记忆条目。
 */

import { useState, useEffect, useCallback } from 'react'
import { useNavigate } from 'react-router-dom'
import { ArrowLeft, Trash2, AlertTriangle, Brain, Loader2 } from 'lucide-react'
import { getToken } from '../lib/auth'

const API_BASE = '/api/v1/memory'

const SOFTWARE_LIST = ['gaussian', 'orca', 'psi4', 'cp2k', 'general']

interface MemoryEntry {
  id: string
  task: string
  lessons: string[]
  result: string
  software: string
}

async function fetchMemories(software: string): Promise<{ entries: MemoryEntry[]; count: number }> {
  const token = getToken()
  const resp = await fetch(`${API_BASE}/list?software=${software}`, {
    headers: token ? { Authorization: `Bearer ${token}` } : {},
  })
  if (!resp.ok) throw new Error(await resp.text())
  return resp.json()
}

async function deleteMemory(params: {
  software: string
  entryId?: string
  taskPrefix?: string
  deleteAll?: boolean
}): Promise<void> {
  const searchParams = new URLSearchParams()
  searchParams.set('software', params.software)
  if (params.deleteAll) searchParams.set('delete_all', 'true')
  if (params.entryId) searchParams.set('entry_id', params.entryId)
  if (params.taskPrefix) searchParams.set('task_prefix', params.taskPrefix)
  const token = getToken()
  const resp = await fetch(`${API_BASE}/delete`, {
    method: 'POST',
    headers: {
      'Content-Type': 'application/json',
      ...(token ? { Authorization: `Bearer ${token}` } : {}),
    },
    body: JSON.stringify(Object.fromEntries(searchParams)),
  })
  // The delete endpoint uses query params, but POST body is fine as fallback
  if (!resp.ok) throw new Error(await resp.text())
}

export function MemoryManager() {
  const navigate = useNavigate()
  const [software, setSoftware] = useState('gaussian')
  const [entries, setEntries] = useState<MemoryEntry[]>([])
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [deleting, setDeleting] = useState<Set<string>>(new Set())
  const [confirmClear, setConfirmClear] = useState(false)

  const load = useCallback(async () => {
    setLoading(true)
    setError(null)
    try {
      const data = await fetchMemories(software)
      setEntries(data.entries || [])
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err))
    } finally {
      setLoading(false)
    }
  }, [software])

  useEffect(() => { load() }, [load])

  const handleDelete = async (id: string) => {
    setDeleting((prev) => new Set(prev).add(id))
    try {
      await deleteMemory({ software, entryId: id })
      setEntries((prev) => prev.filter((e) => e.id !== id))
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err))
    } finally {
      setDeleting((prev) => {
        const next = new Set(prev)
        next.delete(id)
        return next
      })
    }
  }

  const handleClearAll = async () => {
    setDeleting(new Set(['__all__']))
    try {
      await deleteMemory({ software, deleteAll: true })
      setEntries([])
      setConfirmClear(false)
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err))
    } finally {
      setDeleting(new Set())
    }
  }

  return (
    <div className="min-h-screen bg-mf-bg text-mf-text-primary">
      {/* Header */}
      <div className="flex items-center gap-3 px-6 h-14 border-b border-mf-border bg-mf-panel">
        <button
          onClick={() => navigate('/')}
          className="p-1.5 rounded hover:bg-mf-hover text-mf-text-muted hover:text-mf-text-primary transition-colors"
          title="Back to Gallery"
        >
          <ArrowLeft size={16} />
        </button>
        <Brain size={18} className="text-purple-400" />
        <span className="text-sm font-semibold">Memory Manager</span>
        <span className="text-[11px] text-mf-text-muted ml-2">
          Manage agent experience memory
        </span>
      </div>

      {/* Content */}
      <div className="max-w-3xl mx-auto px-6 py-6 space-y-4">
        {/* Software selector */}
        <div className="flex items-center gap-3">
          <span className="text-xs text-mf-text-secondary">Software:</span>
          <div className="flex gap-1">
            {SOFTWARE_LIST.map((sw) => (
              <button
                key={sw}
                onClick={() => setSoftware(sw)}
                className={`px-3 py-1 rounded text-xs transition-colors ${
                  sw === software
                    ? 'bg-purple-700 text-white'
                    : 'bg-mf-card text-mf-text-secondary hover:bg-mf-hover'
                }`}
              >
                {sw}
              </button>
            ))}
          </div>
        </div>

        {/* Error */}
        {error && (
          <div className="flex items-center gap-2 px-3 py-2 rounded bg-red-900/30 border border-red-900/50 text-xs text-red-400">
            <AlertTriangle size={12} />
            {error}
          </div>
        )}

        {/* Loading */}
        {loading && (
          <div className="flex items-center gap-2 text-xs text-mf-text-muted py-8 justify-center">
            <Loader2 size={14} className="animate-spin" />
            Loading memories...
          </div>
        )}

        {/* Empty */}
        {!loading && entries.length === 0 && (
          <div className="text-center py-12 text-mf-text-muted text-xs">
            <Brain size={32} className="mx-auto mb-3 text-mf-text-muted/40" />
            No memories for <span className="text-mf-text-secondary">{software}</span>.
          </div>
        )}

        {/* Entry list */}
        {!loading && entries.length > 0 && (
          <>
            <div className="flex items-center justify-between">
              <span className="text-xs text-mf-text-muted">
                {entries.length} entr{entries.length === 1 ? 'y' : 'ies'}
              </span>
              {!confirmClear ? (
                <button
                  onClick={() => setConfirmClear(true)}
                  className="flex items-center gap-1 px-2 py-1 rounded text-[10px] text-red-400 hover:bg-red-900/30 transition-colors"
                >
                  <Trash2 size={10} />
                  Clear all
                </button>
              ) : (
                <div className="flex items-center gap-1.5">
                  <span className="text-[10px] text-red-400">Are you sure?</span>
                  <button
                    onClick={handleClearAll}
                    disabled={deleting.has('__all__')}
                    className="px-2 py-0.5 rounded text-[10px] bg-red-700 text-white hover:bg-red-600 disabled:opacity-50"
                  >
                    {deleting.has('__all__') ? 'Clearing...' : 'Yes, clear all'}
                  </button>
                  <button
                    onClick={() => setConfirmClear(false)}
                    className="px-2 py-0.5 rounded text-[10px] bg-mf-hover text-mf-text-secondary"
                  >
                    Cancel
                  </button>
                </div>
              )}
            </div>

            <div className="space-y-2">
              {entries.map((entry) => (
                <div
                  key={entry.id}
                  className="border border-mf-border rounded-lg bg-mf-card p-3 space-y-1.5"
                >
                  <div className="flex items-start justify-between gap-2">
                    <div className="flex-1 min-w-0">
                      <div className="text-xs text-mf-text-primary truncate">
                        {entry.task}
                      </div>
                      <div className="flex items-center gap-2 mt-0.5">
                        <span
                          className={`text-[10px] px-1 rounded ${
                            entry.result === 'success'
                              ? 'bg-green-900/40 text-green-400'
                              : 'bg-red-900/40 text-red-400'
                          }`}
                        >
                          {entry.result}
                        </span>
                      </div>
                    </div>
                    <button
                      onClick={() => handleDelete(entry.id)}
                      disabled={deleting.has(entry.id)}
                      className="flex-shrink-0 p-1 rounded text-mf-text-muted hover:text-red-400 hover:bg-red-900/20 disabled:opacity-30 transition-colors"
                      title="Delete this memory"
                    >
                      {deleting.has(entry.id) ? (
                        <Loader2 size={11} className="animate-spin" />
                      ) : (
                        <Trash2 size={11} />
                      )}
                    </button>
                  </div>
                  {entry.lessons.length > 0 && (
                    <div className="text-[10px] text-mf-text-secondary space-y-0.5 pl-2 border-l-2 border-mf-border">
                      {entry.lessons.map((lesson, i) => (
                        <div key={i} className="flex gap-1">
                          <span className="text-purple-400 flex-shrink-0">•</span>
                          <span>{lesson}</span>
                        </div>
                      ))}
                    </div>
                  )}
                </div>
              ))}
            </div>
          </>
        )}
      </div>
    </div>
  )
}
