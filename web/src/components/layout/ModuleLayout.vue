<script setup lang="ts">
import ModuleSidebar, { type ModuleNavItem } from './ModuleSidebar.vue';

defineProps<{ items: ModuleNavItem[]; activeKey: string; label: string }>();
</script>

<template>
  <div
    class="grid min-w-0 items-start gap-4 lg:grid-cols-[12rem_minmax(0,1fr)] lg:gap-6"
    data-testid="module-layout"
  >
    <aside class="hidden min-w-0 lg:sticky lg:top-20 lg:block lg:max-h-[calc(100dvh-6rem)] lg:overflow-y-auto">
      <ModuleSidebar
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
