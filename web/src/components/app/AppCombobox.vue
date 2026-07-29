<script setup lang="ts">
import { computed, ref } from 'vue';
import { Check, ChevronsUpDown, X } from 'lucide-vue-next';
import AppButton from './AppButton.vue';
import { Command, CommandEmpty, CommandGroup, CommandInput, CommandItem, CommandList } from '@/components/ui/command';
import { Label } from '@/components/ui/label';
import { Popover, PopoverContent, PopoverTrigger } from '@/components/ui/popover';
import { cn } from '@/lib/utils';

export type AppComboboxOption = {
  value: string;
  label: string;
  keywords?: string;
  disabled?: boolean;
};

const props = withDefaults(defineProps<{
  modelValue?: string;
  options: AppComboboxOption[];
  label?: string;
  placeholder?: string;
  searchPlaceholder?: string;
  emptyText?: string;
  clearable?: boolean;
  disabled?: boolean;
  class?: string;
}>(), {
  modelValue: '',
  label: '',
  placeholder: '请选择',
  searchPlaceholder: '搜索…',
  emptyText: '没有匹配项',
  clearable: true,
  disabled: false,
  class: '',
});

const emit = defineEmits<{ 'update:modelValue': [value: string] }>();
const open = ref(false);
const selected = computed(() => props.options.find((option) => option.value === props.modelValue));

function choose(value: string) {
  emit('update:modelValue', value);
  open.value = false;
}
</script>

<template>
  <div :class="['grid min-w-0 gap-2', props.class]">
    <Label v-if="label">{{ label }}</Label>
    <div class="flex min-w-0 gap-1">
      <Popover v-model:open="open" modal>
        <PopoverTrigger as-child>
          <AppButton
            variant="outline"
            class="h-10 min-w-0 flex-1 justify-between px-3 font-normal"
            role="combobox"
            :aria-label="label || placeholder"
            :aria-expanded="open"
            :disabled="disabled"
          >
            <span class="truncate" :class="!selected && 'text-muted-foreground'">
              {{ selected?.label ?? placeholder }}
            </span>
            <ChevronsUpDown class="ml-2 size-4 shrink-0 opacity-50" />
          </AppButton>
        </PopoverTrigger>
        <PopoverContent class="w-[var(--reka-popover-trigger-width)] max-w-[calc(100vw-2rem)] p-0">
          <Command>
            <CommandInput :placeholder="searchPlaceholder" />
            <CommandList class="max-h-[min(18rem,55dvh)]">
              <CommandEmpty>{{ emptyText }}</CommandEmpty>
              <CommandGroup>
                <CommandItem
                  v-for="option in options"
                  :key="option.value"
                  :value="`${option.label} ${option.keywords ?? ''}`"
                  :disabled="option.disabled"
                  @select="choose(option.value)"
                >
                  <Check :class="cn('size-4', option.value === modelValue ? 'opacity-100' : 'opacity-0')" />
                  {{ option.label }}
                </CommandItem>
              </CommandGroup>
            </CommandList>
          </Command>
        </PopoverContent>
      </Popover>
      <AppButton
        v-if="clearable && modelValue"
        variant="ghost"
        size="icon"
        aria-label="清空选择"
        @click="emit('update:modelValue', '')"
      >
        <X />
      </AppButton>
    </div>
  </div>
</template>
