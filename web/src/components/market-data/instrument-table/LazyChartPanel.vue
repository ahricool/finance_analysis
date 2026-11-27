<script setup lang="ts">
import { computed, ref, watch } from 'vue';
import { useNearViewport } from './useNearViewport';

const props = defineProps<{ rowVisible: boolean }>();
const panel = ref<HTMLElement | null>(null);
const near = useNearViewport(panel);
const visible = computed(() => near.value || props.rowVisible);
const height = ref(480);
watch([visible, panel], ([active, element], _, cleanup) => {
  if (!active || !element) return;
  const observer = new ResizeObserver(() => {
    if (visible.value && element.offsetHeight) height.value = element.offsetHeight;
  });
  observer.observe(element);
  cleanup(() => observer.disconnect());
}, { flush: 'post' });
</script>

<template>
  <div
    ref="panel"
    class="p-3"
    :style="!visible ? { height: height + 'px' } : undefined"
  >
    <slot v-if="visible" />
  </div>
</template>
