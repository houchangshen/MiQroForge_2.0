import { useState, useCallback, useEffect } from 'react'
import { useQuery, useQueryClient } from '@tanstack/react-query'
import { argoApi } from '../../api/argo-api'
import { useSavedWorkflowsStore, snapshotToRF } from '../../stores/saved-workflows-store'
import { useWorkflowStore } from '../../stores/workflow-store'
import { useProjectStore } from '../../stores/project-store'
import { useUIStore } from '../../stores/ui-store'
import { useRunOverlayStore } from '../../stores/run-overlay-store'
import type { RunSummaryResponse, RunPhase, RunDetailResponse } from '../../types/index-types'
import { RefreshCw, ChevronRight, Terminal, RotateCcw, Trash2, AlertTriangle, Info, Square } from 'lucide-react'
import { phaseBadgeClass, formatDurationSeconds } from '../../lib/phase-utils'

// ─── Helpers for RunDetail ────────────────────────────────────────────────────

interface ArgoStepNode {
  id: string
  name: string
  templateName: string
  phase: RunPhase
}

interface StepGroup {
  templateName: string
  canvasId: string
  instances: ArgoStepNode[]
  phaseCounts: Record<string, number>
  total: number
}

function parseSteps(detail: RunDetailResponse): ArgoStepNode[] {
  const status = (detail.raw.status ?? {}) as Record<string, unknown>
  const nodes = (status.nodes ?? {}) as Record<string, Record<string, unknown>>
  return Object.entries(nodes)
    .filter(([, n]) => n.type === 'Pod' || n.type === 'Skipped')
    .map(([id, n]) => ({
      id,
      name: (n.displayName ?? n.templateName ?? id) as string,
      templateName: (n.templateName ?? '') as string,
      phase: ((n.phase as RunPhase | undefined) ?? 'Unknown'),
    }))
}

/** Group steps by templateName for sweep progress display. */
function groupSteps(steps: ArgoStepNode[]): StepGroup[] {
  const map = new Map<string, ArgoStepNode[]>()
  const order: string[] = []
  for (const step of steps) {
    const key = step.templateName || step.id
    if (!map.has(key)) {
      map.set(key, [])
      order.push(key)
    }
    map.get(key)!.push(step)
  }
  return order.map((templateName) => {
    const instances = map.get(templateName)!
    const phaseCounts: Record<string, number> = {}
    for (const inst of instances) {
      phaseCounts[inst.phase] = (phaseCounts[inst.phase] ?? 0) + 1
    }
    // Derive canvas ID: strip leading "mf-" prefix if present
    const canvasId = templateName.startsWith('mf-')
      ? templateName.slice(3)
      : templateName
    return { templateName, canvasId, instances, phaseCounts, total: instances.length }
  })
}

/** Segmented progress bar for multi-instance (sweep) step groups. */
function SweepProgressBar({
  group,
  expanded,
  onToggle,
}: {
  group: StepGroup
  expanded: boolean
  onToggle: () => void
}) {
  const succeeded = (group.phaseCounts['Succeeded'] ?? 0)
  const running   = (group.phaseCounts['Running'] ?? 0)
  const failed    = (group.phaseCounts['Failed'] ?? 0) + (group.phaseCounts['Error'] ?? 0)

  return (
    <div>
      <button
        onClick={onToggle}
        className="w-full flex items-center gap-1.5 py-0.5 text-left hover:bg-mf-hover/50 rounded transition-colors"
      >
        <ChevronRight
          size={10}
          className={`text-mf-text-muted flex-shrink-0 transition-transform ${expanded ? 'rotate-90' : ''}`}
        />
        <span className="text-[11px] font-mono text-mf-text-secondary truncate min-w-0">
          {group.canvasId}
        </span>
        <div className="flex-1 h-1.5 bg-mf-border/30 rounded-full overflow-hidden flex mx-1">
          {succeeded > 0 && (
            <div
              style={{ width: `${(succeeded / group.total) * 100}%` }}
              className="bg-green-500 transition-all"
            />
          )}
          {running > 0 && (
            <div
              style={{ width: `${(running / group.total) * 100}%` }}
              className="bg-blue-400 animate-pulse transition-all"
            />
          )}
          {failed > 0 && (
            <div
              style={{ width: `${(failed / group.total) * 100}%` }}
              className="bg-red-500 transition-all"
            />
          )}
        </div>
        <span className="text-[10px] text-mf-text-muted flex-shrink-0 tabular-nums">
          {succeeded}/{group.total}
        </span>
      </button>

      {expanded && (
        <div className="ml-4 mt-0.5 mb-1 space-y-0.5 border-l border-mf-border/40 pl-2">
          {group.instances.map((inst) => (
            <div key={inst.id} className="flex items-center justify-between text-xs">
              <span className="text-mf-text-muted font-mono text-[10px] truncate">
                {inst.name}
              </span>
              <PhaseBadge phase={inst.phase} />
            </div>
          ))}
        </div>
      )}
    </div>
  )
}

