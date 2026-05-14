<script setup lang="ts">
import Drawer from '@/components/common/Drawer.vue';
import Tooltip from '@/components/common/Tooltip.vue';
import { historyApi } from '@/api/history';
import type { ReportLanguage } from '@/types/analysis';
import { markdownToPlainText } from '@/utils/markdown';
import { getReportText, normalizeReportLanguage } from '@/utils/reportLanguage';
import { marked } from 'marked';
import { computed, onMounted, onUnmounted, ref } from 'vue';

let fetchActive = true;

const props = withDefaults(
  defineProps<{
    recordId: number;
    stockName: string;
    stockCode: string;
    reportLanguage?: ReportLanguage;
  }>(),
  {
    reportLanguage: 'zh',
  },
);

const emit = defineEmits<{
  close: [];
}>();

const text = getReportText(normalizeReportLanguage(props.reportLanguage));
const loadReportFailedText = text.loadReportFailed;

const content = ref('');
const isLoading = ref(true);
const error = ref<string | null>(null);
const isOpen = ref(true);
const copiedType = ref<'markdown' | 'text' | null>(null);

let closeTimer: number | null = null;

function handleClose() {
  isOpen.value = false;
  closeTimer = window.setTimeout(() => {
    emit('close');
    closeTimer = null;
  }, 300);
}

async function handleCopyMarkdown() {
  if (!content.value) return;
  try {
    await navigator.clipboard.writeText(content.value);
    copiedType.value = 'markdown';
    window.setTimeout(() => {
      copiedType.value = null;
    }, 2000);
  } catch (e) {
    console.error('Copy failed:', e);
  }
}

async function handleCopyPlainText() {
  if (!content.value) return;
  try {
    const plainText = markdownToPlainText(content.value);
    await navigator.clipboard.writeText(plainText);
    copiedType.value = 'text';
    window.setTimeout(() => {
      copiedType.value = null;
    }, 2000);
  } catch (e) {
    console.error('Copy failed:', e);
  }
}

const htmlContent = computed(() => {
  if (!content.value) return '';
  try {
    return marked.parse(content.value, { async: false, gfm: true }) as string;
  } catch {
    return '';
  }
});

onMounted(() => {
  isLoading.value = true;
  error.value = null;
  void historyApi
    .getMarkdown(props.recordId)
    .then((markdownContent) => {
      if (fetchActive) content.value = markdownContent;
    })
    .catch((err: unknown) => {
      if (fetchActive) {
        error.value = err instanceof Error ? err.message : loadReportFailedText;
      }
    })
    .finally(() => {
      if (fetchActive) isLoading.value = false;
    });
});

onUnmounted(() => {
  fetchActive = false;
  if (closeTimer !== null) window.clearTimeout(closeTimer);
});
</script>

