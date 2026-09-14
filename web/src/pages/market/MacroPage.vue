<script setup lang="ts">
import { onBeforeUnmount, onMounted, ref, shallowRef } from 'vue';
import { getMacroDashboard, type MacroDashboard } from '@/api/macro';
import { getParsedApiError, type ParsedApiError } from '@/api/error';
import AppApiErrorAlert from '@/components/app/AppApiErrorAlert.vue';
import PageHeader from '@/components/layout/PageHeader.vue';
import { Skeleton } from '@/components/ui/skeleton';
import MacroDataQuality from '@/components/macro/MacroDataQuality.vue';
import MacroStateCards from '@/components/macro/MacroStateCards.vue';
import MacroPerformanceChart from '@/components/macro/MacroPerformanceChart.vue';
import MacroMetricsTable from '@/components/macro/MacroMetricsTable.vue';
import { formatDateOnly, formatDateTime } from '@/utils/format';
const dashboard = shallowRef<MacroDashboard | null>(null);
const loading = ref(true);
const error = shallowRef<ParsedApiError | null>(null);
let sequence = 0;
async function load() {
  const request = ++sequence;
  loading.value = true; error.value = null;
  try { const data = await getMacroDashboard(); if (request === sequence) dashboard.value = data; }
  catch (cause) { if (request === sequence) error.value = { ...getParsedApiError(cause), title: '宏观数据加载失败' }; }
  finally { if (request === sequence) loading.value = false; }
}
onMounted(load);
onBeforeUnmount(() => { sequence++; });
</script>
<template>
  <div
    class="min-w-0 space-y-5"
    data-testid="macro-page"
  >
    <PageHeader
      title="宏观"
      description="US Macro · 跨资产环境与风险偏好监控"
    >
      <template #actions>
        <div class="text-right">
          <p class="text-sm font-medium">
            数据日期：{{ formatDateOnly(dashboard?.tradeDate) }}
          </p><p
            v-if="dashboard"
            class="mt-1 text-xs text-muted-foreground"
          >
            生成时间：{{ formatDateTime(dashboard.generatedAt) }}
          </p>
        </div>
      </template>
    </PageHeader>
    <AppApiErrorAlert
      v-if="error"
      :error="error"
      action-label="重新加载"
      @action="load"
      @dismiss="error = null"
    />
    <div
      v-if="loading && !dashboard"
      class="grid grid-cols-3 gap-3 min-[87.5rem]:grid-cols-6"
    >
      <Skeleton
        v-for="i in 6"
        :key="i"
        class="h-36"
      />
    </div>
    <template v-if="dashboard">
      <MacroDataQuality
        :quality="dashboard.dataQuality"
        :ratios="dashboard.ratios"
      /><MacroStateCards :dashboard="dashboard" />
    </template>
    <MacroPerformanceChart />
    <MacroPerformanceChart ratios />
    <template v-if="dashboard">
      <MacroMetricsTable :rows="dashboard.instruments" /><MacroMetricsTable
        :rows="dashboard.ratios"
        ratios
      />
    </template>
    <template v-else-if="loading">
      <Skeleton class="h-80" /><Skeleton class="h-56" />
    </template>
  </div>
</template>
