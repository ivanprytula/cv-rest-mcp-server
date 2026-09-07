import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { beforeEach, describe, expect, it } from 'vitest'
import { ThemeProvider } from './ThemeContext'
import ThemeControls from './ThemeControls'

function renderControls() {
  return render(
    <ThemeProvider>
      <ThemeControls />
    </ThemeProvider>,
  )
}

beforeEach(() => {
  localStorage.clear()
  document.documentElement.removeAttribute('data-theme')
  document.documentElement.removeAttribute('data-palette')
})

describe('theme cycle button', () => {
  it('starts on System when nothing is stored', () => {
    renderControls()
    expect(screen.getByRole('button', { name: /Theme: System/ })).toBeInTheDocument()
    expect(document.documentElement.getAttribute('data-theme')).toBeNull()
  })

  it('cycles System -> Light -> Dark -> System and updates data-theme', async () => {
    const user = userEvent.setup()
    renderControls()
    const button = screen.getByRole('button', { name: /Theme:/ })

    await user.click(button)
    expect(screen.getByRole('button', { name: /Theme: Light/ })).toBeInTheDocument()
    expect(document.documentElement.getAttribute('data-theme')).toBe('light')

    await user.click(button)
    expect(screen.getByRole('button', { name: /Theme: Dark/ })).toBeInTheDocument()
    expect(document.documentElement.getAttribute('data-theme')).toBe('dark')

    await user.click(button)
    expect(screen.getByRole('button', { name: /Theme: System/ })).toBeInTheDocument()
    expect(document.documentElement.getAttribute('data-theme')).toBeNull()
  })

  it('persists an explicit choice to localStorage, and clears it back to system', async () => {
    const user = userEvent.setup()
    renderControls()
    const button = screen.getByRole('button', { name: /Theme:/ })

    await user.click(button)
    expect(localStorage.getItem('theme')).toBe('light')

    await user.click(button)
    expect(localStorage.getItem('theme')).toBe('dark')

    await user.click(button)
    expect(localStorage.getItem('theme')).toBeNull()
  })

  it('resumes from a stored theme on mount', () => {
    localStorage.setItem('theme', 'dark')
    renderControls()
    expect(screen.getByRole('button', { name: /Theme: Dark/ })).toBeInTheDocument()
    expect(document.documentElement.getAttribute('data-theme')).toBe('dark')
  })
})

describe('palette select', () => {
  it('defaults to violet and sets data-palette on mount', () => {
    renderControls()
    expect(screen.getByRole('combobox', { name: /Accent color/ })).toHaveValue('violet')
    expect(document.documentElement.getAttribute('data-palette')).toBe('violet')
  })

  it('switching palettes updates data-palette and localStorage', async () => {
    const user = userEvent.setup()
    renderControls()
    await user.selectOptions(screen.getByRole('combobox', { name: /Accent color/ }), 'green')

    expect(document.documentElement.getAttribute('data-palette')).toBe('green')
    expect(localStorage.getItem('palette')).toBe('green')
  })

  it('ignores a corrupted stored palette and falls back to violet', () => {
    localStorage.setItem('palette', 'not-a-real-palette')
    renderControls()
    expect(screen.getByRole('combobox', { name: /Accent color/ })).toHaveValue('violet')
  })
})
