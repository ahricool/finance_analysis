<script setup lang="ts">
import DashboardPanelHeader from '@/components/dashboard/DashboardPanelHeader.vue';
import { Card } from '@/components/ui/card';
import type { ReportDetails as ReportDetailsType, ReportLanguage } from '@/types/analysis';
import { getReportText, normalizeReportLanguage } from '@/utils/reportLanguage';
import { onUnmounted, ref } from 'vue';
import { ChevronDown } from 'lucide-vue-next';

const props = withDefaults(
  defineProps<{
    details?: ReportDetailsType;
    recordId?: number;
    language?: ReportLanguage;
  }>(),
  {
    language: 'zh',
    details: undefined,
    recordId: undefined,
  },
);

type JsonPanel = 'raw' | 'snapshot';
type CopiedPanelState = Record<JsonPanel, boolean>;

const reportLanguage = normalizeReportLanguage(props.language);
const text = getReportText(reportLanguage);

const showRaw = ref(false);
const showSnapshot = ref(false);
const copiedPanels = ref<CopiedPanelState>({ raw: false, snapshot: false });
const copyResetTimerRef = ref<Partial<Record<JsonPanel, number>>>({});

onUnmounted(() => {
  Object.values(copyResetTimerRef.value).forEach((timerId) => {
    if (timerId !== undefined) {
      window.clearTimeout(timerId);
    }
  });
  copyResetTimerRef.value = {};
});

function copyToClipboard(content: string, panel: JsonPanel) {
  void navigator.clipboard.writeText(content).then(
    () => {
      copiedPanels.value = { ...copiedPanels.value, [panel]: true };
      const existing = copyResetTimerRef.value[panel];
      if (existing !== undefined) {
        window.clearTimeout(existing);
      }
      copyResetTimerRef.value[panel] = window.setTimeout(() => {
        copiedPanels.value = { ...copiedPanels.value, [panel]: false };
        delete copyResetTimerRef.value[panel];
      }, 2000);
    },
    (err) => {
      console.error('Copy failed:', err);
    },
  );
}

function renderJsonPre(data: unknown, panel: JsonPanel) {
  const jsonStr = JSON.stringify(data, null, 2);
  return { jsonStr, panel };
}
</script>

<template>
  <Card
    v-if="details?.rawResult || details?.contextSnapshot || recordId"
    class="p-5 text-left"
  >
    <DashboardPanelHeader class="mb-3">
      <template #eyebrow>
        {{ text.transparency }}
      </template>
      <template #title>
        {{ text.traceability }}
      </template>
    </DashboardPanelHeader>

    <div
      v-if="recordId"
      class="border-border mb-3 flex items-center gap-2 border-b pb-3 text-xs text-muted-foreground"
    >
      <span>{{ text.recordId }}:</span>
      <code
        class="inline-flex items-center rounded-full border border-primary/25 bg-primary/10 text-primary px-1.5 py-0.5 font-mono text-xs"
      >{{ recordId }}</code>
    </div>

    <div class="space-y-2">
      <div v-if="details?.rawResult">
        <button
          type="button"
          class="border border-border bg-background transition-colors hover:bg-muted flex w-full items-center justify-between rounded-lg p-2.5"
          @click="showRaw = !showRaw"
        >
          <span class="text-xs text-foreground">{{ text.rawResult }}</span>
          <ChevronDown
            :class="`w-3.5 h-3.5 text-muted-foreground transition-transform ${showRaw ? 'rotate-180' : ''}`"
          />
        </button>
        <div
          v-if="showRaw"
          class="animate-fade-in mt-2 min-w-0 overflow-hidden"
        >
          <div class="relative overflow-hidden">
            <span class="absolute right-2 top-2 z-10 inline-flex">
              <button
                type="button"
                class="text-primary underline-offset-4 hover:underline text-xs text-muted-foreground"
                :aria-label="copiedPanels.raw ? text.copied : text.copy"
                @click="copyToClipboard(renderJsonPre(details.rawResult, 'raw').jsonStr, 'raw')"
              >
                {{ copiedPanels.raw ? text.copied : text.copy }}
              </button>
            </span>
            <pre
              class="max-h-80 w-0 min-w-full overflow-x-auto overflow-y-auto rounded-lg border bg-muted/40 p-3 text-left font-mono text-xs text-foreground"
            >{{ JSON.stringify(details.rawResult, null, 2) }}</pre>
          </div>
        </div>
      </div>

      <div v-if="details?.contextSnapshot">
        <button
          type="button"
          class="border border-border bg-background transition-colors hover:bg-muted flex w-full items-center justify-between rounded-lg p-2.5"
          @click="showSnapshot = !showSnapshot"
        >
          <span class="text-xs text-foreground">{{ text.analysisSnapshot }}</span>
          <ChevronDown
            :class="`w-3.5 h-3.5 text-muted-foreground transition-transform ${showSnapshot ? 'rotate-180' : ''}`"
          />
        </button>
        <div
          v-if="showSnapshot"
          class="animate-fade-in mt-2 min-w-0 overflow-hidden"
        >
          <div class="relative overflow-hidden">
            <span class="absolute right-2 top-2 z-10 inline-flex">
              <button
                type="button"
                class="text-primary underline-offset-4 hover:underline text-xs text-muted-foreground"
                :aria-label="copiedPanels.snapshot ? text.copied : text.copy"
                @click="
                  copyToClipboard(
                    renderJsonPre(details.contextSnapshot, 'snapshot').jsonStr,
                    'snapshot',
                  )
                "
              >
                {{ copiedPanels.snapshot ? text.copied : text.copy }}
              </button>
            </span>
            <pre
              class="max-h-80 w-0 min-w-full overflow-x-auto overflow-y-auto rounded-lg border bg-muted/40 p-3 text-left font-mono text-xs text-foreground"
            >{{ JSON.stringify(details.contextSnapshot, null, 2) }}</pre>
          </div>
        </div>
      </div>
    </div>
  </Card>
</template>
