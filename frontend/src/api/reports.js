const API_BASE = import.meta.env.VITE_API_BASE_URL || '';

async function request(path, options) {
  let response;
  try {
    response = await fetch(`${API_BASE}${path}`, options);
  } catch {
    throw new Error('The server could not be reached. Check that the API is running.');
  }

  const data = await response.json().catch(() => ({}));
  if (!response.ok) {
    const details = Array.isArray(data.errors) ? data.errors.join(' ') : '';
    throw new Error([data.message || 'The request could not be completed.', details].filter(Boolean).join(' '));
  }
  return data;
}

export function submitReport(formData) {
  return request('/reports', { method: 'POST', body: formData });
}

export function importReports(kind, content) {
  return request(`/reports/import/${kind}`, {
    method: 'POST',
    headers: { 'Content-Type': kind === 'json' ? 'application/json' : 'text/csv' },
    body: content,
  });
}