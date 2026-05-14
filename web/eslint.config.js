import js from '@eslint/js';
import globals from 'globals';
import tseslint from 'typescript-eslint';
import pluginVue from 'eslint-plugin-vue';
import vueParser from 'vue-eslint-parser';

export default [
  {
    ignores: ['dist/**', 'playwright-report/**', 'test-results/**', '../static/**'],
  },
  js.configs.recommended,
  ...pluginVue.configs['flat/recommended'],
  ...tseslint.configs.recommended,
  {
    files: ['**/*.vue'],
    languageOptions: {
      ecmaVersion: 'latest',
      globals: globals.browser,
      parser: vueParser,
      parserOptions: {
        parser: tseslint.parser,
        extraFileExtensions: ['.vue'],
        sourceType: 'module',
      },
    },
  },
  {
    files: ['**/*.{ts,mts,cts}'],
    languageOptions: {
      ecmaVersion: 'latest',
      globals: globals.browser,
      parserOptions: {
        sourceType: 'module',
      },
    },
  },
  {
    rules: {
      'vue/multi-word-component-names': 'off',
      'vue/html-self-closing': 'off',
    },
  },
];
