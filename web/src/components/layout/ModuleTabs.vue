<script setup lang="ts">
import type { Component } from 'vue';
import type { RouteLocationRaw } from 'vue-router';
import { nextTick, onMounted, ref, watch } from 'vue';
import { Tabs, TabsList, TabsTrigger } from '@/components/ui/tabs';

export type ModuleTab = { key: string; label: string; icon?: Component; to: RouteLocationRaw };
const props = defineProps<{ items: ModuleTab[]; activeKey: string; label: string }>();

const scroller = ref<HTMLElement | null>(null);
const canScrollLeft = ref(false);
const canScrollRight = ref(false);

function updateFade() {
  const el = scroller.value;
  if (!el) {
    canScrollLeft.value = false;
    canScrollRight.value = false;
    return;
  }
  const max = el.scrollWidth - el.clientWidth;
  canScrollLeft.value = el.scrollLeft > 2;
  canScrollRight.value = max - el.scrollLeft > 2;
}

function scrollActiveIntoView() {
  const el = scroller.value;
  if (!el) return;
  const active = el.querySelector<HTMLElement>('[data-state="active"], [aria-current="page"]');
  if (active && typeof active.scrollIntoView === 'function') {
    active.scrollIntoView({ inline: 'nearest', block: 'nearest', behavior: 'smooth' });
  }
  updateFade();
}

watch(
  () => props.activeKey,
  async () => {
    await nextTick();
    scrollActiveIntoView();
  },
);

onMounted(async () => {
  await nextTick();
  updateFade();
  scrollActiveIntoView();
});
</script>

<template>
  <nav
    :aria-label="label"
    class="relative"
    data-testid="module-tabs"
  >
    <div
      v-show="canScrollLeft"
      class="pointer-events-none absolute inset-y-0 left-0 z-10 w-8 bg-gradient-to-r from-background to-transparent"
      aria-hidden="true"
      data-testid="module-tabs-fade-left"
    />
    <div
      v-show="canScrollRight"
      class="pointer-events-none absolute inset-y-0 right-0 z-10 w-8 bg-gradient-to-l from-background to-transparent"
      aria-hidden="true"
      data-testid="module-tabs-fade-right"
    />
    <div
      ref="scroller"
      class="w-full overflow-x-auto whitespace-nowrap [scrollbar-width:thin]"
      data-testid="module-tabs-scroller"
      @scroll="updateFade"
    >
      <Tabs :model-value="activeKey">
        <TabsList>
          <TabsTrigger
            v-for="item in items"
            :key="item.key"
            :value="item.key"
            as-child
          >
            <RouterLink :to="item.to">
              <component
                :is="item.icon"
                v-if="item.icon"
              />
              {{ item.label }}
            </RouterLink>
          </TabsTrigger>
        </TabsList>
      </Tabs>
    </div>
  </nav>
</template>
