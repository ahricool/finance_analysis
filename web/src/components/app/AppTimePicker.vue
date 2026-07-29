<script setup lang="ts">
import { computed, ref, watch } from 'vue';
import { Clock, X } from 'lucide-vue-next';
import AppButton from './AppButton.vue';
import AppSelect from './AppSelect.vue';
import { Label } from '@/components/ui/label';
import { Popover, PopoverContent, PopoverTrigger } from '@/components/ui/popover';
const props = withDefaults(defineProps<{ modelValue?: string; label?: string; placeholder?: string; minuteStep?: number; withSeconds?: boolean; disabled?: boolean; clearable?: boolean; class?: string }>(), { placeholder: '选择时间', minuteStep: 1, withSeconds: false, clearable: true });
const emit = defineEmits<{ 'update:modelValue': [value: string] }>();
const open = ref(false); const hour = ref('00'); const minute = ref('00'); const second = ref('00');
const makeOptions = (count: number, step = 1) => Array.from({ length: Math.ceil(count / step) }, (_, index) => { const value = String(index * step).padStart(2, '0'); return { value, label: value }; });
const hours = makeOptions(24); const minutes = computed(() => makeOptions(60, Math.max(1, props.minuteStep))); const seconds = makeOptions(60);
function sync(value?: string) { const parts = (value || '00:00:00').split(':'); [hour.value, minute.value, second.value] = [parts[0] || '00', parts[1] || '00', parts[2] || '00']; }
watch(() => props.modelValue, sync, { immediate: true }); watch(open, (value) => { if (value) sync(props.modelValue); });
function confirm() { emit('update:modelValue', props.withSeconds ? `${hour.value}:${minute.value}:${second.value}` : `${hour.value}:${minute.value}`); open.value = false; }
</script>
<template><div :class="['grid min-w-0 gap-2', props.class]"><Label v-if="label">{{ label }}</Label><div class="flex min-w-0 gap-1"><Popover v-model:open="open"><PopoverTrigger as-child><AppButton variant="outline" class="h-10 min-w-0 flex-1 justify-start px-3 font-normal" :disabled="disabled"><Clock class="size-4 text-muted-foreground" /><span :class="!modelValue && 'text-muted-foreground'">{{ modelValue || placeholder }}</span></AppButton></PopoverTrigger><PopoverContent align="start" class="w-[min(22rem,calc(100vw-1rem))] p-4"><div class="grid grid-cols-2 gap-3" :class="withSeconds && 'sm:grid-cols-3'"><AppSelect v-model="hour" label="小时" :options="hours" /><AppSelect v-model="minute" label="分钟" :options="minutes" /><AppSelect v-if="withSeconds" v-model="second" label="秒" :options="seconds" /></div><div class="mt-4 flex justify-end gap-2"><AppButton variant="ghost" @click="open = false">取消</AppButton><AppButton @click="confirm">确认</AppButton></div></PopoverContent></Popover><AppButton v-if="clearable && modelValue" variant="ghost" size="icon" aria-label="清空时间" @click="emit('update:modelValue', '')"><X /></AppButton></div></div></template>
