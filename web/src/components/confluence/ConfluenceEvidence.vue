<script setup lang="ts">
import { computed } from 'vue';
import BilingualEnum from '@/components/app/BilingualEnum.vue';
import IndicatorHelpLabel from '@/components/app/IndicatorHelpLabel.vue';
import { metricHint } from '@/utils/metricHints';
import type { ConfluenceItem, SignalKey } from '@/api/confluence';
import { primary, secondary, labels, signal, strength, states, tone } from './evidence';
const props = defineProps<{ row: ConfluenceItem }>();
const groups = [{ name: '主要指标', keys: primary }, { name: '辅助指标', keys: secondary }];
const matrix = computed(() => (props.row.signals.trend?.evidence.matrix ?? []) as Array<{ period: number; routes: Record<string, number | null>; dominant: string | null; state: string; lifecycle: string; fragility: number | null }>);
const routes = [{ key: 'trend', label: '趋势' }, { key: 'breakout', label: '突破' }, { key: 'rebound', label: '超跌反弹' }];
function metrics(key: SignalKey): [string, unknown][] {
  const e = signal(props.row, key).evidence;
  if (key === 'macro') return [['环境', e.regime], ['风险偏好', e.riskScore], ['有效覆盖', typeof e.signalCoverage === 'number' ? `${(e.signalCoverage * 100).toFixed(0)}%` : null]];
  if (key === 'industry') return [['行业', e.industryName], ['强度', e.strengthScore], ['状态', e.state]];
  if (key === 'trend') return [['趋势状态', e.state], ['生命周期', e.trendLifecycle], ['脆弱性', e.fragilityScore]];
  if (key === 'quant') return [['原生分', e.finalScore], ['信号', e.signal], ['排名', e.universeRank]];
  if (key === 'sentiment') return [['热度', e.heatScore], ['状态', e.state], ['涨停家数', e.limitUpCount]];
  if (key === 'dragonTiger') return [['净流入', e.netInflow], ['机构净额', e.institutionNetInflow], ['榜单窗口', e.rangeDays]];
  if (key === 'options') {
    const scores = (e.scores ?? {}) as Record<string, { value: number | null }>;
    return [['保护需求', scores.bearishDemand?.value], ['异常活跃', scores.unusualActivity?.value], ['流动性风险', scores.liquidityRisk?.value], ['证据等级', e.evidenceGrade]];
  }
  return [];
}
function formatMetric(value: unknown, label: string) {
  return typeof value === 'number' ? value.toLocaleString('zh-CN', { maximumFractionDigits: label === '原生分' ? 3 : 2 }) : value ?? '—';
}
function hint(key: SignalKey, label: string) {
  const fields: Record<string, string> = { '强度': 'strengthScore', '趋势状态': 'state', '原生分': 'finalScore', '生命周期': 'trendLifecycle', '脆弱性': 'fragilityScore', '排名': 'universeRank' };
  return metricHint(`confluence-${key}`, fields[label] ?? label) || '来源模块的正式核心指标，缺失显示为空。';
}
function etfs() { return (signal(props.row, 'etf').evidence.etfs ?? []) as Array<{ code: string; name: string; compositeScore: number | null; mappingReasons: string[] }>; }
</script>
<template>
  <div
    class="space-y-6"
    data-testid="confluence-evidence"
  >
    <section
      v-for="group in groups"
      :key="group.name"
      class="space-y-3"
    >
      <div class="flex items-center gap-3">
        <h3 class="text-sm font-semibold">
          {{ group.name }}
        </h3><div class="h-px flex-1 bg-border" />
      </div>
      <div class="grid gap-3 sm:grid-cols-2">
        <article
          v-for="key in group.keys"
          :key="key"
          class="min-w-0 rounded-xl border bg-card p-4"
          :data-testid="`evidence-${key}`"
        >
          <div class="flex items-start justify-between gap-2">
            <div>
              <h4 class="text-sm font-medium">
                {{ labels[key] }}
              </h4><p class="mt-1 text-xs text-muted-foreground">
                基础权重 {{ signal(row, key).weight }} · 实际 {{ signal(row, key).normalizedWeight?.toFixed(1) ?? '—' }}%
              </p>
            </div>
            <div class="text-right">
              <p
                class="text-xl font-semibold tabular-nums"
                :class="tone(signal(row, key).status)"
              >
                {{ strength(row, key)?.toFixed(1) ?? '—' }}
              </p><p class="text-xs text-muted-foreground">
                {{ states[signal(row, key).status] }}
              </p>
            </div>
          </div>
          <div class="my-3 h-1 overflow-hidden rounded-full bg-muted">
            <div
              v-if="strength(row, key) !== null"
              class="h-full rounded-full bg-current"
              :class="tone(signal(row, key).status)"
              :style="{ width: `${strength(row, key)}%` }"
            />
          </div>
          <dl
            v-if="signal(row, key).status !== 'unavailable' && metrics(key).length"
            class="grid grid-cols-2 gap-2 text-xs"
          >
            <div
              v-for="[label, value] in metrics(key)"
              :key="label"
            >
              <dt class="text-muted-foreground">
                <IndicatorHelpLabel
                  :scope="`confluence-${key}`"
                  :label="label"
                  :description="hint(key, label)"
                  compact
                />
              </dt><dd class="mt-1 break-words font-medium">
                <BilingualEnum
                  v-if="['环境', '状态', '趋势状态', '生命周期', '信号'].includes(label) && typeof value === 'string'"
                  :value="value"
                  size="badge"
                /><template v-else>
                  {{ formatMetric(value, label) }}
                </template>
              </dd>
            </div>
          </dl>
          <div
            v-if="key === 'etf'"
            class="space-y-2 text-xs"
          >
            <div
              v-for="etf in etfs()"
              :key="etf.code"
            >
              <p class="font-medium">
                {{ etf.name }} <span class="font-mono text-muted-foreground">{{ etf.code }}</span> · {{ etf.compositeScore?.toFixed(1) ?? '—' }}
              </p><p
                v-for="reason in etf.mappingReasons"
                :key="reason"
                class="mt-1 text-muted-foreground"
              >
                {{ reason }}
              </p>
            </div>
          </div>
          <div
            v-if="key === 'trend' && matrix.length"
            class="mt-3 overflow-x-auto"
          >
            <table class="w-full text-xs">
              <thead>
                <tr class="text-muted-foreground">
                  <th class="py-2 text-left font-normal">
                    周期
                  </th><th
                    v-for="route in routes"
                    :key="route.key"
                    class="text-right font-normal"
                  >
                    {{ route.label }}
                  </th>
                </tr>
              </thead><tbody>
                <tr
                  v-for="period in matrix"
                  :key="period.period"
                  class="border-t"
                >
                  <th class="py-2 text-left font-medium">
                    {{ period.period }}D
                  </th><td
                    v-for="route in routes"
                    :key="route.key"
                    class="text-right tabular-nums"
                    :class="period.dominant === route.key ? 'font-semibold text-foreground' : 'text-muted-foreground'"
                  >
                    {{ period.routes[route.key]?.toFixed(1) ?? '—' }}
                  </td>
                </tr>
              </tbody>
            </table>
          </div>
          <p class="mt-3 text-xs text-muted-foreground">
            数据 {{ signal(row, key).tradeDate ?? '—' }} <span v-if="signal(row, key).contribution != null">· 贡献 {{ signal(row, key).contribution?.toFixed(2) }} 分</span>
          </p>
          <details class="mt-2 text-xs text-muted-foreground">
            <summary class="cursor-pointer">
              {{ signal(row, key).status === 'unavailable' ? '缺失原因' : '评分依据' }}
            </summary><ul class="mt-2 list-disc space-y-1 pl-4">
              <li
                v-for="reason in signal(row, key).reasons"
                :key="reason"
              >
                {{ reason }}
              </li>
            </ul>
          </details>
        </article>
      </div>
    </section>
  </div>
</template>
