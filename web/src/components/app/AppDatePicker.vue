<script setup lang="ts">
import type { DateValue } from 'reka-ui';
import { CalendarDays, X } from 'lucide-vue-next';
import { parseDate } from '@internationalized/date';
import { computed, ref, useId } from 'vue';
import { Button } from '@/components/ui/button';
import { Calendar } from '@/components/ui/calendar';
import { Label } from '@/components/ui/label';
import { Popover, PopoverContent, PopoverTrigger } from '@/components/ui/popover';

const props = withDefaults(
  defineProps<{
    modelValue?: string;
    label?: string;
    placeholder?: string;
    disabled?: boolean;
    clearable?: boolean;
    min?: string;
    max?: string;
    availableDates?: string[];
    error?: string;
    hint?: string;
    id?: string;
    class?: string;
  }>(),
  {
    placeholder: '选择日期',
    clearable: true,
    disabled: false,
    modelValue: undefined,
    label: '',
    min: undefined,
    max: undefined,
    availableDates: undefined,
    error: '',
    hint: '',
    id: undefined,
    class: '',
  },
);

const emit = defineEmits<{ 'update:modelValue': [value: string] }>();
const open = ref(false);
const generatedId = useId();
const triggerId = computed(() => props.id ?? generatedId);
const descriptionId = computed(() =>
  props.error ? `${triggerId.value}-error` : props.hint ? `${triggerId.value}-hint` : undefined,
);

function toDateValue(value?: string): DateValue | undefined {
  try {
    return value ? parseDate(value.slice(0, 10)) : undefined;
  } catch {
    return undefined;
  }
}

const selected = computed(() => toDateValue(props.modelValue));
const availableSet = computed(
  () => new Set((props.availableDates ?? []).map((value) => value.slice(0, 10))),
);
const sortedAvailable = computed(() => [...availableSet.value].sort());
const effectiveMin = computed(() => props.min ?? sortedAvailable.value[0]);
const effectiveMax = computed(() => props.max ?? sortedAvailable.value.at(-1));

function isDateUnavailable(date: DateValue) {
  return availableSet.value.size > 0 && !availableSet.value.has(date.toString());
}

const display = computed(() =>
  props.modelValue
    ? new Intl.DateTimeFormat('zh-CN', {
        year: 'numeric',
        month: 'long',
        day: 'numeric',
      }).format(new Date(`${props.modelValue.slice(0, 10)}T00:00:00`))
    : '',
);

function choose(value: DateValue | undefined) {
  emit('update:modelValue', value?.toString() ?? '');
  if (value) open.value = false;
}
</script>

<template>
  <div :class="['grid min-w-0 gap-2', props.class]">
    <Label
      v-if="label"
      :for="triggerId"
    >{{ label }}</Label>
    <div class="flex min-w-0 gap-1">
      <Popover v-model:open="open">
        <PopoverTrigger as-child>
          <Button
            :id="triggerId"
            variant="outline"
            class="h-10 min-w-0 flex-1 justify-start px-3 font-normal"
            :disabled="disabled"
            :aria-invalid="error ? true : undefined"
            :aria-describedby="descriptionId"
          >
            <CalendarDays class="size-4 text-muted-foreground" />
            <span
              class="truncate"
              :class="!display && 'text-muted-foreground'"
            >
              {{ display || placeholder }}
            </span>
          </Button>
        </PopoverTrigger>
        <PopoverContent
          align="start"
          class="w-auto max-w-[calc(100vw-1rem)] overflow-auto p-0"
        >
          <Calendar
            :model-value="selected"
            locale="zh-CN"
            layout="month-and-year"
            :min-value="toDateValue(effectiveMin)"
            :max-value="toDateValue(effectiveMax)"
            :is-date-unavailable="isDateUnavailable"
            @update:model-value="choose"
          />
        </PopoverContent>
      </Popover>
      <Button
        v-if="clearable && modelValue"
        variant="ghost"
        size="icon"
        :disabled="disabled"
        aria-label="清空日期"
        @click="emit('update:modelValue', '')"
      >
        <X />
      </Button>
    </div>
    <p
      v-if="error"
      :id="`${triggerId}-error`"
      class="text-xs text-destructive"
      role="alert"
    >
      {{ error }}
    </p>
    <p
      v-else-if="hint"
      :id="`${triggerId}-hint`"
      class="text-xs text-muted-foreground"
    >
      {{ hint }}
    </p>
  </div>
</template>
