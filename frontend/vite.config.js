import { defineConfig } from 'vite';
import react from '@vitejs/plugin-react';

export default defineConfig({
  plugins: [react()],
  server: {
    proxy: {
      '/auth': 'http://127.0.0.1:8000',
      '/reports': 'http://127.0.0.1:8000',
      '/incidents': 'http://127.0.0.1:8000',
      '/priority-configs': 'http://127.0.0.1:8000',
      '/response-plans': 'http://127.0.0.1:8000',
      '/health': 'http://127.0.0.1:8000',
    },
  },
});