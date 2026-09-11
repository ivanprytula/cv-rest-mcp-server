import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { useState } from 'react'
import { useAuth } from '../auth/AuthContext'
import { deletePosting, listPostings } from '../api/gaps'
import { deleteRevision, listRevisions } from '../api/revisions'
import {
  createTrackedBoard,
  deleteTrackedBoard,
  listTrackedBoards,
  updateTrackedBoard,
  type TrackedBoard,
} from '../api/trackedBoards'
import { enableUser, listUsers, setUserRole, disableUser } from '../api/auth'
import { DataTable, TableScroll, th } from '../components/Table'

const fieldClass =
  'rounded border border-border bg-surface px-2 py-1 text-sm disabled:cursor-default disabled:opacity-60'

const SECTIONS = ['Users', 'Tracked Boards', 'Revisions', 'Job Postings'] as const
type Section = (typeof SECTIONS)[number]

export default function Admin() {
  const [section, setSection] = useState<Section>('Users')

  return (
    <>
      <nav className="mb-4 flex flex-wrap gap-2" aria-label="Admin sections">
        {SECTIONS.map((name) => (
          <button
            key={name}
            type="button"
            onClick={() => setSection(name)}
            className={`rounded border border-border px-3 py-1.5 text-sm ${
              section === name ? 'bg-accent text-accent-contrast' : ''
            }`}
          >
            {name}
          </button>
        ))}
      </nav>
      {section === 'Users' && <UsersSection />}
      {section === 'Tracked Boards' && <TrackedBoardsSection />}
      {section === 'Revisions' && <RevisionsSection />}
      {section === 'Job Postings' && <JobPostingsSection />}
    </>
  )
}

function UsersSection() {
  const { username: ownUsername } = useAuth()
  const queryClient = useQueryClient()
  const { data, isLoading, isError, error } = useQuery({
    queryKey: ['admin', 'users'],
    queryFn: listUsers,
  })

  const invalidate = () => queryClient.invalidateQueries({ queryKey: ['admin', 'users'] })
  const toggleActive = useMutation({
    mutationFn: ({ username, isActive }: { username: string; isActive: boolean }) =>
      isActive ? disableUser(username) : enableUser(username),
    onSuccess: invalidate,
  })
  const toggleRole = useMutation({
    mutationFn: ({ username, role }: { username: string; role: string }) =>
      setUserRole(username, role === 'admin' ? 'user' : 'admin'),
    onSuccess: invalidate,
  })

  if (isLoading) return <p>Loading users…</p>
  if (isError) return <p role="alert">Failed to load users: {(error as Error).message}</p>
  if (!data || data.length === 0) return <p>No users yet.</p>

  return (
    <TableScroll>
      <DataTable>
        <caption className="mb-2 text-muted">Every account</caption>
        <thead>
          <tr>
            <th className={th}>Username</th>
            <th className={th}>Email</th>
            <th className={th}>Role</th>
            <th className={th}>Status</th>
            <th className={th}>Actions</th>
          </tr>
        </thead>
        <tbody>
          {data.map((user) => {
            const isSelf = user.username === ownUsername
            return (
              <tr key={user.id}>
                <td className={th}>
                  {user.username}
                  {isSelf && ' (you)'}
                </td>
                <td className={th}>{user.email}</td>
                <td className={th}>{user.role}</td>
                <td className={th}>{user.is_active ? 'Active' : 'Disabled'}</td>
                <td className={th}>
                  <div className="flex flex-wrap gap-2">
                    <button
                      type="button"
                      onClick={() =>
                        toggleActive.mutate({ username: user.username, isActive: user.is_active })
                      }
                      disabled={isSelf || toggleActive.isPending}
                      title={isSelf ? "You can't disable your own account" : undefined}
                      className="rounded border border-border px-2 py-1 text-sm disabled:cursor-default disabled:opacity-60"
                    >
                      {user.is_active ? 'Disable' : 'Enable'}
                    </button>
                    <button
                      type="button"
                      onClick={() =>
                        toggleRole.mutate({ username: user.username, role: user.role })
                      }
                      disabled={isSelf || toggleRole.isPending}
                      title={isSelf ? "You can't change your own role" : undefined}
                      className="rounded border border-border px-2 py-1 text-sm disabled:cursor-default disabled:opacity-60"
                    >
                      {user.role === 'admin' ? 'Demote to user' : 'Promote to admin'}
                    </button>
                  </div>
                </td>
              </tr>
            )
          })}
        </tbody>
      </DataTable>
    </TableScroll>
  )
}

