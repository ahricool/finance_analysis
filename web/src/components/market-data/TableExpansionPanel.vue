<script setup lang="ts">
import { onBeforeUnmount, onMounted, ref } from 'vue';

// Expanded table rows must fit the visible scroll container, not the full table width.
const panel = ref<HTMLElement>();
const panelWidth = ref('100%');
let observer: ResizeObserver | undefined;
onMounted(() => {
  const container = panel.value?.closest('[data-slot="table-container"]');
  if (!container) return;
  const resize = () => { panelWidth.value = `${Math.max(0, container.clientWidth - 24)}px`; };
  resize();
  observer = new ResizeObserver(resize);
  observer.observe(container);
});
onBeforeUnmount(() => observer?.disconnect());
</script>

<template>
  <section
    ref="panel"
    :style="{ width: panelWidth }"
    class="sticky left-3 min-w-0 space-y-3 whitespace-normal break-words rounded-lg border bg-muted/20 p-3"
  >
    <slot />
  </section>
</template>
