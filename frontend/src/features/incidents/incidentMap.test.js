import assert from 'node:assert/strict';
import test from 'node:test';
import {
  filterAndSortIncidents,
  findIncidentRecord,
  findReportForContext,
  getIncidentCoordinates,
  getMappableIncidents,
  getMarkerPresentation,
  getPriorityPresentation,
  mergeReportsWithIncidents,
  PRIORITY_LEVELS,
} from './incidentMap.js';

function relativeLuminance(hexColor) {
  const channels = hexColor.slice(1).match(/.{2}/g).map((channel) => parseInt(channel, 16) / 255);
  const linear = channels.map((channel) => channel <= 0.04045
    ? channel / 12.92
    : ((channel + 0.055) / 1.055) ** 2.4);
  return (0.2126 * linear[0]) + (0.7152 * linear[1]) + (0.0722 * linear[2]);
}

function contrastRatio(first, second) {
  const luminances = [relativeLuminance(first), relativeLuminance(second)].sort((a, b) => b - a);
  return (luminances[0] + 0.05) / (luminances[1] + 0.05);
}

test('maps multiple coordinate-only and addressed incidents in latitude-longitude order', () => {
  const withoutAddress = { id: 'no-address', report: { latitude: '10.027', longitude: '76.308' } };
  const withAddress = { id: 'with-address', report: {
    latitude: 47.6062, longitude: -122.3321, location_name: 'Seattle',
  } };
  const incidents = [withoutAddress, withAddress];

  assert.deepEqual(getMappableIncidents(incidents), incidents);
  assert.deepEqual(getIncidentCoordinates(withoutAddress), [10.027, 76.308]);
  assert.deepEqual(getIncidentCoordinates(withAddress), [47.6062, -122.3321]);
});

test('excludes missing, blank, non-numeric, and out-of-range coordinates safely', () => {
  const incidents = [
    { id: 'missing', report: { latitude: null, longitude: 76 } },
    { id: 'invalid', report: { latitude: 91, longitude: 0 } },
    { id: 'non-finite', report: { latitude: 'NaN', longitude: 0 } },
    { id: 'blank', report: { latitude: ' ', longitude: '0' } },
    { id: 'boolean', report: { latitude: true, longitude: 0 } },
    { id: 'longitude-out-of-range', report: { latitude: 0, longitude: 180.1 } },
    null,
  ];

  assert.deepEqual(getMappableIncidents(incidents), []);
  assert.equal(getIncidentCoordinates(null), null);
  assert.equal(getIncidentCoordinates({ report: { latitude: 0 } }), null);
});

test('shows saved reports immediately and replaces confirmed reports without duplicates', () => {
  const report = {
    id: 'report-1',
    status: 'SUBMITTED',
    disaster_type: 'FLOOD',
    description: 'Water rising',
    latitude: 15,
    longitude: 20,
    location_name: null,
    submitted_at: '2026-10-31T12:00:00Z',
  };
  const confirmed = {
    id: 'incident-1',
    report_id: 'report-1',
    status: 'CONFIRMED',
    priority_band: 'HIGH',
    report: { id: 'report-1', latitude: 15, longitude: 20 },
  };
  const dismissed = { ...report, id: 'report-dismissed', status: 'DISMISSED' };

  const submittedRecords = mergeReportsWithIncidents([report, dismissed], []);
  assert.equal(submittedRecords.length, 1);
  assert.equal(submittedRecords[0].status, 'SUBMITTED');
  assert.deepEqual(getIncidentCoordinates(submittedRecords[0]), [15, 20]);
  assert.equal(submittedRecords[0].priority_band, null);
  assert.equal(submittedRecords[0].report.submitted_at, report.submitted_at);

  const confirmedRecords = mergeReportsWithIncidents([report], [confirmed]);
  assert.deepEqual(confirmedRecords, [confirmed]);
  assert.equal(mergeReportsWithIncidents([], [confirmed]).length, 1);
});

test('resolves incident or report context IDs to the correct current record', () => {
  const records = [
    { id: 'report-1', report_id: 'report-1', status: 'SUBMITTED' },
    { id: 'incident-2', report_id: 'report-2', status: 'CONFIRMED' },
  ];

  assert.equal(findIncidentRecord(records, 'report-1'), records[0]);
  assert.equal(findIncidentRecord(records, 'incident-2'), records[1]);
  assert.equal(findIncidentRecord(records, 'report-2'), records[1]);
  assert.equal(findIncidentRecord(records, 'unknown'), null);
});

test('resolves report review context from either report ID or incident ID', () => {
  const reports = [
    { id: 'report-1', incident: null },
    { id: 'report-2', incident: { id: 'incident-2' } },
  ];

  assert.equal(findReportForContext(reports, { reportId: 'report-1' }), reports[0]);
  assert.equal(findReportForContext(reports, { incidentId: 'incident-2' }), reports[1]);
  assert.equal(findReportForContext(reports, { incidentId: 'unknown' }), null);
});

test('uses coordinator-corrected coordinates for submitted report map records', () => {
  const report = {
    id: 'report-corrected',
    status: 'SUBMITTED',
    disaster_type: 'FLOOD',
    description: 'Water rising',
    latitude: 10,
    longitude: 76,
    location_name: 'Submitted location',
    location_correction: {
      latitude: 11,
      longitude: 77,
      location_name: 'Corrected location',
    },
  };

  const [record] = mergeReportsWithIncidents([report], []);
  assert.deepEqual(getIncidentCoordinates(record), [11, 77]);
  assert.equal(record.report.location_name, 'Corrected location');
});

