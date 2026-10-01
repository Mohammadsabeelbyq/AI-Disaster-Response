import { request } from './client.js';

export function getCurrentUser() {
  return request('/auth/me');
}

export function login(email, password, role) {
  return request('/auth/login', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ email, password, role }),
  });
}

export function logout() {
  return request('/auth/logout', { method: 'POST' });
}