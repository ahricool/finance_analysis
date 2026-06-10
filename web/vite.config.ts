import { readFileSync } from 'node:fs';
import { defineConfig, loadEnv } from 'vite';
import vue from '@vitejs/plugin-vue';
import path from 'path';

const packageJson = JSON.parse(
  readFileSync(new URL('./package.json', import.meta.url), 'utf-8'),
) as { version?: string };
const buildTime = new Date().toISOString();

function optionalPort(value: string | undefined): number | undefined {
  if (!value) return undefined;
  const parsed = Number(value);
  return Number.isInteger(parsed) && parsed > 0 ? parsed : undefined;
}

export default defineConfig(({ mode }) => {
  const env = loadEnv(mode, process.cwd(), '');
  const devHost = env.VITE_DEV_HOST || env.WEBUI_HOST;
  const devPort = optionalPort(env.VITE_DEV_PORT || env.DEV_WEB_PORT);
  const apiProxyTarget = env.VITE_API_PROXY_TARGET;

  return {
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
      host: devHost,
      port: devPort,
      proxy: apiProxyTarget
        ? {
            '/api': {
              target: apiProxyTarget,
              changeOrigin: true,
            },
          }
        : undefined,
    },
    build: {
      outDir: path.resolve(__dirname, '../static'),
      emptyOutDir: true,
    },
  };
});
