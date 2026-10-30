<script setup lang="ts">
import { onBeforeUnmount, ref, watch } from 'vue';
import { RouterLink } from 'vue-router';
import { industryStrengthApi, type StockIndustryContext } from '@/api/industryStrength';
import { getParsedApiError, type ParsedApiError } from '@/api/error';
import AppApiErrorAlert from '@/components/app/AppApiErrorAlert.vue';
import BilingualEnum from '@/components/app/BilingualEnum.vue';
import { formatRank } from '@/utils/rank';
import { formatFixed } from '@/utils/number';
import { formatDateTimeInDisplayTimezone } from '@/utils/format';
import type { StockDetailPanelProps } from './types';

const props = defineProps<StockDetailPanelProps>();
const items = ref<StockIndustryContext[]>([]);
const loading = ref(false);
const error = ref<ParsedApiError | null>(null);
let generation = 0;
async function load() {
  const request = ++generation;
  items.value = []; error.value = null; loading.value = false;
  if (props.market !== 'CN') return;
  loading.value = true;
  try {
    const rows = await industryStrengthApi.stockContext(props.symbol);
    if (request === generation) items.value = rows;
  } catch (cause) {
    if (request === generation && getParsedApiError(cause).status !== 404) error.value = getParsedApiError(cause);
  } finally {
    if (request === generation) loading.value = false;
  }
}
watch([() => props.symbol, () => props.market], load, { immediate: true });
onBeforeUnmount(() => { ++generation; });
</script>

<template>
  <section
    class="space-y-4"
    data-testid="industry-detail-panel"
  >
    <p class="text-sm text-muted-foreground">
      最新正式行业背景 · 按卡片日期查看，不随其他研究页签的历史日期或预演切换。行业背景不代表个股交易建议。
    </p>
    <p
      v-if="loading"
      role="status"
    >
      正在读取行业背景…
    </p>
    <AppApiErrorAlert
      v-else-if="error"
      :error="error"
      action-label="重试行业背景"
      @action="load"
    />
    <p
      v-else-if="!items.length"
      class="text-sm text-muted-foreground"
    >
      {{ market === 'CN' ? '暂无正式行业结果或不在覆盖范围内。' : '行业背景仅覆盖 A 股。' }}
    </p>
    <article
      v-for="item in items"
      :key="item.industryCode"
      class="space-y-2 rounded-lg border p-4 text-sm"
    >
      <h3 class="font-semibold">
        {{ item.industryName }} · 正式 · {{ item.tradeDate }}
      </h3>
      <p>
        <BilingualEnum
          :value="item.state"
          size="badge"
        /> · 排名 {{ formatRank(item.strengthRank, item.rankTotal) }} · 强度 {{ formatFixed(item.strengthScore) }}
      </p>
      <p class="text-xs text-muted-foreground">
        当前成分观测时间 {{ formatDateTimeInDisplayTimezone(item.membersObservedAt) }}
      </p>
      <RouterLink
        :to="{ path: '/research/industry-strength', query: { industry: item.industryCode, tradeDate: item.tradeDate } }"
        class="inline-block text-xs underline"
      >
        查看行业详情
      </RouterLink>
    </article>
  </section>
</template>
