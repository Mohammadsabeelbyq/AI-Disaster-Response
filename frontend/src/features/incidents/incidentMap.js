export const PRIORITY_LEVELS = [
  { band: 'LOW', label: 'Low', className: 'low', radius: 9, color: '#FECACA', textColor: '#7F1D1D' },
  { band: 'MEDIUM', label: 'Medium', className: 'medium', radius: 12, color: '#F87171', textColor: '#3F0D0D' },
  { band: 'HIGH', label: 'High', className: 'high', radius: 15, color: '#B91C1C', textColor: '#FFFFFF' },
  { band: 'CRITICAL', label: 'Critical', className: 'critical', radius: 18, color: '#7F1D1D', textColor: '#FFFFFF' },
];

const PRIORITY_BY_BAND = Object.fromEntries(PRIORITY_LEVELS.map((priority) => [priority.band, priority]));
const PRIORITY_RANK = { LOW: 1, MEDIUM: 2, HIGH: 3, CRITICAL: 4 };
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

export function findIncidentRecord(incidents, contextId) {
  if (!Array.isArray(incidents) || !contextId) return null;
  return incidents.find((incident) => (
    incident?.id === contextId || incident?.report_id === contextId
  )) || null;
}

export function findReportForContext(reports, { incidentId, reportId } = {}) {
  if (!Array.isArray(reports)) return null;
  return reports.find((report) => report.id === reportId)
    || reports.find((report) => report.incident?.id === incidentId)
    || null;
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
          latitude: report.location_correction?.latitude ?? report.latitude,
          longitude: report.location_correction?.longitude ?? report.longitude,
          location_name: report.location_correction?.location_name ?? report.location_name,
          submitted_at: report.submitted_at,
        },
      };
    });

  const incidentRecordsWithoutReport = confirmedIncidents.filter(
    (incident) => !reportIds.has(incident.report_id),
  );
  return [...reportRecords, ...incidentRecordsWithoutReport];
}

function incidentTimestamp(incident) {
  const timestamp = incident?.confirmed_at || incident?.report?.submitted_at;
  const parsed = Date.parse(timestamp);
  return Number.isFinite(parsed) ? parsed : null;
}

export function filterAndSortIncidents(incidents, {
  status = 'ALL',
  type = 'ALL',
  timeRange = 'ALL',
  sortBy = 'NEWEST',
  now = Date.now(),
} = {}) {
  const rangeMs = { '24H': 24 * 60 * 60 * 1000, '7D': 7 * 24 * 60 * 60 * 1000, '30D': 30 * 24 * 60 * 60 * 1000 }[timeRange];
  const normalizedStatus = String(status || 'ALL').toUpperCase();
  const normalizedType = String(type || 'ALL').toUpperCase();
  const filtered = (Array.isArray(incidents) ? incidents : []).filter((incident) => {
    if (normalizedStatus !== 'ALL' && String(incident?.status || '').toUpperCase() !== normalizedStatus) return false;
    if (normalizedType !== 'ALL' && String(incident?.report?.disaster_type || '').toUpperCase() !== normalizedType) return false;
    if (rangeMs !== undefined) {
      const timestamp = incidentTimestamp(incident);
      if (timestamp === null || timestamp < now - rangeMs) return false;
    }
    return true;
  });

  return filtered.sort((first, second) => {
    if (sortBy === 'PRIORITY_HIGH' || sortBy === 'PRIORITY_LOW') {
      const firstRank = PRIORITY_RANK[String(first?.priority_band || '').toUpperCase()] || 0;
      const secondRank = PRIORITY_RANK[String(second?.priority_band || '').toUpperCase()] || 0;
      if ((firstRank === 0) !== (secondRank === 0)) return firstRank === 0 ? 1 : -1;
      const direction = sortBy === 'PRIORITY_HIGH' ? -1 : 1;
      const rankDifference = (firstRank - secondRank) * direction;
      if (rankDifference) return rankDifference;
      const scoreDifference = (Number(first?.priority_score) || 0) - (Number(second?.priority_score) || 0);
      if (scoreDifference) return scoreDifference * direction;
    } else {
      const firstTime = incidentTimestamp(first);
      const secondTime = incidentTimestamp(second);
      if ((firstTime === null) !== (secondTime === null)) return firstTime === null ? 1 : -1;
      if (firstTime !== null && secondTime !== null && firstTime !== secondTime) {
        return (firstTime - secondTime) * (sortBy === 'OLDEST' ? 1 : -1);
      }
    }
    return 0;
  });
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