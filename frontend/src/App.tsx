import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { BrowserRouter, Route, Routes } from 'react-router-dom'
import { AuthProvider } from './auth/AuthContext'
import RequireAuth from './auth/RequireAuth'
import AdminShell from './routes/AdminShell'
import Login from './routes/Login'
import PostingReport from './routes/PostingReport'
import Postings from './routes/Postings'
import RevisionPreview from './routes/RevisionPreview'
import Revisions from './routes/Revisions'
import Roadmap from './routes/Roadmap'

const queryClient = new QueryClient()

export default function App() {
  return (
    <QueryClientProvider client={queryClient}>
      <AuthProvider>
        <BrowserRouter>
          <Routes>
            <Route path="/login" element={<Login />} />
            <Route
              path="/"
              element={
                <RequireAuth>
                  <AdminShell />
                </RequireAuth>
              }
            >
              <Route index element={<Revisions />} />
              <Route path="revisions/:id" element={<RevisionPreview />} />
              <Route path="roadmap" element={<Roadmap />} />
              <Route path="postings" element={<Postings />} />
              <Route path="postings/:id" element={<PostingReport />} />
            </Route>
          </Routes>
        </BrowserRouter>
      </AuthProvider>
    </QueryClientProvider>
  )
}
