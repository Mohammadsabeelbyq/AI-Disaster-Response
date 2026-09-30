import { Activity, FileJson2, FileText } from 'lucide-react';
import { NavLink, useLocation } from 'react-router-dom';

export default function AppShell({ children }) {
  const location = useLocation();
  const isImport = location.pathname === '/import';

  return (
    <div className="intake-app">
      <header className="intake-header">
        <NavLink className="brand" to="/" aria-label="Incident intake">
          <span className="brand__mark"><Activity size={20} strokeWidth={2.2} /></span>
          <span className="brand__words"><strong>INCIDENT INTAKE</strong><small>REPORT & MEDIA MODULE</small></span>
        </NavLink>
        <nav className="mode-switch" aria-label="Submission method">
          <NavLink to="/" className={!isImport ? 'mode-switch__link mode-switch__link--active' : 'mode-switch__link'}>
            <FileText size={16} />Web form
          </NavLink>
          <NavLink to="/import" className={isImport ? 'mode-switch__link mode-switch__link--active' : 'mode-switch__link'}>
            <FileJson2 size={16} />JSON / CSV
          </NavLink>
        </nav>
      </header>
      <main className="page-content">{children}</main>
      <footer className="page-footer">INCIDENT REPORTING <span>·</span> INTAKE</footer>
    </div>
  );
}