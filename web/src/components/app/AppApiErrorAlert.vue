<script setup lang="ts">
import type { ParsedApiError } from '@/api/error';
import { computed } from 'vue';
import { X } from 'lucide-vue-next';
import AppButton from './AppButton.vue';
const props = withDefaults(defineProps<{ error: ParsedApiError; class?: string; actionLabel?: string; dismissLabel?: string }>(), { dismissLabel: '关闭' });
const emit = defineEmits<{ dismiss: []; action: [] }>();
const showDetails = computed(() => props.error.rawMessage.trim() !== '' && props.error.rawMessage.trim() !== props.error.message.trim());
</script>
<template><div :class="['rounded-xl border border-destructive/25 bg-destructive/8 p-4 text-destructive', props.class]" role="alert"><div class="flex items-start gap-3"><div class="min-w-0 flex-1"><p class="font-semibold">{{ error.title }}</p><p class="mt-1 text-sm">{{ error.message }}</p></div><AppButton variant="ghost" size="icon-sm" :aria-label="dismissLabel" @click="emit('dismiss')"><X /></AppButton></div><details v-if="showDetails" class="mt-3 rounded-lg border border-destructive/20 p-3"><summary class="cursor-pointer text-xs">查看详情</summary><pre class="mt-2 whitespace-pre-wrap text-xs">{{ error.rawMessage }}</pre></details><AppButton v-if="actionLabel" variant="outline" size="sm" class="mt-3" @click="emit('action')">{{ actionLabel }}</AppButton></div></template>
