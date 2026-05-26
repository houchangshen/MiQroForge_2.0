import { useState } from 'react'
// X icon imported where needed
import { useSettingsStore } from '../../stores/settings-store'
import type { Theme, FontSize } from '../../stores/settings-store'
import {
  useShortcutsStore,
  SHORTCUT_DEFS,
  bindingFromEvent,
  displayKey,
} from '../../stores/shortcuts-store'
import type { ShortcutId } from '../../stores/shortcuts-store'

// ─── Theme definitions ───────────────────────────────────────────────────────────

interface ThemeOption {
  id: Theme
  label: string
  icon: string
}
const THEMES: ThemeOption[] = [
  { id: 'light',    label: 'Warm',      icon: '☀' },
  { id: 'dark',     label: 'Dark',      icon: '🌙' },
  { id: 'forest',   label: 'Forest',    icon: '🌲' },
  { id: 'ocean',    label: 'Ocean',     icon: '🌊' },
  { id: 'sunset',   label: 'Sunset',    icon: '🌇' },
  { id: 'midnight', label: 'Midnight',  icon: '🌌' },
]

// RGB triplets for color preview: [bg-base, bg-card, text-primary]
const THEME_COLORS: Record<Theme, [string, string, string]> = {
  light:    ['255 253 245', '244 240 226', '45 36 25'],
  dark:     ['3 7 18',    '31 41 55',   '243 244 246'],
  forest:   ['240 250 240', '220 237 225', '30 60 40'],
  ocean:    ['240 248 255', '218 235 248', '15 45 75'],
  sunset:   ['255 248 240', '248 230 215', '60 35 20'],
  midnight: ['10 15 30',  '26 35 58',   '230 235 245'],
}

// ─── Shortcut row ──────────────────────────────────────────────────────────────

function ShortcutRow({ id }: { id: ShortcutId }) {
  const def = SHORTCUT_DEFS[id]
  const binding   = useShortcutsStore((s) => s.bindings[id])
  const setBinding  = useShortcutsStore((s) => s.setBinding)
  const resetBinding = useShortcutsStore((s) => s.resetBinding)
  const [recording, setRecording] = useState(false)

  const handleKeyDown = (e: React.KeyboardEvent) => {
    e.preventDefault()
    e.stopPropagation()
    const b = bindingFromEvent(e.nativeEvent)
    if (!b) return          // bare modifier — keep recording
    if (e.key === 'Escape') {
      setRecording(false)
      return
    }
    setBinding(id, b)
    setRecording(false)
  }

  const isDefault = binding === def.defaultKey

  return (
    <div className="flex items-center gap-2 py-1">
      <div className="flex-1 min-w-0">
        <div className="text-xs text-mf-text-secondary truncate">{def.label}</div>
        {def.description && (
          <div className="text-[10px] text-mf-text-muted truncate">{def.description}</div>
        )}
      </div>

      <div className="flex items-center gap-1 flex-shrink-0">
        {/* Key badge / recording button */}
        <button
          onClick={() => setRecording(true)}
          onKeyDown={recording ? handleKeyDown : undefined}
          onBlur={() => setRecording(false)}
          title="Click then press a key to rebind"
          className={`px-2 py-0.5 rounded border text-[11px] font-mono transition-colors ${
            recording
              ? 'bg-blue-600 border-blue-400 text-white animate-pulse'
              : 'bg-mf-card border-mf-border text-mf-text-secondary hover:border-gray-400 hover:text-mf-text-primary'
          }`}
        >
          {recording ? 'press key…' : displayKey(binding)}
        </button>

        {/* Reset to default — only shown when overridden */}
        {!isDefault && (
          <button
            onClick={() => resetBinding(id)}
            title="Reset to default"
            className="text-mf-text-muted hover:text-mf-text-secondary text-[10px] px-1"
          >
            ↺
          </button>
        )}
      </div>
    </div>
  )
}

// ─── SettingsContent (shared between panel and modal) ──────────────────────────

