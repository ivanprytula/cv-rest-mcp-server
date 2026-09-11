import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { describe, expect, it, vi } from 'vitest'
import * as authApi from '../api/auth'
import Profile from './Profile'

describe('Profile page', () => {
  it('shows a placeholder-email notice and lets the user set a real one', async () => {
    const user = userEvent.setup()
    vi.spyOn(authApi, 'getProfile').mockResolvedValue({
      username: 'newuser',
      email: 'newuser@users.noreply.example.com',
      email_is_placeholder: true,
      role: 'user',
    })
    const updateSpy = vi.spyOn(authApi, 'updateProfileEmail').mockResolvedValue({
      username: 'newuser',
      email: 'real@example.com',
      email_is_placeholder: false,
      role: 'user',
    })

    render(<Profile />)

    expect(await screen.findByText('newuser')).toBeInTheDocument()
    expect(screen.getByText(/No email on file yet/)).toBeInTheDocument()

    await user.type(screen.getByLabelText('Email'), 'real@example.com')
    await user.click(screen.getByRole('button', { name: /Save email/ }))

    expect(updateSpy).toHaveBeenCalledWith('real@example.com')
    expect(await screen.findByText('Saved.')).toBeInTheDocument()
    expect(screen.queryByText(/No email on file yet/)).not.toBeInTheDocument()
  })

  it('prefills the field with a real email and skips the placeholder notice', async () => {
    vi.spyOn(authApi, 'getProfile').mockResolvedValue({
      username: 'operator',
      email: 'real@example.com',
      email_is_placeholder: false,
      role: 'admin',
    })

    render(<Profile />)

    expect(await screen.findByDisplayValue('real@example.com')).toBeInTheDocument()
    expect(screen.queryByText(/No email on file yet/)).not.toBeInTheDocument()
  })

  it('shows an error when saving fails', async () => {
    const user = userEvent.setup()
    vi.spyOn(authApi, 'getProfile').mockResolvedValue({
      username: 'newuser',
      email: 'newuser@users.noreply.example.com',
      email_is_placeholder: true,
      role: 'user',
    })
    vi.spyOn(authApi, 'updateProfileEmail').mockRejectedValue(
      new Error('That email is already in use'),
    )

    render(<Profile />)
    await screen.findByText('newuser')
    await user.type(screen.getByLabelText('Email'), 'taken@example.com')
    await user.click(screen.getByRole('button', { name: /Save email/ }))

    expect(await screen.findByRole('alert')).toHaveTextContent('That email is already in use')
  })
})
