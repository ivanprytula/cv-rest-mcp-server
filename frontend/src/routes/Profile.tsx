import { useEffect, useState, type FormEvent } from 'react'
import { getProfile, updateProfileEmail, type Profile as ProfileData } from '../api/auth'

const fieldClass = 'rounded border border-border bg-bg px-2 py-2 text-text'

export default function Profile() {
  const [profile, setProfile] = useState<ProfileData | null>(null)
  const [loadError, setLoadError] = useState<string | null>(null)

  const [email, setEmail] = useState('')
  const [saving, setSaving] = useState(false)
  const [saveError, setSaveError] = useState<string | null>(null)
  const [saved, setSaved] = useState(false)

  useEffect(() => {
    getProfile()
      .then((data) => {
        setProfile(data)
        setEmail(data.email_is_placeholder ? '' : data.email)
      })
      .catch((err) => setLoadError((err as Error).message))
  }, [])

  async function handleSubmit(event: FormEvent) {
    event.preventDefault()
    setSaveError(null)
    setSaved(false)
    setSaving(true)
    try {
      const updated = await updateProfileEmail(email)
      setProfile(updated)
      setSaved(true)
    } catch (err) {
      setSaveError((err as Error).message)
    } finally {
      setSaving(false)
    }
  }

  if (loadError) return <p role="alert">Failed to load profile: {loadError}</p>
  if (!profile) return <p>Loading profile…</p>

  return (
    <div className="flex max-w-96 flex-col gap-4">
      <h1 className="text-2xl text-text-h">Profile</h1>

      <div>
        <p className="text-muted">Username</p>
        <p>{profile.username}</p>
      </div>

      <div>
        <p className="text-muted">Role</p>
        <p>{profile.role}</p>
      </div>

      <form onSubmit={handleSubmit} className="flex flex-col gap-2">
        <label htmlFor="email">Email</label>
        {profile.email_is_placeholder && (
          <p className="text-sm text-muted">
            No email on file yet — needed later for password reset and notifications.
          </p>
        )}
        <input
          id="email"
          type="email"
          className={fieldClass}
          value={email}
          onChange={(e) => setEmail(e.target.value)}
          autoComplete="email"
          required
        />
        {saveError && (
          <p role="alert" className="text-danger">
            {saveError}
          </p>
        )}
        {saved && <p className="text-accent">Saved.</p>}
        <button
          type="submit"
          disabled={saving}
          className="mt-2 w-fit rounded bg-accent px-4 py-2 text-accent-contrast disabled:cursor-default disabled:opacity-60"
        >
          {saving ? 'Saving…' : 'Save email'}
        </button>
      </form>
    </div>
  )
}