/** Render step groups: single-instance groups as plain rows, multi-instance as progress bars. */
function StepsDisplay({ steps }: { steps: ArgoStepNode[] }) {
  const [expandedGroups, setExpandedGroups] = useState<Set<string>>(new Set())
  const groups = groupSteps(steps)

  const toggleGroup = useCallback((templateName: string) => {
    setExpandedGroups((prev) => {
      const next = new Set(prev)
      if (next.has(templateName)) {
        next.delete(templateName)
      } else {
        next.add(templateName)
      }
      return next
    })
  }, [])

  return (
    <div>
      <div className="text-[10px] text-mf-text-muted mb-1 uppercase tracking-wide">Steps</div>
      <div className="max-h-48 overflow-y-auto mf-scroll space-y-1">
        {groups.map((group) =>
          group.total === 1 ? (
            // Single-instance: render as a plain row (existing behavior)
            <div key={group.templateName} className="flex items-center justify-between text-xs">
              <span className="text-mf-text-secondary font-mono text-[11px] truncate">
                {group.instances[0].name}
              </span>
              <PhaseBadge phase={group.instances[0].phase} />
            </div>
          ) : (
            // Multi-instance (sweep): render progress bar with expand/collapse
            <SweepProgressBar
              key={group.templateName}
              group={group}
              expanded={expandedGroups.has(group.templateName)}
              onToggle={() => toggleGroup(group.templateName)}
            />
          ),
        )}
      </div>
    </div>
  )
}

function getStatusMessage(detail: RunDetailResponse): string | undefined {
  const status = (detail.raw.status ?? {}) as Record<string, unknown>
  return status.message as string | undefined
}

function PhaseBadge({ phase }: { phase: RunPhase }) {
  return <span className={phaseBadgeClass(phase)}>{phase}</span>
}

function formatDuration(secs?: number): string {
  if (!secs) return '—'
  return formatDurationSeconds(secs)
}

// ─── Run list ─────────────────────────────────────────────────────────────────

