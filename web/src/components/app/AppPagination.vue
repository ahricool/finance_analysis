<script setup lang="ts">
import { computed } from 'vue';
import { ChevronLeft, ChevronRight } from 'lucide-vue-next';
import { Button } from '@/components/ui/button';

const props = withDefaults(
  defineProps<{
    currentPage: number;
    totalPages: number;
    class?: string;
  }>(),
  { class: '' },
);
const emit = defineEmits<{ pageChange: [page: number] }>();

const pages = computed(() => {
  const values: Array<number | 'ellipsis'> = [];
  for (let page = 1; page <= props.totalPages; page += 1) {
    if (page === 1 || page === props.totalPages || Math.abs(page - props.currentPage) <= 1) {
      values.push(page);
    } else if (values.at(-1) !== 'ellipsis') {
      values.push('ellipsis');
    }
  }
  return values;
});
</script>
<template>
  <nav
    v-if="totalPages > 1"
    :class="['flex items-center justify-center gap-1', props.class]"
    aria-label="分页"
  >
    <Button
      variant="outline"
      size="icon"
      :disabled="currentPage <= 1"
      aria-label="上一页"
      @click="emit('pageChange', currentPage - 1)"
    >
      <ChevronLeft />
    </Button>
    <template
      v-for="(page, index) in pages"
      :key="`${page}-${index}`"
    >
      <span
        v-if="page === 'ellipsis'"
        class="px-1 text-muted-foreground"
      >…</span>
      <Button
        v-else
        :variant="page === currentPage ? 'default' : 'outline'"
        size="icon"
        :aria-current="page === currentPage ? 'page' : undefined"
        @click="emit('pageChange', page)"
      >
        {{ page }}
      </Button>
    </template>
    <Button
      variant="outline"
      size="icon"
      :disabled="currentPage >= totalPages"
      aria-label="下一页"
      @click="emit('pageChange', currentPage + 1)"
    >
      <ChevronRight />
    </Button>
  </nav>
</template>
