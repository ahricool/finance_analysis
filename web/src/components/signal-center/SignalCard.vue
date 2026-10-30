<script setup lang="ts">
import { formatRank } from '@/utils/rank';
import { computed } from 'vue';
import { ArrowUpRight, ShieldCheck, ScanLine, Globe2 } from 'lucide-vue-next';
import StockLink from '@/components/stocks/StockLink.vue';
import type { SignalDetail } from '@/api/signalCenter';
import { formatDateTime } from '@/utils/format';
import { Badge } from '@/components/ui/badge';
import SignalEvaluation from './SignalEvaluation.vue';
import SignalEvidence from './SignalEvidence.vue';
import { noTradeReasons, signalPicks, sourceUrl } from './picks';
const props = defineProps<{ signal: SignalDetail }>();
const picks = computed(() => signalPicks(props.signal));
const statuses = { pending: '分析中', completed: '已完成', failed: '分析失败，未产生信号', skipped: '数据不足，跳过' };
const sourceNames: Record<string, string> = { trend: '趋势', trend20: '20日趋势', trend40: '40日趋势', trend60: '60日趋势', quant: '量化（历史）', industry: '行业强度', etf: 'ETF轮动', confluence: '信号共振', regime: '市场环境' };
const sourceStatuses: Record<string, string> = { available: '可用', missing: '缺失', stale: '过期', running: '运行中', failed: '读取失败', unsupported: '不适用' };
const confidence: Record<string, string> = { high: '高', medium: '中', low: '低' };
const searches: Record<string, string> = { confirmed: '已执行检索', unverified: '检索未获确认', unavailable: '检索不可用', not_requested: '未请求检索' };
</script>

