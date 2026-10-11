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

export function getImpactArea(incidentId) {
  return request(`/incidents/${incidentId}/impact-area`);
}

export function saveImpactArea(incidentId, impactArea) {
  return request(`/incidents/${incidentId}/impact-area`, {
    method: 'PUT',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(impactArea),
  });
}

export function findNearbyResources(incidentId) {
  return request(`/incidents/${incidentId}/resources`);
}

export function registerResource(resource) {
  return request('/resources', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(resource),
  });
}

export function updateResource(resourceId, resource) {
  return request(`/resources/${resourceId}`, {
    method: 'PUT',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(resource),
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