test('filters the incident queue by status, type, and time period', () => {
  const now = Date.parse('2026-11-01T12:00:00Z');
  const records = [
    { id: 'recent-flood', status: 'ACTIVE', confirmed_at: '2026-11-01T08:00:00Z', report: { disaster_type: 'FLOOD' } },
    { id: 'recent-fire', status: 'CLOSED', confirmed_at: '2026-10-31T12:00:00Z', report: { disaster_type: 'FIRE' } },
    { id: 'old-flood', status: 'ACTIVE', confirmed_at: '2026-10-01T12:00:00Z', report: { disaster_type: 'FLOOD' } },
    { id: 'unknown-time', status: 'ACTIVE', report: { disaster_type: 'FLOOD' } },
  ];

  assert.deepEqual(filterAndSortIncidents(records, {
    status: 'ACTIVE', type: 'FLOOD', timeRange: '24H', now,
  }).map(({ id }) => id), ['recent-flood']);
  assert.deepEqual(filterAndSortIncidents(records, {
    type: 'FIRE', timeRange: '7D', now,
  }).map(({ id }) => id), ['recent-fire']);
  assert.deepEqual(filterAndSortIncidents(records, {
    timeRange: '30D', now,
  }).map(({ id }) => id), ['recent-flood', 'recent-fire']);
});

test('sorts the incident queue by priority and time with unrated or unknown values last', () => {
  const records = [
    { id: 'medium', priority_band: 'MEDIUM', priority_score: 50, confirmed_at: '2026-11-01T10:00:00Z' },
    { id: 'critical', priority_band: 'CRITICAL', priority_score: 91, confirmed_at: '2026-10-31T10:00:00Z' },
    { id: 'low', priority_band: 'LOW', priority_score: 20, confirmed_at: '2026-11-01T11:00:00Z' },
    { id: 'unrated', priority_band: null, confirmed_at: null },
  ];

  assert.deepEqual(filterAndSortIncidents(records, { sortBy: 'PRIORITY_HIGH' }).map(({ id }) => id),
    ['critical', 'medium', 'low', 'unrated']);
  assert.deepEqual(filterAndSortIncidents(records, { sortBy: 'PRIORITY_LOW' }).map(({ id }) => id),
    ['low', 'medium', 'critical', 'unrated']);
  assert.deepEqual(filterAndSortIncidents(records, { sortBy: 'OLDEST' }).map(({ id }) => id),
    ['critical', 'medium', 'low', 'unrated']);
  assert.deepEqual(filterAndSortIncidents(records, { sortBy: 'NEWEST' }).map(({ id }) => id),
    ['low', 'medium', 'critical', 'unrated']);
});

test('maps every supported priority to a darker shade and clear label', () => {
  assert.deepEqual(PRIORITY_LEVELS.map(({ band, label, color }) => ({ band, label, color })), [
    { band: 'LOW', label: 'Low', color: '#FECACA' },
    { band: 'MEDIUM', label: 'Medium', color: '#F87171' },
    { band: 'HIGH', label: 'High', color: '#B91C1C' },
    { band: 'CRITICAL', label: 'Critical', color: '#7F1D1D' },
  ]);

  assert.deepEqual(getMarkerPresentation({ status: 'CONFIRMED', priority_band: 'LOW' }), {
    statusClass: 'confirmed', priorityClass: 'low', priorityLabel: 'Low',
    priorityColor: '#FECACA', priorityTextColor: '#7F1D1D', radius: 9,
  });
  assert.deepEqual(getMarkerPresentation({ status: 'ACTIVE', priority_band: 'HIGH' }), {
    statusClass: 'active', priorityClass: 'high', priorityLabel: 'High',
    priorityColor: '#B91C1C', priorityTextColor: '#FFFFFF', radius: 15,
  });
  assert.equal(getPriorityPresentation('medium').label, 'Medium');
});

test('priority colors darken with increasing priority and retain readable contrast', () => {
  const luminances = PRIORITY_LEVELS.map(({ color }) => relativeLuminance(color));
  assert.ok(luminances.every((value, index) => index === 0 || value < luminances[index - 1]));
  assert.ok(PRIORITY_LEVELS.every(({ color, textColor }) => contrastRatio(color, textColor) >= 4.5));
});

test('falls back safely for unknown statuses and missing priority', () => {
  assert.equal(getMarkerPresentation({ status: 'SUBMITTED', priority_band: null }).priorityLabel, 'Awaiting decision');
  assert.equal(getMarkerPresentation({ status: 'UNDER_REVIEW', priority_band: null }).priorityLabel, 'Awaiting decision');
  assert.deepEqual(getMarkerPresentation({ status: '<script>', priority_band: null }), {
    statusClass: 'unknown', priorityClass: 'unrated', priorityLabel: 'Unrated',
    priorityColor: '#78837D', priorityTextColor: '#FFFFFF', radius: 10,
  });
  assert.equal(getPriorityPresentation('NOT_A_PRIORITY').label, 'Unrated');
  assert.equal(getPriorityPresentation('__proto__').label, 'Unrated');
});