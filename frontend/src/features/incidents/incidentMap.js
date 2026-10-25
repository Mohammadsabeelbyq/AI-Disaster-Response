export const PRIORITY_LEVELS = [
  { band: 'LOW', label: 'Low', className: 'low', radius: 9, color: '#FECACA', textColor: '#7F1D1D' },
  { band: 'MEDIUM', label: 'Medium', className: 'medium', radius: 12, color: '#F87171', textColor: '#3F0D0D' },
  { band: 'HIGH', label: 'High', className: 'high', radius: 15, color: '#B91C1C', textColor: '#FFFFFF' },
  { band: 'CRITICAL', label: 'Critical', className: 'critical', radius: 18, color: '#7F1D1D', textColor: '#FFFFFF' },
];

const PRIORITY_BY_BAND = Object.fromEntries(PRIORITY_LEVELS.map((priority) => [priority.band, priority]));
const UNRATED_PRIORITY = {
  band: 'UNRATED',
  label: 'Unrated',
  className: 'unrated',
  radius: 10,
  color: '#78837D',
  textColor: '#FFFFFF',
};

export function getPriorityPresentation(priorityBand) {
  const band = String(priorityBand || '').toUpperCase();
  return Object.hasOwn(PRIORITY_BY_BAND, band) ? PRIORITY_BY_BAND[band] : UNRATED_PRIORITY;
}

function numericCoordinate(value) {
  if (typeof value === 'number') return Number.isFinite(value) ? value : null;
  if (typeof value !== 'string' || !value.trim()) return null;
  const coordinate = Number(value);
  return Number.isFinite(coordinate) ? coordinate : null;
}

export function getIncidentCoordinates(incident) {
  const latitude = numericCoordinate(incident?.report?.latitude);
  const longitude = numericCoordinate(incident?.report?.longitude);
  if (latitude === null || longitude === null
      || latitude < -90 || latitude > 90
      || longitude < -180 || longitude > 180) {
    return null;
  }
  return [latitude, longitude];
}

export function getMappableIncidents(incidents) {
  if (!Array.isArray(incidents)) return [];
  return incidents.filter((incident) => getIncidentCoordinates(incident) !== null);
}

export function mergeReportsWithIncidents(reports, incidents) {
  const savedReports = Array.isArray(reports) ? reports : [];
  const confirmedIncidents = Array.isArray(incidents) ? incidents : [];
  const incidentsByReportId = new Map(
    confirmedIncidents.map((incident) => [incident.report_id, incident]),
  );
  const reportIds = new Set();
  const reportRecords = savedReports
    .filter((report) => report.status !== 'DISMISSED')
    .map((report) => {
      reportIds.add(report.id);
      const incident = incidentsByReportId.get(report.id);
      if (incident) return incident;
      return {
        id: report.id,
        report_id: report.id,
        status: report.status,
        priority_band: null,
        priority_score: null,
        priority_is_overridden: false,
        report: {
          id: report.id,
          disaster_type: report.disaster_type,
          description: report.description,
          latitude: report.latitude,
          longitude: report.longitude,
          location_name: report.location_name,
        },
      };
    });

  const incidentRecordsWithoutReport = confirmedIncidents.filter(
    (incident) => !reportIds.has(incident.report_id),
  );
  return [...reportRecords, ...incidentRecordsWithoutReport];
}

export function getMarkerPresentation(incident) {
  const status = String(incident?.status || 'UNKNOWN').toUpperCase();
  const statusClass = /^[A-Z0-9_-]+$/.test(status) ? status.toLowerCase() : 'unknown';
  const priority = getPriorityPresentation(incident?.priority_band);
  const awaitingDecision = priority.className === 'unrated'
    && ['SUBMITTED', 'UNDER_REVIEW'].includes(status);
  return {
    statusClass,
    priorityClass: priority.className,
    priorityLabel: awaitingDecision ? 'Awaiting decision' : priority.label,
    priorityColor: priority.color,
    priorityTextColor: priority.textColor,
    radius: priority.radius,
  };
}