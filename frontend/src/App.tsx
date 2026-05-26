import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { ReactFlowProvider } from '@xyflow/react'
import { BrowserRouter, Routes, Route, Navigate, useParams } from 'react-router-dom'
import { useEffect } from 'react'

import { isAuthenticated } from './lib/auth'
import { LoginPage } from './pages/LoginPage'
import { TopBar, StatusBar } from './components/layout/TopBar'
import { NodePalette } from './components/palette/NodePalette'
import { WorkflowsSidebar } from './components/palette/WorkflowsSidebar'
import { WorkflowCanvas } from './components/canvas/WorkflowCanvas'
import { NodeInspector } from './components/inspector/NodeInspector'
import { RunsPanel } from './components/runs/RunsPanel'
import { FilesPanel } from './components/files/FilesPanel'

import { UnitsPage } from './components/docs/UnitsPage'
import { SharedParamsPage } from './components/docs/SharedParamsPage'
import { ChatPanel } from './components/chat/ChatPanel'
import { ProjectGallery } from './pages/ProjectGallery'
import { NodeRepository } from './pages/NodeRepository'
import { NodeFilesPage } from './pages/NodeFilesPage'
import { MemoryManager } from './pages/MemoryManager'
import { AdminUsagePage } from './pages/AdminUsagePage'
import { useUIStore } from './stores/ui-store'
import { useRunOverlayStore } from './stores/run-overlay-store'
import { useAgentStore } from './stores/agent-store'
import { setSavedWorkflowsProjectId } from './stores/saved-workflows-store'
import { useProjectStore } from './stores/project-store'
import { useWorkflowStore } from './stores/workflow-store'
import { nodesApi } from './api/nodes-api'
import { setSemanticRegistry } from './lib/semantic-labels'
import { loadGlobalPrefs, setPreferenceProjectId } from './lib/node-preferences'
import { useRunOverlayPolling } from './hooks/useRunOverlayPolling'
import { useGlobalShortcuts } from './hooks/useGlobalShortcuts'

// Import settings store to trigger initial theme/font-size application
import './stores/settings-store'

const queryClient = new QueryClient({
  defaultOptions: {
    queries: {
      retry: 1,
      refetchOnWindowFocus: false,
    },
  },
})

// ─── Main canvas layout ─────────────────────────────────────────────────────

