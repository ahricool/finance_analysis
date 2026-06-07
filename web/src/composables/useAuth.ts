import { storeToRefs } from 'pinia';
import { useAuthStore } from '@/stores/authStore';

/**
 * Mirrors the old React `useAuth` hook API using Pinia `authStore`.
 */
export function useAuth() {
  const store = useAuthStore();
  const {
    loggedIn,
    currentUser,
    isLoading,
    loadError,
  } = storeToRefs(store);

  return {
    loggedIn,
    currentUser,
    isLoading,
    loadError,
    lookupEmail: store.lookupEmail,
    setupPassword: store.setupPassword,
    login: store.login,
    changePassword: store.changePassword,
    logout: store.logout,
    refreshStatus: store.refreshStatus,
    fetchStatus: store.fetchStatus,
  };
}
