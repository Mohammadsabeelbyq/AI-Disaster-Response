import assert from 'node:assert/strict';
import { afterEach, test } from 'node:test';
import { findNearbyResources, getImpactArea, saveImpactArea } from '../../api/reports.js';

const originalFetch = globalThis.fetch;

afterEach(() => {
  globalThis.fetch = originalFetch;
});

test('impact-area and nearby-resource reads use the selected incident endpoints', async () => {
  const requests = [];
  globalThis.fetch = async (url, options) => {
    requests.push({ url, options });
    return new Response(JSON.stringify({ incident_id: 'incident-1', resources: [] }), {
      status: 200,
      headers: { 'Content-Type': 'application/json' },
    });
  };

  await getImpactArea('incident-1');
  await findNearbyResources('incident-1');

  assert.deepEqual(requests.map(({ url }) => url), [
    '/incidents/incident-1/impact-area',
    '/incidents/incident-1/resources',
  ]);
  assert.ok(requests.every(({ options }) => options.credentials === 'include'));
});

test('saving an impact area sends JSON to the selected incident', async () => {
  let request;
  globalThis.fetch = async (url, options) => {
    request = { url, options };
    return new Response(JSON.stringify({ incident_id: 'incident-2', radius_m: 750 }), {
      status: 200,
      headers: { 'Content-Type': 'application/json' },
    });
  };
  const geometry = { geometry_type: 'RADIUS', radius_m: 750, polygon: null };

  const response = await saveImpactArea('incident-2', geometry);

  assert.equal(request.url, '/incidents/incident-2/impact-area');
  assert.equal(request.options.method, 'PUT');
  assert.equal(request.options.headers['Content-Type'], 'application/json');
  assert.deepEqual(JSON.parse(request.options.body), geometry);
  assert.equal(response.radius_m, 750);
});

test('impact-area API validation errors are exposed to the UI', async () => {
  globalThis.fetch = async () => new Response(JSON.stringify({
    message: 'Invalid impact area.',
    errors: ['radius_m must be positive.'],
  }), {
    status: 422,
    headers: { 'Content-Type': 'application/json' },
  });

  await assert.rejects(
    saveImpactArea('incident-3', { geometry_type: 'RADIUS', radius_m: -1 }),
    { message: 'Invalid impact area. radius_m must be positive.' },
  );
});
