import { request } from './client.js';

export function listDepartments({ activeOnly = false } = {}) {
  return request(`/departments${activeOnly ? '?active_only=true' : ''}`);
}

export function createDepartment(payload) {
  return request('/departments', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(payload),
  });
}

export function updateDepartment(departmentId, payload) {
  return request(`/departments/${departmentId}`, {
    method: 'PATCH',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(payload),
  });
}

export function listResources(filters = {}) {
  const query = new URLSearchParams();
  if (filters.departmentId) query.set('department_id', filters.departmentId);
  if (filters.availability) query.set('availability', filters.availability);
  return request(`/resources${query.size ? `?${query}` : ''}`);
}

export function createResource(payload) {
  return request('/resources', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(payload),
  });
}

export function updateResource(resourceId, payload) {
  return request(`/resources/${resourceId}`, {
    method: 'PATCH',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(payload),
  });
}

export function updateResourceAvailability(resourceId, availability, reason) {
  return request(`/resources/${resourceId}/availability`, {
    method: 'PATCH',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ availability, reason }),
  });
}
