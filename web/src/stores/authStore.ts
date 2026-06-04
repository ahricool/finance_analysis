import { defineStore } from 'pinia';
import { ref } from 'vue';
import { authApi, type AuthStatusResponse } from '../api/auth';
import { createParsedApiError, getParsedApiError, type ParsedApiError } from '../api/error';
import { useStockPoolStore } from './stockPoolStore';

function extractLoginError(err: unknown): ParsedApiError {
  const parsed = getParsedApiError(err);
  if (parsed.status === 429) {
    return createParsedApiError({
      title: '登录尝试过于频繁',
      message: '尝试次数过多，请稍后再试。',
      rawMessage: parsed.rawMessage,
      status: parsed.status,
      category: parsed.category,
    });
  }
  return parsed;
}

export const useAuthStore = defineStore('auth', () => {
  const authEnabled = ref(true);
  const loggedIn = ref(false);
  const passwordChangeable = ref(false);
  const setupState = ref<'enabled'>('enabled');
  const currentUser = ref<AuthStatusResponse['user']>(null);
  const isLoading = ref(true);
  const loadError = ref<ParsedApiError | null>(null);

  async function fetchStatus() {
    isLoading.value = true;
    loadError.value = null;
    try {
      const status = await authApi.getStatus();
      authEnabled.value = status.authEnabled;
      loggedIn.value = status.loggedIn;
      passwordChangeable.value = status.passwordChangeable ?? false;
      setupState.value = status.setupState;
      currentUser.value = status.user ?? null;
      if (!status.loggedIn) {
        useStockPoolStore.getState().resetDashboardState();
      }
    } catch (err) {
      loadError.value = getParsedApiError(err);
      authEnabled.value = true;
      loggedIn.value = false;
      passwordChangeable.value = false;
      setupState.value = 'enabled';
      currentUser.value = null;
      useStockPoolStore.getState().resetDashboardState();
    } finally {
      isLoading.value = false;
    }
  }

  async function lookupEmail(
    email: string,
  ): Promise<{ success: boolean; needsPasswordSetup?: boolean; error?: ParsedApiError }> {
    try {
      const result = await authApi.lookupEmail(email);
      return { success: true, needsPasswordSetup: result.needsPasswordSetup };
    } catch (err: unknown) {
      return { success: false, error: extractLoginError(err) };
    }
  }

  async function setupPassword(
    email: string,
    password: string,
    passwordConfirm: string,
  ): Promise<{ success: boolean; error?: ParsedApiError }> {
    try {
      const result = await authApi.login(email, password, passwordConfirm);
      if (result.requiresRelogin) {
        return { success: true };
      }
      await fetchStatus();
      return { success: true };
    } catch (err: unknown) {
      return { success: false, error: extractLoginError(err) };
    }
  }

  async function login(
    email: string,
    password: string,
  ): Promise<{ success: boolean; error?: ParsedApiError }> {
    try {
      await authApi.login(email, password);
      await fetchStatus();
      return { success: true };
    } catch (err: unknown) {
      return { success: false, error: extractLoginError(err) };
    }
  }

  async function changePassword(
    currentPassword: string,
    newPassword: string,
    newPasswordConfirm: string,
  ): Promise<{ success: boolean; error?: ParsedApiError }> {
    try {
      await authApi.changePassword(currentPassword, newPassword, newPasswordConfirm);
      return { success: true };
    } catch (err: unknown) {
      return { success: false, error: getParsedApiError(err) };
    }
  }

  async function logout() {
    let logoutError: unknown = null;
    try {
      await authApi.logout();
    } catch (err) {
      logoutError = err;
    } finally {
      await fetchStatus();
    }

    if (logoutError && getParsedApiError(logoutError).status !== 401) {
      throw logoutError;
    }
  }

  return {
    authEnabled,
    loggedIn,
    passwordChangeable,
    setupState,
    currentUser,
    isLoading,
    loadError,
    lookupEmail,
    setupPassword,
    login,
    changePassword,
    logout,
    refreshStatus: fetchStatus,
    fetchStatus,
  };
});