function RunList({
  runs,
  onSelect,
}: {
  runs: RunSummaryResponse[]
  onSelect: (name: string) => void
}) {
  const queryClient = useQueryClient()
  const { runSnapshots } = useSavedWorkflowsStore()
  const { loadFromNodes, setMeta } = useWorkflowStore()
  const { showNotification, selectNode, setRightPanel } = useUIStore()
  const { setActiveRun } = useRunOverlayStore()

  const handleRestore = useCallback(
    async (runName: string, e: React.MouseEvent) => {
      e.stopPropagation()
      const projectId = useProjectStore.getState().currentProjectId
      // Try afterrun_canvas from backend first
      if (projectId) {
        try {
          const canvas = await argoApi.getAfterrunCanvas(runName, projectId) as {
            meta: Record<string, unknown>
            nodes: Array<Record<string, unknown>>
            edges: Array<Record<string, unknown>>
            nodeStatuses?: Record<string, unknown>
            workflowPhase?: string | null
          }
          setMeta(canvas.meta as Parameters<typeof setMeta>[0])
          loadFromNodes(
            canvas.nodes as Parameters<typeof loadFromNodes>[0],
            canvas.edges as Parameters<typeof loadFromNodes>[1],
          )
          selectNode(null)
          setRightPanel(null)
          // Restore nodeStatuses if persisted in afterrun_canvas
          if (canvas.nodeStatuses) {
            useRunOverlayStore.setState({
              activeRunName: runName,
              workflowPhase: (canvas.workflowPhase ?? null) as RunPhase | null,
              nodeStatuses: canvas.nodeStatuses as Record<string, import('../../stores/run-overlay-store').NodeRunStatus>,
            })
          } else {
            setActiveRun(runName)
          }
          showNotification('success', `Restored canvas from run "${runName}"`)
          return
        } catch {
          // afterrun_canvas not found, fall through to localStorage
        }
      }
      // Fallback: localStorage snapshot
      const snap = useSavedWorkflowsStore.getState().runSnapshots[runName]
      if (!snap) return
      const { meta, nodes, edges } = snapshotToRF(snap.snapshot)
      setMeta(meta)
      loadFromNodes(nodes, edges)
      selectNode(null)
      setRightPanel(null)
      setActiveRun(runName)
      showNotification('success', `Restored canvas from run "${runName}"`)
    },
    [loadFromNodes, setMeta, selectNode, setRightPanel, showNotification, setActiveRun],
  )

  const TERMINAL_PHASES = new Set(['Succeeded', 'Failed', 'Error', 'Unknown'])

  const handleDelete = useCallback(
    async (runName: string, e: React.MouseEvent) => {
      e.stopPropagation()
      if (!confirm(`删除 run "${runName}" 的本地运行数据？\nArgo 数据将按保留策略自动清理。`)) return
      try {
        await argoApi.deleteRun(runName, useProjectStore.getState().currentProjectId ?? undefined)
        useSavedWorkflowsStore.getState().deleteRunSnapshot(runName)
        showNotification('success', `Deleted run "${runName}"`)
        queryClient.invalidateQueries({ queryKey: ['runs'] })
      } catch (err) {
        showNotification('error', `Delete failed: ${err instanceof Error ? err.message : String(err)}`)
      }
    },
    [showNotification, queryClient],
  )

  const handleStop = useCallback(
    async (runName: string, e: React.MouseEvent) => {
      e.stopPropagation()
      if (!confirm(`中止并删除 run "${runName}"？`)) return
      try {
        await argoApi.stopRun(runName, useProjectStore.getState().currentProjectId ?? undefined)
        useSavedWorkflowsStore.getState().deleteRunSnapshot(runName)
        showNotification('success', `Stopped run "${runName}"`)
        queryClient.invalidateQueries({ queryKey: ['runs'] })
      } catch (err) {
        showNotification('error', `Stop failed: ${err instanceof Error ? err.message : String(err)}`)
      }
    },
    [showNotification, queryClient],
  )

  if (runs.length === 0) {
    return <p className="px-3 py-4 text-xs text-mf-text-muted text-center">No runs found</p>
  }

  return (
    <div className="divide-y divide-mf-border/50">
      {runs.map((run) => {
        const isLocalOnly = !!runSnapshots[run.name]?.localOnly
        return (
          <div key={run.name} className="group relative">
            <button
              onClick={() => onSelect(run.name)}
              className="w-full px-3 py-2 text-left hover:bg-mf-hover transition-colors flex items-center justify-between gap-2"
            >
              <div className="min-w-0">
                <div className="text-xs font-mono text-mf-text-secondary truncate">{run.name}</div>
                <div className="text-[10px] text-mf-text-muted mt-0.5">
                  {run.started_at?.slice(0, 16).replace('T', ' ')}
                  {!isLocalOnly && ` · ${formatDuration(run.duration_seconds)}`}
                </div>
              </div>
              <div className="flex items-center gap-1 flex-shrink-0">
                <PhaseBadge phase={run.phase} />
                <ChevronRight size={12} className="text-mf-text-muted" />
              </div>
            </button>

            {/* Action buttons — appear on hover */}
            <div className="absolute right-8 top-1/2 -translate-y-1/2 hidden group-hover:flex items-center gap-0.5 bg-mf-card rounded px-0.5 shadow">
              {!isLocalOnly && (
                <button
                  onClick={(e) => handleRestore(run.name, e)}
                  className="p-1 text-blue-400 hover:text-blue-200 hover:bg-mf-hover rounded transition-colors"
                  title="Restore canvas to this run's workflow"
                >
                  <RotateCcw size={11} />
                </button>
              )}
              {!isLocalOnly && !TERMINAL_PHASES.has(run.phase) && (
                <button
                  onClick={(e) => handleStop(run.name, e)}
                  className="p-1 text-orange-400 hover:text-orange-200 hover:bg-mf-hover rounded transition-colors"
                  title="中止运行"
                >
                  <Square size={10} />
                </button>
              )}
              {!isLocalOnly && (
                <button
                  onClick={(e) => handleDelete(run.name, e)}
                  className="p-1 text-mf-text-muted hover:text-red-400 hover:bg-mf-hover rounded transition-colors"
                  title="删除本地运行数据"
                >
                  <Trash2 size={11} />
                </button>
              )}
            </div>
          </div>
        )
      })}
    </div>
  )
}

