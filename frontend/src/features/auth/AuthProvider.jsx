import { createContext, useContext, useEffect, useState } from 'react';
import { getCurrentUser, login as loginRequest, logout as logoutRequest } from '../../api/auth.js';

const AuthContext = createContext(null);

export function AuthProvider({ children }) {
  const [user, setUser] = useState(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    let active = true;
    getCurrentUser()
      .then((currentUser) => active && setUser(currentUser))
      .catch(() => active && setUser(null))
      .finally(() => active && setLoading(false));
    return () => { active = false; };
  }, []);

  async function signIn(email, password, role) {
    const currentUser = await loginRequest(email, password, role);
    setUser(currentUser);
    return currentUser;
  }

  async function signOut() {
    try {
      await logoutRequest();
    } finally {
      setUser(null);
    }
  }

  return (
    <AuthContext.Provider value={{ user, loading, signIn, signOut }}>
      {children}
    </AuthContext.Provider>
  );
}

export function useAuth() {
  const context = useContext(AuthContext);
  if (!context) throw new Error('useAuth must be used inside AuthProvider.');
  return context;
}