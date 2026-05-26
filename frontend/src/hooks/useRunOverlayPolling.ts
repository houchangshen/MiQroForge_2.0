import { useRef, useEffect } from 'react'
import { useQuery } from '@tanstack/react-query'
import { argoApi } from '../api/argo-api'
import { useRunOverlayStore } from '../stores/run-overlay-store'
import { useProjectStore } from '../stores/project-store'
import { useWorkflowStore } from '../stores/workflow-store'

const TERMINAL = new Set(['Succeeded', 'Failed', 'Error', 'PartialSuccess'])

/**
 * Polls the Argo API for the active run and updates the run overlay store.
 * Must be mounted at the App level so polling persists across panel changes.
 *
 * On reaching a terminal state, saves output parameters to runs/{name}/outputs.json
 * via the backend save-outputs endpoint (fire-and-forget), along with the current
 * canvas state (afterrun_canvas.json).
 */
export function useRunOverlayPolling() {
  const activeRunName = useRunOverlayStore((s) => s.activeRunName)
  const updateFromArgo = useRunOverlayStore((s) => s.updateFromArgo)
  // Persist saved run names to sessionStorage so restores don't re-trigger saveOutputs
  const savedRuns = useRef<Set<string>>(loadSavedRunsFromStorage())
  // Track whether the polling query itself was the one that triggered save
  const saveTriggeredByPolling = useRef(false)

  useEffect(() => {
    // When activeRunName changes to a new run, reset the flag
    saveTriggeredByPolling.current = false
  }, [activeRunName])

  useQuery({
    queryKey: ['run-overlay', activeRunName],
    queryFn: async () => {
      const detail = await argoApi.getRun(activeRunName!)
      updateFromArgo(detail.raw)

      // Save outputs + canvas to runs/ when run first reaches a terminal state
      if (TERMINAL.has(detail.phase) && !savedRuns.current.has(activeRunName!)) {
        const projectId = useProjectStore.getState().currentProjectId ?? undefined
        const { meta, nodes, edges } = useWorkflowStore.getState()
        const { nodeStatuses, workflowPhase } = useRunOverlayStore.getState()
        const canvas = { meta, nodes, edges, nodeStatuses, workflowPhase }
        argoApi.saveOutputs(activeRunName!, projectId, canvas).then((result) => {
          // Update nodeStatuses with full error text from outputs.json
          if (result.error_texts) {
            const current = useRunOverlayStore.getState().nodeStatuses
            let changed = false
            const merged = { ...current }
            for (const [canvasId, errorText] of Object.entries(result.error_texts)) {
              if (merged[canvasId] && merged[canvasId].error !== errorText) {
                merged[canvasId] = { ...merged[canvasId], error: errorText }
                changed = true
              }
            }
            if (changed) {
              useRunOverlayStore.setState({ nodeStatuses: merged })
              // Re-save afterrun_canvas with updated error text
              const updatedCanvas = {
                ...canvas,
                nodeStatuses: useRunOverlayStore.getState().nodeStatuses,
              }
              argoApi.saveOutputs(activeRunName!, projectId, updatedCanvas).catch(() => {})
            }
          }
          // Persist that we saved this run so restores don't duplicate
          savedRuns.current.add(activeRunName!)
          saveSavedRunsToStorage(savedRuns.current)
          saveTriggeredByPolling.current = true
          // ── Apply nodegen_updates to live workflow canvas ──
          const updates = (result as Record<string, unknown>).nodegen_updates as
            | Record<string, Record<string, unknown>>
            | undefined
          if (updates && Object.keys(updates).length > 0) {
            const wfStore = useWorkflowStore.getState()
            const currentNodes = wfStore.nodes
            const currentEdges = [...wfStore.edges]
            let nodesChanged = false
            let edgesChanged = false
            for (const [canvasId, nodeData] of Object.entries(updates)) {
              const idx = currentNodes.findIndex((n) => n.id === canvasId)
              if (idx < 0) continue
              const existing = currentNodes[idx].data as Record<string, unknown>
              const existingNg = (existing.node_generator ?? {}) as Record<string, unknown>
              // Merge display fields + update node_generator.result
              const merged: Record<string, unknown> = {
                ...existing,
                display_name: nodeData.display_name ?? existing.display_name,
                name: nodeData.name ?? existing.name,
                version: nodeData.version ?? existing.version,
                description: nodeData.description ?? existing.description,
                node_type: nodeData.node_type ?? existing.node_type,
                category: nodeData.category ?? existing.category,
                software: nodeData.software ?? existing.software,
                stream_inputs: nodeData.stream_inputs ?? existing.stream_inputs,
                stream_outputs: nodeData.stream_outputs ?? existing.stream_outputs,
                onboard_inputs: nodeData.onboard_inputs ?? existing.onboard_inputs,
                onboard_outputs: nodeData.onboard_outputs ?? existing.onboard_outputs,
                resources: nodeData.resources ?? existing.resources,
                nodespec_path: nodeData.nodespec_path ?? existing.nodespec_path,
                ports: nodeData.stream_inputs != null || nodeData.stream_outputs != null
                  ? existing.ports  // keep original ports; stream_io now provides named ports
                  : existing.ports,
                node_generator: {
                  ...existingNg,
                  result: {
                    node_name: nodeData.node_name ?? (existingNg.result as Record<string,unknown> | undefined)?.node_name ?? '',
                    nodespec_yaml: nodeData.nodespec_yaml ?? (existingNg.result as Record<string,unknown> | undefined)?.nodespec_yaml ?? '',
                    run_sh: nodeData.run_sh ?? (existingNg.result as Record<string,unknown> | undefined)?.run_sh ?? '',
                    input_templates: (existingNg.result as Record<string,unknown> | undefined)?.input_templates ?? {},
                    evaluation: (existingNg.result as Record<string,unknown> | undefined)?.evaluation,
                  },
                },
              }
              currentNodes[idx] = { ...currentNodes[idx], data: merged as never }
              nodesChanged = true

              // ── Remap edge handles using port_map (Agent may have renamed ports) ──
              const portMap = nodeData._port_map as Record<string, Record<string, string>> | undefined
              if (portMap) {
                const inputMap = portMap.inputs ?? {}
                const outputMap = portMap.outputs ?? {}
                for (const edge of currentEdges) {
                  if (edge.source === canvasId && edge.sourceHandle && outputMap[edge.sourceHandle]) {
                    edge.sourceHandle = outputMap[edge.sourceHandle]
                    edgesChanged = true
                  }
                  if (edge.target === canvasId && edge.targetHandle && inputMap[edge.targetHandle]) {
                    edge.targetHandle = inputMap[edge.targetHandle]
                    edgesChanged = true
                  }
                }
              }

              // ── Inject sandbox output values into nodeStatuses ──
              const outputValues = nodeData._output_values as Record<string, string> | undefined
              if (outputValues && Object.keys(outputValues).length > 0) {
                const { nodeStatuses } = useRunOverlayStore.getState()
                const existing = nodeStatuses[canvasId] ?? { phase: 'Succeeded' as const, outputs: {} }
                const mergedOutputs = { ...(existing.outputs ?? {}), ...outputValues }
                useRunOverlayStore.setState({
                  nodeStatuses: {
                    ...nodeStatuses,
                    [canvasId]: { ...existing, outputs: mergedOutputs },
                  },
                })
              }
            }
            if (nodesChanged) {
              useWorkflowStore.setState({ nodes: currentNodes })
            }
            if (edgesChanged) {
              useWorkflowStore.setState({ edges: currentEdges })
            }
          }
        }).catch(() => {})
      }

      return detail
    },
    enabled: !!activeRunName,
    refetchInterval: (query) => {
      const phase = query.state.data?.phase
      if (phase && TERMINAL.has(phase)) return false
      return 3000   // poll every 3 s while running
    },
  })
}

// ── sessionStorage dedup helpers ─────────────────────────────────────────────
const SAVED_RUNS_KEY = 'mf2:saved-runs'

function loadSavedRunsFromStorage(): Set<string> {
  try {
    const raw = sessionStorage.getItem(SAVED_RUNS_KEY)
    return new Set(raw ? JSON.parse(raw) : [])
  } catch {
    return new Set()
  }
}

function saveSavedRunsToStorage(runs: Set<string>) {
  try {
    sessionStorage.setItem(SAVED_RUNS_KEY, JSON.stringify([...runs]))
  } catch {
    // ignore quota errors
  }
}