export function SettingsContent() {
  const { theme, fontSize, setTheme, setFontSize } = useSettingsStore()
  const resetAll = useShortcutsStore((s) => s.resetAll)

  const shortcutIds = Object.keys(SHORTCUT_DEFS) as ShortcutId[]

  return (
    <div className="space-y-5">
      {/* Theme */}
      <div>
        <div className="text-xs font-semibold text-mf-text-secondary uppercase tracking-wide mb-2">
          Theme
        </div>
        <div className="grid grid-cols-3 gap-2">
          {THEMES.map((t) => {
            const colors = THEME_COLORS[t.id]
            return (
              <button
                key={t.id}
                onClick={() => setTheme(t.id)}
                title={t.label}
                className={`flex flex-col items-center gap-1 p-2 rounded-lg border transition-all ${
                  theme === t.id
                    ? 'border-blue-500 bg-blue-500/10 ring-1 ring-blue-400'
                    : 'border-mf-border bg-mf-card hover:bg-mf-hover hover:border-mf-text-muted'
                }`}
              >
                {/* Mini color preview: 3 swatches */}
                <div className="flex gap-0.5 rounded overflow-hidden w-full h-5">
                  <div
                    className="flex-1"
                    style={{ backgroundColor: `rgb(${colors[0]})` }}
                  />
                  <div
                    className="flex-1"
                    style={{ backgroundColor: `rgb(${colors[1]})` }}
                  />
                  <div
                    className="flex-1"
                    style={{ backgroundColor: `rgb(${colors[2]})` }}
                  />
                </div>
                {/* Icon + name */}
                <div className="flex items-center gap-1 text-[11px] font-medium">
                  <span className="text-xs leading-none">{t.icon}</span>
                  <span className={theme === t.id ? 'text-blue-400' : 'text-mf-text-secondary'}>
                    {t.label}
                  </span>
                </div>
                {/* Checkmark for selected */}
                {theme === t.id && (
                  <div className="text-[9px] text-blue-400 font-semibold">● Active</div>
                )}
              </button>
            )
          })}
        </div>
      </div>

      {/* Font size */}
      <div>
        <div className="text-xs font-semibold text-mf-text-secondary uppercase tracking-wide mb-2">
          Font Size
        </div>
        <div className="flex gap-2">
          {([
            { id: 'small', label: 'S' },
            { id: 'medium', label: 'M' },
            { id: 'large', label: 'L' },
          ] as { id: FontSize; label: string }[]).map(({ id, label }) => (
            <button
              key={id}
              onClick={() => setFontSize(id)}
              className={`flex-1 py-1.5 text-xs rounded border transition-colors ${
                fontSize === id
                  ? 'bg-blue-600 border-blue-500 text-white'
                  : 'bg-mf-card border-mf-border text-mf-text-secondary hover:bg-mf-hover hover:text-mf-text-primary'
              }`}
            >
              {label}
            </button>
          ))}
        </div>
        <p className="text-[10px] text-mf-text-muted mt-1.5">
          Scales all text and spacing proportionally.
        </p>
      </div>

      {/* Keyboard shortcuts */}
      <div>
        <div className="flex items-center justify-between mb-2">
          <div className="text-xs font-semibold text-mf-text-secondary uppercase tracking-wide">
            Keyboard Shortcuts
          </div>
          <button
            onClick={resetAll}
            className="text-[10px] text-mf-text-muted hover:text-mf-text-secondary transition-colors"
            title="Reset all shortcuts to defaults"
          >
            Reset all
          </button>
        </div>
        <p className="text-[10px] text-mf-text-muted mb-2">
          Click a key badge, then press the new shortcut key.
        </p>
        <div className="bg-mf-card rounded border border-mf-border px-2 py-1 divide-y divide-mf-border/50">
          {shortcutIds.map((id) => (
            <ShortcutRow key={id} id={id} />
          ))}
        </div>
      </div>

      <p className="text-[10px] text-mf-text-muted pt-2 border-t border-mf-border">
        Settings are saved automatically.
      </p>
    </div>
  )
}
