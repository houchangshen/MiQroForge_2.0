import { create } from 'zustand'

export type Theme = 'light' | 'dark' | 'forest' | 'ocean' | 'sunset' | 'midnight'
export type FontSize = 'small' | 'medium' | 'large'

/** Themes that are dark (used for ReactFlow colorMode and minimap maskColor) */
export const DARK_THEMES: ReadonlySet<Theme> = new Set(['dark', 'midnight'])

/** Get ReactFlow compatible colorMode ('light' | 'dark') for any theme */
export function getColorMode(theme: Theme): 'light' | 'dark' {
  return DARK_THEMES.has(theme) ? 'dark' : 'light'
}

/** Get minimap maskColor string for any theme */
export function getMinimapMaskColor(theme: Theme): string {
  return DARK_THEMES.has(theme) ? 'rgba(0,0,0,0.4)' : 'rgba(200,190,170,0.3)'
}

interface SettingsState {
  theme: Theme
  fontSize: FontSize
  setTheme: (t: Theme) => void
  setFontSize: (f: FontSize) => void
}

const FONT_SIZE_MAP: Record<FontSize, string> = {
  small:  '13px',
  medium: '15px',
  large:  '17px',
}

// Read from localStorage; default to dark + medium
function loadInitial(): { theme: Theme; fontSize: FontSize } {
  try {
    const raw = localStorage.getItem('mf-settings')
    if (raw) return JSON.parse(raw) as { theme: Theme; fontSize: FontSize }
  } catch {
    // ignore parse errors
  }
  return { theme: 'dark', fontSize: 'medium' }
}

function applyTheme(theme: Theme) {
  // Remove all theme-related classes first
  document.documentElement.classList.remove(
    'dark',
    'theme-forest',
    'theme-ocean',
    'theme-sunset',
    'theme-midnight'
  )
  // Apply the new theme class
  if (theme === 'dark') {
    document.documentElement.classList.add('dark')
  } else if (theme !== 'light') {
    // light is the default (:root CSS), no class needed
    document.documentElement.classList.add(`theme-${theme}`)
  }
}

function applyFontSize(fontSize: FontSize) {
  document.documentElement.style.fontSize = FONT_SIZE_MAP[fontSize]
}

function persist(state: { theme: Theme; fontSize: FontSize }) {
  localStorage.setItem('mf-settings', JSON.stringify(state))
}

// Apply immediately (before React renders) to prevent FOUC
const initial = loadInitial()
applyTheme(initial.theme)
applyFontSize(initial.fontSize)

export const useSettingsStore = create<SettingsState>((set) => ({
  theme:    initial.theme,
  fontSize: initial.fontSize,

  setTheme: (theme) => {
    applyTheme(theme)
    set({ theme })
    persist({ theme, fontSize: useSettingsStore.getState().fontSize })
  },

  setFontSize: (fontSize) => {
    applyFontSize(fontSize)
    set({ fontSize })
    persist({ theme: useSettingsStore.getState().theme, fontSize })
  },
}))