// ─── Run logs ─────────────────────────────────────────────────────────────────

function RunLogs({ runName }: { runName: string }) {
  const query = useQuery({
    queryKey: ['run-logs', runName],
    queryFn: () => argoApi.getLogs(runName),
    refetchInterval: 5000,
  })

  return (
    <div className="mt-2">
      <div className="flex items-center gap-1 text-[11px] text-mf-text-muted px-1 mb-1">
        <Terminal size={11} />
        Logs
        {query.isLoading && <RefreshCw size={10} className="animate-spin ml-1" />}
      </div>
      <pre className="bg-mf-base border border-mf-border rounded p-2 text-[10px] text-green-300 font-mono max-h-60 overflow-auto mf-scroll whitespace-pre-wrap">
        {query.data?.logs || (query.isLoading ? 'Loading…' : 'No logs')}
      </pre>
    </div>
  )
}

// ─── Validation summary (warnings/infos stored with snapshot) ─────────────────

function ValidationSummary({ runName }: { runName: string }) {
  const snap = useSavedWorkflowsStore.getState().runSnapshots[runName]
  if (!snap) return null

  const warnings = snap.validationWarnings ?? []
  const infos    = snap.validationInfos    ?? []
  if (warnings.length === 0 && infos.length === 0) return null

  return (
    <div className="mt-2">
      <div className="text-[10px] text-mf-text-muted mb-1 uppercase tracking-wide px-1">
        Validation
      </div>
      <div className="bg-mf-card border border-mf-border rounded p-2 space-y-0.5 max-h-32 overflow-y-auto mf-scroll">
        {warnings.map((w, i) => (
          <div key={i} className="flex gap-1.5 text-[11px]">
            <AlertTriangle size={11} className="text-yellow-400 flex-shrink-0 mt-0.5" />
            <span className="text-yellow-300 break-words">
              {w.node_id && <span className="font-mono text-mf-text-muted">[{w.node_id}] </span>}
              {w.message}
            </span>
          </div>
        ))}
        {infos.map((info, i) => (
          <div key={i} className="flex gap-1.5 text-[11px]">
            <Info size={11} className="text-blue-400 flex-shrink-0 mt-0.5" />
            <span className="text-mf-text-secondary break-words">
              {info.node_id && <span className="font-mono text-mf-text-muted">[{info.node_id}] </span>}
              {info.message}
            </span>
          </div>
        ))}
      </div>
    </div>
  )
}

