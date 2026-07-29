<script setup lang="ts">
import type { DateValue } from 'reka-ui';
import { computed, ref } from 'vue';
import { CalendarDays, X } from 'lucide-vue-next';
import { parseDate } from '@internationalized/date';
import AppButton from './AppButton.vue';
import { Calendar } from '@/components/ui/calendar';
import { Label } from '@/components/ui/label';
import { Popover, PopoverContent, PopoverTrigger } from '@/components/ui/popover';
const props = withDefaults(defineProps<{ modelValue?: string; label?: string; placeholder?: string; disabled?: boolean; clearable?: boolean; min?: string; max?: string; error?: string; class?: string }>(), { placeholder: '选择日期', clearable: true });
const emit = defineEmits<{ 'update:modelValue': [value: string] }>();
const open = ref(false);
function toDateValue(value?: string): DateValue | undefined { try { return value ? parseDate(value.slice(0, 10)) : undefined; } catch { return undefined; } }
const selected = computed(() => toDateValue(props.modelValue));
const display = computed(() => props.modelValue ? new Intl.DateTimeFormat('zh-CN', { year: 'numeric', month: 'long', day: 'numeric' }).format(new Date(`${props.modelValue.slice(0, 10)}T00:00:00`)) : '');
function choose(value: DateValue | undefined) { emit('update:modelValue', value?.toString() ?? ''); if (value) open.value = false; }
</script>
<template><div :class="['grid min-w-0 gap-2', props.class]"><Label v-if="label">{{ label }}</Label><div class="flex min-w-0 gap-1"><Popover v-model:open="open"><PopoverTrigger as-child><AppButton variant="outline" class="h-10 min-w-0 flex-1 justify-start px-3 font-normal" :disabled="disabled"><CalendarDays class="size-4 text-muted-foreground" /><span class="truncate" :class="!display && 'text-muted-foreground'">{{ display || placeholder }}</span></AppButton></PopoverTrigger><PopoverContent align="start" class="w-auto max-w-[calc(100vw-1rem)] overflow-auto p-0"><Calendar :model-value="selected" locale="zh-CN" layout="month-and-year" :min-value="toDateValue(min)" :max-value="toDateValue(max)" @update:model-value="choose" /></PopoverContent></Popover><AppButton v-if="clearable && modelValue" variant="ghost" size="icon" aria-label="清空日期" @click="emit('update:modelValue', '')"><X /></AppButton></div><p v-if="error" class="text-xs text-destructive">{{ error }}</p></div></template>
