import { request } from './client.js';

export function submitReport(formData) {
  return request('/reports', { method: 'POST', body: formData });
}

export function analyzeReport(payload) {
  return request('/reports/analyze', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(payload),
  });
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

export function detectPotentialReportRelationships(reportId) {
  return request(`/reports/${encodeURIComponent(reportId)}/potential-relationships`, {
    method: 'POST',
  });
}

export function listReportRelationships(status = 'PROPOSED') {
  return request(`/report-relationships?status=${encodeURIComponent(status)}`);
}

export function decideReportRelationship(relationshipId, decision, reason = '') {
  return request(`/report-relationships/${encodeURIComponent(relationshipId)}/${decision}`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ reason: reason.trim() || null }),
  });
}

export function correctExtraction(reportId, facts) {
  return request(`/reports/${reportId}/extraction`, {
    method: 'PATCH',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ facts }),
  });
}

export function correctReportLocation(reportId, location) {
  return request(`/reports/${reportId}/location`, {
    method: 'PATCH',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(location),
  });
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

export function reopenDismissedReport(reportId, reason) {
  return request(`/reports/${encodeURIComponent(reportId)}/reopen`, {
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

export function closeIncident(incidentId, reason) {
  return request(`/incidents/${encodeURIComponent(incidentId)}/close`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ reason }),
  });
}

export function reopenIncident(incidentId, reason) {
  return request(`/incidents/${encodeURIComponent(incidentId)}/reopen`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ reason }),
  });
}

export function getIncidentImpactArea(incidentId) {
  return request(`/incidents/${encodeURIComponent(incidentId)}/impact-area`);
}

export function listNearbyResources(incidentId, statuses = ['AVAILABLE']) {
  const query = new URLSearchParams();
  statuses.forEach((status) => query.append('status', status));
  return request(`/incidents/${encodeURIComponent(incidentId)}/resources?${query}`);
}

export function linkReportToIncident(incidentId, reportId, reason) {
  return request(`/incidents/${incidentId}/reports/${reportId}/link`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ reason }),
  });
}

export function unlinkReportFromIncident(incidentId, reportId, reason) {
  return request(`/incidents/${incidentId}/reports/${reportId}/unlink`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ reason }),
  });
}

export function deleteReport(reportId, reason) {
  return request(`/reports/${encodeURIComponent(reportId)}`, {
    method: 'DELETE',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ reason }),
  });
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

export function assignResponsePlanResources(planId, resourceIds, reason) {
  return request(`/response-plans/${encodeURIComponent(planId)}/assignments`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ resource_ids: resourceIds, reason }),
  });
}

export function releaseResponsePlanAssignment(planId, assignmentId, reason) {
  return request(
    `/response-plans/${encodeURIComponent(planId)}/assignments/${encodeURIComponent(assignmentId)}/release`,
    {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ reason }),
    },
  );
}