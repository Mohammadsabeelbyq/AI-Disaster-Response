import assert from 'node:assert/strict';
import test from 'node:test';
import { getMappableIncidents, getMarkerPresentation } from './incidentMap.js';

test('keeps incidents with valid saved coordinates and excludes invalid locations', () => {
  const located = { id: 'located', report: { latitude: '10.027', longitude: '76.308' } };
  const incidents = [
    located,
    { id: 'missing', report: { latitude: null, longitude: 76 } },
    { id: 'invalid', report: { latitude: 91, longitude: 0 } },
    { id: 'non-finite', report: { latitude: 'NaN', longitude: 0 } },
  ];

  assert.deepEqual(getMappableIncidents(incidents), [located]);
});

test('uses the actual incident status and priority as separate marker encodings', () => {
  assert.deepEqual(getMarkerPresentation({ status: 'CONFIRMED', priority_band: 'CRITICAL' }), {
    statusClass: 'confirmed', priorityClass: 'critical', radius: 18,
  });
  assert.deepEqual(getMarkerPresentation({ status: 'CONFIRMED', priority_band: 'LOW' }), {
    statusClass: 'confirmed', priorityClass: 'low', radius: 9,
  });
});

test('falls back safely for unknown statuses and missing priority', () => {
  assert.deepEqual(getMarkerPresentation({ status: '<script>', priority_band: null }), {
    statusClass: 'unknown', priorityClass: 'unrated', radius: 10,
  });
});