const BOARD_KINDS = ['greenhouse', 'lever', 'ashby', 'url_only'] as const

function TrackedBoardsSection() {
  const queryClient = useQueryClient()
  const { data, isLoading, isError, error } = useQuery({
    queryKey: ['admin', 'tracked-boards'],
    queryFn: listTrackedBoards,
  })
  const invalidate = () =>
    queryClient.invalidateQueries({ queryKey: ['admin', 'tracked-boards'] })

  const [kind, setKind] = useState<string>('greenhouse')
  const [companyName, setCompanyName] = useState('')
  const [companySlug, setCompanySlug] = useState('')
  const [url, setUrl] = useState('')
  const [createError, setCreateError] = useState('')

  const create = useMutation({
    mutationFn: createTrackedBoard,
    onSuccess: () => {
      setCompanyName('')
      setCompanySlug('')
      setUrl('')
      setCreateError('')
      invalidate()
    },
    onError: (err) => setCreateError((err as Error).message),
  })
  const toggleActive = useMutation({
    mutationFn: (board: TrackedBoard) =>
      updateTrackedBoard(board.id, { active: !board.active }),
    onSuccess: invalidate,
  })
  const remove = useMutation({
    mutationFn: (id: number) => deleteTrackedBoard(id),
    onSuccess: invalidate,
  })

  function handleCreate(event: React.FormEvent) {
    event.preventDefault()
    create.mutate({
      kind,
      company_name: companyName,
      company_slug: kind === 'url_only' ? undefined : companySlug || undefined,
      url: kind === 'url_only' ? url || undefined : undefined,
    })
  }

  return (
    <>
      <form onSubmit={handleCreate} className="mb-4 flex flex-wrap items-end gap-2">
        <label className="flex flex-col text-sm">
          Kind
          <select value={kind} onChange={(e) => setKind(e.target.value)} className={fieldClass}>
            {BOARD_KINDS.map((k) => (
              <option key={k} value={k}>
                {k}
              </option>
            ))}
          </select>
        </label>
        <label className="flex flex-col text-sm">
          Company name
          <input
            value={companyName}
            onChange={(e) => setCompanyName(e.target.value)}
            required
            className={fieldClass}
          />
        </label>
        {kind === 'url_only' ? (
          <label className="flex flex-col text-sm">
            URL
            <input value={url} onChange={(e) => setUrl(e.target.value)} className={fieldClass} />
          </label>
        ) : (
          <label className="flex flex-col text-sm">
            Company slug
            <input
              value={companySlug}
              onChange={(e) => setCompanySlug(e.target.value)}
              className={fieldClass}
            />
          </label>
        )}
        <button
          type="submit"
          disabled={create.isPending}
          className="rounded bg-accent px-3 py-1.5 text-sm text-accent-contrast disabled:cursor-default disabled:opacity-60"
        >
          Track board
        </button>
      </form>
      {createError && <p role="alert">{createError}</p>}

      {isLoading && <p>Loading tracked boards…</p>}
      {isError && <p role="alert">Failed to load tracked boards: {(error as Error).message}</p>}
      {data && data.length === 0 && <p>No tracked boards yet.</p>}
      {data && data.length > 0 && (
        <TableScroll>
          <DataTable>
            <caption className="mb-2 text-muted">Tracked boards</caption>
            <thead>
              <tr>
                <th className={th}>Company</th>
                <th className={th}>Kind</th>
                <th className={th}>Slug / URL</th>
                <th className={th}>Active</th>
                <th className={th}>Actions</th>
              </tr>
            </thead>
            <tbody>
              {data.map((board) => (
                <tr key={board.id}>
                  <td className={th}>{board.company_name}</td>
                  <td className={th}>{board.kind}</td>
                  <td className={th}>{board.company_slug ?? board.url ?? '—'}</td>
                  <td className={th}>{board.active ? 'Yes' : 'No'}</td>
                  <td className={th}>
                    <div className="flex flex-wrap gap-2">
                      <button
                        type="button"
                        onClick={() => toggleActive.mutate(board)}
                        disabled={toggleActive.isPending}
                        className="rounded border border-border px-2 py-1 text-sm disabled:cursor-default disabled:opacity-60"
                      >
                        {board.active ? 'Deactivate' : 'Activate'}
                      </button>
                      <button
                        type="button"
                        onClick={() => {
                          if (confirm(`Delete tracked board "${board.company_name}"?`)) {
                            remove.mutate(board.id)
                          }
                        }}
                        disabled={remove.isPending}
                        className="rounded border border-danger px-2 py-1 text-sm text-danger disabled:cursor-default disabled:opacity-60"
                      >
                        Delete
                      </button>
                    </div>
                  </td>
                </tr>
              ))}
            </tbody>
          </DataTable>
        </TableScroll>
      )}
    </>
  )
}

