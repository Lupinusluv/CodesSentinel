import { BrowserRouter, Routes, Route, Navigate } from 'react-router-dom'
import { Layout }       from './components/Layout'
import { NewReview }    from './pages/NewReview'
import { Dashboard }    from './pages/Dashboard'
import { ReviewDetail } from './pages/ReviewDetail'
import { Repositories } from './pages/Repositories'
import { Metrics }      from './pages/Metrics'

export default function App() {
  return (
    <BrowserRouter>
      <Routes>
        <Route element={<Layout />}>
          <Route index             element={<NewReview />}    />
          <Route path="dashboard"  element={<Dashboard />}    />
          <Route path="review/:reviewId" element={<ReviewDetail />} />
          <Route path="repositories" element={<Repositories />} />
          <Route path="metrics"    element={<Metrics />}      />
          <Route path="*"          element={<Navigate to="/" replace />} />
        </Route>
      </Routes>
    </BrowserRouter>
  )
}
