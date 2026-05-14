<script setup lang="ts">
import { cn } from '@/utils/cn';
import { ref } from 'vue';

const props = defineProps<{
  class?: string;
  viewportClassName?: string;
  testId?: string;
}>();

defineEmits<{
  scroll: [event: Event];
}>();

const viewportEl = ref<HTMLDivElement | null>(null);

defineExpose({
  viewportEl,
});
</script>

<template>
  <div :class="cn('min-h-0 flex-1 overflow-hidden', props.class)">
    <div
      ref="viewportEl"
      :data-testid="testId"
      :class="cn('h-full overflow-y-auto custom-scrollbar', viewportClassName)"
      @scroll="$emit('scroll', $event)"
    >
      <slot />
    </div>
  </div>
</template>