<template>
  <Drawer
    :is-open="isOpen"
    width="max-w-3xl"
    :z-index="100"
    backdrop-class-name="bg-background/56 backdrop-blur-[2px]"
    @close="handleClose"
  >
    <div class="mb-4 flex items-center justify-between gap-3">
      <div class="flex flex-1 items-center gap-3">
        <div
          class="flex h-8 w-8 items-center justify-center rounded-lg bg-[var(--home-action-report-bg)] text-[var(--home-action-report-text)]"
        >
          <svg class="h-4 w-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
            <path
              stroke-linecap="round"
              stroke-linejoin="round"
              stroke-width="2"
              d="M9 12h6m-6 4h6m2 5H7a2 2 0 01-2-2V5a2 2 0 012-2h5.586a1 1 0 01.707.293l5.414 5.414a1 1 0 01.293.707V19a2 2 0 01-2 2z"
            />
          </svg>
        </div>
        <div>
          <h2 class="text-base font-semibold text-foreground">
            {{ stockName || stockCode }}
          </h2>
          <p class="text-xs text-muted-text">{{ text.fullReport }}</p>
        </div>
      </div>

      <div class="flex items-center gap-2">
        <Tooltip :content="text.copyMarkdownSource">
          <span class="inline-flex">
            <button
              type="button"
              :disabled="isLoading || !content || copiedType !== null"
              class="home-surface-button flex h-10 w-10 items-center justify-center rounded-lg text-secondary-text hover:text-foreground disabled:opacity-50"
              :aria-label="text.copyMarkdownSource"
              @click="handleCopyMarkdown"
            >
              <svg
                v-if="copiedType === 'markdown'"
                class="h-6 w-6 text-success"
                fill="none"
                stroke="currentColor"
                viewBox="0 0 24 24"
              >
                <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M5 13l4 4L19 7" />
              </svg>
              <svg v-else class="h-6 w-6" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                <path
                  stroke-linecap="round"
                  stroke-linejoin="round"
                  stroke-width="2"
                  d="M10 20l4-16m4 4l4 4-4 4M6 16l-4-4 4-4"
                />
              </svg>
            </button>
          </span>
        </Tooltip>

        <Tooltip :content="text.copyPlainText">
          <span class="inline-flex">
            <button
              type="button"
              :disabled="isLoading || !content || copiedType !== null"
              class="home-surface-button flex h-10 w-10 items-center justify-center rounded-lg text-secondary-text hover:text-foreground disabled:opacity-50"
              :aria-label="text.copyPlainText"
              @click="handleCopyPlainText"
            >
              <svg
                v-if="copiedType === 'text'"
                class="h-6 w-6 text-success"
                fill="none"
                stroke="currentColor"
                viewBox="0 0 24 24"
              >
                <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M5 13l4 4L19 7" />
              </svg>
              <svg v-else class="h-6 w-6" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                <path
                  stroke-linecap="round"
                  stroke-linejoin="round"
                  stroke-width="2"
                  d="M9 12h6m-6 4h6m2 5H7a2 2 0 01-2-2V5a2 2 0 012-2h5.586a1 1 0 01.707.293l5.414 5.414a1 1 0 01.293.707V19a2 2 0 01-2 2z"
                />
              </svg>
            </button>
          </span>
        </Tooltip>
      </div>
    </div>

    <div v-if="isLoading" class="flex h-64 flex-col items-center justify-center">
      <div class="home-spinner h-10 w-10 animate-spin border-[3px]" />
      <p class="mt-4 text-sm text-secondary-text">{{ text.loadingReport }}</p>
    </div>
    <div v-else-if="error" class="flex h-64 flex-col items-center justify-center">
      <div class="mb-3 flex h-12 w-12 items-center justify-center rounded-xl bg-danger/10">
        <svg class="h-6 w-6 text-danger" fill="none" stroke="currentColor" viewBox="0 0 24 24">
          <path
            stroke-linecap="round"
            stroke-linejoin="round"
            stroke-width="2"
            d="M12 9v2m0 4h.01m-6.938 4h13.856c1.54 0 2.502-1.667 1.732-3L13.732 4c-.77-1.333-2.694-1.333-3.464 0L3.34 16c-.77 1.333.192 3 1.732 3z"
          />
        </svg>
      </div>
      <p class="text-sm text-danger">{{ error }}</p>
      <button
        type="button"
        class="home-surface-button mt-4 rounded-lg px-4 py-2 text-sm text-secondary-text"
        @click="handleClose"
      >
        {{ text.dismiss }}
      </button>
    </div>
    <div
      v-else
      class="home-markdown-prose prose prose-invert prose-sm max-w-none whitespace-pre-line break-words
        prose-headings:mb-2 prose-headings:mt-4 prose-headings:font-semibold prose-headings:text-foreground
        prose-h1:text-xl
        prose-h2:text-lg
        prose-h3:text-base
        prose-p:mb-3 prose-p:last:mb-0 prose-p:leading-relaxed
        prose-strong:font-semibold prose-strong:text-foreground
        prose-ul:my-2 prose-ol:my-2 prose-li:my-1
        prose-code:rounded prose-code:px-1.5 prose-code:py-0.5 prose-code:before:content-none prose-code:after:content-none
        prose-pre:border
        prose-table:border-collapse
        prose-hr:my-4
        prose-a:no-underline hover:prose-a:underline
        prose-blockquote:text-secondary-text"
      v-html="htmlContent"
    />

    <div class="home-divider mt-6 flex justify-end border-t pt-4">
      <button
        type="button"
        class="home-surface-button rounded-lg px-4 py-2 text-sm text-secondary-text hover:text-foreground"
        @click="handleClose"
      >
        {{ text.dismiss }}
      </button>
    </div>
  </Drawer>
</template>
