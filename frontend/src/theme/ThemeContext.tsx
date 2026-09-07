import { createContext, useCallback, useContext, useEffect, useState, type ReactNode } from 'react'

// 'system' means "no explicit choice" — the CSS falls back to
// prefers-color-scheme. 'light'/'dark' set data-theme, which always wins
// over the OS setting (see index.css's token rules).
export type Theme = 'system' | 'light' | 'dark'
export type Palette = 'violet' | 'blue' | 'green'

const THEME_KEY = 'theme'
const PALETTE_KEY = 'palette'
const DEFAULT_PALETTE: Palette = 'violet'

interface ThemeState {
  theme: Theme
  palette: Palette
  setTheme: (theme: Theme) => void
  setPalette: (palette: Palette) => void
}

const ThemeContext = createContext<ThemeState | null>(null)

function readStored<T extends string>(key: string, valid: readonly T[], fallback: T): T {
  try {
    const stored = localStorage.getItem(key)
    return (valid as readonly string[]).includes(stored ?? '') ? (stored as T) : fallback
  } catch {
    return fallback
  }
}

// clearValue, when given, removes the key instead of storing it — used for
// 'system', which means "no explicit choice" and must fall back to the CSS
// media query rather than being written as a literal string.
function persist(key: string, value: string, clearValue?: string): void {
  try {
    if (value === clearValue) localStorage.removeItem(key)
    else localStorage.setItem(key, value)
  } catch {
    // Storage unavailable — in-memory state still applies for this tab.
  }
}

export function ThemeProvider({ children }: { children: ReactNode }) {
  const [theme, setThemeState] = useState<Theme>(() =>
    readStored(THEME_KEY, ['system', 'light', 'dark'], 'system'),
  )
  const [palette, setPaletteState] = useState<Palette>(() =>
    readStored(PALETTE_KEY, ['violet', 'blue', 'green'], DEFAULT_PALETTE),
  )

  // Mirrors state onto <html data-theme/data-palette> — the single thing
  // index.css's token rules key off. The index.html boot script does the
  // same lookup before first paint; this effect keeps it in sync as the
  // user changes it during the session.
  useEffect(() => {
    const root = document.documentElement
    if (theme === 'system') root.removeAttribute('data-theme')
    else root.setAttribute('data-theme', theme)
  }, [theme])

  useEffect(() => {
    document.documentElement.setAttribute('data-palette', palette)
  }, [palette])

  const setTheme = useCallback((next: Theme) => {
    setThemeState(next)
    persist(THEME_KEY, next, 'system')
  }, [])

  const setPalette = useCallback((next: Palette) => {
    setPaletteState(next)
    persist(PALETTE_KEY, next)
  }, [])

  return (
    <ThemeContext.Provider value={{ theme, palette, setTheme, setPalette }}>
      {children}
    </ThemeContext.Provider>
  )
}

export function useTheme(): ThemeState {
  const ctx = useContext(ThemeContext)
  if (!ctx) throw new Error('useTheme must be used within ThemeProvider')
  return ctx
}
