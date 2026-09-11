import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { MemoryRouter, Route, Routes } from 'react-router-dom'
import { describe, expect, it, vi } from 'vitest'
import * as authApi from '../api/auth'
import { AuthProvider } from '../auth/AuthContext'
import Register from './Register'

function renderRegister() {
  return render(
    <AuthProvider>
      <MemoryRouter initialEntries={['/register']}>
        <Routes>
          <Route path="/register" element={<Register />} />
          <Route path="/onboarding" element={<p>Onboarding page</p>} />
        </Routes>
      </MemoryRouter>
    </AuthProvider>,
  )
}

describe('Register form', () => {
  it('registers, logs in, and navigates to onboarding on success', async () => {
    const user = userEvent.setup()
    const registerSpy = vi
      .spyOn(authApi, 'register')
      .mockResolvedValue({ id: 1, username: 'newuser', email: 'new@example.com' })
    const loginSpy = vi.spyOn(authApi, 'login').mockResolvedValue({
      access_token: 'token',
      token_type: 'bearer',
      expires_in: 900,
    })

    renderRegister()
    await user.type(screen.getByLabelText('Username'), 'newuser')
    await user.type(screen.getByLabelText('Email'), 'new@example.com')
    await user.type(screen.getByLabelText('Password'), 'a-long-enough-password')
    await user.click(screen.getByRole('button', { name: /Create account/ }))

    expect(await screen.findByText('Onboarding page')).toBeInTheDocument()
    expect(registerSpy).toHaveBeenCalledWith('newuser', 'new@example.com', 'a-long-enough-password')
    expect(loginSpy).toHaveBeenCalledWith('newuser', 'a-long-enough-password')
  })

  it('shows the backend error and stays on the page when the username is taken', async () => {
    const user = userEvent.setup()
    vi.spyOn(authApi, 'register').mockRejectedValue(new Error('That username is taken'))

    renderRegister()
    await user.type(screen.getByLabelText('Username'), 'newuser')
    await user.type(screen.getByLabelText('Email'), 'new@example.com')
    await user.type(screen.getByLabelText('Password'), 'a-long-enough-password')
    await user.click(screen.getByRole('button', { name: /Create account/ }))

    expect(await screen.findByRole('alert')).toHaveTextContent('That username is taken')
    expect(screen.queryByText('Onboarding page')).not.toBeInTheDocument()
  })
})
