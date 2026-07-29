<script setup lang="ts">
import { CalendarClock, X } from 'lucide-vue-next';
import { computed, ref, useId, watch } from 'vue';
import AppButton from './AppButton.vue';
import AppDatePicker from './AppDatePicker.vue';
import AppTimePicker from './AppTimePicker.vue';
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from '@/components/ui/dialog';
import { Label } from '@/components/ui/label';

const props = withDefaults(
  defineProps<{
    modelValue?: string;
    label?: string;
    placeholder?: string;
    disabled?: boolean;
    clearable?: boolean;
    minuteStep?: number;
    error?: string;
    hint?: string;
    id?: string;
    class?: string;
  }>(),
  {
    placeholder: '选择日期和时间',
    disabled: false,
    clearable: true,
    minuteStep: 1,
    modelValue: undefined,
    label: '',
    error: '',
    hint: '',
    id: undefined,
    class: '',
  },
);

const emit = defineEmits<{ 'update:modelValue': [value: string] }>();
const open = ref(false);
const date = ref('');
const time = ref('00:00');
const generatedId = useId();
const triggerId = computed(() => props.id ?? generatedId);
const descriptionId = computed(() =>
  props.error ? `${triggerId.value}-error` : props.hint ? `${triggerId.value}-hint` : undefined,
);
const display = computed(() => (props.modelValue ? props.modelValue.replace('T', ' ') : ''));

function sync() {
  const [datePart = '', timePart = '00:00'] = (props.modelValue || '').split('T');
  date.value = datePart;
  time.value = timePart.slice(0, 5) || '00:00';
}

watch(() => props.modelValue, sync, { immediate: true });
watch(open, (value) => {
  if (value) sync();
});

function confirm() {
  if (!date.value) return;
  emit('update:modelValue', `${date.value}T${time.value || '00:00'}`);
  open.value = false;
}
</script>

<template>
  <div :class="['grid min-w-0 gap-2', props.class]">
    <Label
      v-if="label"
      :for="triggerId"
    >{{ label }}</Label>
    <div class="flex min-w-0 gap-1">
      <AppButton
        :id="triggerId"
        variant="outline"
        class="h-10 min-w-0 flex-1 justify-start px-3 font-normal"
        :disabled="disabled"
        :aria-invalid="error ? true : undefined"
        :aria-describedby="descriptionId"
        @click="open = true"
      >
        <CalendarClock class="size-4 text-muted-foreground" />
        <span
          class="truncate"
          :class="!display && 'text-muted-foreground'"
        >
          {{ display || placeholder }}
        </span>
      </AppButton>
      <AppButton
        v-if="clearable && modelValue"
        variant="ghost"
        size="icon"
        :disabled="disabled"
        aria-label="清空日期时间"
        @click="emit('update:modelValue', '')"
      >
        <X />
      </AppButton>
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

    <Dialog v-model:open="open">
      <DialogContent
        class="max-h-[calc(100dvh-1rem)] max-w-[calc(100%-1rem)] overflow-y-auto sm:max-w-lg"
      >
        <DialogHeader>
          <DialogTitle>选择日期和时间</DialogTitle>
          <DialogDescription>日期和时间确认后才会应用。</DialogDescription>
        </DialogHeader>
        <div class="grid gap-4 sm:grid-cols-2">
          <AppDatePicker
            v-model="date"
            label="日期"
            :clearable="false"
          />
          <AppTimePicker
            v-model="time"
            label="时间"
            :minute-step="minuteStep"
            :clearable="false"
          />
        </div>
        <DialogFooter class="sticky bottom-0 bg-popover pt-2">
          <AppButton
            variant="outline"
            @click="open = false"
          >
            取消
          </AppButton>
          <AppButton
            :disabled="!date"
            @click="confirm"
          >
            确认
          </AppButton>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  </div>
</template>
