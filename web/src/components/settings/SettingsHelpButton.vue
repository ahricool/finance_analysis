<script setup lang="ts">
import Tooltip from '@/components/common/Tooltip.vue';
import { getSettingsHelpContent } from '@/locales/settingsHelp';
import { cn } from '@/utils/cn';
import type { SystemConfigFieldSchema } from '@/types/systemConfig';
import { CircleHelp, ExternalLink, X } from 'lucide-vue-next';
import {
  computed,
  nextTick,
  onUnmounted,
  ref,
  useId,
  watch,
} from 'vue';

const props = defineProps<{
  fieldKey: string;
  title: string;
  schema?: SystemConfigFieldSchema;
  description?: string;
}>();

const FOCUSABLE_SELECTOR = [
  'a[href]',
  'button:not([disabled])',
  'textarea:not([disabled])',
  'input:not([disabled])',
  'select:not([disabled])',
  '[tabindex]:not([tabindex="-1"])',
].join(',');

function getFocusableElements(container: HTMLElement): HTMLElement[] {
  return Array.from(container.querySelectorAll<HTMLElement>(FOCUSABLE_SELECTOR));
}

function hasItems<T>(items: T[] | undefined): items is T[] {
  return Boolean(items?.length);
}

const help = computed(() => getSettingsHelpContent(props.schema?.helpKey, props.description));

const open = ref(false);
const buttonRef = ref<HTMLButtonElement | null>(null);
const dialogRef = ref<HTMLDivElement | null>(null);
const closeButtonRef = ref<HTMLButtonElement | null>(null);
const titleId = useId();

const examples = computed(() => props.schema?.examples ?? []);
const docs = computed(() =>
  props.schema?.docs?.length ? props.schema.docs : help.value?.docs ?? [],
);

let overflowPrev = '';

function onGlobalKeyDown(event: KeyboardEvent) {
  if (event.key === 'Escape') {
    open.value = false;
    return;
  }

  if (event.key !== 'Tab') {
    return;
  }

  const dialog = dialogRef.value;
  if (!dialog) {
    return;
  }

  const focusableElements = getFocusableElements(dialog);
  if (!focusableElements.length) {
    event.preventDefault();
    dialog.focus();
    return;
  }

  const firstElement = focusableElements[0];
  const lastElement = focusableElements[focusableElements.length - 1];
  const activeElement = document.activeElement;

  if (event.shiftKey) {
    if (!activeElement || !dialog.contains(activeElement) || activeElement === firstElement) {
      event.preventDefault();
      lastElement.focus();
    }
    return;
  }

  if (!activeElement || !dialog.contains(activeElement) || activeElement === lastElement) {
    event.preventDefault();
    firstElement.focus();
  }
}

watch(open, (isOpen) => {
  if (!isOpen) {
    document.removeEventListener('keydown', onGlobalKeyDown);
    document.body.style.overflow = overflowPrev;
    nextTick(() => buttonRef.value?.focus());
    return;
  }

  document.addEventListener('keydown', onGlobalKeyDown);
  overflowPrev = document.body.style.overflow;
  document.body.style.overflow = 'hidden';
  nextTick(() => closeButtonRef.value?.focus());
});

onUnmounted(() => {
  document.removeEventListener('keydown', onGlobalKeyDown);
  document.body.style.overflow = overflowPrev;
});
</script>

