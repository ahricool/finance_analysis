<script setup lang="ts">
import { computed } from 'vue';
import { useSecurityName } from '@/composables/useSecurityName';
const props = withDefaults(defineProps<{ code?: string | null; name?: string | null }>(), { code: '', name: '' });
const resolvedName = useSecurityName(() => props.code, () => props.name);
const codeText = computed(() => props.code?.trim() || '代码暂缺');
const nameText = computed(() => {
  const name = resolvedName.value;
  return name && name.toUpperCase() !== codeText.value.toUpperCase() ? name : '名称暂缺';
});
</script>

<template>
  <span class="stock-identity inline-flex max-w-full flex-wrap items-baseline gap-x-1 break-words"><span class="font-mono text-xs font-normal text-muted-foreground">{{ codeText }}</span><span class="font-normal text-muted-foreground"> - </span><strong class="font-bold">{{ nameText }}</strong></span>
</template>
