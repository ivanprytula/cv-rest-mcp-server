import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { BrowserRouter, Route, Routes } from 'react-router-dom'
import { AuthProvider } from './auth/AuthContext'
import RequireAuth from './auth/RequireAuth'
import AdminShell from './routes/AdminShell'
import CvIntake from './routes/CvIntake'
import Login from './routes/Login'
import NewPosting from './routes/NewPosting'
import Onboarding from './routes/Onboarding'
import PostingReport from './routes/PostingReport'
import Postings from './routes/Postings'
import Register from './routes/Register'
import RevisionPreview from './routes/RevisionPreview'
import Revisions from './routes/Revisions'
import Roadmap from './routes/Roadmap'
import { ThemeProvider } from './theme/ThemeContext'

const queryClient = new QueryClient()

export default function App() {
  return (
    <QueryClientProvider client={queryClient}>
      <ThemeProvider>
        <AuthProvider>
          <BrowserRouter>
            <Routes>
              <Route path="/login" element={<Login />} />
              <Route path="/register" element={<Register />} />
              <Route
                path="/"
                element={
                  <RequireAuth>
                    <AdminShell />
                  </RequireAuth>
                }
              >
                <Route index element={<Revisions />} />
                <Route path="onboarding" element={<Onboarding />} />
                <Route path="revisions/:id" element={<RevisionPreview />} />
                <Route path="cv/import" element={<CvIntake />} />
                <Route path="roadmap" element={<Roadmap />} />
                <Route path="postings" element={<Postings />} />
                <Route path="postings/new" element={<NewPosting />} />
                <Route path="postings/:id" element={<PostingReport />} />
              </Route>
            </Routes>
          </BrowserRouter>
        </AuthProvider>
      </ThemeProvider>
    </QueryClientProvider>
  )
}
