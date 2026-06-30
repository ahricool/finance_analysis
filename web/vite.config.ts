import { readFileSync } from 'node:fs';
import { defineConfig } from 'vite';
import vue from '@vitejs/plugin-vue';
import path from 'path';

const packageJson = JSON.parse(
  readFileSync(new URL('./package.json', import.meta.url), 'utf-8'),
) as { version?: string };
const buildTime = new Date().toISOString();

export default defineConfig({
  define: {
    __APP_PACKAGE_VERSION__: JSON.stringify(packageJson.version ?? '0.0.0'),
    __APP_BUILD_TIME__: JSON.stringify(buildTime),
  },
  plugins: [vue()],
  resolve: {
    alias: {
      '@': path.resolve(__dirname, './src'),
    },
  },
  server: {
    host: '0.0.0.0',
    port: 5173,
    proxy: {
      '/api': {
        target: 'http://127.0.0.1:8000',
        changeOrigin: true,
        ws: true,
      },
    },
  },
  build: {
    outDir: path.resolve(__dirname, '../static'),
    emptyOutDir: true,
  },
});
