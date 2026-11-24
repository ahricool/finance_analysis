<script setup lang="ts">
import { computed, ref, shallowRef, watch } from 'vue';
import { useIntervalFn } from '@vueuse/core';
import { fetchIndustryMapMetadata, type IndustryMapMetadata, type IntradayOptionRow } from '@/api/intradayOptions';
import { getParsedApiError, type ParsedApiError } from '@/api/error';
import AppApiErrorAlert from '@/components/app/AppApiErrorAlert.vue';
import { buildIndustryMap } from './industryMap';
import IndustryMapNode from './IndustryMapNode.vue';

const props = defineProps<{ rows: IntradayOptionRow[]; disconnected: boolean }>();
const nyDateTime = new Intl.DateTimeFormat('zh-CN', {
  timeZone: 'America/New_York',
  dateStyle: 'medium',
  timeStyle: 'short',
  hour12: false,
});
const metadata = shallowRef<IndustryMapMetadata>();
const error = shallowRef<ParsedApiError | null>(null);
const attempt = ref(0);
const expanded = ref(new Set(['QQQ']));
const membership = computed(() => props.rows.map(row => row.symbol).sort().join(','));
const map = computed(() => buildIndustryMap(props.rows, metadata.value?.items ?? []));
const capTime = computed(() => {
  const value = Date.parse(metadata.value?.marketCapAsOf ?? '');
  return Number.isFinite(value) ? nyDateTime.format(value) : null;
});

useIntervalFn(() => attempt.value++, 15 * 60_000);
watch([membership, attempt], async (_value, _previous, onCleanup) => {
  const controller = new AbortController();
  onCleanup(() => controller.abort());
  error.value = null;
  try {
    const result = await fetchIndustryMapMetadata(controller.signal);
    if (!controller.signal.aborted) metadata.value = result;
  } catch (err) {
    if (!controller.signal.aborted) error.value = getParsedApiError(err);
  }
}, { immediate: true });

function toggle(id: string) {
  if (expanded.value.has(id)) expanded.value.delete(id);
  else expanded.value.add(id);
}
</script>

<template>
  <section
    id="intraday-industry-map"
    class="min-w-0 scroll-mt-24 space-y-3 rounded-lg border bg-card p-3 sm:p-4"
    aria-labelledby="intraday-industry-map-title"
    tabindex="-1"
  >
    <div class="space-y-1">
      <h2
        id="intraday-industry-map-title"
        class="text-base font-semibold"
      >
        QQQ 成分股行业图
      </h2>
      <p class="text-xs text-muted-foreground">
        行业涨跌为成分股等权平均，仅计入有效报价。个股在二级行业内按市值从大到小排列。
      </p>
      <p
        v-if="metadata && (capTime || map.missingCaps)"
        class="text-xs text-muted-foreground"
      >
        <span v-if="capTime">市值快照 {{ capTime }}（纽约）</span>
        <span v-if="capTime && map.missingCaps"> · </span>
        <span v-if="map.missingCaps">{{ map.missingCaps }} 只个股缺少市值，排在各行业末尾</span>
      </p>
      <p
        v-if="disconnected"
        class="text-xs text-muted-foreground"
      >
        行情暂未更新，显示上次收到的涨跌幅。
      </p>
    </div>
    <AppApiErrorAlert
      v-if="error"
      :error="error"
      action-label="重试行业数据"
      @action="attempt++"
    />
    <p
      v-if="!metadata"
      class="py-2 text-sm text-muted-foreground"
      role="status"
    >
      {{ error ? '行业数据暂不可用' : '正在加载行业数据…' }}
    </p>
    <div
      v-else
      class="@container max-h-[36rem] overflow-auto rounded-md bg-muted/35 p-3 sm:p-4"
      data-testid="industry-map-tree"
    >
      <IndustryMapNode
        :node="map.root"
        :expanded="expanded"
        @toggle="toggle"
      />
    </div>
  </section>
</template>
