<script setup lang="ts">
import { onMounted, ref } from 'vue';
import { loadCatalog, usdt, type Catalog } from '@/api/cryptoStrategy';
import AppApiErrorAlert from '@/components/app/AppApiErrorAlert.vue';
import { getParsedApiError, type ParsedApiError } from '@/api/error';

const catalog = ref<Catalog>();
const error = ref<ParsedApiError | null>(null);
async function load() {
  try { catalog.value = await loadCatalog(); error.value = null; }
  catch (e) { error.value = getParsedApiError(e); }
}
onMounted(load);
</script>

<template>
  <main class="space-y-5 py-6">
    <h1 class="text-3xl font-semibold">
      Strategy
    </h1>
    <p class="text-sm text-muted-foreground">
      Paper Trade 与 Live Trade 分开记录。收益为已结束区间的账户权益差额，包含期间出入金和外部交易。
    </p>
    <AppApiErrorAlert
      v-if="error"
      :error="error"
      action-label="重试"
      @action="load"
    />
    <p v-if="!catalog && !error">
      加载中…
    </p>
    <div class="grid items-start gap-4 lg:grid-cols-2">
      <details
        v-for="item in catalog?.items"
        :key="item.key"
        class="rounded-lg border bg-card p-4"
      >
        <summary class="cursor-pointer font-semibold">
          {{ item.name }}
          <span
            v-for="env in (['paper', 'live'] as const)"
            :key="env"
            class="text-xs text-muted-foreground"
          >
            {{ catalog?.selected[env] === item.key ? ' · ' + (env === 'paper' ? 'Paper' : 'Live') + ' 使用中' : '' }}
          </span>
          <dl class="mt-3 grid grid-cols-3 gap-2 text-sm">
            <div><dt>回测收益</dt><dd>{{ usdt(item.backtest) }}</dd></div>
            <div><dt>Paper Trade 收益</dt><dd>{{ usdt(item.paper) }}</dd></div>
            <div><dt>Live Trade 收益</dt><dd>{{ usdt(item.live) }}</dd></div>
          </dl>
        </summary>
        <p class="my-3 text-sm">
          {{ item.description }} · {{ catalog?.interval_seconds }} 秒评估
        </p>

        <p
          v-if="item.parameters"
          class="text-sm text-muted-foreground"
        >
          Demo 名义额度 {{ item.parameters.notional }} USDT · 杠杆上限 {{ item.parameters.leverage_limit }}× ·
          止损上限 {{ item.parameters.stop_pct }}% · 最大亏损 {{ item.parameters.max_loss }} USDT
        </p>
        <h3 class="mt-4 font-medium">
          切换记录
        </h3>
        <p
          v-if="!item.periods.length"
          class="text-sm text-muted-foreground"
        >
          暂无使用记录
        </p>
        <ul class="divide-y">
          <li
            v-for="p in item.periods"
            :key="p.environment + p.start"
            class="py-2 text-sm"
          >
            {{ p.environment === 'paper' ? 'Paper Trade' : 'Live Trade' }} · {{ new Date(p.start).toLocaleString() }} 至 {{ p.end ? new Date(p.end).toLocaleString() : '使用中' }}
            <p>{{ usdt(p.start_equity) }} → {{ usdt(p.end_equity) }} · 收益 {{ usdt(p.profit) }}</p>
          </li>
        </ul>
      </details>
    </div>
  </main>
</template>
