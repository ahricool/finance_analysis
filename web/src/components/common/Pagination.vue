<script setup lang="ts">
import { cn } from '@/utils/cn';
import { computed } from 'vue';

const props = withDefaults(
  defineProps<{
    currentPage: number;
    totalPages: number;
    class?: string;
  }>(),
  {
    class: '',
  },
);

const emit = defineEmits<{
  pageChange: [page: number];
}>();

type PageEntry = number | string;

function getPageNumbers(): PageEntry[] {
  const pages: PageEntry[] = [];
  const delta = 2;
  const { totalPages, currentPage } = props;

  for (let i = 1; i <= totalPages; i++) {
    if (
      i === 1 ||
      i === totalPages ||
      (i >= currentPage - delta && i <= currentPage + delta)
    ) {
      pages.push(i);
    } else if (pages[pages.length - 1] !== '...') {
      pages.push('...');
    }
  }

  return pages;
}

const pageList = computed(() => getPageNumbers());

function goTo(page: number) {
  emit('pageChange', page);
}
</script>

<template>
  <div v-if="totalPages > 1" :class="cn('flex items-center justify-center gap-2', props.class)">
    <button
      type="button"
      :disabled="currentPage === 1"
      :class="
        cn(
          'inline-flex h-10 min-w-[2.5rem] items-center justify-center rounded-xl border px-3 text-sm font-medium transition-all duration-200',
          'border-border/60 bg-elevated text-secondary-text hover:bg-hover hover:text-foreground',
          currentPage === 1 ? 'cursor-not-allowed opacity-50' : 'cursor-pointer',
        )
      "
      @click="goTo(currentPage - 1)"
    >
      <svg class="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
        <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M15 19l-7-7 7-7" />
      </svg>
    </button>

    <template v-for="(page, index) in pageList" :key="`${page}-${index}`">
      <span v-if="page === '...'" class="px-3 py-2 text-muted-text">...</span>
      <button
        v-else
        type="button"
        :class="
          cn(
            'inline-flex h-10 min-w-[2.5rem] items-center justify-center rounded-xl border px-3 text-sm font-medium transition-all duration-200',
            page === currentPage
              ? 'border-cyan/30 bg-cyan text-slate-950 shadow-lg shadow-cyan/20'
              : 'border-border/60 bg-elevated text-secondary-text hover:bg-hover hover:text-foreground',
          )
        "
        @click="typeof page === 'number' && goTo(page)"
      >
        {{ page }}
      </button>
    </template>

    <button
      type="button"
      :disabled="currentPage === totalPages"
      :class="
        cn(
          'inline-flex h-10 min-w-[2.5rem] items-center justify-center rounded-xl border px-3 text-sm font-medium transition-all duration-200',
          'border-border/60 bg-elevated text-secondary-text hover:bg-hover hover:text-foreground',
          currentPage === totalPages ? 'cursor-not-allowed opacity-50' : 'cursor-pointer',
        )
      "
      @click="goTo(currentPage + 1)"
    >
      <svg class="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
        <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M9 5l7 7-7 7" />
      </svg>
    </button>
  </div>
</template>
