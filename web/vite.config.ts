import { defineConfig } from 'vite';
import react from '@vitejs/plugin-react';

// Part A's FastAPI server. Only used when the mock is off (VITE_MOCK=0) or in a build.
const API = process.env.API_TARGET ?? 'http://localhost:8000';

export default defineConfig({
  plugins: [react()],
  server: {
    host: true, // phones on the LAN / tunnel
    allowedHosts: ['.trycloudflare.com'],
    proxy: {
      '/rounds': { target: API, changeOrigin: true },
      '/frames': { target: API, changeOrigin: true },
      '/ws': { target: API.replace(/^http/, 'ws'), ws: true },
    },
  },
});
