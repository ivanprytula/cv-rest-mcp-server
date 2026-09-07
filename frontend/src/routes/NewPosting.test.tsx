import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { MemoryRouter, Route, Routes } from 'react-router-dom'
import { describe, expect, it, vi } from 'vitest'
import * as gapsApi from '../api/gaps'
import NewPosting from './NewPosting'

function renderNewPosting() {
  return render(
    <MemoryRouter initialEntries={['/postings/new']}>
      <Routes>
        <Route path="/postings/new" element={<NewPosting />} />
        <Route path="/postings/:id" element={<p>Report page</p>} />
      </Routes>
    </MemoryRouter>,
  )
}

describe('NewPosting form', () => {
  it('disables submit until the job description has non-whitespace text', async () => {
    const user = userEvent.setup()
    renderNewPosting()

    const submit = screen.getByRole('button', { name: /Store & analyze/ })
    expect(submit).toBeDisabled()

    await user.type(screen.getByLabelText('Job description'), '   ')
    expect(submit).toBeDisabled()

    await user.type(screen.getByLabelText('Job description'), 'Senior Engineer role')
    expect(submit).toBeEnabled()
  })

  it('stores then analyzes the posting and navigates to its report on submit', async () => {
    const user = userEvent.setup()
    const storeSpy = vi
      .spyOn(gapsApi, 'storePosting')
      .mockResolvedValue({ id: 42, content_hash: 'abc', duplicate: false })
    const analyzeSpy = vi.spyOn(gapsApi, 'analyzePosting').mockResolvedValue({
      posting_id: 42,
      coverage: 1,
      gaps: [],
      unrecognized: [],
    })

    renderNewPosting()
    await user.type(screen.getByLabelText('Title'), 'Senior Engineer')
    await user.type(screen.getByLabelText('Job description'), 'Some JD text')
    await user.click(screen.getByRole('button', { name: /Store & analyze/ }))

    expect(await screen.findByText('Report page')).toBeInTheDocument()
    expect(storeSpy).toHaveBeenCalledWith('Some JD text', {
      title: 'Senior Engineer',
      company: '',
    })
    expect(analyzeSpy).toHaveBeenCalledWith(42)
  })

  it('shows an error and re-enables the form when storing fails', async () => {
    const user = userEvent.setup()
    vi.spyOn(gapsApi, 'storePosting').mockRejectedValue(new Error('Payload too large'))

    renderNewPosting()
    await user.type(screen.getByLabelText('Job description'), 'Some JD text')
    await user.click(screen.getByRole('button', { name: /Store & analyze/ }))

    expect(await screen.findByRole('alert')).toHaveTextContent('Payload too large')
    expect(screen.getByRole('button', { name: /Store & analyze/ })).toBeEnabled()
  })
})
