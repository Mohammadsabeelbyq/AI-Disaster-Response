const PRIORITY_RADIUS = {
  LOW: 9,
  MEDIUM: 12,
  HIGH: 15,
  CRITICAL: 18,
};

export function getMappableIncidents(incidents) {
  return incidents.filter(({ report }) => {
    if (report?.latitude === null || report?.latitude === undefined || report.latitude === '') return false;
    if (report?.longitude === null || report?.longitude === undefined || report.longitude === '') return false;
    const latitude = Number(report.latitude);
    const longitude = Number(report.longitude);
    return Number.isFinite(latitude) && Number.isFinite(longitude)
      && latitude >= -90 && latitude <= 90
      && longitude >= -180 && longitude <= 180;
  });
}

export function getMarkerPresentation(incident) {
  const status = String(incident.status || 'UNKNOWN').toUpperCase();
  const priority = String(incident.priority_band || '').toUpperCase();
  const statusClass = /^[A-Z0-9_-]+$/.test(status) ? status.toLowerCase() : 'unknown';
  const priorityClass = Object.hasOwn(PRIORITY_RADIUS, priority) ? priority.toLowerCase() : 'unrated';
  return {
    statusClass,
    priorityClass,
    radius: PRIORITY_RADIUS[priority] || 10,
  };
}