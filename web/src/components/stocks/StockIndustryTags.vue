<script setup lang="ts">
import { computed, ref, watch } from 'vue';
import { stocksApi, type StockETFProxy, type StockIndustryMembership } from '@/api/stocks';
import { getParsedApiError, type ParsedApiError } from '@/api/error';
import AppApiErrorAlert from '@/components/app/AppApiErrorAlert.vue';
import { Badge } from '@/components/ui/badge';
import { formatDateTimeInDisplayTimezone } from '@/utils/format';

const props = defineProps<{ code: string }>();
const industries = ref<StockIndustryMembership[]>([]);
const etfs = ref<StockETFProxy[]>([]);
const unavailableReasons = ref<string[]>([]);
const loading = ref(false);
const error = ref<ParsedApiError | null>(null);
const attempt = ref(0);
const observedAt = computed(() => industries.value[0]?.membersObservedAt);

watch(() => [props.code, attempt.value], async (_value, _previous, onCleanup) => {
  const controller = new AbortController();
  onCleanup(() => controller.abort());
  industries.value = []; etfs.value = []; unavailableReasons.value = []; error.value = null; loading.value = true;
  try {
    const result = await stocksApi.classification(props.code, controller.signal);
    if (!controller.signal.aborted) {
      industries.value = result.memberships.industries ?? [];
      etfs.value = result.etfProxies ?? [];
      unavailableReasons.value = result.etfProxyUnavailableReasons ?? [];
    }
  } catch (err) {
    if (!controller.signal.aborted && getParsedApiError(err).status !== 404) error.value = getParsedApiError(err);
  } finally {
    if (!controller.signal.aborted) loading.value = false;
  }
}, { immediate: true });
</script>

<template>
  <div
    class="mt-3 space-y-1.5 text-xs text-muted-foreground"
    data-testid="stock-industry-tags"
    aria-label="当前所属行业"
  >
    <p v-if="loading">
      正在加载所属行业…
    </p>
    <AppApiErrorAlert
      v-else-if="error"
      :error="error"
      action-label="重试行业"
      @action="attempt++"
    />
    <template v-else-if="industries.length">
      <div class="flex flex-wrap items-center gap-1.5">
        <span>所属行业</span>
        <Badge
          v-for="industry in industries"
          :key="industry.code"
          variant="secondary"
        >
          {{ industry.name }}
        </Badge>
      </div>
      <p>成分观测时间 {{ formatDateTimeInDisplayTimezone(observedAt) }} · 每周同步</p>
    </template>
    <p v-else>
      暂无所属行业数据
    </p>
    <div
      v-if="!loading && !error"
      class="space-y-1.5"
      data-testid="stock-etf-proxies"
      aria-label="关联ETF"
    >
      <div class="flex flex-wrap items-center gap-1.5">
        <span>关联 ETF</span>
        <Badge
          v-for="etf in etfs"
          :key="etf.code"
          variant="outline"
          class="whitespace-normal break-words"
        >
          {{ etf.name }} · {{ etf.code }}
        </Badge>
        <span v-if="!etfs.length">暂无关联 ETF</span>
        <span v-else>行业代理，非实际持仓</span>
      </div>
      <details v-if="etfs.length || unavailableReasons.length">
        <summary class="cursor-pointer">
          查看关联依据
        </summary>
        <ul class="mt-1 list-disc space-y-1 pl-4 break-words">
          <template
            v-for="etf in etfs"
            :key="etf.code"
          >
            <li
              v-for="reason in etf.reasons"
              :key="reason"
            >
              {{ etf.name }}：{{ reason }}
            </li>
          </template>
          <li
            v-for="reason in unavailableReasons"
            :key="reason"
          >
            {{ reason }}
          </li>
        </ul>
      </details>
    </div>
  </div>
</template>
