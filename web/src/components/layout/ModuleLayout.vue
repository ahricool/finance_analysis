<script setup lang="ts">
import type { NavDestination } from '@/config/mainNav';
import ModuleSidebar from './ModuleSidebar.vue';

defineProps<{ items: NavDestination[]; activeKey: string; label: string }>();
</script>

<template>
  <div
    class="module-layout relative min-w-0"
    data-testid="module-layout"
  >
    <aside
      class="absolute inset-y-0 right-full z-30 mr-3 hidden w-[3.25rem] lg:block"
    >
      <ModuleSidebar
        class="sticky top-20 max-h-[calc(100dvh-6rem)]"
        :items="items"
        :active-key="activeKey"
        :label="label"
      />
    </aside>
    <div
      class="min-w-0 space-y-4"
      data-testid="module-content"
    >
      <slot />
    </div>
  </div>
</template>