function CanvasLayout() {
  const { projectId } = useParams<{ projectId: string }>()
  const rightPanel      = useUIStore((s) => s.rightPanel)
  const paletteCollapsed = useUIStore((s) => s.paletteCollapsed)
  const filesOpen       = useUIStore((s) => s.filesOpen)
  const selectedNodeId  = useUIStore((s) => s.selectedNodeId)
  const chatOpen        = useAgentStore((s) => s.isOpen)

  const loadProject = useProjectStore((s) => s.loadProject)
  const clearProject = useProjectStore((s) => s.clearProject)
  const clearOverlay = useRunOverlayStore((s) => s.clearOverlay)
  const loadFromNodes = useWorkflowStore((s) => s.loadFromNodes)

  // Mount run overlay polling at app level (persists across panel changes)
  useRunOverlayPolling()
  // Mount global keyboard shortcuts
  useGlobalShortcuts()

  // Load project and canvas data when projectId changes
  useEffect(() => {
    if (!projectId) return

    let cancelled = false
    // Clear stale run overlay from previous project before loading new one
    clearOverlay()
    setSavedWorkflowsProjectId(projectId)
    useWorkflowStore.getState().setProjectId(projectId)
    setPreferenceProjectId(projectId)
    ;(async () => {
      await loadProject(projectId)
      if (cancelled) return
      try {
        const canvas = await useProjectStore.getState().loadCanvas()
        if (cancelled) return
        if (!canvas || ((!canvas.nodes || canvas.nodes.length === 0) && (!canvas.edges || canvas.edges.length === 0))) {
          // Empty project — clear canvas to prevent stale localStorage bleed-through
          useWorkflowStore.getState().clearCanvas()
          return
        }
        const nodes = canvas.nodes as Parameters<typeof loadFromNodes>[0]
        const edges = canvas.edges as Parameters<typeof loadFromNodes>[1]
        if (nodes.length > 0 || edges.length > 0) {
          loadFromNodes(nodes, edges)
          if (canvas.meta && typeof canvas.meta === 'object') {
            useWorkflowStore.getState().setMeta(canvas.meta as unknown as import('./types/workflow').WorkflowMeta)
          }
        }
      } catch { /* empty project, no canvas yet */ }
    })()

    return () => {
      cancelled = true
      // Save canvas on unmount
      useProjectStore.getState().saveCanvas().catch(() => {})
      clearProject()
      clearOverlay()
      setSavedWorkflowsProjectId(null)
      useWorkflowStore.getState().setProjectId(null)
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [projectId])

  return (
    <div className="flex flex-col h-screen bg-mf-base overflow-hidden">
      <TopBar />

      <div className="flex flex-1 min-h-0 overflow-hidden">

        {/* Far left: Files panel (toggled, narrow) */}
        {filesOpen && <FilesPanel />}

        {/* Left column: Node palette + Saved workflows */}
        <div
          className="flex-shrink-0 flex flex-col border-r border-mf-border bg-mf-panel overflow-hidden"
          style={{ width: paletteCollapsed ? 32 : 256 }}
        >
          <div className="flex-1 min-h-0">
            <NodePalette />
          </div>
          {!paletteCollapsed && <WorkflowsSidebar />}
        </div>

        {/* Center: Canvas */}
        <WorkflowCanvas />

        {/* Right: Inspector (always when node selected) */}
        {selectedNodeId && <NodeInspector />}

        {/* Right: Context panel (history) */}
        {rightPanel === 'runs'      && <RunsPanel />}

        {/* Far right: Chat panel (AI Assistant) */}
        {chatOpen && <ChatPanel />}
      </div>

      <StatusBar />
    </div>
  )
}

// ─── Protected Route wrapper ──────────────────────────────────────────────────

function ProtectedRoute({ children }: { children: React.ReactNode }) {
  if (!isAuthenticated()) {
    return <Navigate to="/login" replace />
  }
  return <>{children}</>
}

// ─── App root ─────────────────────────────────────────────────────────────────

function AppRoutes() {
  // Load semantic registry + global prefs once at app startup (all routes)
  useEffect(() => {
    nodesApi.semanticRegistry()
      .then((data) => setSemanticRegistry(data.types))
      .catch(() => { /* silently fall back to hardcoded labels */ })
    loadGlobalPrefs()
  }, [])

  return (
    <Routes>
      <Route path="/login" element={<LoginPage />} />
      <Route path="/" element={
        <ProtectedRoute><ProjectGallery /></ProtectedRoute>
      } />
      <Route path="/project/:projectId" element={
        <ProtectedRoute>
          <ReactFlowProvider>
            <CanvasLayout />
          </ReactFlowProvider>
        </ProtectedRoute>
      } />
      <Route path="/ref/units" element={<ProtectedRoute><UnitsPage /></ProtectedRoute>} />
      <Route path="/ref/shared-params" element={<ProtectedRoute><SharedParamsPage /></ProtectedRoute>} />
      <Route path="/node-repository" element={<Navigate to="/node-repository/preference" replace />} />
      <Route path="/node-repository/preference" element={<ProtectedRoute><NodeRepository /></ProtectedRoute>} />
      <Route path="/node-repository/nodefiles" element={<ProtectedRoute><NodeFilesPage /></ProtectedRoute>} />
      <Route path="/memory" element={<ProtectedRoute><MemoryManager /></ProtectedRoute>} />
      <Route path="/admin/usage" element={
        <ProtectedRoute><AdminUsagePage /></ProtectedRoute>
      } />
    </Routes>
  )
}

export default function App() {
  return (
    <QueryClientProvider client={queryClient}>
      <BrowserRouter>
        <AppRoutes />
      </BrowserRouter>
    </QueryClientProvider>
  )
}
