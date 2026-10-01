import { request } from './client.js';

export function submitReport(formData) {
  return request('/reports', { method: 'POST', body: formData });
}

export function importReports(kind, content) {
  return request(`/reports/import/${kind}`, {
    method: 'POST',
    headers: { 'Content-Type': kind === 'json' ? 'application/json' : 'text/csv' },
    body: content,
  });
}