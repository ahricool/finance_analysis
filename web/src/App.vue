<script setup lang="ts">
import { storeToRefs } from 'pinia';
import { onMounted, watch } from 'vue';
import { RouterView, useRoute, useRouter } from 'vue-router';
import ApiErrorAlert from '@/components/app/AppApiErrorAlert.vue';
import { Button } from '@/components/ui/button';
import ThemeProvider from '@/components/theme/ThemeProvider.vue';
import { Toaster } from '@/components/ui/sonner';
import { useAuthStore } from '@/stores/authStore';
import { useAgentChatStore } from '@/stores/agentChatStore';

const auth = useAuthStore();
const { isLoading, loadError, loggedIn } = storeToRefs(auth);
const route = useRoute();
const router = useRouter();

onMounted(() => {
  if (isLoading.value) {
    void auth.fetchStatus();
  }
});

watch(
  () => route.path,
  (path) => {
    useAgentChatStore.getState().setCurrentRoute(path);
  },
  { immediate: true },
);

watch(
  [isLoading, loadError, loggedIn, () => route.path],
  () => {
    if (isLoading.value || loadError.value) return;
    if (!loggedIn.value) {
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
    <div
      v-if="isLoading"
      class="flex min-h-screen items-center justify-center bg-background"
    >
      <div class="h-8 w-8 animate-spin rounded-full border-2 border-primary/20 border-t-primary" />
    </div>
    <div
      v-else-if="loadError"
      class="flex min-h-screen flex-col items-center justify-center gap-4 bg-background px-4"
    >
      <div class="w-full max-w-lg">
        <ApiErrorAlert :error="loadError" />
      </div>
      <Button @click="void auth.refreshStatus()">
        重试
      </Button>
    </div>
    <RouterView v-else />
    <Toaster
      position="top-center"
      close-button
      rich-colors
    />
  </ThemeProvider>
</template>