function RevisionsSection() {
  const queryClient = useQueryClient()
  const { data, isLoading, isError, error } = useQuery({
    queryKey: ['revisions'],
    queryFn: listRevisions,
  })
  const remove = useMutation({
    mutationFn: (id: string) => deleteRevision(id),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ['revisions'] }),
  })

  if (isLoading) return <p>Loading revisions…</p>
  if (isError) return <p role="alert">Failed to load revisions: {(error as Error).message}</p>
  if (!data || data.length === 0) return <p>No tailored CV revisions yet.</p>

  return (
    <TableScroll>
      <DataTable>
        <caption className="mb-2 text-muted">Tailored CV revisions</caption>
        <thead>
          <tr>
            <th className={th}>Name</th>
            <th className={th}>Created</th>
            <th className={th}>Size</th>
            <th className={th}>Actions</th>
          </tr>
        </thead>
        <tbody>
          {data.map((revision) => (
            <tr key={revision.id}>
              <td className={th}>{revision.name}</td>
              <td className={th}>{new Date(revision.created_at).toLocaleString()}</td>
              <td className={th}>{revision.size_bytes.toLocaleString()} bytes</td>
              <td className={th}>
                <button
                  type="button"
                  onClick={() => {
                    if (confirm(`Delete revision "${revision.name}"?`)) {
                      remove.mutate(revision.id)
                    }
                  }}
                  disabled={remove.isPending}
                  className="rounded border border-danger px-2 py-1 text-sm text-danger disabled:cursor-default disabled:opacity-60"
                >
                  Delete
                </button>
              </td>
            </tr>
          ))}
        </tbody>
      </DataTable>
    </TableScroll>
  )
}

function JobPostingsSection() {
  const queryClient = useQueryClient()
  const { data, isLoading, isError, error } = useQuery({
    queryKey: ['postings'],
    queryFn: listPostings,
  })
  const remove = useMutation({
    mutationFn: (id: number) => deletePosting(id),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ['postings'] }),
  })

  if (isLoading) return <p>Loading job postings…</p>
  if (isError) return <p role="alert">Failed to load job postings: {(error as Error).message}</p>
  if (!data || data.length === 0) return <p>No job postings stored yet.</p>

  return (
    <TableScroll>
      <DataTable>
        <caption className="mb-2 text-muted">Stored job postings</caption>
        <thead>
          <tr>
            <th className={th}>Title</th>
            <th className={th}>Company</th>
            <th className={th}>Source</th>
            <th className={th}>Status</th>
            <th className={th}>Actions</th>
          </tr>
        </thead>
        <tbody>
          {data.map((posting) => (
            <tr key={posting.id}>
              <td className={th}>{posting.title || `Posting ${posting.id}`}</td>
              <td className={th}>{posting.company || '—'}</td>
              <td className={th}>{posting.source}</td>
              <td className={th}>{posting.closed_at ? 'Closed' : 'Open'}</td>
              <td className={th}>
                <button
                  type="button"
                  onClick={() => {
                    if (confirm(`Delete posting "${posting.title || posting.id}"?`)) {
                      remove.mutate(posting.id)
                    }
                  }}
                  disabled={remove.isPending}
                  className="rounded border border-danger px-2 py-1 text-sm text-danger disabled:cursor-default disabled:opacity-60"
                >
                  Delete
                </button>
              </td>
            </tr>
          ))}
        </tbody>
      </DataTable>
    </TableScroll>
  )
}
