<script setup lang="ts">
import { computed, onBeforeUnmount, ref, shallowRef, watch } from 'vue';
import { Layers3, Network, TrendingUp, ChartNoAxesCombined } from 'lucide-vue-next';
import { confluenceApi, type ConfluenceItem } from '@/api/confluence';
import type { Confirmation, Market, Source } from '@/api/intradayConfirmation';
import { getParsedApiError, type ParsedApiError } from '@/api/error';
import AppApiErrorAlert from '@/components/app/AppApiErrorAlert.vue';
import BilingualLabel from '@/components/app/BilingualLabel.vue';
import { Badge } from '@/components/ui/badge';
import { Skeleton } from '@/components/ui/skeleton';
import { primary, secondary, labels, signal, strength, states, tone } from '@/components/confluence/evidence';
import { intradayLabel } from '@/i18n/labels';
import { formatDateTime } from '@/utils/format';
import { formatFixed, isFiniteNumber } from '@/utils/number';

const props = defineProps<{ confirmation: Confirmation; market: Market }>();
const sources = computed(() => [...new Set([
  ...(props.confirmation.candidateSources ?? []), props.confirmation.candidateSource,
  ...(props.confirmation.sourceEvidence ?? []).map(e => e.source),
])]);
const icons = { confluence: Network, trend: TrendingUp, etf: ChartNoAxesCombined, quant: Layers3 };
const evidence = (source: Source) => props.confirmation.sourceEvidence?.find(e => e.source === source);
const confluence = shallowRef<ConfluenceItem | null>(null);
const algorithmVersion = ref('');
const loading = ref(false);
const unavailable = ref('');
const error = shallowRef<ParsedApiError | null>(null);
const groups = [{ label: '主要指标', keys: primary }, { label: '辅助指标', keys: secondary }];
let generation = 0;
let controller: AbortController | undefined;

async function loadConfluence() {
  const token = ++generation;
  controller?.abort();
  controller = new AbortController();
  confluence.value = null; algorithmVersion.value = ''; error.value = null; unavailable.value = ''; loading.value = false;
  if (!sources.value.includes('confluence')) return;
  const row = props.confirmation;
  const frozen = evidence('confluence');
  const date = frozen?.tradeDate ?? row.candidateTradeDate;
  const generated = frozen?.generatedAt ?? (row.candidateSource === 'confluence' ? row.sourceGeneratedAt : null);
  if (!generated || !Number.isFinite(Date.parse(generated))) {
    unavailable.value = '历史记录未保存共振批次，无法核验昨日分数。';
    return;
  }
  loading.value = true;
  try {
    const response = await confluenceApi.detail(row.code, props.market, date, controller.signal);
    if (token !== generation) return;
    // Same-day official runs replace one another. Never substitute a later run for frozen selection evidence.
    if (response.market !== props.market || response.tradeDate !== date || response.item.code !== row.code
      || Date.parse(response.item.generatedAt) !== Date.parse(generated)) {
      unavailable.value = '昨日共振批次已变化，无法展示冻结选股时的原始分数。';
      return;
    }
    confluence.value = response.item;
    algorithmVersion.value = response.algorithmVersion;
  } catch (cause) {
    if (token !== generation) return;
    const parsed = getParsedApiError(cause);
    if (parsed.status === 404) unavailable.value = '该日期的共振记录已不可用，原始分数暂缺。';
    else error.value = parsed;
  } finally {
    if (token === generation) loading.value = false;
  }
}
watch([() => props.confirmation, () => props.market], loadConfluence, { immediate: true });
onBeforeUnmount(() => { ++generation; controller?.abort(); });
function contribution(key: typeof primary[number]) {
  if (!confluence.value) return null;
  const s = signal(confluence.value, key);
  if (s.status === 'unavailable') return null;
  return s.contribution ?? (s.score !== null && confluence.value.availableWeight > 0
    ? s.score / confluence.value.availableWeight * 100 : null);
}
function score(key: typeof primary[number]) {
  return confluence.value && signal(confluence.value, key).status !== 'unavailable' ? strength(confluence.value, key) : null;
}
function barWidth(value: unknown) { return `${isFiniteNumber(value) ? Math.max(0, Math.min(100, value)) : 0}%`; }
const macroLabel = computed(() => /confluence_v2_[12]/.test(algorithmVersion.value) ? labels.macro : '宏观环境');
</script>

