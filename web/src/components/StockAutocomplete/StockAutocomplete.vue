<script setup lang="ts">
import SuggestionsList from '@/components/StockAutocomplete/SuggestionsList.vue';
import { useAutocomplete } from '@/composables/useAutocomplete';
import type { AssetType, Market } from '@/types/stockIndex';
import { cn } from '@/utils/cn';
import { nextTick, onUnmounted, ref, watch } from 'vue';

const AUTOCOMPLETE_INPUT_CLASS =
  'border-input bg-background shadow-xs focus:border-ring focus:ring-2 focus:ring-ring/30 h-11 w-full rounded-xl border bg-transparent px-4 text-sm transition-all focus:outline-none disabled:cursor-not-allowed disabled:opacity-60';

const props = withDefaults(
  defineProps<{
    modelValue: string;
    disabled?: boolean;
    placeholder?: string;
    class?: string;
  }>(),
  {
    disabled: false,
    placeholder: '输入股票代码或名称',
    class: '',
  },
);

const emit = defineEmits<{
  'update:modelValue': [value: string];
  submit: [
    code: string,
    name?: string,
    source?: 'manual' | 'autocomplete',
    market?: Market,
    assetType?: AssetType,
  ];
}>();

const {
  setQuery,
  suggestions,
  isOpen,
  searching,
  highlightedIndex,
  setHighlightedIndex,
  highlightPrevious,
  highlightNext,
  close,
  isComposing,
  setIsComposing,
} = useAutocomplete();

const inputRef = ref<HTMLInputElement | null>(null);
const prevValue = ref(props.modelValue);
const dropdownStyle = ref<{ top: string; left: string; width: string } | null>(null);

let openListenersCleanup: (() => void) | null = null;

function updateDropdownPosition() {
  const el = inputRef.value;
  if (!el) {
    dropdownStyle.value = null;
    return;
  }
  const rect = el.getBoundingClientRect();
  dropdownStyle.value = {
    top: `${rect.bottom}px`,
    left: `${rect.left}px`,
    width: `${rect.width}px`,
  };
}

function closeSuggestions() {
  close();
  dropdownStyle.value = null;
}

watch(
  () => props.modelValue,
  (v) => {
    if (prevValue.value !== v) {
      setQuery(v);
      prevValue.value = v;
    }
  },
  { immediate: true },
);

watch(isOpen, (open) => {
  openListenersCleanup?.();
  openListenersCleanup = null;

  if (!open) {
    dropdownStyle.value = null;
    return;
  }

  // Wait for DOM (ref + layout) so getBoundingClientRect is valid; IME can open the panel
  // in the same tick as isOpen flipping true without a prior dropdownStyle.
  void nextTick().then(() => {
    if (!isOpen.value) {
      return;
    }
    updateDropdownPosition();
    const frame = requestAnimationFrame(() => {
      if (!isOpen.value) {
        return;
      }
      updateDropdownPosition();
    });
    window.addEventListener('resize', updateDropdownPosition);
    window.addEventListener('scroll', updateDropdownPosition, true);
    openListenersCleanup = () => {
      cancelAnimationFrame(frame);
      window.removeEventListener('resize', updateDropdownPosition);
      window.removeEventListener('scroll', updateDropdownPosition, true);
    };
  });
});

watch(suggestions, () => {
  if (isOpen.value) {
    void nextTick(() => updateDropdownPosition());
  }
});

onUnmounted(() => {
  openListenersCleanup?.();
});

function onKeyDown(e: KeyboardEvent) {
  if (isComposing.value) return;

  switch (e.key) {
    case 'ArrowDown':
      e.preventDefault();
      highlightNext();
      break;
    case 'ArrowUp':
      e.preventDefault();
      highlightPrevious();
      break;
    case 'Enter':
      e.preventDefault();
      if (highlightedIndex.value >= 0 && suggestions.value[highlightedIndex.value]) {
        const selected = suggestions.value[highlightedIndex.value]!;
        emit('update:modelValue', selected.displayCode);
        closeSuggestions();
        emit(
          'submit',
          selected.canonicalCode,
          selected.nameZh,
          'autocomplete',
          selected.market,
          selected.assetType,
        );
      } else {
        emit('submit', props.modelValue, undefined, 'manual');
      }
      break;
    case 'Escape':
      e.preventDefault();
      closeSuggestions();
      break;
    default:
  }
}

function onBlur() {
  window.setTimeout(() => closeSuggestions(), 200);
}

function onSelectSuggestion(s: (typeof suggestions.value)[number]) {
  emit('update:modelValue', s.displayCode);
  closeSuggestions();
  emit('submit', s.canonicalCode, s.nameZh, 'autocomplete', s.market, s.assetType);
}

function onFocus() {
  if (isOpen.value) {
    void nextTick(() => updateDropdownPosition());
  }
}

function onCompositionEnd(e: CompositionEvent) {
  setIsComposing(false);
  const el = e.target;
  if (!(el instanceof HTMLInputElement) || props.disabled) return;
  // Some IMEs (notably Safari / macOS) commit composed text without a final `input` event;
  // sync so debounced search runs on the final Chinese string (e.g. 贵州).
  emit('update:modelValue', el.value);
  setQuery(el.value);
}
</script>

<template>
  <div class="stock-autocomplete relative">
    <input
      ref="inputRef"
      type="text"
      :value="modelValue"
      :disabled="disabled"
      :placeholder="placeholder"
      :class="cn(AUTOCOMPLETE_INPUT_CLASS, isOpen && 'rounded-b-none', props.class)"
      aria-autocomplete="none"
      role="combobox"
      :aria-expanded="isOpen"
      aria-haspopup="listbox"
      aria-controls="suggestions-list"
      @input="
        (e) => {
          const v = (e.target as HTMLInputElement).value;
          emit('update:modelValue', v);
          setQuery(v);
        }
      "
      @keydown="onKeyDown"
      @compositionstart="setIsComposing(true)"
      @compositionend="onCompositionEnd"
      @focus="onFocus"
      @blur="onBlur"
    />

    <div
      v-if="searching"
      class="absolute top-1/2 right-3 -translate-y-1/2"
    >
      <div class="h-4 w-4 animate-spin rounded-full border-2 border-primary/20 border-t-primary" />
    </div>

    <Teleport to="body">
      <SuggestionsList
        v-if="isOpen && dropdownStyle"
        :suggestions="suggestions"
        :highlighted-index="highlightedIndex"
        :list-style="dropdownStyle"
        @select="onSelectSuggestion"
        @mouse-enter="setHighlightedIndex"
      />
    </Teleport>
  </div>
</template>
