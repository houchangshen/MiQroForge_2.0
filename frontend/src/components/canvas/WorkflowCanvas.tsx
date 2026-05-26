import React, { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import {
  ReactFlow,
  Background,
  Controls,
  MiniMap,
  BackgroundVariant,
  useReactFlow,
  type Node as RFNode,
  type NodeTypes,
  type EdgeTypes,
  type Edge,
  type Connection,
} from '@xyflow/react'
import '@xyflow/react/dist/style.css'

import { MFNode } from './MFNode'
import type { MFNodeType } from './MFNode'
import { MFEdge, SemanticEdgeComponent } from './MFEdge'
import { useWorkflowStore, type MFNodeData, selectCanUndo, selectCanRedo } from '../../stores/workflow-store'
import { useUIStore } from '../../stores/ui-store'
import { useConnectionValidator } from '../../hooks/useConnectionValidator'
import { nodesApi } from '../../api/nodes-api'
import { agentsApi } from '../../api/agents-api'
import { buildNodeData } from '../../lib/node-utils'
import { semanticLabel } from '../../lib/semantic-labels'
import type { PickerOption } from '../../lib/semantic-labels'
import { useSettingsStore, getColorMode, getMinimapMaskColor } from '../../stores/settings-store'
import { useShortcutsStore, keyMatch, displayKey } from '../../stores/shortcuts-store'

const NODE_TYPES: NodeTypes = { mfNode: MFNode as NodeTypes[string] }
const EDGE_TYPES: EdgeTypes = { mfEdge: MFEdge, semanticEdge: SemanticEdgeComponent }

// ─── Context menu state ───────────────────────────────────────────────────────

interface ContextMenu {
  nodeId: string
  x: number
  y: number
}

// ─── WorkflowCanvas ───────────────────────────────────────────────────────────

export function WorkflowCanvas() {
  const {
    nodes, edges,
    onNodesChange, onEdgesChange, onConnect, addNode, removeNode,
    updateNodeWithHistory, undoNode, redoNode,
    nodeHistory,
  } = useWorkflowStore()
  const deleteEdge = useCallback(
    (edgeId: string) => onEdgesChange([{ id: edgeId, type: 'remove' }]),
    [onEdgesChange],
  )
  const { selectNode, showNotification } = useUIStore()
  const _projectId = useWorkflowStore((s) => s._projectId); void _projectId
  const { isValidConnection: checkConnection } = useConnectionValidator()
  const { fitView } = useReactFlow()
  const theme = useSettingsStore((s) => s.theme)
  const reactFlowWrapper = useRef<HTMLDivElement>(null)
  const [contextMenu, setContextMenu] = useState<ContextMenu | null>(null)

  // Node selection
  const onNodeClick = useCallback(
    (_: React.MouseEvent, node: RFNode) => {
      selectNode(node.id)
      setContextMenu(null)
    },
    [selectNode],
  )
  const onPaneClick = useCallback(() => {
    selectNode(null)
    setContextMenu(null)
  }, [selectNode])

  // Edge deletion: double-click on edge deletes it
  const onEdgeDoubleClick = useCallback(
    (_: React.MouseEvent, edge: Edge) => {
      deleteEdge(edge.id)
    },
    [deleteEdge],
  )

  // Handle × button click on edge (via event delegation on canvas wrapper)
  const handleCanvasClick = useCallback(
    (e: React.MouseEvent) => {
      const target = e.target as HTMLElement
      const btn = target.closest('[data-edge-id]') as HTMLElement | null
      if (btn) {
        e.stopPropagation()
        deleteEdge(btn.dataset.edgeId!)
      }
    },
    [deleteEdge],
  )

  // Right-click context menu on a node
  const onNodeContextMenu = useCallback(
    (event: React.MouseEvent, node: RFNode) => {
      event.preventDefault()
      const wrapper = reactFlowWrapper.current
      if (!wrapper) return
      const rect = wrapper.getBoundingClientRect()
      setContextMenu({
        nodeId: node.id,
        x: event.clientX - rect.left,
        y: event.clientY - rect.top,
      })
    },
    [],
  )

  const handleDeleteFromMenu = useCallback(() => {
    if (!contextMenu) return
    removeNode(contextMenu.nodeId)
    selectNode(null)
    setContextMenu(null)
  }, [contextMenu, removeNode, selectNode])

  const handleSaveNodeToLibrary = useCallback(async () => {
    if (!contextMenu) return
    const node = nodes.find((n) => n.id === contextMenu.nodeId)
    const gen = (node?.data as MFNodeData | undefined)?.node_generator
    const result = gen?.result as Record<string, unknown> | undefined
    if (!result?.nodespec_yaml || !result?.node_name) {
      showNotification('error', 'No generated node files to save')
      setContextMenu(null)
      return
    }
    try {
      const acceptResult = await agentsApi.acceptNode({
        node_name: result.node_name as string,
        nodespec_yaml: result.nodespec_yaml as string,
        run_sh: (result.run_sh as string) || undefined,
        input_templates: (result.input_templates as Record<string, string>) || {},
        category: 'chemistry',
      })
      showNotification('success',
        acceptResult.collision_renamed
          ? `Saved as ${acceptResult.node_name}`
          : `Saved ${acceptResult.node_name} to library`
      )
    } catch (err: unknown) {
      showNotification('error', err instanceof Error ? err.message : 'Save failed')
    }
    setContextMenu(null)
  }, [contextMenu, nodes, showNotification])

  // ── Create a brand-new resolved node at a canvas position (direct drag) ──

  const createNodeAtPosition = useCallback(
    async (nodeName: string, position: { x: number; y: number }) => {
      let detail: Awaited<ReturnType<typeof nodesApi.get>>
      try {
        detail = await nodesApi.get(nodeName)
      } catch {
        console.error('Failed to load node:', nodeName)
        return
      }
      const newNode: MFNodeType = {
        id: `${nodeName}-${Date.now()}`,
        type: 'mfNode',
        position,
        data: buildNodeData(detail) as MFNodeData,
      }
      addNode(newNode as RFNode<MFNodeData>)
      selectNode(newNode.id)
    },
    [addNode, selectNode],
  )

  // ── Resolve a pending node in-place (preserves ID → enables history) ──────

  const resolveNodeInPlace = useCallback(
    async (nodeId: string, nodeName: string) => {
      let detail: Awaited<ReturnType<typeof nodesApi.get>>
      try {
        detail = await nodesApi.get(nodeName)
      } catch {
        console.error('Failed to load node:', nodeName)
        return
      }
      updateNodeWithHistory(nodeId, buildNodeData(detail) as MFNodeData)
      selectNode(nodeId)
    },
    [updateNodeWithHistory, selectNode],
  )

  // ── Create a pending node (semantic type, multiple implementations) ───────

  const createPendingNode = useCallback(
    (stType: string, options: PickerOption[], position: { x: number; y: number }) => {
      const nodeId = `pending-${stType}-${Date.now()}`
      const label = semanticLabel(stType)

      // handleSelect is stable: captures nodeId (fixed string) and resolveNodeInPlace
      // When undo restores the pending state the same callback is still valid.
      const handleSelect = async (nodeName: string) => {
        await resolveNodeInPlace(nodeId, nodeName)
      }

      const pendingNode: RFNode<MFNodeData> = {
        id: nodeId,
        type: 'mfNode',
        position,
        data: {
          name: '',
          version: '',
          display_name: label,
          description: '',
          node_type: 'pending',
          category: 'pending',
          nodespec_path: '',
          stream_inputs: [],
          stream_outputs: [],
          onboard_inputs: [],
          onboard_params: {},
          pending: true,
          pending_semantic_type: stType,
          pending_implementations: options,
          pending_on_select: handleSelect,
        } as unknown as MFNodeData,
      }

      addNode(pendingNode)
      selectNode(nodeId)
    },
    [addNode, selectNode, resolveNodeInPlace],
  )

  // ── Drag-and-drop from palette ────────────────────────────────────────────

  const onDragOver = useCallback((event: React.DragEvent) => {
    event.preventDefault()
    event.dataTransfer.dropEffect = 'copy'
  }, [])

  const onDrop = useCallback(
    async (event: React.DragEvent) => {
      event.preventDefault()

      const wrapper = reactFlowWrapper.current
      if (!wrapper) return
      const rect = wrapper.getBoundingClientRect()
      const dropPosition = {
        x: event.clientX - rect.left - 110,
        y: event.clientY - rect.top - 60,
      }

      // Protocol 1: direct node name (SoftwareRow drag)
      const nodeName = event.dataTransfer.getData('application/mf-node-name')
      if (nodeName) {
        await createNodeAtPosition(nodeName, dropPosition)
        return
      }

      // Protocol 3: ephemeral node drag
      const isEphemeral = event.dataTransfer.getData('application/mf-ephemeral')
      if (isEphemeral) {
        const ephemeralNode: RFNode<MFNodeData> = {
          id: `ephemeral-${Date.now()}`,
          type: 'mfNode',
          position: dropPosition,
          data: {
            name: 'ephemeral-node',
            version: '\u2014',
            display_name: 'Ephemeral Node',
            description: '',
            node_type: 'lightweight',
            category: 'ephemeral',
            nodespec_path: '',
            stream_inputs: [],
            stream_outputs: [],
            onboard_inputs: [],
            onboard_outputs: [],
            onboard_params: {},
            ephemeral: true,
            ephemeral_description: '',
            ports: {
              inputs: [{ name: 'I1', type: 'software_data_package' }],
              outputs: [{ name: 'O1', type: 'software_data_package' }],
            },
          } as unknown as MFNodeData,
        }
        addNode(ephemeralNode)
        selectNode(ephemeralNode.id)
        return
      }

      // Protocol 4: node generator drag
      const isNodeGen = event.dataTransfer.getData('application/mf-node-gen')
      if (isNodeGen) {
        const genNode: RFNode<MFNodeData> = {
          id: `nodegen-${Date.now()}`,
          type: 'mfNode',
          position: dropPosition,
          data: {
            name: 'node-generator',
            version: '\u2014',
            display_name: 'Generate Node',
            description: '',
            node_type: 'lightweight',
            category: 'node_generator',
            nodespec_path: '',
            stream_inputs: [],
            stream_outputs: [],
            onboard_inputs: [],
            onboard_outputs: [],
            onboard_params: {},
            node_generator: { generating: false },
            ports: { inputs: [], outputs: [] },
          } as unknown as MFNodeData,
        }
        addNode(genNode)
        selectNode(genNode.id)
        return
      }

      // Protocol 2: semantic type card drag
      const semanticType = event.dataTransfer.getData('application/mf-semantic-type')
      const implJson = event.dataTransfer.getData('application/mf-node-implementations')
      if (!semanticType || !implJson) return

      let options: PickerOption[]
      try {
        options = JSON.parse(implJson) as PickerOption[]
      } catch {
        console.error('Failed to parse implementations JSON')
        return
      }

      if (options.length === 1) {
        await createNodeAtPosition(options[0].nodeName, dropPosition)
      } else {
        createPendingNode(semanticType, options, dropPosition)
      }
    },
    [createNodeAtPosition, createPendingNode],
  )

  // ── A / D keyboard shortcuts — undo / redo implementation for selected ────

  useEffect(() => {
    const handleKeyDown = (e: KeyboardEvent) => {
      // Do not fire while user is typing in any input / contenteditable
      const target = e.target as HTMLElement
      if (
        target.tagName === 'INPUT' ||
        target.tagName === 'TEXTAREA' ||
        target.isContentEditable
      ) return

      const bindings = useShortcutsStore.getState().bindings

      if (keyMatch(e, bindings.fitView)) {
        e.preventDefault()
        fitView({ padding: 0.2, duration: 300 })
        return
      }

      if (keyMatch(e, bindings.nodeUndo)) {
        const selectedNodes = useWorkflowStore.getState().nodes.filter((n) => n.selected)
        const eligible = selectedNodes.filter((n) => selectCanUndo(n.id))
        if (eligible.length === 0) return
        e.preventDefault()
        eligible.forEach((n) => undoNode(n.id))
      } else if (keyMatch(e, bindings.nodeRedo)) {
        const selectedNodes = useWorkflowStore.getState().nodes.filter((n) => n.selected)
        const eligible = selectedNodes.filter((n) => selectCanRedo(n.id))
        if (eligible.length === 0) return
        e.preventDefault()
        eligible.forEach((n) => redoNode(n.id))
      }
    }

    window.addEventListener('keydown', handleKeyDown)
    return () => window.removeEventListener('keydown', handleKeyDown)
  }, [fitView, undoNode, redoNode])

  // ── Connection validator ──────────────────────────────────────────────────

  const isValidConnection = useCallback(
    (edgeOrConn: Edge | Connection) => {
      return checkConnection({
        source: edgeOrConn.source,
        sourceHandle: edgeOrConn.sourceHandle ?? null,
        target: edgeOrConn.target,
        targetHandle: edgeOrConn.targetHandle ?? null,
      })
    },
    [checkConnection],
  )

  // MiniMap node coloring
  const minimapNodeColor = useCallback((node: RFNode) => {
    const data = node.data as MFNodeData
    if (data?.pending) return '#92400e'
    const cat = data?.category ?? ''
    if (cat.includes('chem')) return '#3b82f6'
    if (cat.includes('quantum')) return '#a855f7'
    return '#374151'
  }, [])

  const defaultEdgeOptions = useMemo(() => ({ type: 'mfEdge' }), [])

  // ── Context menu: derive undo/redo availability ───────────────────────────

  const ctxCanUndo = contextMenu ? selectCanUndo(contextMenu.nodeId) : false
  const ctxCanRedo = contextMenu ? selectCanRedo(contextMenu.nodeId) : false
  const ctxNode = contextMenu ? nodes.find((n) => n.id === contextMenu.nodeId) : undefined
  const ctxHasNodeFiles = !!(ctxNode?.data as MFNodeData | undefined)?.node_generator?.result?.nodespec_yaml
  // Re-derive when nodeHistory changes so the menu updates live
  void nodeHistory  // subscribe to store slice

  // Shortcut labels for context menu (reactive — user may have rebound them)
  const undoLabel = displayKey(useShortcutsStore.getState().bindings.nodeUndo)
  const redoLabel = displayKey(useShortcutsStore.getState().bindings.nodeRedo)

  return (
    <div ref={reactFlowWrapper} className="flex-1 h-full relative" onClick={handleCanvasClick}>
      <ReactFlow
        nodes={nodes}
        edges={edges}
        onNodesChange={onNodesChange}
        onEdgesChange={onEdgesChange}
        onConnect={onConnect}
        onNodeClick={onNodeClick}
        onEdgeDoubleClick={onEdgeDoubleClick}
        onPaneClick={onPaneClick}
        onNodeContextMenu={onNodeContextMenu}
        onDragOver={onDragOver}
        onDrop={onDrop}
        nodeTypes={NODE_TYPES}
        edgeTypes={EDGE_TYPES}
        defaultEdgeOptions={defaultEdgeOptions}
        isValidConnection={isValidConnection}
        fitView
        fitViewOptions={{ padding: 0.2 }}
        minZoom={0.2}
        maxZoom={2}
        deleteKeyCode="Delete"
        multiSelectionKeyCode="Shift"
        selectionOnDrag
        panOnDrag={[1, 2]}
        panActivationKeyCode={null}
        colorMode={getColorMode(theme)}
      >
        <Background
          variant={BackgroundVariant.Dots}
          gap={20}
          size={1}
          color="rgb(var(--mf-border))"
        />
        <Controls />
        <MiniMap
          nodeColor={minimapNodeColor}
          maskColor={getMinimapMaskColor(theme)}
        />
      </ReactFlow>

      {/* Right-click context menu */}
      {contextMenu && (
        <div
          className="absolute z-50 bg-mf-card border border-mf-border rounded shadow-lg py-1 min-w-[160px]"
          style={{ left: contextMenu.x, top: contextMenu.y }}
        >
          {/* Undo / redo rows — only shown when meaningful */}
          {ctxCanUndo && (
            <button
              className="w-full text-left px-3 py-1.5 text-xs text-mf-text-secondary hover:bg-mf-hover hover:text-mf-text-primary transition-colors flex items-center justify-between"
              onClick={() => { undoNode(contextMenu.nodeId); setContextMenu(null) }}
            >
              <span>↩ Go back</span>
              <kbd className="text-[10px] text-mf-text-muted font-mono ml-3">{undoLabel}</kbd>
            </button>
          )}
          {ctxCanRedo && (
            <button
              className="w-full text-left px-3 py-1.5 text-xs text-mf-text-secondary hover:bg-mf-hover hover:text-mf-text-primary transition-colors flex items-center justify-between"
              onClick={() => { redoNode(contextMenu.nodeId); setContextMenu(null) }}
            >
              <span>↪ Go forward</span>
              <kbd className="text-[10px] text-mf-text-muted font-mono ml-3">{redoLabel}</kbd>
            </button>
          )}
          {(ctxCanUndo || ctxCanRedo) && (
            <div className="border-t border-mf-border/60 my-0.5" />
          )}

          {ctxHasNodeFiles && (
            <>
              <button
                className="w-full text-left px-3 py-1.5 text-xs text-green-400 hover:bg-mf-hover hover:text-green-300 transition-colors"
                onClick={handleSaveNodeToLibrary}
              >
                💾 Save node to library
              </button>
              <div className="border-t border-mf-border/60 my-0.5" />
            </>
          )}
          <button
            className="w-full text-left px-3 py-1.5 text-xs text-red-400 hover:bg-mf-hover hover:text-red-300 transition-colors"
            onClick={handleDeleteFromMenu}
          >
            🗑 Delete node
          </button>
          <button
            className="w-full text-left px-3 py-1.5 text-xs text-mf-text-muted hover:bg-mf-hover hover:text-mf-text-secondary transition-colors"
            onClick={() => setContextMenu(null)}
          >
            Cancel
          </button>
        </div>
      )}
    </div>
  )
}
