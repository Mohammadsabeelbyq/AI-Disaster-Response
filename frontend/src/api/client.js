const API_BASE = import.meta.env.VITE_API_BASE_URL || '';

export async function request(path, options = {}) {
  let response;
  try {
    response = await fetch(`${API_BASE}${path}`, { credentials: 'include', ...options });
  } catch {
    throw new Error('The server could not be reached. Check that the API is running.');
  }

  const data = response.status === 204 ? {} : await response.json().catch(() => ({}));
  if (!response.ok) {
    const details = Array.isArray(data.errors) ? data.errors.join(' ') : '';
    throw new Error([data.message || data.detail || 'The request could not be completed.', details]
      .filter(Boolean).join(' '));
  }
  return data;
}