// ─── Run detail — restore button at top ──────────────────────────────────────

function RunDetailHeader({ runName, onBack, isLocalOnly }: { runName: string; onBack: () => void; isLocalOnly?: boolean }) {
  const { loadFromNodes, setMeta } = useWorkflowStore()
  const { showNotification, selectNode, setRightPanel } = useUIStore()
  const { setActiveRun } = useRunOverlayStore()

  const handleRestore = async () => {
    const projectId = useProjectStore.getState().currentProjectId
    // Try afterrun_canvas from backend first
    if (projectId) {
      try {
        const canvas = await argoApi.getAfterrunCanvas(runName, projectId) as {
          meta: Record<string, unknown>
          nodes: Array<Record<string, unknown>>
          edges: Array<Record<string, unknown>>
          nodeStatuses?: Record<string, unknown>
          workflowPhase?: string | null
        }
        setMeta(canvas.meta as Parameters<typeof setMeta>[0])
        loadFromNodes(
          canvas.nodes as Parameters<typeof loadFromNodes>[0],
          canvas.edges as Parameters<typeof loadFromNodes>[1],
        )
        selectNode(null)
        setRightPanel(null)
        // Restore nodeStatuses if persisted in afterrun_canvas
        if (canvas.nodeStatuses) {
          useRunOverlayStore.setState({
            activeRunName: runName,
            workflowPhase: (canvas.workflowPhase ?? null) as RunPhase | null,
            nodeStatuses: canvas.nodeStatuses as Record<string, import('../../stores/run-overlay-store').NodeRunStatus>,
          })
        } else {
          setActiveRun(runName)
        }
        showNotification('success', `Restored canvas from run "${runName}"`)
        return
      } catch {
        // afterrun_canvas not found, fall through to localStorage
      }
    }
    // Fallback: localStorage snapshot
    const snap = useSavedWorkflowsStore.getState().runSnapshots[runName]
    if (!snap) return
    const { meta, nodes, edges } = snapshotToRF(snap.snapshot)
    setMeta(meta)
    loadFromNodes(nodes, edges)
    selectNode(null)
    setRightPanel(null)
    setActiveRun(runName)
    showNotification('success', `Restored canvas from run "${runName}"`)
  }

  return (
    <div className="flex items-center justify-between px-3 py-1.5 border-b border-mf-border">
      <button
        onClick={onBack}
        className="text-xs text-mf-text-muted hover:text-mf-text-primary flex items-center gap-1"
      >
        ← Back
      </button>
      {!isLocalOnly && (
        <button
          onClick={handleRestore}
          className="flex items-center gap-1 px-2 py-0.5 text-[11px] text-blue-400 hover:text-blue-200 hover:bg-mf-hover rounded transition-colors"
          title="Restore canvas to this workflow"
        >
          <RotateCcw size={11} />
          Restore Canvas
        </button>
      )}
    </div>
  )
}

// ─── Runs Panel ───────────────────────────────────────────────────────────────

