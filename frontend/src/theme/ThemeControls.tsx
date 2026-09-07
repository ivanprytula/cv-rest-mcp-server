import { useTheme, type Palette } from './ThemeContext'

const THEME_CYCLE: Record<string, { next: 'system' | 'light' | 'dark'; label: string }> = {
  system: { next: 'light', label: 'Theme: System' },
  light: { next: 'dark', label: 'Theme: Light' },
  dark: { next: 'system', label: 'Theme: Dark' },
}

const PALETTES: { value: Palette; label: string }[] = [
  { value: 'violet', label: 'Violet' },
  { value: 'blue', label: 'Blue' },
  { value: 'green', label: 'Green' },
]

export default function ThemeControls() {
  const { theme, palette, setTheme, setPalette } = useTheme()
  const current = THEME_CYCLE[theme]

  return (
    <div className="flex items-center gap-2">
      <button
        type="button"
        onClick={() => setTheme(current.next)}
        aria-label={`${current.label}. Click to switch to ${current.next}.`}
        title={`${current.label} — click to change`}
        className="rounded border border-border px-3 py-1.5 whitespace-nowrap"
      >
        {current.label}
      </button>
      <label className="sr-only" htmlFor="palette-select">
        Accent color
      </label>
      <select
        id="palette-select"
        value={palette}
        onChange={(e) => setPalette(e.target.value as Palette)}
        className="rounded border border-border bg-bg px-2 py-1.5 text-text"
      >
        {PALETTES.map((p) => (
          <option key={p.value} value={p.value}>
            {p.label}
          </option>
        ))}
      </select>
    </div>
  )
}
