<script setup lang="ts">
import { computed } from 'vue';
import { ChevronLeft, ChevronRight } from 'lucide-vue-next';
import AppButton from './AppButton.vue';
const props = defineProps<{ currentPage: number; totalPages: number; class?: string }>();
const emit = defineEmits<{ pageChange: [page: number] }>();
const pages = computed(() => {
  const values: Array<number | 'ellipsis'> = [];
  for (let page = 1; page <= props.totalPages; page += 1) {
    if (page === 1 || page === props.totalPages || Math.abs(page - props.currentPage) <= 1) values.push(page);
    else if (values.at(-1) !== 'ellipsis') values.push('ellipsis');
  }
  return values;
});
</script>
<template>
  <nav v-if="totalPages > 1" :class="['flex items-center justify-center gap-1', props.class]" aria-label="分页">
    <AppButton variant="outline" size="icon" :disabled="currentPage <= 1" aria-label="上一页" @click="emit('pageChange', currentPage - 1)"><ChevronLeft /></AppButton>
    <template v-for="(page, index) in pages" :key="`${page}-${index}`">
      <span v-if="page === 'ellipsis'" class="px-1 text-muted-foreground">…</span>
      <AppButton v-else :variant="page === currentPage ? 'default' : 'outline'" size="icon" :aria-current="page === currentPage ? 'page' : undefined" @click="emit('pageChange', page)">{{ page }}</AppButton>
    </template>
    <AppButton variant="outline" size="icon" :disabled="currentPage >= totalPages" aria-label="下一页" @click="emit('pageChange', currentPage + 1)"><ChevronRight /></AppButton>
  </nav>
</template>
