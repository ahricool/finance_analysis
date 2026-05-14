<script setup lang="ts">
import { cn } from '@/utils/cn';
import { computed, ref } from 'vue';

const props = withDefaults(
  defineProps<{
    data: Record<string, unknown> | unknown[] | null | undefined;
    maxHeight?: string;
    class?: string;
  }>(),
  {
    maxHeight: '400px',
    class: '',
  },
);

const copied = ref(false);

const jsonString = computed(() =>
  props.data ? JSON.stringify(props.data, null, 2) : '',
);

function highlightLine(line: string): string {
  let highlighted = line.replace(
    /"([^"]+)":/g,
    '<span class="text-cyan-400">"$1"</span>:',
  );
  highlighted = highlighted.replace(
    /: "([^"]*)"/g,
    ': <span class="text-emerald-400">"$1"</span>',
  );
  highlighted = highlighted.replace(/: (-?\d+\.?\d*)/g, ': <span class="text-amber-400">$1</span>');
  highlighted = highlighted.replace(
    /: (true|false|null)/g,
    ': <span class="text-purple-400">$1</span>',
  );
  return highlighted;
}

const highlightedLines = computed(() => {
  if (!props.data) return [];
  return jsonString.value.split('\n').map((line) => highlightLine(line));
});

async function handleCopy() {
  await navigator.clipboard.writeText(jsonString.value);
  copied.value = true;
  window.setTimeout(() => {
    copied.value = false;
  }, 2000);
}
</script>

<template>
  <div v-if="!data" class="py-4 text-center text-gray-500 italic">暂无数据</div>
  <div v-else :class="cn('relative', props.class)">
    <button
      type="button"
      class="absolute top-2 right-2 z-10 rounded bg-slate-700 px-2 py-1 text-xs text-gray-300 transition-colors hover:bg-slate-600"
      @click="handleCopy"
    >
      {{ copied ? '已复制!' : '复制' }}
    </button>

    <div
      class="custom-scrollbar overflow-auto rounded-lg border border-slate-700/50 bg-slate-900/80 p-4 font-mono text-sm text-gray-300"
      :style="{ maxHeight }"
    >
      <pre class="whitespace-pre-wrap break-words">
        <div v-for="(line, index) in highlightedLines" :key="index" class="leading-relaxed" v-html="line" />
      </pre>
    </div>
  </div>
</template>
