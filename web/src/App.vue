<script setup lang="ts">
import { storeToRefs } from 'pinia';
import { onMounted, watch } from 'vue';
import { RouterView, useRoute, useRouter } from 'vue-router';
import ApiErrorAlert from '@/components/app/AppApiErrorAlert.vue';
import { Button } from '@/components/ui/button';
import ThemeProvider from '@/components/theme/ThemeProvider.vue';
import { Toaster } from '@/components/ui/sonner';
import { useAuthStore } from '@/stores/authStore';

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
      class="flex min-h-screen flex-col items-center justify-center gap-4 bg-background"
      role="status"
      aria-live="polite"
      aria-busy="true"
    >
      <div class="relative size-10">
        <div class="absolute inset-0 animate-spin rounded-full border-2 border-brand/15 border-t-brand" />
        <div class="absolute inset-1.5 animate-pulse rounded-full bg-brand/10" />
      </div>
      <p class="text-sm text-muted-foreground">
        正在加载工作台…
      </p>
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
