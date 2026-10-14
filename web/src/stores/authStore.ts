import { defineStore } from 'pinia';
import { ref } from 'vue';
import { authApi, type AuthStatusResponse } from '../api/auth';
import { createParsedApiError, getParsedApiError, type ParsedApiError } from '../api/error';

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
  const loggedIn = ref(false);
  const currentUser = ref<AuthStatusResponse['user']>(null);
  const isLoading = ref(true);
  const loadError = ref<ParsedApiError | null>(null);
  let statusTask: Promise<void> | null = null;
  let statusGeneration = 0;

  function fetchStatus(force = false): Promise<void> {
    if (statusTask && !force) return statusTask;
    const generation = ++statusGeneration;
    isLoading.value = true;
    loadError.value = null;
    const task = loadStatus(generation);
    statusTask = task;
    return task;
  }

  async function loadStatus(generation: number) {
    try {
      const status = await authApi.getStatus();
      if (generation !== statusGeneration) return;
      loggedIn.value = status.loggedIn;
      currentUser.value = status.user ?? null;
    } catch (err) {
      if (generation !== statusGeneration) return;
      loadError.value = getParsedApiError(err);
      loggedIn.value = false;
      currentUser.value = null;
    } finally {
      if (generation === statusGeneration) {
        isLoading.value = false;
        statusTask = null;
      }
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
      await fetchStatus(true);
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
      await fetchStatus(true);
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
      await fetchStatus(true);
    }

    if (logoutError && getParsedApiError(logoutError).status !== 401) {
      throw logoutError;
    }
  }

  return {
    loggedIn,
    currentUser,
    isLoading,
    loadError,
    lookupEmail,
    setupPassword,
    login,
    changePassword,
    logout,
    refreshStatus: () => fetchStatus(true),
    fetchStatus,
  };
});
