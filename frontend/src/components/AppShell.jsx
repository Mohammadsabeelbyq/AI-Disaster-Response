import { Activity, ClipboardCheck, FileJson2, FileText, LogOut, Map as MapIcon, SlidersHorizontal } from 'lucide-react';
import { NavLink, useLocation } from 'react-router-dom';

export default function AppShell({ children, user = null, onSignOut }) {
  const location = useLocation();
  const isImport = location.pathname === '/import';
  const isReview = location.pathname === '/review';
  const isIncidentMap = location.pathname === '/incidents/map';
  const isPriorityPolicy = location.pathname === '/admin/priority-policy';

  return (
    <div className="intake-app">
      <header className="intake-header">
        <NavLink className="brand" to="/" aria-label="Incident intake">
          <span className="brand__mark"><Activity size={20} strokeWidth={2.2} /></span>
          <span className="brand__words"><strong>INCIDENT INTAKE</strong><small>REPORT & MEDIA MODULE</small></span>
        </NavLink>
        {user && (
          <div className="intake-header__tools">
            <nav className="mode-switch" aria-label="Submission method">
              <NavLink to="/" className={!isImport ? 'mode-switch__link mode-switch__link--active' : 'mode-switch__link'}>
                <FileText size={16} />Web form
              </NavLink>
              <NavLink to="/import" className={isImport ? 'mode-switch__link mode-switch__link--active' : 'mode-switch__link'}>
                <FileJson2 size={16} />JSON / CSV
              </NavLink>
              {(user.role === 'MANAGEMENT' || user.role === 'ADMIN') && (
                <NavLink to="/review" className={isReview ? 'mode-switch__link mode-switch__link--active' : 'mode-switch__link'}>
                  <ClipboardCheck size={16} />Review
                </NavLink>
              )}
              {(user.role === 'MANAGEMENT' || user.role === 'ADMIN') && (
                <NavLink to="/incidents/map" className={isIncidentMap ? 'mode-switch__link mode-switch__link--active' : 'mode-switch__link'}>
                  <MapIcon size={16} />Incident map
                </NavLink>
              )}
              {user.role === 'ADMIN' && (
                <NavLink to="/admin/priority-policy" className={isPriorityPolicy ? 'mode-switch__link mode-switch__link--active' : 'mode-switch__link'}>
                  <SlidersHorizontal size={16} />Priority policy
                </NavLink>
              )}
            </nav>
            <div className="account-menu">
              <span className="account-role">{user.role === 'MANAGEMENT' ? 'COORDINATOR' : user.role}</span>
              <button className="header-link header-link--button" type="button" onClick={onSignOut}>
                <LogOut size={16} />Sign out
              </button>
            </div>
          </div>
        )}
      </header>
      <main className="page-content">{children}</main>
      <footer className="page-footer">INCIDENT REPORTING <span>·</span> INTAKE</footer>
    </div>
  );
}