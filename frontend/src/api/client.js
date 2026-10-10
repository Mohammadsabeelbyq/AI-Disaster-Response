const API_BASE = import.meta.env.VITE_API_BASE_URL || '';

export async function request(path, options = {}) {
  let response;
  const controller = new AbortController();
  const timeout = setTimeout(() => controller.abort(), 15000);
  try {
    response = await fetch(`${API_BASE}${path}`, {
      credentials: 'include',
      ...options,
      signal: options.signal || controller.signal,
    });
  } catch (error) {
    clearTimeout(timeout);
    if (error.name === 'AbortError') {
      throw new Error('The server did not respond in time. Check that the API is running.');
    }
    throw new Error('The server could not be reached. Check that the API is running.');
  }

  try {
    let data = {};
    if (response.status !== 204) {
      const contentType = response.headers.get('content-type') || '';
      if (!contentType.includes('application/json')) {
        throw new Error('The server returned an unexpected response. Check the API URL and dev-server proxy.');
      }
      data = await response.json();
    }
    if (!response.ok) {
      const details = Array.isArray(data.errors) ? data.errors.join(' ') : '';
      throw new Error([data.message || data.detail || 'The request could not be completed.', details]
        .filter(Boolean).join(' '));
    }
    return data;
  } finally {
    clearTimeout(timeout);
  }
}