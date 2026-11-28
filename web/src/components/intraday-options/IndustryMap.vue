<script setup lang="ts">
import { formatDateTime, displayTimezoneLabel } from '@/utils/format';
import { computed, ref, shallowRef, watch } from 'vue';
import { useElementSize, useIntervalFn } from '@vueuse/core';
import { fetchIndustryMapMetadata, type IndustryMapMetadata, type IntradayOptionRow } from '@/api/intradayOptions';
import { getParsedApiError, type ParsedApiError } from '@/api/error';
import AppApiErrorAlert from '@/components/app/AppApiErrorAlert.vue';
import { Button } from '@/components/ui/button';
import { buildIndustryMap } from './industryMap';
import { branchIds, layoutIndustryMap } from './industryMapLayout';
import IndustryMapNode from './IndustryMapNode.vue';

const props = defineProps<{ rows: IntradayOptionRow[]; disconnected: boolean }>();
const metadata = shallowRef<IndustryMapMetadata>();
const error = shallowRef<ParsedApiError | null>(null);
const attempt = ref(0);
const collapsed = ref(new Set<string>());
const canvas = ref<HTMLElement | null>(null);
const { width } = useElementSize(canvas);
const compact = computed(() => width.value > 0 && width.value < 900);
const membership = computed(() => props.rows.map(row => row.symbol).sort().join(','));
const map = computed(() => buildIndustryMap(props.rows, metadata.value?.items ?? []));
const layout = computed(() => layoutIndustryMap(map.value.root, collapsed.value, compact.value));
const capTime = computed(() => {
  const value = Date.parse(metadata.value?.marketCapAsOf ?? '');
  return Number.isFinite(value) ? formatDateTime(metadata.value?.marketCapAsOf) : null;
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
  if (collapsed.value.has(id)) collapsed.value.delete(id);
  else collapsed.value.add(id);
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
      <div class="flex flex-wrap items-center justify-between gap-2">
        <h2
          id="intraday-industry-map-title"
          class="text-base font-semibold"
        >
          QQQ 成分股行业图
        </h2>
        <div
          v-if="metadata"
          class="flex gap-2"
        >
          <Button
            type="button"
            variant="outline"
            size="sm"
            @click="collapsed.clear()"
          >
            全部展开
          </Button>
          <Button
            type="button"
            variant="outline"
            size="sm"
            @click="collapsed = new Set(branchIds(map.root))"
          >
            全部折叠
          </Button>
        </div>
      </div>
      <p class="text-xs text-muted-foreground">
        行业涨跌为成分股等权平均，仅计入有效报价。个股在二级行业内按市值从大到小排列。
      </p>
      <p class="flex flex-wrap items-center gap-x-3 gap-y-1 text-xs text-muted-foreground">
        <span class="inline-flex items-center gap-1.5"><span class="h-0.5 w-4 bg-market-up" />上涨</span>
        <span class="inline-flex items-center gap-1.5"><span class="h-0.5 w-4 bg-market-down" />下跌</span>
        <span>线越粗，子节点与父节点的涨跌幅相差越大。</span>
      </p>
      <p
        v-if="metadata && (capTime || map.missingCaps)"
        class="text-xs text-muted-foreground"
      >
        <span v-if="capTime">市值快照 {{ capTime }}（{{ displayTimezoneLabel() }}）</span>
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
      class="rounded-md bg-muted/25 p-2 sm:p-4"
    >
      <div
        ref="canvas"
        class="relative"
        :style="{ height: `${layout.height}px`, '--map-underline-bottom': `${layout.underlineBottom}px` }"
        data-testid="industry-map-tree"
      >
        <svg
          class="pointer-events-none absolute inset-0 size-full"
          aria-hidden="true"
          :viewBox="`0 0 1000 ${layout.height}`"
          preserveAspectRatio="none"
        >
          <path
            v-for="edge in layout.edges"
            :key="edge.to"
            :d="edge.path"
            :class="[`map-edge-${edge.direction}`, { 'map-edge-missing': edge.missing }]"
            class="map-edge"
            :stroke-width="edge.width"
            :data-from="edge.from"
            :data-to="edge.to"
            vector-effect="non-scaling-stroke"
          />
        </svg>
        <IndustryMapNode
          v-for="position in layout.nodes"
          :key="position.node.id"
          :node="position.node"
          :expanded="!collapsed.has(position.node.id)"
          :compact="compact"
          :style="{
            left: `${position.x}%`,
            top: `${position.y}px`,
            width: `${position.width}%`,
            height: `${layout.rowHeight}px`,
          }"
          @toggle="toggle"
        />
      </div>
    </div>
  </section>
</template>

<style scoped>
.map-edge {
  fill: none;
  stroke-linecap: round;
}
.map-edge-up { stroke: hsl(var(--market-up) / 0.7); }
.map-edge-down { stroke: hsl(var(--market-down) / 0.7); }
.map-edge-neutral { stroke: hsl(var(--muted-foreground) / 0.46); }
.map-edge-missing { stroke-dasharray: 3 3; }
</style>
