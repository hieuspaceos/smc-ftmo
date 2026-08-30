import { defineConfig } from 'vite';
import vue from '@vitejs/plugin-vue';

// Phase 05 Vue SPA — FastAPI backend lives at the path prefix the user
// configures via VITE_API_BASE. In dev, Vite proxies /api → :8501.
export default defineConfig({
  plugins: [vue()],
  build: {
    outDir: 'dist',
    sourcemap: false,
  },
  server: {
    port: 5173,
    proxy: {
      '/api': 'http://127.0.0.1:8501',
    },
  },
});