<template>
  <template v-if="help">
    <Tooltip content="查看配置说明">
      <span class="inline-flex">
        <button
          ref="buttonRef"
          type="button"
          class="inline-flex h-7 w-7 items-center justify-center rounded-lg border border-transparent text-muted-text transition-colors hover:border-[var(--settings-border)] hover:bg-[var(--settings-surface-hover)] hover:text-foreground focus-visible:outline-none focus-visible:ring-4 focus-visible:ring-cyan/15"
          :aria-label="`查看 ${title} 配置说明`"
          :aria-expanded="open"
          :aria-controls="open ? titleId : undefined"
          @click="open = true"
        >
          <CircleHelp aria-hidden="true" class="h-4 w-4" />
        </button>
      </span>
    </Tooltip>

    <Teleport to="body">
      <div
        v-if="open"
        class="fixed inset-0 z-[140] flex items-end bg-background/25 backdrop-blur-sm sm:items-center sm:justify-center"
      >
        <button
          type="button"
          class="absolute inset-0 cursor-default"
          aria-label="关闭配置说明"
          tabindex="-1"
          @click="open = false"
        />
        <div
          ref="dialogRef"
          role="dialog"
          aria-modal="true"
          :aria-labelledby="titleId"
          tabindex="-1"
          :class="
            cn(
              'relative flex max-h-[88vh] w-full flex-col overflow-hidden rounded-t-2xl border border-border/80 bg-card shadow-soft-card-strong',
              'sm:max-w-2xl sm:rounded-2xl',
            )
          "
        >
          <div class="h-1 w-full bg-gradient-to-r from-cyan/80 via-primary/70 to-purple/70" />
          <div class="flex items-start justify-between gap-4 border-b border-border/60 px-5 py-4">
            <div class="min-w-0">
              <p class="text-[11px] font-semibold uppercase tracking-[0.18em] text-muted-text">
                {{ fieldKey }}
              </p>
              <h2 :id="titleId" class="mt-1 text-lg font-semibold text-foreground">
                {{ help.title || title }}
              </h2>
              <p v-if="help.summary" class="mt-2 text-sm leading-6 text-secondary-text">{{ help.summary }}</p>
            </div>
            <button
              ref="closeButtonRef"
              type="button"
              class="inline-flex h-9 w-9 shrink-0 items-center justify-center rounded-xl border border-border/70 bg-card/80 text-secondary-text transition-colors hover:bg-hover hover:text-foreground focus-visible:outline-none focus-visible:ring-4 focus-visible:ring-cyan/15"
              aria-label="关闭配置说明"
              @click="open = false"
            >
              <X aria-hidden="true" class="h-4 w-4" />
            </button>
          </div>

          <div class="space-y-5 overflow-y-auto px-5 py-5">
            <section v-if="help.usage" class="space-y-2">
              <h3 class="text-xs font-semibold uppercase tracking-[0.16em] text-muted-text">用途</h3>
              <p class="text-sm leading-6 text-secondary-text">{{ help.usage }}</p>
            </section>

            <section v-if="hasItems(help.valueNotes)" class="space-y-2">
              <h3 class="text-xs font-semibold uppercase tracking-[0.16em] text-muted-text">取值说明</h3>
              <ul class="space-y-1.5 text-sm leading-6 text-secondary-text">
                <li v-for="item in help.valueNotes" :key="item" class="flex gap-2">
                  <span class="mt-2 h-1.5 w-1.5 shrink-0 rounded-full bg-cyan/70" />
                  <span>{{ item }}</span>
                </li>
              </ul>
            </section>

            <section v-if="hasItems(examples)" class="space-y-2">
              <h3 class="text-xs font-semibold uppercase tracking-[0.16em] text-muted-text">配置样例</h3>
              <div class="space-y-2">
                <code
                  v-for="example in examples"
                  :key="example"
                  class="block whitespace-pre-wrap break-words rounded-lg border border-border/70 bg-background/70 px-3 py-2 font-mono text-xs leading-5 text-foreground"
                >
                  {{ example }}
                </code>
              </div>
            </section>

            <section v-if="hasItems(help.impact)" class="space-y-2">
              <h3 class="text-xs font-semibold uppercase tracking-[0.16em] text-muted-text">影响范围</h3>
              <ul class="space-y-1.5 text-sm leading-6 text-secondary-text">
                <li v-for="item in help.impact" :key="item" class="flex gap-2">
                  <span class="mt-2 h-1.5 w-1.5 shrink-0 rounded-full bg-cyan/70" />
                  <span>{{ item }}</span>
                </li>
              </ul>
            </section>

            <section v-if="hasItems(help.notes)" class="space-y-2">
              <h3 class="text-xs font-semibold uppercase tracking-[0.16em] text-muted-text">注意事项</h3>
              <ul class="space-y-1.5 text-sm leading-6 text-secondary-text">
                <li v-for="item in help.notes" :key="item" class="flex gap-2">
                  <span class="mt-2 h-1.5 w-1.5 shrink-0 rounded-full bg-cyan/70" />
                  <span>{{ item }}</span>
                </li>
              </ul>
            </section>

            <section v-if="hasItems(docs)" class="space-y-2">
              <h3 class="text-xs font-semibold uppercase tracking-[0.16em] text-muted-text">相关文档</h3>
              <div class="flex flex-wrap gap-2">
                <a
                  v-for="doc in docs"
                  :key="`${doc.label}-${doc.href}`"
                  class="inline-flex items-center gap-1.5 rounded-lg border border-border/70 bg-background/60 px-3 py-2 text-xs text-secondary-text transition-colors hover:bg-hover hover:text-foreground"
                  :href="doc.href"
                  rel="noreferrer"
                  target="_blank"
                >
                  <span>{{ doc.label }}</span>
                  <ExternalLink aria-hidden="true" class="h-3.5 w-3.5" />
                </a>
              </div>
            </section>
          </div>
        </div>
      </div>
    </Teleport>
  </template>
</template>
