import assert from 'node:assert/strict';
import test from 'node:test';
import { parseLocationInput, validateCoordinates } from './mapLocation.js';

test('validates separate latitude and longitude values and geographic boundaries', () => {
  assert.deepEqual(validateCoordinates('10.027', '76.308'), {
    kind: 'coordinates', latitude: 10.027, longitude: 76.308,
  });
  assert.deepEqual(validateCoordinates('-90', '180'), {
    kind: 'coordinates', latitude: -90, longitude: 180,
  });
  assert.deepEqual(validateCoordinates('90', '-180'), {
    kind: 'coordinates', latitude: 90, longitude: -180,
  });
});

test('rejects incomplete, non-numeric, and out-of-range coordinate fields', () => {
  assert.match(validateCoordinates('10', '').message, /both latitude and longitude/);
  assert.match(validateCoordinates(' ', '20').message, /both latitude and longitude/);
  assert.match(validateCoordinates('north', '20').message, /valid numbers/);
  assert.match(validateCoordinates('91', '20').message, /outside the valid/);
  assert.match(validateCoordinates('10', '181').message, /outside the valid/);
});

test('parses pasted latitude and longitude', () => {
  assert.deepEqual(parseLocationInput('10.027, 76.308'), {
    kind: 'coordinates', latitude: 10.027, longitude: 76.308,
  });
});

test('parses Google Maps @latitude,longitude URL', () => {
  assert.deepEqual(parseLocationInput('https://www.google.com/maps/@10.027,76.308,15z'), {
    kind: 'coordinates', latitude: 10.027, longitude: 76.308,
  });
});

test('parses Google Maps place URL with !3d and !4d coordinates', () => {
  assert.deepEqual(parseLocationInput(
    'https://www.google.com/maps/place/Kochi/@10.027,76.308,15z/data=!3m1!4b1!3d9.9312!4d76.2673',
  ), { kind: 'coordinates', latitude: 9.9312, longitude: 76.2673 });
});

test('parses maps.google.com coordinate query URL', () => {
  assert.deepEqual(parseLocationInput('https://maps.google.com/?q=10.027,76.308'), {
    kind: 'coordinates', latitude: 10.027, longitude: 76.308,
  });
});

test('returns a place query from a Google Maps search URL', () => {
  assert.deepEqual(parseLocationInput('https://www.google.com/maps/search/Kochi+Kerala'), {
    kind: 'query', query: 'Kochi Kerala',
  });
});

test('keeps a plain address as a geocoding query', () => {
  assert.deepEqual(parseLocationInput('Kochi, Kerala'), {
    kind: 'query', query: 'Kochi, Kerala',
  });
});

test('rejects out-of-range coordinates and unsupported map links', () => {
  assert.equal(parseLocationInput('91, 0').kind, 'error');
  assert.equal(parseLocationInput('https://www.google.com/maps/@10,181,12z').kind, 'error');
  assert.match(parseLocationInput('https://example.com/maps?q=10,76').message, /Unsupported map link/);
});

test('explains unsupported shortened Google Maps links', () => {
  assert.match(parseLocationInput('https://maps.app.goo.gl/example').message, /Shortened map links/);
});

test('reports malformed URLs and treats empty input as an empty query', () => {
  assert.equal(parseLocationInput('https://%zz.google.com/maps?q=place').kind, 'error');
  assert.deepEqual(parseLocationInput('   '), { kind: 'query', query: '' });
});