<template>
  <div
    class="@container min-w-0 space-y-5"
    data-testid="signal-card"
  >
    <div class="flex flex-wrap items-center gap-2 text-xs">
      <Badge :variant="signal.decision === 'BUY' ? 'default' : 'secondary'">
        {{ signal.decision === 'BUY' ? `${picks.length} 个精选信号` : signal.decision === 'NO_TRADE' ? '当日不交易' : statuses[signal.status] }}
      </Badge>
      <span class="text-muted-foreground">{{ signal.completedAt ? formatDateTime(signal.completedAt) : '等待完成' }}</span>
    </div>
    <p
      v-if="signal.analysis"
      class="whitespace-pre-wrap text-sm leading-7 text-foreground/85"
    >
      {{ signal.analysis.thesis }}
    </p>
    <div
      v-if="signal.decision === 'NO_TRADE'"
      class="flex items-start gap-3 rounded-xl border border-dashed bg-muted/25 p-5"
    >
      <ShieldCheck class="mt-0.5 size-5 shrink-0 text-muted-foreground" />
      <div>
        <p class="font-medium">
          保留选择，等待更清晰的机会
        </p><p class="mt-1 text-sm text-muted-foreground">
          {{ noTradeReasons[signal.analysis?.noTradeReason || ''] || '当日候选未形成明确优势' }} · 不为凑数推荐
        </p>
      </div>
    </div>
    <p
      v-else-if="!signal.analysis"
      class="rounded-lg bg-muted/30 p-4 text-sm text-muted-foreground"
    >
      {{ signal.error || statuses[signal.status] }}
    </p>
    <SignalEvidence
      v-if="signal.analysis?.evidence?.length"
      :evidence="signal.analysis.evidence"
      label="结论证据"
    />
    <div class="grid grid-cols-1 items-start gap-4 @xl:grid-cols-2 @4xl:grid-cols-3">
      <article
        v-for="(pick, index) in picks"
        :key="pick.symbol"
        class="min-w-0 overflow-hidden rounded-xl border bg-background"
        data-testid="signal-pick"
      >
        <div class="flex items-start justify-between gap-3 border-b bg-muted/20 p-4">
          <div class="min-w-0 space-y-2">
            <div class="flex items-center gap-2 text-xs text-muted-foreground">
              <span class="tabular-nums">推荐内 {{ formatRank(index + 1, picks.length) }}</span><span>{{ pick.instrumentType === 'ETF' ? 'ETF' : '股票' }}</span>
            </div>
            <StockLink
              :code="pick.symbol"
              :name="pick.name"
              :market="signal.market"
              :context="{ tradeDate: signal.signalDate }"
              class="text-base font-semibold"
            />
          </div>
          <Badge
            variant="outline"
            class="shrink-0"
          >
            信心 {{ confidence[pick.confidence || ''] || '—' }}
          </Badge>
        </div>
        <div class="space-y-4 p-4">
          <p class="whitespace-pre-wrap text-sm leading-7">
            {{ pick.thesis }}
          </p>
          <div
            v-for="section in [{ label: '支持依据', items: pick.positiveSignals }, { label: '主要风险', items: pick.risks }, { label: '失效条件', items: pick.invalidations }]"
            :key="section.label"
            class="space-y-1.5"
          >
            <h4 class="text-xs font-semibold text-muted-foreground">
              {{ section.label }}
            </h4>
            <ul class="space-y-1.5 text-sm leading-6">
              <li
                v-for="(item, i) in section.items"
                :key="i"
                class="flex gap-2"
              >
                <span class="text-muted-foreground">·</span><span class="min-w-0 break-words">{{ item }}</span>
              </li>
            </ul>
          </div>
          <SignalEvidence
            v-if="pick.evidence.length"
            :evidence="pick.evidence"
          />
          <details
            v-if="pick.externalSources.length"
            class="rounded-lg border"
          >
            <summary class="flex cursor-pointer items-center gap-2 p-3 text-sm font-medium">
              <Globe2 class="size-4 text-muted-foreground" />外部研究来源
            </summary>
            <div class="space-y-3 border-t p-3 text-xs">
              <div
                v-for="(source, i) in pick.externalSources"
                :key="i"
                class="space-y-1.5"
              >
                <a
                  v-if="sourceUrl(source.url)"
                  :href="sourceUrl(source.url)"
                  target="_blank"
                  rel="noopener noreferrer"
                  class="inline-flex items-center gap-1 underline underline-offset-4"
                >{{ source.title }}<ArrowUpRight class="size-3 shrink-0" /></a>
                <span v-else>{{ source.title }}</span>
                <p class="text-muted-foreground">
                  {{ source.publishedDate || '发布日期未知' }}
                </p><p class="leading-6">
                  {{ source.excerpt }}
                </p>
              </div>
              <p class="text-muted-foreground">
                外部摘录为模型引用，未逐篇核验原文。
              </p>
            </div>
          </details>
          <details v-if="pick.evaluation">
            <summary class="cursor-pointer text-xs text-muted-foreground">
              查看信号后的价格表现
            </summary><div class="pt-3">
              <SignalEvaluation :evaluation="pick.evaluation" />
            </div>
          </details>
        </div>
      </article>
    </div>
    <details class="border-t pt-3 text-xs text-muted-foreground">
      <summary class="flex cursor-pointer items-center gap-2">
        <ScanLine class="size-3.5" />输入与研究记录 <span class="ml-auto">{{ signal.candidateSnapshot.candidates.length }} 个候选</span>
      </summary>
      <div class="mt-3 space-y-2 leading-6">
        <p>交易日期：{{ signal.signalDate }} · 输入采集：{{ formatDateTime(signal.candidateSnapshot.capturedAt) }}</p>
        <p
          v-for="(source, name) in signal.candidateSnapshot.sourceAvailability"
          :key="name"
        >
          {{ sourceNames[name] || name }}：{{ sourceStatuses[source.status] || source.status }} · {{ source.dataAsOf || '—' }} · {{ source.generatedAt ? formatDateTime(source.generatedAt) : '—' }}
        </p>
        <p
          v-for="batch in signal.screening || []"
          :key="batch.batch"
        >
          第 {{ batch.batch + 1 }} 桶 · 入围 {{ batch.output.symbols.length }} 个 · {{ searches[batch.searchEvidence?.status || ''] || '检索状态未记录' }}：{{ batch.output.reason }}
        </p>
        <p v-if="signal.searchEvidence">
          最终轮搜索：{{ searches[signal.searchEvidence.status] || signal.searchEvidence.status }}
        </p>
        <p class="break-all">
          最终轮模型：{{ signal.model || '—' }} · 版本：{{ signal.promptVersion }}
        </p>
      </div>
    </details>
  </div>
</template>
