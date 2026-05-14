/// <reference types="vite/client" />

declare const __APP_PACKAGE_VERSION__: string | undefined;
declare const __APP_BUILD_TIME__: string | undefined;

declare module '*.vue' {
  import type { DefineComponent } from 'vue';
  const component: DefineComponent<object, object, unknown>;
  export default component;
}
