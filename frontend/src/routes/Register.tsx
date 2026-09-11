import { useState, type FormEvent } from 'react'
import { Link, useNavigate } from 'react-router-dom'
import { useAuth } from '../auth/AuthContext'
import { register } from '../api/auth'

export default function Register() {
  const { login } = useAuth()
  const navigate = useNavigate()
  const [username, setUsername] = useState('')
  const [password, setPassword] = useState('')
  const [error, setError] = useState<string | null>(null)
  const [submitting, setSubmitting] = useState(false)

  async function handleSubmit(event: FormEvent) {
    event.preventDefault()
    setError(null)
    setSubmitting(true)
    try {
      await register(username, password)
      await login(username, password)
      navigate('/onboarding', { replace: true })
    } catch (err) {
      setError((err as Error).message)
    } finally {
      setSubmitting(false)
    }
  }

  return (
    <main className="flex min-h-svh items-center justify-center p-4">
      <form onSubmit={handleSubmit} className="flex w-full max-w-70 flex-col gap-2">
        <h1 className="text-2xl text-text-h">Create an account</h1>
        <label htmlFor="username">Username</label>
        <input
          id="username"
          className="rounded border border-border bg-bg px-2 py-2 text-text"
          value={username}
          onChange={(e) => setUsername(e.target.value)}
          autoComplete="username"
          pattern="[A-Za-z0-9._-]+"
          minLength={3}
          maxLength={64}
          required
        />
        <label htmlFor="password">Password</label>
        <input
          id="password"
          type="password"
          className="rounded border border-border bg-bg px-2 py-2 text-text"
          value={password}
          onChange={(e) => setPassword(e.target.value)}
          autoComplete="new-password"
          minLength={12}
          maxLength={128}
          required
        />
        {error && (
          <p role="alert" className="text-danger">
            {error}
          </p>
        )}
        <button
          type="submit"
          disabled={submitting}
          className="mt-2 rounded bg-accent px-2 py-2 text-accent-contrast disabled:cursor-default disabled:opacity-60"
        >
          {submitting ? 'Creating account…' : 'Create account'}
        </button>
        <Link to="/login" className="text-sm text-muted">
          Already have an account? Sign in
        </Link>
      </form>
    </main>
  )
}
