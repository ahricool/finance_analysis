<script setup lang="ts">
import ReportDetails from '@/components/report/ReportDetails.vue';
import ReportNews from '@/components/report/ReportNews.vue';
import ReportOverview from '@/components/report/ReportOverview.vue';
import ReportStrategy from '@/components/report/ReportStrategy.vue';
import type { AnalysisReport, AnalysisResult } from '@/types/analysis';
import { getReportText, normalizeReportLanguage } from '@/utils/reportLanguage';
import { computed } from 'vue';

const props = withDefaults(
  defineProps<{
    data: AnalysisResult | AnalysisReport;
    isHistory?: boolean;
  }>(),
  {
    isHistory: false,
  },
);

const report = computed<AnalysisReport>(() =>
  'report' in props.data ? props.data.report : props.data,
);

const recordId = computed(() => report.value.meta.id);
const reportLanguage = computed(() => normalizeReportLanguage(report.value.meta.reportLanguage));
const text = computed(() => getReportText(reportLanguage.value));

const modelUsed = computed(() => (report.value.meta.modelUsed || '').trim());
const shouldShowModel = computed(() =>
  Boolean(
    modelUsed.value &&
      !['unknown', 'error', 'none', 'null', 'n/a'].includes(modelUsed.value.toLowerCase()),
  ),
);
</script>

<template>
  <div class="animate-fade-in space-y-5 pb-8">
    <ReportOverview
      :meta="report.meta"
      :summary="report.summary"
      :details="report.details"
      :is-history="isHistory"
    />
    <ReportStrategy :strategy="report.strategy" :language="reportLanguage" />
    <ReportNews :record-id="recordId" :limit="8" :language="reportLanguage" />
    <ReportDetails :details="report.details" :record-id="recordId" :language="reportLanguage" />
    <p v-if="shouldShowModel" class="px-1 text-xs text-muted-text">
      {{ text.analysisModel }}: {{ modelUsed }}
    </p>
  </div>
</template>
