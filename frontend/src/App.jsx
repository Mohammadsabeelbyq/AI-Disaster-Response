import { Navigate, Outlet, Route, Routes } from 'react-router-dom';
import AppShell from './components/AppShell.jsx';
import { useAuth } from './features/auth/AuthProvider.jsx';
import LoginPage from './features/auth/LoginPage.jsx';
import ImportPage from './features/reports/ImportPage.jsx';
import ReportFormPage from './features/reports/ReportFormPage.jsx';
import ReviewPage from './features/reports/ReviewPage.jsx';
import PriorityPolicyPage from './features/admin/PriorityPolicyPage.jsx';
import IncidentMapPage from './features/incidents/IncidentMapPage.jsx';

export default function App() {
  const { user, loading, signOut } = useAuth();

  if (loading) {
    return <AppShell><div className="auth-loading" role="status">Checking your session…</div></AppShell>;
  }

  return (
    <AppShell user={user} onSignOut={signOut}>
      <Routes>
        <Route path="/login" element={user ? <Navigate to="/" replace /> : <LoginPage />} />
        <Route element={user ? <Outlet /> : <Navigate to="/login" replace />}>
          <Route path="/" element={<ReportFormPage />} />
          <Route path="/report-form" element={<Navigate to="/intake" replace />} />
          <Route path="/intake" element={<ReportFormPage />} />
          <Route path="/import" element={<ImportPage />} />
          {(user?.role === 'MANAGEMENT' || user?.role === 'ADMIN') && (
            <Route path="/review" element={<ReviewPage />} />
          )}
          {(user?.role === 'MANAGEMENT' || user?.role === 'ADMIN') && (
            <Route path="/incidents/map" element={<IncidentMapPage />} />
          )}
          {user?.role === 'ADMIN' && (
            <Route path="/admin/priority-policy" element={<PriorityPolicyPage />} />
          )}
        </Route>
        <Route path="*" element={<Navigate to={user ? '/' : '/login'} replace />} />
      </Routes>
    </AppShell>
  );
}