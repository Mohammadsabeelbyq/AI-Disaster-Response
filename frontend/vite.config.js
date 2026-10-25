import { defineConfig } from 'vite';
import react from '@vitejs/plugin-react';

function serveFrontendForUiRoutes(req) {
  const pathname = req.url?.split('?')[0];
  const isUiRoute = pathname === '/resources' || pathname === '/incidents/map';

  if (isUiRoute && req.headers.accept?.includes('text/html')) {
    return '/index.html';
  }

  return null;
}

export default defineConfig({
  plugins: [react()],
  server: {
    proxy: {
      '/auth': 'http://127.0.0.1:8000',
      '/reports': 'http://127.0.0.1:8000',
      '/incidents': {
        target: 'http://127.0.0.1:8000',
        bypass: serveFrontendForUiRoutes,
      },
      '/departments': 'http://127.0.0.1:8000',
      '/resources': {
        target: 'http://127.0.0.1:8000',
        bypass: serveFrontendForUiRoutes,
      },
      '/priority-configs': 'http://127.0.0.1:8000',
      '/response-plans': 'http://127.0.0.1:8000',
      '/health': 'http://127.0.0.1:8000',
    },
  },
});