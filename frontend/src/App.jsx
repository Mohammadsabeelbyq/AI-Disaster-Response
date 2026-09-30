import { Navigate, Route, Routes } from 'react-router-dom';
import AppShell from './components/AppShell.jsx';
import ImportPage from './features/reports/ImportPage.jsx';
import ReportFormPage from './features/reports/ReportFormPage.jsx';

export default function App() {
  return (
    <AppShell>
      <Routes>
        <Route path="/" element={<ReportFormPage />} />
        <Route path="/report-form" element={<Navigate to="/intake" replace />} />
        <Route path="/intake" element={<ReportFormPage />} />
        <Route path="/import" element={<ImportPage />} />
        <Route path="*" element={<Navigate to="/" replace />} />
      </Routes>
    </AppShell>
  );
}