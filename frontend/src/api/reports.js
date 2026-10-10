import { request } from './client.js';

export function submitReport(formData) {
  return request('/reports', { method: 'POST', body: formData });
}

export function getReport(reportId) {
  return request(`/reports/${encodeURIComponent(reportId)}`);
}

export function importReports(kind, content) {
  return request(`/reports/import/${kind}`, {
    method: 'POST',
    headers: { 'Content-Type': kind === 'json' ? 'application/json' : 'text/csv' },
    body: content,
  });
}

export function listReports() {
  return request('/reports?limit=200');
}

export function correctExtraction(reportId, facts) {
  return request(`/reports/${reportId}/extraction`, {
    method: 'PATCH',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ facts }),
  });
}

export function startReportReview(reportId) {
  return request(`/reports/${reportId}/review`, { method: 'POST' });
}

export function confirmReport(reportId) {
  return request(`/reports/${reportId}/confirm`, { method: 'POST' });
}

export function dismissReport(reportId, reason) {
  return request(`/reports/${reportId}/dismiss`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ reason }),
  });
}

export function getIncident(incidentId) {
  return request(`/incidents/${incidentId}`);
}

export function listIncidents() {
  return request('/incidents');
}

export function getIncidentPriority(incidentId) {
  return request(`/incidents/${incidentId}/priority`);
}

export function overrideIncidentPriority(incidentId, { reason, score, band }) {
  return request(`/incidents/${incidentId}/priority/override`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ reason, score, band }),
  });
}

export function generateResponsePlan(incidentId) {
  return request(`/incidents/${incidentId}/plans`, { method: 'POST' });
}

export function approveResponsePlan(planId, reason) {
  return request(`/response-plans/${planId}/approve`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ reason }),
  });
}

export function rejectResponsePlan(planId, reason) {
  return request(`/response-plans/${planId}/reject`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ reason }),
  });
}