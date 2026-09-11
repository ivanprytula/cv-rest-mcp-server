import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { MemoryRouter, Route, Routes } from 'react-router-dom'
import { describe, expect, it, vi } from 'vitest'
import * as documentsApi from '../api/documents'
import Onboarding from './Onboarding'

function renderOnboarding() {
  return render(
    <MemoryRouter initialEntries={['/onboarding']}>
      <Routes>
        <Route path="/onboarding" element={<Onboarding />} />
        <Route path="/cv/import" element={<p>Import page</p>} />
      </Routes>
    </MemoryRouter>,
  )
}

describe('Onboarding page', () => {
  it('shows empty state when no documents exist yet', async () => {
    vi.spyOn(documentsApi, 'readDocument').mockResolvedValue(null)

    renderOnboarding()

    expect(await screen.findByText('No CV yet.')).toBeInTheDocument()
    expect(screen.getByRole('button', { name: /Save skill bank/ })).toBeDisabled()
    expect(screen.getByRole('button', { name: /Save JD vocabulary/ })).toBeDisabled()
  })

  it('enables and saves the skill bank once required fields and the category hint format are valid', async () => {
    vi.spyOn(documentsApi, 'readDocument').mockResolvedValue(null)
    const writeSpy = vi.spyOn(documentsApi, 'writeDocument').mockResolvedValue({ version: 1 })

    const user = userEvent.setup()
    renderOnboarding()
    await screen.findByText('No CV yet.')

    await user.click(screen.getByRole('button', { name: /Add skill/ }))
    const saveButton = screen.getByRole('button', { name: /Save skill bank/ })
    expect(saveButton).toBeDisabled()

    await user.type(screen.getByPlaceholderText('Skill (e.g. PostgreSQL)'), 'PostgreSQL')
    await user.type(screen.getByPlaceholderText('Group id (e.g. databases)'), 'databases')
    await user.type(screen.getByPlaceholderText('Category hint (Group > Sub)'), 'Databases')
    expect(saveButton).toBeDisabled()

    await user.type(screen.getByPlaceholderText('Category hint (Group > Sub)'), ' > SQL')
    expect(saveButton).toBeEnabled()

    await user.click(saveButton)

    expect(await screen.findByText('Saved.')).toBeInTheDocument()
    expect(writeSpy).toHaveBeenCalledWith('skill_bank', {
      skills: [
        {
          atom: 'PostgreSQL',
          group_id: 'databases',
          level: 'middle',
          priority: 'medium',
          category_hint: 'Databases > SQL',
          aliases: [],
        },
      ],
    })
  })

  it('shows a write error for one section without affecting the other', async () => {
    vi.spyOn(documentsApi, 'readDocument').mockResolvedValue(null)
    vi.spyOn(documentsApi, 'writeDocument').mockRejectedValue(new Error('Vocabulary entry missing a term'))

    const user = userEvent.setup()
    renderOnboarding()
    await screen.findByText('No CV yet.')

    await user.click(screen.getByRole('button', { name: /Add term/ }))
    await user.type(screen.getByPlaceholderText('Term (e.g. AWS)'), 'AWS')
    await user.click(screen.getByRole('button', { name: /Save JD vocabulary/ }))

    expect(await screen.findByRole('alert')).toHaveTextContent('Vocabulary entry missing a term')
    expect(screen.getByRole('button', { name: /Save skill bank/ })).toBeDisabled()
  })
})
