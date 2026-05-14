<script setup lang="ts">
import { storeToRefs } from 'pinia';
import { onMounted, watch } from 'vue';
import { RouterView, useRoute, useRouter } from 'vue-router';
import ApiErrorAlert from '@/components/common/ApiErrorAlert.vue';
import ThemeProvider from '@/components/theme/ThemeProvider.vue';
import { useAuthStore } from '@/stores/authStore';
import { useAgentChatStore } from '@/stores/agentChatStore';

const auth = useAuthStore();
const { isLoading, loadError, authEnabled, loggedIn } = storeToRefs(auth);
const route = useRoute();
const router = useRouter();

onMounted(() => {
  void auth.fetchStatus();
});

watch(
  () => route.path,
  (path) => {
    useAgentChatStore.getState().setCurrentRoute(path);
  },
  { immediate: true },
);

watch(
  [isLoading, loadError, authEnabled, loggedIn, () => route.path],
  () => {
    if (isLoading.value || loadError.value) return;
    if (authEnabled.value && !loggedIn.value) {
      if (route.path !== '/login') {
        const redirect = encodeURIComponent(route.fullPath);
        void router.replace(`/login?redirect=${redirect}`);
      }
      return;
    }
    if (route.path === '/login' && loggedIn.value) {
      void router.replace('/');
    }
  },
  { immediate: true },
);
</script>

<template>
  <ThemeProvider>
    <div v-if="isLoading" class="flex min-h-screen items-center justify-center bg-base">
      <div class="h-8 w-8 animate-spin rounded-full border-2 border-cyan/20 border-t-cyan" />
    </div>
    <div
      v-else-if="loadError"
      class="flex min-h-screen flex-col items-center justify-center gap-4 bg-base px-4"
    >
      <div class="w-full max-w-lg">
        <ApiErrorAlert :error="loadError" />
      </div>
      <button type="button" class="btn-primary" @click="void auth.refreshStatus()">重试</button>
    </div>
    <RouterView v-else />
  </ThemeProvider>
</template>
