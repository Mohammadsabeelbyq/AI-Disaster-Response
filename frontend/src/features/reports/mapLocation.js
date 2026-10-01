const COORDINATE_PAIR = /(-?(?:\d+\.?\d*|\.\d+))\s*,\s*(-?(?:\d+\.?\d*|\.\d+))/;
const COMPLETE_COORDINATE_PAIR = /^\s*(-?(?:\d+\.?\d*|\.\d+))\s*,\s*(-?(?:\d+\.?\d*|\.\d+))\s*$/;

function coordinates(latitude, longitude) {
  const lat = Number(latitude);
  const lon = Number(longitude);
  if (!Number.isFinite(lat) || !Number.isFinite(lon) || lat < -90 || lat > 90 || lon < -180 || lon > 180) {
    return { kind: 'error', message: 'Those coordinates are outside the valid latitude/longitude range.' };
  }
  return { kind: 'coordinates', latitude: lat, longitude: lon };
}

export function parseLocationInput(input) {
  const value = input.trim();
  if (!value) return { kind: 'query', query: '' };

  const exactPair = value.match(COMPLETE_COORDINATE_PAIR);
  if (exactPair) return coordinates(exactPair[1], exactPair[2]);
  if (!/^https?:\/\//i.test(value)) return { kind: 'query', query: value };

  let url;
  try {
    url = new URL(value);
  } catch {
    return { kind: 'error', message: 'That map link is not valid. Paste a full Google Maps link or search for a place.' };
  }

  const host = url.hostname.toLowerCase();
  if (host === 'maps.app.goo.gl' || host === 'goo.gl') {
    return { kind: 'error', message: 'Shortened map links are not supported. Open the link in Google Maps and copy the full location URL.' };
  }
  const isMapsHost = host === 'maps.google.com';
  const isGoogleMapsPath = (host === 'google.com' || host.endsWith('.google.com'))
    && url.pathname.toLowerCase().includes('/maps');
  if (!isMapsHost && !isGoogleMapsPath) {
    return { kind: 'error', message: 'Unsupported map link. Use a Google Maps link, paste coordinates, or search for a place.' };
  }

  const pathCoordinates = url.href.match(/!3d(-?(?:\d+\.?\d*|\.\d+))!4d(-?(?:\d+\.?\d*|\.\d+))/i)
    || url.href.match(/@(-?(?:\d+\.?\d*|\.\d+)),\s*(-?(?:\d+\.?\d*|\.\d+))/);
  if (pathCoordinates) return coordinates(pathCoordinates[1], pathCoordinates[2]);

  for (const key of ['q', 'query', 'll', 'center', 'destination']) {
    const parameter = url.searchParams.get(key);
    if (!parameter) continue;
    const pair = parameter.match(COORDINATE_PAIR);
    if (pair) return coordinates(pair[1], pair[2]);
    if (key === 'q' || key === 'query') return { kind: 'query', query: parameter };
  }

  let pathQuery;
  try {
    pathQuery = decodeURIComponent(url.pathname)
      .replace(/^\/maps\/?/i, '')
      .replace(/^(?:place|search)\/?/i, '')
      .replace(/[+/_]/g, ' ')
      .trim();
  } catch {
    return { kind: 'error', message: 'That map link is malformed. Paste a full Google Maps link or search for a place.' };
  }
  if (pathQuery) return { kind: 'query', query: pathQuery };
  return { kind: 'error', message: 'No location was found in that link. Search by place name or paste a full Google Maps link.' };
}