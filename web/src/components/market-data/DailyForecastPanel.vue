<script setup lang="ts">
import type { DailyForecast, DailyForecastBar } from '@/api/marketData';

const props = defineProps<{ forecast: DailyForecast; bars: DailyForecastBar[]; pricePrecision?: number }>();
const showForecast = defineModel<boolean>('showForecast', { required: true });
function price(value: number) { return value.toFixed(props.pricePrecision ?? 2); }
</script>

<template>
  <section
    class="mt-3 rounded-lg border bg-card p-3 text-sm"
    data-testid="daily-forecast"
  >
    <div class="flex flex-wrap items-center justify-between gap-2">
      <p>
        <span class="font-semibold">Kronos 日 K 预测</span>
        <span class="ml-2 text-xs text-muted-foreground">基准 {{ forecast.anchorDate }} · {{ bars.length }} 个交易日</span>
      </p>
      <label class="flex cursor-pointer items-center gap-1.5 text-xs">
        <input
          v-model="showForecast"
          type="checkbox"
          class="accent-blue-600"
        >
        显示预测 K 线
      </label>
    </div>
    <details class="mt-2">
      <summary class="cursor-pointer text-xs text-muted-foreground">
        查看预测开高低收
      </summary>
      <ul class="mt-2 grid gap-2 sm:grid-cols-2 lg:grid-cols-3">
        <li
          v-for="bar in bars"
          :key="bar.tradeDate"
          class="rounded border p-2"
        >
          <time :datetime="bar.tradeDate">{{ bar.tradeDate }}</time>
          <dl class="mt-1 grid grid-cols-4 gap-1 text-xs tabular-nums">
            <div>
              <dt class="text-muted-foreground">
                开盘
              </dt><dd>{{ price(bar.open) }}</dd>
            </div>
            <div>
              <dt class="text-muted-foreground">
                最高
              </dt><dd>{{ price(bar.high) }}</dd>
            </div>
            <div>
              <dt class="text-muted-foreground">
                最低
              </dt><dd>{{ price(bar.low) }}</dd>
            </div>
            <div>
              <dt class="text-muted-foreground">
                收盘
              </dt><dd class="font-semibold">
                {{ price(bar.close) }}
              </dd>
            </div>
          </dl>
        </li>
      </ul>
    </details>
  </section>
</template>