export function RunsPanel() {
  const [selectedRun, setSelectedRun] = useState<string | null>(null)
  const { pendingRunName, setPendingRunName } = useUIStore()
  const { runSnapshots } = useSavedWorkflowsStore()

  // Auto-open the detail view when TopBar submits a new run
  useEffect(() => {
    if (!pendingRunName) return
    setSelectedRun(pendingRunName)
    setPendingRunName(null)
  }, [pendingRunName, setPendingRunName])

  const listQuery = useQuery({
    queryKey: ['runs'],
    queryFn: () => argoApi.listRuns(useProjectStore.getState().currentProjectId ?? undefined),
    refetchInterval: 10000,
  })

  // Check if selected run is a local-only snapshot
  const selectedIsLocalOnly = selectedRun ? !!runSnapshots[selectedRun]?.localOnly : false

  const detailQuery = useQuery({
    queryKey: ['run-detail', selectedRun],
    queryFn: () => (selectedRun ? argoApi.getRun(selectedRun) : null),
    enabled: !!selectedRun && !selectedIsLocalOnly,
    refetchInterval: 5000,
  })

  // Merge local-only snapshots into the run list
  const localRuns: RunSummaryResponse[] = Object.values(runSnapshots)
    .filter((s) => s.localOnly)
    .map((s) => ({
      name: s.runName,
      namespace: '',
      phase: 'Failed' as RunPhase,
      started_at: s.savedAt,
      finished_at: s.savedAt,
    }))

  const apiRuns = listQuery.data?.runs ?? []
  // Deduplicate: if a local run name also appears in api runs, prefer api version
  const apiRunNames = new Set(apiRuns.map((r) => r.name))
  const mergedRuns = [
    ...localRuns.filter((r) => !apiRunNames.has(r.name)),
    ...apiRuns,
  ].sort((a, b) => (b.started_at ?? '').localeCompare(a.started_at ?? ''))

  return (
    <div className="w-80 mf-panel border-l border-r-0 flex-shrink-0">
      <div className="flex items-center justify-between px-3 py-2 border-b border-mf-border">
        <span className="text-xs font-semibold text-mf-text-secondary uppercase tracking-wide">
          History {listQuery.data ? `(${listQuery.data.total + localRuns.length})` : `(${localRuns.length})`}
        </span>
        <button
          onClick={() => listQuery.refetch()}
          className="text-mf-text-muted hover:text-mf-text-primary"
          title="Refresh"
        >
          <RefreshCw size={12} className={listQuery.isFetching ? 'animate-spin' : ''} />
        </button>
      </div>

      <div className="flex-1 overflow-y-auto mf-scroll">
        {selectedRun ? (
          <div>
            <RunDetailHeader
              runName={selectedRun}
              onBack={() => setSelectedRun(null)}
              isLocalOnly={selectedIsLocalOnly}
            />

            {/* Local-only run detail */}
            {selectedIsLocalOnly && runSnapshots[selectedRun] && (
              <div className="px-3 pb-3 space-y-2 pt-2">
                <div>
                  <div className="text-xs font-mono text-mf-text-secondary break-all">{selectedRun}</div>
                  <PhaseBadge phase={'Failed' as RunPhase} />
                </div>

                <div className="text-[10px] text-mf-text-muted">
                  {runSnapshots[selectedRun].savedAt.slice(0, 16).replace('T', ' ')}
                </div>

                {runSnapshots[selectedRun].error && (
                  <div className="mt-2">
                    <div className="text-[10px] text-red-400 mb-1 uppercase tracking-wide px-1">
                      Error
                    </div>
                    <pre className="bg-mf-base border border-red-500/30 rounded p-2 text-[11px] text-red-300 font-mono max-h-60 overflow-auto mf-scroll whitespace-pre-wrap select-text">
                      {runSnapshots[selectedRun].error}
                    </pre>
                  </div>
                )}

                <ValidationSummary runName={selectedRun} />
              </div>
            )}

            {/* Argo run detail */}
            {!selectedIsLocalOnly && detailQuery.data && (
              <div className="px-3 pb-3 space-y-2 pt-2">
                <div>
                  <div className="text-xs font-mono text-mf-text-secondary break-all">{detailQuery.data.name}</div>
                  <PhaseBadge phase={detailQuery.data.phase} />
                </div>

                {getStatusMessage(detailQuery.data) && (
                  <p className="text-xs text-mf-text-muted">{getStatusMessage(detailQuery.data)}</p>
                )}

                {(() => {
                  const steps = parseSteps(detailQuery.data)
                  if (steps.length === 0) return null
                  return <StepsDisplay steps={steps} />
                })()}

                <ValidationSummary runName={selectedRun} />
                <RunLogs runName={selectedRun} />
              </div>
            )}
          </div>
        ) : (
          <RunList
            runs={mergedRuns}
            onSelect={setSelectedRun}
          />
        )}
      </div>
    </div>
  )
}
