<script setup lang="ts">
import { historyApi } from '@/api/history';
import { Alert, AlertDescription, AlertTitle } from '@/components/ui/alert';
import { Button } from '@/components/ui/button';
import { ScrollArea } from '@/components/ui/scroll-area';
import { Separator } from '@/components/ui/separator';
import { Sheet, SheetContent, SheetDescription, SheetFooter, SheetHeader, SheetTitle } from '@/components/ui/sheet';
import { Skeleton } from '@/components/ui/skeleton';
import { Tooltip, TooltipContent, TooltipProvider, TooltipTrigger } from '@/components/ui/tooltip';
import type { ReportLanguage } from '@/types/analysis';
import { markdownToPlainText } from '@/utils/markdown';
import { renderMarkdownToHtml } from '@/utils/renderMarkdown';
import { getReportText, normalizeReportLanguage } from '@/utils/reportLanguage';
import { formatSecurityLabel } from '@/utils/security';
import { computed, onMounted, onUnmounted, ref } from 'vue';
import { Check, Code2, Copy, FileText } from 'lucide-vue-next';

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

const htmlContent = computed(() => renderMarkdownToHtml(content.value));

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
  <!-- eslint-disable vue/no-v-html -->
  <Sheet
    :open="isOpen"
    @update:open="!$event && handleClose()"
  >
    <SheetContent class="flex max-h-dvh w-full flex-col overflow-hidden sm:max-w-3xl">
      <SheetHeader class="text-left">
        <SheetTitle class="flex items-center gap-2">
          <FileText class="size-5 text-primary" />
          {{ formatSecurityLabel(stockCode, stockName, text.fullReport) }}
        </SheetTitle>
        <SheetDescription>{{ text.fullReport }}</SheetDescription>
      </SheetHeader>
      <Separator />

      <div class="flex items-center justify-end gap-2">
        <TooltipProvider :delay-duration="0">
          <Tooltip>
            <TooltipTrigger as-child>
              <Button
                size="icon"
                variant="outline"
                :disabled="isLoading || !content || copiedType !== null"
                :aria-label="text.copyMarkdownSource"
                @click="handleCopyMarkdown"
              >
                <Check
                  v-if="copiedType === 'markdown'"
                  class="size-4 text-success"
                />
                <Code2
                  v-else
                  class="size-4"
                />
              </Button>
            </TooltipTrigger>
            <TooltipContent>{{ text.copyMarkdownSource }}</TooltipContent>
          </Tooltip>
          <Tooltip>
            <TooltipTrigger as-child>
              <Button
                size="icon"
                variant="outline"
                :disabled="isLoading || !content || copiedType !== null"
                :aria-label="text.copyPlainText"
                @click="handleCopyPlainText"
              >
                <Check
                  v-if="copiedType === 'text'"
                  class="size-4 text-success"
                />
                <Copy
                  v-else
                  class="size-4"
                />
              </Button>
            </TooltipTrigger>
            <TooltipContent>{{ text.copyPlainText }}</TooltipContent>
          </Tooltip>
        </TooltipProvider>
      </div>

      <ScrollArea class="min-h-0 flex-1 pr-4">
        <div
          v-if="isLoading"
          class="space-y-3 py-4"
        >
          <Skeleton class="h-8 w-2/3" />
          <Skeleton
            v-for="line in 8"
            :key="line"
            class="h-4 w-full"
          />
        </div>
        <Alert
          v-else-if="error"
          variant="destructive"
        >
          <AlertTitle>{{ text.loadReportFailed }}</AlertTitle>
          <AlertDescription>{{ error }}</AlertDescription>
        </Alert>
        <div
          v-else
          class="prose max-w-none whitespace-pre-line break-words prose-headings:mb-2 prose-headings:mt-4 prose-headings:font-semibold prose-headings:text-foreground prose-h1:text-xl prose-h2:text-lg prose-h3:text-base prose-p:mb-3 prose-p:last:mb-0 prose-p:leading-relaxed prose-strong:font-semibold prose-strong:text-foreground prose-ul:my-2 prose-ol:my-2 prose-li:my-1 prose-code:rounded prose-code:px-1.5 prose-code:py-0.5 prose-code:before:content-none prose-code:after:content-none prose-pre:border prose-table:border-collapse prose-hr:my-4 prose-a:no-underline hover:prose-a:underline prose-blockquote:text-muted-foreground"
          v-html="htmlContent"
        />
      </ScrollArea>

      <Separator />
      <SheetFooter class="pb-[max(0rem,env(safe-area-inset-bottom))]">
        <Button
          variant="outline"
          @click="handleClose"
        >
          {{ text.dismiss }}
        </Button>
      </SheetFooter>
    </SheetContent>
  </Sheet>
</template>
