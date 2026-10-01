import { useState } from 'react';
import { ArrowRight, KeyRound } from 'lucide-react';
import { useNavigate } from 'react-router-dom';
import { useAuth } from './AuthProvider.jsx';

const roles = [
  {
    id: 'USER',
    label: 'User',
    description: 'Report and observe',
    responsibilities: 'Submit incident reports with media, view public-safe incident updates, and access your own reports.',
    boundary: 'Cannot change official incident status, priority, resources, or assignments.',
  },
  {
    id: 'MANAGEMENT',
    label: 'Coordinator',
    description: 'Coordinate response',
    responsibilities: 'View departments and resources, review and update operational incidents, approve response plans, assign resources, and alert departments.',
    boundary: 'Operational actions require validation and audit; dispatch is not autonomous.',
  },
  {
    id: 'ADMIN',
    label: 'Admin',
    description: 'Administer platform',
    responsibilities: 'Manage users and roles, departments, resources, system rules, simulation, and audit access.',
    boundary: 'Administrative actions remain subject to system validation and audit.',
  },
];

export default function LoginPage() {
  const navigate = useNavigate();
  const { signIn } = useAuth();
  const [role, setRole] = useState('USER');
  const [status, setStatus] = useState('');
  const [submitting, setSubmitting] = useState(false);
  const selectedRole = roles.find((item) => item.id === role);

  async function handleSubmit(event) {
    event.preventDefault();
    setStatus('');
    setSubmitting(true);
    const formData = new FormData(event.currentTarget);
    try {
      await signIn(String(formData.get('email') || ''), String(formData.get('password') || ''), role);
      navigate('/', { replace: true });
    } catch (error) {
      setStatus(error.message);
    } finally {
      setSubmitting(false);
    }
  }

  return (
    <section className="login-page">
      <div className="login-heading">
        <div className="eyebrow"><span className="eyebrow__line" />ACCOUNT ACCESS</div>
        <h1>Sign in<span className="heading-period">.</span></h1>
        <p>Choose your account role and sign in to continue.</p>
      </div>

      <div className="panel login-panel">
        <div className="login-panel__top">
          <span className="login-icon"><KeyRound size={19} /></span>
          <div><strong>Welcome back</strong><span>Continue to your workspace</span></div>
        </div>

        <div className="role-picker" role="group" aria-label="Choose account role">
          {roles.map((item) => (
            <button
              key={item.id}
              className={`role-option${role === item.id ? ' role-option--active' : ''}`}
              type="button"
              aria-pressed={role === item.id}
              onClick={() => { setRole(item.id); setStatus(''); }}
            >
              <strong>{item.label}</strong>
              <small>{item.description}</small>
            </button>
          ))}
        </div>
        <div className="role-contract">Application role: <code>{role}</code></div>
        <div className="login-role-details" aria-live="polite">
          <p>{selectedRole.responsibilities}</p>
          <small>{selectedRole.boundary}</small>
        </div>

        <form className="login-form" onSubmit={handleSubmit}>
          <label className="field">
            <span>Email address</span>
            <input name="email" type="email" autoComplete="username" placeholder="name@example.com" required />
          </label>
          <label className="field">
            <span>Password</span>
            <input name="password" type="password" autoComplete="current-password" placeholder="Enter your password" required />
          </label>
          <button className="button button--primary login-submit" type="submit" disabled={submitting}>
            {submitting ? 'Signing in…' : 'Sign in'} <ArrowRight size={16} />
          </button>
        </form>

        {status && <div className="notice notice--error login-status" role="alert">{status}</div>}
        <p className="login-prototype-note">Sign-in is verified by the backend. Coordinator and administration workspaces will be added with their modules.</p>
      </div>
    </section>
  );
}