<template>
  <section
    class="overflow-hidden rounded-xl border bg-card"
    data-testid="intraday-selection-sources"
  >
    <header class="flex flex-wrap items-center justify-between gap-3 border-b bg-muted/30 px-4 py-3 sm:px-5">
      <div class="flex items-center gap-2.5">
        <Layers3
          class="size-4 text-muted-foreground"
          aria-hidden="true"
        />
        <BilingualLabel
          zh="选股来源"
          en="Selection sources"
          class="text-sm font-semibold"
        />
      </div>
      <span class="text-xs text-muted-foreground">昨日正式研究 · {{ confirmation.candidateTradeDate }}</span>
    </header>
    <div class="space-y-4 p-4 sm:p-5">
      <div
        class="grid gap-2"
        :class="sources.length > 1 ? 'sm:grid-cols-2' : ''"
      >
        <div
          v-for="source in sources"
          :key="source"
          class="flex min-w-0 items-center gap-3 rounded-lg border p-3"
          :class="source === 'confluence' ? 'border-violet-500/25 bg-violet-500/5' : 'bg-muted/20'"
        >
          <span
            class="flex size-9 shrink-0 items-center justify-center rounded-lg"
            :class="source === 'confluence' ? 'bg-violet-500/10 text-violet-600 dark:text-violet-300' : 'bg-muted text-muted-foreground'"
          >
            <component
              :is="icons[source]"
              class="size-4"
              aria-hidden="true"
            />
          </span>
          <div class="min-w-0 flex-1">
            <p class="text-sm font-semibold">
              {{ intradayLabel(source) }}
            </p>
            <p class="mt-0.5 text-xs text-muted-foreground">
              {{ evidence(source)?.rank ? `正式综合排名第 ${evidence(source)!.rank} 名` : source === 'confluence' ? '昨日精选候选' : '正式候选已冻结' }}
            </p>
          </div>
          <Badge
            variant="outline"
            class="shrink-0"
          >
            已入池
          </Badge>
        </div>
      </div>
      <template v-if="sources.includes('confluence')">
        <div
          v-if="loading"
          class="space-y-3"
          role="status"
          aria-label="正在读取昨日共振分数"
        >
          <Skeleton class="h-20 w-full" /><div class="grid grid-cols-2 gap-3">
            <Skeleton
              v-for="i in 4"
              :key="i"
              class="h-24"
            />
          </div>
        </div>
        <AppApiErrorAlert
          v-else-if="error"
          :error="error"
          action-label="重试共振分数"
          @action="loadConfluence"
        />
        <p
          v-else-if="unavailable"
          class="rounded-lg border border-dashed p-3 text-sm text-muted-foreground"
          data-testid="intraday-confluence-unavailable"
        >
          {{ unavailable }}
        </p>
        <div
          v-else-if="confluence"
          class="space-y-4"
          data-testid="intraday-confluence-scores"
        >
          <div class="flex flex-wrap items-center justify-between gap-4 rounded-lg bg-violet-500/5 p-4">
            <div>
              <BilingualLabel
                zh="昨日共振总分"
                en="Prior-session confluence"
                class="text-xs text-muted-foreground"
              />
              <p
                class="mt-1 text-3xl font-semibold tracking-tight tabular-nums"
                data-testid="intraday-confluence-total"
              >
                {{ formatFixed(confluence.confluenceScore, { digits: 2 }) }}<span class="ml-1 text-sm font-normal text-muted-foreground">/ 100</span>
              </p>
            </div>
            <div class="space-y-1 text-xs text-muted-foreground">
              <p><span class="font-medium text-foreground">{{ confluence.positiveSignalCount }}</span> 个正向 · {{ confluence.availableSignalCount }} 个有效指标</p>
              <p>可用基础权重 {{ confluence.availableWeight }}/100</p>
              <p>{{ formatDateTime(confluence.generatedAt) }}</p>
            </div>
          </div>
          <div
            v-for="group in groups"
            :key="group.label"
            class="space-y-2"
          >
            <h4 class="text-xs font-medium text-muted-foreground">
              {{ group.label }}
            </h4>
            <div class="grid grid-cols-2 gap-2 sm:grid-cols-4">
              <div
                v-for="key in group.keys"
                :key="key"
                class="min-w-0 rounded-lg border p-3"
                :data-testid="`intraday-confluence-${key}`"
              >
                <div class="flex flex-wrap items-center justify-between gap-1">
                  <span class="text-xs font-medium">{{ key === 'macro' ? macroLabel : labels[key] }}</span>
                  <span
                    class="text-[10px]"
                    :class="tone(signal(confluence, key).status)"
                  >{{ states[signal(confluence, key).status] }}</span>
                </div>
                <p class="mt-2 text-xl font-semibold tabular-nums">
                  {{ formatFixed(score(key), { digits: 1 }) }}<span class="ml-0.5 text-[10px] font-normal text-muted-foreground">/100</span>
                </p>
                <div
                  class="mt-2 h-1 overflow-hidden rounded-full bg-muted"
                  aria-hidden="true"
                >
                  <div
                    class="h-full rounded-full bg-violet-500/65"
                    :style="{ width: barWidth(score(key)) }"
                  />
                </div>
                <p class="mt-2 text-[10px] text-muted-foreground">
                  总分贡献 <span class="tabular-nums">{{ formatFixed(contribution(key), { digits: 2 }) }}</span>
                </p>
                <p class="mt-1 text-[10px] text-muted-foreground">
                  {{ signal(confluence, key).tradeDate ?? '来源日期暂缺' }}
                </p>
              </div>
            </div>
          </div>
          <p class="text-xs leading-relaxed text-muted-foreground">
            子指标统一展示 0–100 强度分；贡献为归一化后计入总分的分值。缺失不记零、不参与分母。
          </p>
        </div>
      </template>
      <details class="group border-t pt-3">
        <summary class="cursor-pointer text-xs font-medium text-muted-foreground hover:text-foreground">
          查看昨日入选依据与来源时间
        </summary>
        <div class="mt-3 space-y-3 text-xs">
          <div
            v-for="source in sources"
            :key="source"
            class="space-y-1.5"
          >
            <p class="font-medium">
              {{ intradayLabel(source) }}<span class="ml-2 font-normal text-muted-foreground">{{ evidence(source)?.generatedAt ? formatDateTime(evidence(source)!.generatedAt) : source === confirmation.candidateSource ? formatDateTime(confirmation.sourceGeneratedAt) : '来源时间暂缺' }}</span>
            </p>
            <ul class="space-y-1 text-muted-foreground">
              <li
                v-for="reason in evidence(source)?.reasons ?? (source === confirmation.candidateSource ? confirmation.candidateReason : [])"
                :key="reason"
                class="border-l-2 pl-3 leading-relaxed"
              >
                {{ reason }}
              </li>
            </ul>
          </div>
        </div>
      </details>
    </div>
  </section>
</template>
